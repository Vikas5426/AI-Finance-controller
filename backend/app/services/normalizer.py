import logging
import re
import statistics
import uuid
from datetime import datetime, timezone, date
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from typing import Any, Dict, List, Optional, Tuple
from app.models.schemas import (
    CanonicalTransaction, SourceKind, TxnDirection, MatchStatus, ReferenceKeys
)

logger = logging.getLogger(__name__)

STOP_WORDS = {"neft", "imps", "upi", "rtgs", "cr", "dr", "ref", "pvt", "ltd", "no", "software", "corp"}

# ---------------------------------------------------------------------------
# Per-source amount scale
# ---------------------------------------------------------------------------
# The multiplier that converts a source's native amount unit into minor units
# (paise). Payment gateways export minor units natively (Razorpay/Stripe style:
# amount=49900 means Rs 499.00), whereas bank statements and ERP general-ledger
# exports carry major units with decimals ("487.22").
#
# Getting this wrong is not a rounding problem: it scales every amount from one
# source by 100x relative to the others, so no cross-source amount comparison
# can ever succeed. Override per source via the source profile
# (source_profiles.amount_scale) or by passing amount_scale= explicitly.

SOURCE_AMOUNT_SCALE: Dict[SourceKind, int] = {
    SourceKind.GATEWAY: 1,      # already minor units
    SourceKind.BANK: 100,       # major units
    SourceKind.LEDGER: 100,     # major units
    SourceKind.SETTLEMENT: 100,  # major units
}

# Ratio between the median amounts of two sources beyond which a unit-scale
# misconfiguration is more likely than a genuine business difference. Gateway
# gross vs bank net differ only by fees (a few percent); a 100x gap is a bug.
SCALE_MISMATCH_RATIO = 20


def resolve_amount_scale(source_kind: SourceKind, override: Optional[int] = None) -> int:
    """Resolves the minor-unit multiplier for a source, honouring an explicit override."""
    if override is not None:
        return int(override)
    return SOURCE_AMOUNT_SCALE.get(source_kind, 100)


class RowNormalizationError(Exception):
    """Raised when a mandatory row field fails validation during normalization."""
    def __init__(self, message: str, row_data: Dict[str, Any], row_number: Optional[int] = None):
        super().__init__(message)
        self.row_data = row_data
        self.row_number = row_number


