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
        "payment", "payment_id", "invoice", "invoice_id", "settlement", "settlement_id",
        "order", "order_id", "journal", "journal_id", "debit", "credit", "ref", "pay",
        "inv", "utr", "je", "je_id", "date", "type", "description", "bank_transaction_id",
        "merchant_reference", "amount", "fee", "tax", "line", "line_no", "memo", "doc_ref"
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
        # Strip trailing banking direction suffixes like -CR, -DR, _CR, _DR
        pay_raw = [k for k in re.findall(r"\bPAY[-_]?[A-Za-z0-9]+(?:[-_][A-Za-z0-9]+)*", text, re.IGNORECASE) if k.lower() not in cls.EXCLUDE_KEYWORDS]
        pay_cleaned = []
        for p in pay_raw:
            cleaned = re.sub(r"[-_](?:CR|DR|cr|dr)$", "", p)
            if cleaned and cleaned.lower() not in cls.EXCLUDE_KEYWORDS:
                pay_cleaned.append(cleaned)
        if pay_cleaned:
            keys.payment = list(set(pay_cleaned))

        # Settlement references: e.g. setl_9KA22, SETL9KA22, SETL-01, SETTLE_BATCH_8821
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
        """
        if val is None or str(val).strip() == "":
            if default_zero:
                return 0
            raise ValueError("Empty or missing monetary value")
        try:
            val_cleaned = str(val).strip().replace(",", "")
            d = Decimal(val_cleaned)
            # Auto-Scale Intelligence:
            # If the raw value contains a decimal point (e.g. "1200.00", "430.25", "99.99"),
            # it represents major currency units (Rupees/Dollars). Minor units (paise) are integers.
            # If amount_scale is 1 but val has decimal fractions/places, scale up by 100 to avoid 100x truncation.
            effective_scale = amount_scale
            if amount_scale == 1 and "." in val_cleaned:
                parts = val_cleaned.split(".")
                if len(parts) == 2 and len(parts[1]) > 0:
                    effective_scale = 100
            return int((d * Decimal(effective_scale)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
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

    @classmethod
    def _first_present(cls, row: Dict[str, Any], *keys: str) -> Any:
        """Returns the first non-None, non-empty value from row matching any key (case-insensitive and format-agnostic)."""
        if not row:
            return None
        # 1. Exact match check
        for k in keys:
            if k in row and row[k] is not None and str(row[k]).strip() != "":
                return row[k]

        # 2. Case-insensitive and normalized key lookup
        norm_map = {}
        for rk, rv in row.items():
            if rk is not None and rv is not None and str(rv).strip() != "":
                norm_key = str(rk).strip().lower().replace(" ", "_").replace("-", "_")
                if norm_key not in norm_map:
                    norm_map[norm_key] = rv

        for k in keys:
            norm_k = str(k).strip().lower().replace(" ", "_").replace("-", "_")
            if norm_k in norm_map:
                return norm_map[norm_k]
        return None

    @classmethod
    def normalize_row(
        cls,
        raw_row: Dict[str, Any],
        source_kind: SourceKind,
        org_id: str,
        batch_id: str,
        amount_scale: Optional[int] = None,
        row_num: Optional[int] = None
    ) -> CanonicalTransaction:
        """
        Normalizes a single heterogeneous CSV/API row into a unified CanonicalTransaction
        with complete physical source lineage.
        """
        from app.models.schemas import JournalLine
        scale = resolve_amount_scale(source_kind, amount_scale)
        txn_id = str(uuid.uuid4())
        raw_desc = str(cls._first_present(raw_row, "description", "Description", "memo", "narrative") or "")
        norm_desc = cls.normalize_text(raw_desc)
        
        # Search for references in targeted content fields, NOT the dict keys repr
        ref_fields = [
            raw_desc,
            cls._first_present(raw_row, "ref_no", "doc_ref", "reference", "merchant_reference", "order_id", "payment_id", "entry_id", "txn_id") or "",
            cls._first_present(raw_row, "payment_id") or "",
            cls._first_present(raw_row, "order_id", "merchant_reference") or ""
        ]
        search_text = " ".join(str(f) for f in ref_fields if f)
        ref_keys = cls.extract_reference_keys(search_text)

        effective_row_num = row_num if row_num is not None else cls._first_present(raw_row, "__row_num__")
        source_filename = f"{source_kind.value.lower()}.csv"
        source_row_id = f"{source_filename}:row_{effective_row_num}" if effective_row_num else None

        payment_id_field = None
        order_id_field = None
        settlement_id_field = None
        journal_id_field = None
        journal_line_no_field = None
        orig_amount_str = None
        orig_date_str = None
        source_ref_str = None
        lines_list: List[JournalLine] = []
        has_explicit_dir = True
        txn_status = None
        settle_status = None
        gl_memo_field = None
        is_material_field = False
        declared_net_minor_field = None

        # Source-specific field normalization
        if source_kind == SourceKind.GATEWAY:
            ext_id = str(cls._first_present(raw_row, "transaction_id", "gateway_payment_id", "payment_id", "Payment ID", "gateway_record_id", "id", "txn_id") or txn_id)
            payment_id_field = ext_id
            gross_val = cls._first_present(raw_row, "gross_amount", "amount", "Gross Amount", "gross", "total")
            fee_val = cls._first_present(raw_row, "gateway_fee", "fee_amount", "fee", "Fee", "fees")
            tax_val = cls._first_present(raw_row, "tax_amount", "tax", "Tax", "tax_on_fees")
            
            orig_amount_str = str(gross_val or "")
            amount_paise = cls._to_paise(gross_val, default_zero=False, amount_scale=scale)
            gross_paise = amount_paise
            fee_paise = cls._to_paise(fee_val, default_zero=True, amount_scale=scale)
            tax_paise = cls._to_paise(tax_val, default_zero=True, amount_scale=scale)
            
            # Status & Settlement Status
            p_status = cls._first_present(raw_row, "payment_status", "status", "Payment Status")
            if p_status:
                txn_status = str(p_status).strip().upper()
            s_status = cls._first_present(raw_row, "settlement_status", "Settlement Status")
            if s_status:
                settle_status = str(s_status).strip().upper()
            
            # Net settlement
            net_val = cls._first_present(raw_row, "net_settlement", "net_amount", "net")
            if net_val is not None and str(net_val).strip() != "":
                declared_net_minor_field = cls._to_paise(net_val, default_zero=True, amount_scale=scale)

            if amount_paise >= 10000000:
                is_material_field = True

            date_val = cls._first_present(
                raw_row, "transaction_date", "captured_at", "created_at",
                "txn_date", "value_date", "date", "Date"
            )
            orig_date_str = str(date_val or "")
            occurred_at, val_date = cls._parse_datetime(date_val)
            
            dir_col = cls._first_present(raw_row, "direction", "type", "txn_type", "payment_type", "dr_cr")
            if dir_col:
                has_explicit_dir = True
                d_str = str(dir_col).strip().upper()
                if d_str in ("DEBIT", "OUTFLOW", "PAYOUT", "REFUND", "DR", "WITHDRAWAL", "EXPENSE"):
                    direction = TxnDirection.OUTFLOW
                else:
                    direction = TxnDirection.INFLOW
            else:
                has_explicit_dir = False
                direction = TxnDirection.INFLOW
            cp_raw = cls._first_present(raw_row, "customer_email", "Customer Email", "customer", "customer_name", "merchant_account") or "CUSTOMER_DIRECT"
            cp_norm = cp_raw.split("@")[0].lower() if "@" in cp_raw else cp_raw.lower()
            acct_code = "1210 Accounts Receivable"

            if ext_id and ext_id not in ref_keys.payment:
                ref_keys.payment.append(ext_id)

            # Explicit transaction_id and gateway_payment_id cross-stream keys
            txn_id_val = cls._first_present(raw_row, "transaction_id", "txn_id")
            if txn_id_val:
                t_str = str(txn_id_val).strip()
                if t_str not in ref_keys.payment:
                    ref_keys.payment.append(t_str)
                if t_str not in ref_keys.order:
                    ref_keys.order.append(t_str)

            gw_pay_val = cls._first_present(raw_row, "gateway_payment_id", "payment_id")
            if gw_pay_val:
                p_str = str(gw_pay_val).strip()
                if p_str not in ref_keys.payment:
                    ref_keys.payment.append(p_str)
            
            merch_ref = cls._first_present(raw_row, "merchant_reference", "order_id", "reference", "invoice_id")
            if merch_ref:
                m_str = str(merch_ref).strip()
                order_id_field = m_str
                if "INV" in m_str.upper() and m_str not in ref_keys.invoice:
                    ref_keys.invoice.append(m_str)
                elif m_str not in ref_keys.order:
                    ref_keys.order.append(m_str)

            settle_val = cls._first_present(raw_row, "settlement_id", "settlement_status")
            if settle_val and "SETTLED" not in str(settle_val).upper():
                s_id = str(settle_val).upper().replace("_", "")
                settlement_id_field = s_id
                if s_id not in ref_keys.settlement:
                    ref_keys.settlement.append(s_id)
            
            source_ref_str = str(cls._first_present(raw_row, "transaction_id", "gateway_payment_id", "merchant_reference", "order_id", "reference", "payment_id") or "")

        elif source_kind == SourceKind.BANK:
            ext_id = str(cls._first_present(raw_row, "transaction_id", "bank_reference", "bank_transaction_id", "bank_record_id", "Ref No", "ref_no", "utr", "id", "txn_id") or txn_id)
            source_ref_str = ext_id
            amt_val = cls._first_present(raw_row, "amount", "Amount", "net_amount", "Net Amount")
            credit_val = cls._first_present(raw_row, "Credit", "credit")
            debit_val = cls._first_present(raw_row, "Debit", "debit")
            type_str = str(cls._first_present(raw_row, "direction", "type", "Type") or "").upper()
            
            if amt_val is not None and str(amt_val).strip() != "":
                orig_amount_str = str(amt_val)
                amt_paise_val = cls._to_paise(amt_val, default_zero=False, amount_scale=scale)
                amount_paise = abs(amt_paise_val)
                direction = TxnDirection.OUTFLOW if (type_str in ("DEBIT", "DR", "WITHDRAWAL") or amt_paise_val < 0) else TxnDirection.INFLOW
            elif credit_val is not None and str(credit_val).strip() != "" and str(credit_val).strip() != "0":
                orig_amount_str = str(credit_val)
                amount_paise = cls._to_paise(credit_val, default_zero=False, amount_scale=scale)
                direction = TxnDirection.INFLOW
            elif debit_val is not None and str(debit_val).strip() != "" and str(debit_val).strip() != "0":
                orig_amount_str = str(debit_val)
                amount_paise = cls._to_paise(debit_val, default_zero=False, amount_scale=scale)
                direction = TxnDirection.OUTFLOW
            else:
                raise ValueError("Bank row missing valid amount, credit, or debit value")

            gross_paise = None
            fee_paise = None
            tax_paise = None

            b_status = cls._first_present(raw_row, "status", "Status", "txn_status")
            if b_status:
                txn_status = str(b_status).strip().upper()
            if amount_paise >= 10000000:
                is_material_field = True
            
            date_val = cls._first_present(
                raw_row, "transaction_date", "txn_date", "value_date",
                "Value Date", "Txn Date", "date", "Date"
            )
            orig_date_str = str(date_val or "")
            occurred_at, val_date = cls._parse_datetime(date_val)
            
            cp_raw = cls._first_present(raw_row, "counterparty", "party", "beneficiary", "customer", "customer_name", "merchant") or raw_desc or "BANK_DIRECT"
            cp_norm = cls.normalize_text(str(cp_raw)).split(" ")[0].lower() if cp_raw else "bank"
            acct_code = "1010 Bank Control"

            if ext_id and ext_id not in ref_keys.utr:
                ref_keys.utr.append(ext_id)

            # Explicit transaction_id and bank_reference cross-stream keys
            txn_id_val = cls._first_present(raw_row, "transaction_id", "txn_id")
            if txn_id_val:
                t_str = str(txn_id_val).strip()
                if t_str not in ref_keys.payment:
                    ref_keys.payment.append(t_str)
                if t_str not in ref_keys.utr:
                    ref_keys.utr.append(t_str)

            pay_ref = cls._first_present(raw_row, "payment_id", "bank_reference", "reference", "ref_no", "doc_ref")
            if pay_ref:
                p_str = str(pay_ref).strip()
                p_cleaned = re.sub(r"[-_](?:CR|DR|cr|dr)$", "", p_str)
                if "PAY" in p_cleaned.upper() and p_cleaned not in ref_keys.payment:
                    ref_keys.payment.append(p_cleaned)
                elif "INV" in p_str.upper() and p_str not in ref_keys.invoice:
                    ref_keys.invoice.append(p_str)
                elif p_cleaned not in ref_keys.utr:
                    ref_keys.utr.append(p_cleaned)

        elif source_kind == SourceKind.LEDGER:
            je_id = str(cls._first_present(raw_row, "transaction_id", "journal_id", "je_id", "entry_id", "journal_line_id", "document_id", "id") or "JE-000")
            line_no = str(cls._first_present(raw_row, "line_no", "line") or "1")
            journal_id_field = je_id
            journal_line_no_field = int(line_no) if line_no.isdigit() else 1
            ext_id = f"{je_id}:{line_no}" if ":" not in je_id else je_id
            
            debit_val = cls._first_present(raw_row, "debit", "debit_amount")
            credit_val = cls._first_present(raw_row, "credit", "credit_amount")
            if debit_val is not None and str(debit_val).strip() != "" and str(debit_val).strip() != "0":
                orig_amount_str = str(debit_val)
                amount_paise = cls._to_paise(debit_val, default_zero=False, amount_scale=scale)
                direction = TxnDirection.DEBIT
            elif credit_val is not None and str(credit_val).strip() != "" and str(credit_val).strip() != "0":
                orig_amount_str = str(credit_val)
                amount_paise = cls._to_paise(credit_val, default_zero=False, amount_scale=scale)
                direction = TxnDirection.CREDIT
            else:
                raise ValueError(f"Ledger row '{ext_id}' missing both debit and credit amounts")
            
            gross_paise = None
            fee_paise = None
            tax_paise = None

            l_status = cls._first_present(raw_row, "posting_status", "status", "Status")
            if l_status:
                txn_status = str(l_status).strip().upper()
            gl_memo_val = cls._first_present(raw_row, "control_note", "memo", "description")
            if gl_memo_val:
                gl_memo_field = str(gl_memo_val).strip()
            if amount_paise >= 10000000 or (gl_memo_field and "high_value" in gl_memo_field.lower()):
                is_material_field = True
            
            date_val = cls._first_present(
                raw_row, "posting_date", "entry_date", "posted_at",
                "txn_date", "value_date", "date", "Date"
            )
            orig_date_str = str(date_val or "")
            occurred_at, val_date = cls._parse_datetime(date_val)
            
            cp_raw = cls._first_present(raw_row, "counterparty", "account_name", "customer", "vendor")
            cp_norm = cls.normalize_text(str(cp_raw)).split(" ")[0].lower() if cp_raw else None
            acct_code = str(cls._first_present(raw_row, "gl_account", "account", "account_code", "account_name") or "1210 Accounts Receivable")

            if je_id and je_id not in ref_keys.je:
                ref_keys.je.append(je_id)

            # Explicit transaction_id link
            txn_id_val = cls._first_present(raw_row, "transaction_id", "txn_id")
            if txn_id_val:
                t_str = str(txn_id_val).strip()
                if t_str not in ref_keys.payment:
                    ref_keys.payment.append(t_str)
                if t_str not in ref_keys.je:
                    ref_keys.je.append(t_str)

            doc_ref = cls._first_present(raw_row, "doc_ref", "document_id", "reference", "ref_no")
            if doc_ref:
                d_str = str(doc_ref).strip()
                source_ref_str = d_str
                if "INV" in d_str.upper() and d_str not in ref_keys.invoice:
                    ref_keys.invoice.append(d_str)
                elif "PAY" in d_str.upper() and d_str not in ref_keys.payment:
                    ref_keys.payment.append(d_str)
                elif d_str not in ref_keys.invoice:
                    ref_keys.invoice.append(d_str)
                if "INV" in d_str.upper() and d_str not in ref_keys.invoice:
                    ref_keys.invoice.append(d_str)
                elif "PAY" in d_str.upper() and d_str not in ref_keys.payment:
                    ref_keys.payment.append(d_str)
                elif d_str not in ref_keys.invoice:
                    ref_keys.invoice.append(d_str)

            lines_list.append(JournalLine(
                line_no=journal_line_no_field,
                account_code=acct_code,
                account_name=str(cls._first_present(raw_row, "account_name") or ""),
                direction=direction,
                amount_minor=amount_paise,
                original_amount=orig_amount_str,
                memo=raw_desc,
                doc_ref=str(doc_ref or "")
            ))

        else: # SETTLEMENT
            ext_id = str(cls._first_present(raw_row, "settlement_id", "id") or txn_id)
            amount_paise = cls._to_paise(cls._first_present(raw_row, "net", "amount") or 0, amount_scale=scale)
            gross_paise = cls._to_paise(cls._first_present(raw_row, "gross", "gross_amount") or 0, amount_scale=scale)
            fee_paise = cls._to_paise(cls._first_present(raw_row, "fees", "fee", "fee_amount") or 0, amount_scale=scale)
            tax_paise = cls._to_paise(cls._first_present(raw_row, "tax_on_fees", "tax", "tax_amount") or 0, amount_scale=scale)
            
            date_val = cls._first_present(raw_row, "settlement_date", "date", "txn_date", "value_date")
            orig_date_str = str(date_val or "")
            occurred_at, val_date = cls._parse_datetime(date_val)
            
            direction = TxnDirection.INFLOW
            cp_raw = cls._first_present(raw_row, "counterparty", "processor", "gateway", "customer") or "PAYMENT_PROCESSOR"
            cp_norm = cls.normalize_text(str(cp_raw)).split(" ")[0].lower() if cp_raw else "processor"
            acct_code = "1010 Bank"

            if ext_id and ext_id not in ref_keys.settlement:
                ref_keys.settlement.append(ext_id)

        return CanonicalTransaction(
            id=txn_id,
            org_id=org_id,
            batch_id=batch_id,
            source_kind=source_kind,
            external_id=ext_id,
            direction=direction,
            amount_minor=amount_paise,
            gross_minor=gross_paise,
            fee_minor=fee_paise,
            tax_minor=tax_paise,
            currency=str(cls._first_present(raw_row, "currency", "Currency", "curr") or "INR").upper(),
            occurred_at=occurred_at,
            value_date=val_date,
            counterparty_raw=cp_raw,
            counterparty_norm=cp_norm,
            description_raw=raw_desc,
            description_norm=norm_desc,
            reference_keys=ref_keys,
            account_code=acct_code,
            match_status=MatchStatus.UNMATCHED,
            source_row_id=source_row_id,
            source_row_number=row_num,
            payment_id=payment_id_field,
            order_id=order_id_field,
            settlement_id=settlement_id_field,
            journal_id=journal_id_field,
            journal_line_no=journal_line_no_field,
            original_amount=orig_amount_str,
            normalized_amount=amount_paise,
            original_date=orig_date_str,
            normalized_date=val_date,
            source_reference=source_ref_str,
            lines=lines_list,
            has_explicit_direction=has_explicit_dir,
            status=txn_status,
            settlement_status=settle_status,
            gl_memo=gl_memo_field,
            is_material=is_material_field,
            declared_net_minor=declared_net_minor_field
        )

    @classmethod
    def normalize_journal_entry(
        cls,
        raw_rows: List[Dict[str, Any]],
        org_id: str,
        batch_id: str,
        amount_scale: Optional[int] = None
    ) -> CanonicalTransaction:
        """
        Normalizes a multi-line GL Journal Entry (e.g. AR Debit, Revenue Credit, GST Credit)
        into ONE unified CanonicalTransaction, preserving all lines in `lines`
        and verifying double-entry balance: sum(debits) == sum(credits).
        """
        from app.models.schemas import JournalLine
        if not raw_rows:
            raise ValueError("Cannot normalize empty journal entry row list")

        scale = resolve_amount_scale(SourceKind.LEDGER, amount_scale)
        txn_id = str(uuid.uuid4())
        
        first_row = raw_rows[0]
        je_id = str(cls._first_present(first_row, "transaction_id", "je_id", "journal_id", "entry_id", "document_id", "id") or "JE-000")
        row_num = cls._first_present(first_row, "__row_num__")
        source_row_id = f"general_ledger.csv:row_{row_num}" if row_num else None

        lines: List[JournalLine] = []
        total_debit = 0
        total_credit = 0
        ar_debit = 0
        ar_account_code = "1210 Accounts Receivable"
        all_doc_refs: List[str] = []
        all_memos: List[str] = []
        all_control_notes: List[str] = []
        statuses: List[str] = []
        dates: List[Any] = []

        for r in raw_rows:
            l_no = int(cls._first_present(r, "line_no", "line") or len(lines) + 1)
            acct_code = str(cls._first_present(r, "gl_account", "account_code", "account") or "")
            acct_name = str(cls._first_present(r, "account_name") or "")
            memo = str(cls._first_present(r, "memo", "description") or "")
            doc_ref = str(cls._first_present(r, "doc_ref", "document_id", "reference", "ref_no") or "")
            txn_id_col = str(cls._first_present(r, "transaction_id", "txn_id") or "")
            if txn_id_col and txn_id_col not in all_doc_refs:
                all_doc_refs.append(txn_id_col)
            
            if doc_ref:
                all_doc_refs.append(doc_ref)
            if memo:
                all_memos.append(memo)

            c_note = cls._first_present(r, "control_note", "memo")
            if c_note and str(c_note).strip():
                all_control_notes.append(str(c_note).strip())
            p_stat = cls._first_present(r, "posting_status", "status", "Status")
            if p_stat and str(p_stat).strip():
                statuses.append(str(p_stat).strip().upper())

            d_val = cls._first_present(r, "debit", "debit_amount")
            c_val = cls._first_present(r, "credit", "credit_amount")

            if d_val is not None and str(d_val).strip() not in ("", "0", "0.0", "0.00"):
                amt_paise = cls._to_paise(d_val, default_zero=False, amount_scale=scale)
                total_debit += amt_paise
                direction = TxnDirection.DEBIT
                orig_amt = str(d_val)
                if "1210" in acct_code or "RECEIVABLE" in acct_name.upper() or ar_debit == 0:
                    ar_debit = amt_paise
                    ar_account_code = acct_code if acct_code else "1210 Accounts Receivable"
            elif c_val is not None and str(c_val).strip() not in ("", "0", "0.0", "0.00"):
                amt_paise = cls._to_paise(c_val, default_zero=False, amount_scale=scale)
                total_credit += amt_paise
                direction = TxnDirection.CREDIT
                orig_amt = str(c_val)
            else:
                amt_paise = 0
                direction = TxnDirection.DEBIT
                orig_amt = "0"

            dt_val = cls._first_present(r, "posted_at", "posting_date", "entry_date", "date", "txn_date", "value_date")
            if dt_val:
                dates.append(dt_val)

            lines.append(JournalLine(
                line_no=l_no,
                account_code=acct_code,
                account_name=acct_name,
                direction=direction,
                amount_minor=amt_paise,
                original_amount=orig_amt,
                memo=memo,
                doc_ref=doc_ref
            ))

        # Check double-entry balance
        is_balanced = (total_debit == total_credit)

        # Primary transaction amount: use Accounts Receivable debit leg for 3-way matching tie-out
        primary_amount_minor = ar_debit if ar_debit > 0 else (total_debit if total_debit > 0 else total_credit)

        # Parse date from first available date
        date_val = dates[0] if dates else datetime.now(timezone.utc)
        occurred_at, val_date = cls._parse_datetime(date_val)

        # Build reference keys
        combined_text = f"{je_id} {' '.join(all_doc_refs)} {' '.join(all_memos)}"
        ref_keys = cls.extract_reference_keys(combined_text)
        if je_id not in ref_keys.je:
            ref_keys.je.append(je_id)
        if "TXN" in je_id.upper() and je_id not in ref_keys.payment:
            ref_keys.payment.append(je_id)
        for d in all_doc_refs:
            if "INV" in d.upper() and d not in ref_keys.invoice:
                ref_keys.invoice.append(d)
            elif "PAY" in d.upper() and d not in ref_keys.payment:
                ref_keys.payment.append(d)
            elif "TXN" in d.upper() and d not in ref_keys.payment:
                ref_keys.payment.append(d)
            elif d not in ref_keys.invoice:
                ref_keys.invoice.append(d)

        # Determine semantic status and memo
        je_status = "REVERSED" if "REVERSED" in statuses else (statuses[0] if statuses else "POSTED")
        defect_notes = [n for n in all_control_notes if n.lower() not in ("balanced", "")]
        if defect_notes:
            je_memo = defect_notes[0]
        elif all_memos:
            je_memo = all_memos[0]
        else:
            je_memo = "balanced"

        is_material_je = (primary_amount_minor >= 10000000 or total_debit >= 10000000 or (je_memo and "high_value" in str(je_memo).lower()))

        primary_memo = all_memos[0] if all_memos else f"Journal Entry {je_id}"
        norm_desc = cls.normalize_text(primary_memo)

        return CanonicalTransaction(
            id=txn_id,
            org_id=org_id,
            batch_id=batch_id,
            source_kind=SourceKind.LEDGER,
            external_id=je_id,
            direction=TxnDirection.DEBIT if total_debit >= total_credit else TxnDirection.CREDIT,
            amount_minor=primary_amount_minor,
            gross_minor=primary_amount_minor,
            currency="INR",
            occurred_at=occurred_at,
            value_date=val_date,
            description_raw=primary_memo,
            description_norm=norm_desc,
            reference_keys=ref_keys,
            account_code=ar_account_code,
            match_status=MatchStatus.UNMATCHED,
            source_row_id=source_row_id,
            source_row_number=row_num,
            journal_id=je_id,
            original_amount=f"Debit: {Decimal(total_debit)/100} / Credit: {Decimal(total_credit)/100}",
            normalized_amount=primary_amount_minor,
            original_date=str(date_val),
            normalized_date=val_date,
            source_reference=all_doc_refs[0] if all_doc_refs else je_id,
            lines=lines,
            is_balanced_je=is_balanced,
            total_debit_minor=total_debit,
            total_credit_minor=total_credit,
            status=je_status,
            gl_memo=je_memo,
            is_material=is_material_je,
            declared_net_minor=None
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