class NormalizerService:
    EXCLUDE_KEYWORDS = {
        "payment", "payment_id", "invoice", "invoice_id", "settlement", "order", "order_id",
        "journal", "debit", "credit", "ref", "pay", "inv", "utr", "je", "date", "type",
        "description", "bank_transaction_id", "merchant_reference", "amount", "fee", "tax"
    }

    @classmethod
    def extract_reference_keys(cls, text: str) -> ReferenceKeys:
        """Extracts typed reference keys from free-form text using regex."""
        keys = ReferenceKeys()
        if not text:
            return keys

        # Invoice references: e.g. INV-2026-0412, INV-2026-9901, INV-1001, INV_1001
        inv_matches = [k.upper() for k in re.findall(r"\bINV[-_]?[A-Za-z0-9]+(?:[-_][A-Za-z0-9]+)*", text, re.IGNORECASE) if k.lower() not in cls.EXCLUDE_KEYWORDS]
        if inv_matches:
            keys.invoice = list(set(inv_matches))

        # Payment references: e.g. pay_LtPk29Xq7, PAY-1001, PAY_1001, pay_CSV_TEST_01
        pay_matches = [k for k in re.findall(r"\bPAY[-_]?[A-Za-z0-9]+(?:[-_][A-Za-z0-9]+)*", text, re.IGNORECASE) if k.lower() not in cls.EXCLUDE_KEYWORDS]
        if pay_matches:
            keys.payment = list(set(pay_matches))

        # Settlement references: e.g. setl_9KA22, SETL9KA22, SETL-01, SETTLE_BATCH_8821, SETTLEMENT_123
        setl_matches = [k.upper().replace("_", "") for k in re.findall(r"\bSETTL(?:E|EMENT|L)?[-_]?[A-Za-z0-9]+(?:[-_][A-Za-z0-9]+)*", text, re.IGNORECASE) if k.lower() not in cls.EXCLUDE_KEYWORDS]
        if setl_matches:
            keys.settlement = list(set(setl_matches))

        # UTR / Bank transaction numbers: e.g. N2604029912, R2604029912, UTR-1001, UTR-DUP-01
        utr_matches = [k.upper() for k in re.findall(r"\b(?:UTR[-_]?[A-Za-z0-9]+(?:[-_][A-Za-z0-9]+)*|[NR]\d{10,})", text, re.IGNORECASE) if k.lower() not in cls.EXCLUDE_KEYWORDS]
        if utr_matches:
            keys.utr = list(set(utr_matches))

        # Order IDs: e.g. ord_88213, ORD-1001
        ord_matches = [k.lower() for k in re.findall(r"\bORD[-_]?[A-Za-z0-9]+(?:[-_][A-Za-z0-9]+)*", text, re.IGNORECASE) if k.lower() not in cls.EXCLUDE_KEYWORDS]
        if ord_matches:
            keys.order = list(set(ord_matches))

        # Journal Entry: e.g. JE-4471, JE-1001-REV
        je_matches = [k.upper() for k in re.findall(r"\bJE[-_]?[A-Za-z0-9]+(?:[-_][A-Za-z0-9]+)*", text, re.IGNORECASE) if k.lower() not in cls.EXCLUDE_KEYWORDS]
        if je_matches:
            keys.je = list(set(je_matches))

        return keys

    @staticmethod
    def normalize_text(text: Optional[str]) -> str:
        if not text:
            return ""
        # Lowercase, replace non-alphanumeric with spaces
        s = re.sub(r"[^a-zA-Z0-9\s]", " ", text.lower())
        tokens = [t for t in s.split() if t not in STOP_WORDS]
        return " ".join(tokens)

    @staticmethod
    def _to_paise(val: Any, default_zero: bool = False, amount_scale: int = 100) -> int:
        """
        Parses a monetary value to integer minor units (paise) using Decimal rounding.

        ``amount_scale`` is the multiplier that converts the source's native unit
        into minor units:
          * 100 -> the source reports major units ("487.22" rupees)
          * 1   -> the source already reports minor units ("48722" paise)

        Passing the wrong scale silently inflates or deflates every amount by
        100x, which makes cross-source amount matching impossible, so the value
        is resolved per source rather than assumed.
        """
        if val is None or str(val).strip() == "":
            if default_zero:
                return 0
            raise ValueError("Empty or missing monetary value")
        try:
            val_cleaned = str(val).strip().replace(",", "")
            d = Decimal(val_cleaned)
            return int((d * Decimal(amount_scale)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        except (InvalidOperation, ValueError, TypeError) as e:
            if default_zero:
                return 0
            raise ValueError(f"Invalid monetary value '{val}': cannot parse Decimal amount ({e})")

    @staticmethod
    def _parse_datetime(val: Any) -> Tuple[datetime, date]:
        """Parses datetime/date strictly without silent fake defaults."""
        if not val or str(val).strip() == "":
            raise ValueError("Mandatory timestamp / date field is empty or missing")
        if isinstance(val, datetime):
            return val, val.date()
        if isinstance(val, date):
            return datetime(val.year, val.month, val.day, 0, 0, 0), val

        val_str = str(val).strip()
        for fmt in (
            "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d", "%d/%m/%Y %H:%M:%S", "%d/%m/%Y", "%m/%d/%Y", "%Y/%m/%d"
        ):
            try:
                dt = datetime.strptime(val_str, fmt)
                return dt, dt.date()
            except ValueError:
                continue
        try:
            dt = datetime.fromisoformat(val_str)
            return dt, dt.date()
        except Exception:
            raise ValueError(f"Invalid timestamp/date value '{val}': unrecognized format")

    @staticmethod
    def _first_present(row: Dict[str, Any], *keys: str) -> Any:
        """Returns the first non-None, non-empty value from row matching any key."""
        for k in keys:
            if k in row and row[k] is not None and str(row[k]).strip() != "":
                return row[k]
        return None

    @classmethod
    def normalize_row(
        cls,
        raw_row: Dict[str, Any],
        source_kind: SourceKind,
        org_id: str,
        batch_id: str,
        amount_scale: Optional[int] = None
    ) -> CanonicalTransaction:
        """
        Normalizes a single heterogeneous CSV/API row into a unified CanonicalTransaction.

        ``amount_scale`` overrides the per-source default from SOURCE_AMOUNT_SCALE;
        leave it None to use the documented default for this source kind.
        """
        scale = resolve_amount_scale(source_kind, amount_scale)
        txn_id = str(uuid.uuid4())
        raw_desc = str(cls._first_present(raw_row, "description", "Description", "memo") or "")
        norm_desc = cls.normalize_text(raw_desc)
        ref_keys = cls.extract_reference_keys(f"{raw_desc} {str(raw_row)}")

        # Source-specific field normalization
        if source_kind == SourceKind.GATEWAY:
            ext_id = str(cls._first_present(raw_row, "payment_id", "Payment ID", "id") or txn_id)
            gross_val = cls._first_present(raw_row, "gross_amount", "amount", "Gross Amount", "gross")
            fee_val = cls._first_present(raw_row, "fee_amount", "fee", "Fee", "fees")
            tax_val = cls._first_present(raw_row, "tax_amount", "tax", "Tax", "tax_on_fees")
            
            amount_paise = cls._to_paise(gross_val, default_zero=False, amount_scale=scale)
            gross_paise = amount_paise
            fee_paise = cls._to_paise(fee_val, default_zero=True, amount_scale=scale)
            tax_paise = cls._to_paise(tax_val, default_zero=True, amount_scale=scale)
            
            date_val = cls._first_present(
                raw_row, "transaction_date", "captured_at", "created_at",
                "txn_date", "value_date", "date", "Date"
            )
            occurred_at, val_date = cls._parse_datetime(date_val)
            
            direction = TxnDirection.INFLOW
            txn_type = "PAYMENT"
            cp_raw = cls._first_present(raw_row, "customer_email", "Customer Email") or "CUSTOMER_DIRECT"
            cp_norm = cp_raw.split("@")[0].lower() if "@" in cp_raw else cp_raw.lower()
            acct_code = "1210 Accounts Receivable"

            if ext_id and ext_id not in ref_keys.payment:
                ref_keys.payment.append(ext_id)
            
            merch_ref = cls._first_present(raw_row, "merchant_reference", "order_id", "reference", "invoice_id")
            if merch_ref:
                m_str = str(merch_ref).strip()
                if "INV" in m_str.upper() and m_str not in ref_keys.invoice:
                    ref_keys.invoice.append(m_str)
                elif m_str not in ref_keys.order:
                    ref_keys.order.append(m_str)

            if raw_row.get("settlement_id"):
                s_id = str(raw_row["settlement_id"]).upper().replace("_", "")
                if s_id not in ref_keys.settlement:
                    ref_keys.settlement.append(s_id)

        elif source_kind == SourceKind.BANK:
            ext_id = str(cls._first_present(raw_row, "bank_transaction_id", "Ref No", "ref_no", "utr", "id") or txn_id)
            amt_val = cls._first_present(raw_row, "amount", "Amount", "net_amount", "Net Amount")
            credit_val = cls._first_present(raw_row, "Credit", "credit")
            debit_val = cls._first_present(raw_row, "Debit", "debit")
            type_str = str(cls._first_present(raw_row, "type", "Type") or "").upper()
            
            if amt_val is not None and str(amt_val).strip() != "":
                amt_paise_val = cls._to_paise(amt_val, default_zero=False, amount_scale=scale)
                amount_paise = abs(amt_paise_val)
                if type_str == "DEBIT" or amt_paise_val < 0:
                    direction = TxnDirection.OUTFLOW
                    txn_type = "BANK_DEBIT"
                else:
                    direction = TxnDirection.INFLOW
                    txn_type = "SETTLEMENT_CREDIT"
            elif credit_val is not None and str(credit_val).strip() != "" and str(credit_val).strip() != "0":
                amount_paise = cls._to_paise(credit_val, default_zero=False, amount_scale=scale)
                direction = TxnDirection.INFLOW
                txn_type = "SETTLEMENT_CREDIT"
            elif debit_val is not None and str(debit_val).strip() != "" and str(debit_val).strip() != "0":
                amount_paise = cls._to_paise(debit_val, default_zero=False, amount_scale=scale)
                direction = TxnDirection.OUTFLOW
                txn_type = "BANK_DEBIT"
            else:
                raise ValueError("Bank row missing valid amount, credit, or debit value")

            gross_paise = None
            fee_paise = None
            tax_paise = None
            
            date_val = (
                raw_row.get("transaction_date") or raw_row.get("txn_date") or raw_row.get("value_date") or
                raw_row.get("Value Date") or raw_row.get("Txn Date") or raw_row.get("date") or raw_row.get("Date")
            )
            occurred_at, val_date = cls._parse_datetime(date_val)
            
            cp_raw = "RAZORPAY SOFTWARE PVT"
            cp_norm = "razorpay"
            acct_code = "1010 Bank Control"

            if ext_id and ext_id not in ref_keys.utr:
                ref_keys.utr.append(ext_id)

            pay_ref = raw_row.get("payment_id") or raw_row.get("reference")
            if pay_ref:
                p_str = str(pay_ref).strip()
                if "PAY" in p_str.upper() and p_str not in ref_keys.payment:
                    ref_keys.payment.append(p_str)
                elif "INV" in p_str.upper() and p_str not in ref_keys.invoice:
                    ref_keys.invoice.append(p_str)

        elif source_kind == SourceKind.LEDGER:
            je_id = str(raw_row.get("journal_id") or raw_row.get("je_id") or raw_row.get("id") or "JE-000")
            line_no = str(raw_row.get("line_no") or raw_row.get("line") or "1")
            ext_id = f"{je_id}:{line_no}" if ":" not in je_id else je_id
            
            debit_val = raw_row.get("debit") or raw_row.get("debit_amount")
            credit_val = raw_row.get("credit") or raw_row.get("credit_amount")
            if debit_val is not None and str(debit_val).strip() != "" and str(debit_val).strip() != "0":
                amount_paise = cls._to_paise(debit_val, default_zero=False, amount_scale=scale)
                direction = TxnDirection.DEBIT
            elif credit_val is not None and str(credit_val).strip() != "" and str(credit_val).strip() != "0":
                amount_paise = cls._to_paise(credit_val, default_zero=False, amount_scale=scale)
                direction = TxnDirection.CREDIT
            else:
                raise ValueError(f"Ledger row '{ext_id}' missing both debit and credit amounts")
            
            gross_paise = None
            fee_paise = None
            tax_paise = None
            
            date_val = (
                raw_row.get("entry_date") or raw_row.get("posted_at") or raw_row.get("posting_date") or
                raw_row.get("txn_date") or raw_row.get("value_date") or raw_row.get("date") or raw_row.get("Date")
            )
            occurred_at, val_date = cls._parse_datetime(date_val)
            
            txn_type = "JOURNAL_ENTRY"
            cp_raw = None
            cp_norm = None
            acct_code = str(raw_row.get("account") or raw_row.get("account_code") or raw_row.get("account_name") or "1210 Accounts Receivable")

            if je_id and je_id not in ref_keys.je:
                ref_keys.je.append(je_id)

            doc_ref = raw_row.get("reference") or raw_row.get("doc_ref") or raw_row.get("ref_no")
            if doc_ref:
                d_str = str(doc_ref).strip()
                if "INV" in d_str.upper() and d_str not in ref_keys.invoice:
                    ref_keys.invoice.append(d_str)
                elif "PAY" in d_str.upper() and d_str not in ref_keys.payment:
                    ref_keys.payment.append(d_str)
                elif d_str not in ref_keys.invoice:
                    ref_keys.invoice.append(d_str)

        else: # SETTLEMENT
            ext_id = str(raw_row.get("settlement_id") or txn_id)
            amount_paise = cls._to_paise(raw_row.get("net", 0), amount_scale=scale)
            gross_paise = cls._to_paise(raw_row.get("gross", 0), amount_scale=scale)
            fee_paise = cls._to_paise(raw_row.get("fees", 0), amount_scale=scale)
            tax_paise = cls._to_paise(raw_row.get("tax_on_fees", 0), amount_scale=scale)
            
            date_val = raw_row.get("settlement_date") or raw_row.get("date")
            occurred_at, val_date = cls._parse_datetime(date_val)
            
            direction = TxnDirection.INFLOW
            txn_type = "SETTLEMENT_REPORT"
            cp_raw = "RAZORPAY"
            cp_norm = "razorpay"
            acct_code = "1010 Bank"

            if ext_id and ext_id not in ref_keys.settlement:
                ref_keys.settlement.append(ext_id)

        return CanonicalTransaction(
            id=txn_id,
            org_id=org_id,
            batch_id=batch_id,
            source_kind=source_kind,
            external_id=ext_id,
            txn_type=txn_type,
            direction=direction,
            amount_minor=amount_paise,
            amount=Decimal(amount_paise) / Decimal(100),
            gross_minor=gross_paise,
            fee_minor=fee_paise,
            tax_minor=tax_paise,
            currency="INR",
            occurred_at=occurred_at,
            value_date=val_date,
            counterparty_raw=cp_raw,
            counterparty_norm=cp_norm,
            description_raw=raw_desc,
            description_norm=norm_desc,
            reference_keys=ref_keys,
            account_code=acct_code,
            match_status=MatchStatus.UNMATCHED,
            normalizer_version="v1.0.0"
        )

    @staticmethod
    def detect_scale_mismatch(txns: List[CanonicalTransaction]) -> Optional[Dict[str, Any]]:
        """
        Flags a suspected minor-unit misconfiguration across sources.

        A wrong amount_scale is silent: matching simply drops to near zero while
        every individual amount still looks plausible on its own. Comparing the
        median magnitude per source surfaces it immediately. Returns None when
        the sources are mutually consistent.
        """
        medians: Dict[str, float] = {}
        for kind in {t.source_kind for t in txns}:
            amounts = [abs(t.amount_minor) for t in txns if t.source_kind == kind and t.amount_minor]
            if amounts:
                medians[getattr(kind, "value", str(kind))] = float(statistics.median(amounts))

        if len(medians) < 2:
            return None

        lo_src, lo = min(medians.items(), key=lambda kv: kv[1])
        hi_src, hi = max(medians.items(), key=lambda kv: kv[1])
        if lo <= 0 or (hi / lo) < SCALE_MISMATCH_RATIO:
            return None

        warning = {
            "code": "SUSPECTED_AMOUNT_SCALE_MISMATCH",
            "message": (
                f"Median amount for '{hi_src}' is {hi / lo:.0f}x that of '{lo_src}'. "
                f"This usually means one source reports minor units and the other major units. "
                f"Check SOURCE_AMOUNT_SCALE / source_profiles.amount_scale before trusting the match rate."
            ),
            "median_minor_by_source": medians,
            "ratio": round(hi / lo, 2),
        }
        logger.warning("[normalizer] %s", warning["message"])
        return warning
