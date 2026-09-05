import csv
import hashlib
import io
import json
import os
from typing import Any, Dict, List, Optional, Tuple
import polars as pl
from app.models.schemas import SourceKind, CanonicalTransaction
from app.services.normalizer import NormalizerService

class IngestionService:
    @staticmethod
    def compute_file_hash(content: bytes) -> str:
        return hashlib.sha256(content).hexdigest()

    @staticmethod
    def compute_row_hash(source_id: str, row_payload: Dict[str, Any]) -> str:
        canonical_str = json.dumps(row_payload, sort_keys=True, separators=(',', ':'), default=str)
        preimage = f"{source_id}|{canonical_str}"
        return hashlib.sha256(preimage.encode("utf-8")).hexdigest()

    @classmethod
    def parse_file(
        cls,
        file_path: str,
        source_kind: SourceKind,
        column_map: Optional[Dict[str, str]] = None,
        amount_scale: int = 100
    ) -> List[Dict[str, Any]]:
        """Parses CSV/TSV/JSON file using Polars and robust Python fallback with smart header row detection."""
        ext = os.path.splitext(file_path)[1].lower()
        records: List[Dict[str, Any]] = []

        if ext == ".json":
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    raw_rows = data
                else:
                    raw_rows = [data]
            for row in raw_rows:
                records.append(row)
            return records

        import io
        financial_keywords = {
            "date", "amount", "debit", "credit", "txn_id", "id", "description", "desc", "memo",
            "reference", "ref_no", "payment_id", "order_id", "je_id", "posted_at", "account_code",
            "currency", "type", "withdrawal", "deposit", "gross", "fee", "tax", "narrative",
            "particulars", "party", "beneficiary", "utr", "settlement_id", "customer", "remarks"
        }

        # 1. Read raw text to handle leading title/metadata rows and detect true header
        cleaned_content = ""
        try:
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()

            lines = content.splitlines()
            header_idx = 0
            for idx, line in enumerate(lines[:20]):
                line_str = line.strip()
                if not line_str:
                    continue
                # Check standard delimiters
                for delim in (",", ";", "\t", "|"):
                    tokens = [t.strip().strip('"').strip("'").lower() for t in line_str.split(delim)]
                    if len(tokens) > 1 and any(tok in financial_keywords or any(k in tok for k in ("date", "amount", "id", "ref", "desc", "debit", "credit")) for tok in tokens):
                        header_idx = idx
                        break
                if header_idx > 0 or (idx == 0 and len([t for t in line_str.split(',') if t]) > 1):
                    break

            cleaned_content = "\n".join(lines[header_idx:])
        except Exception:
            pass

        # Try Polars first on cleaned content
        if cleaned_content:
            try:
                df = pl.read_csv(io.StringIO(cleaned_content), infer_schema_length=10000, ignore_errors=True)
                if len(df.columns) > 1:
                    for row in df.iter_rows(named=True):
                        cleaned_row = {k: ("" if v is None else v) for k, v in row.items()}
                        if any(str(v).strip() for v in cleaned_row.values() if v is not None and str(v).strip() != ""):
                            records.append(cleaned_row)
                    if records:
                        return records
            except Exception:
                pass

        # Robust Python CSV reader fallback
        try:
            target_stream = io.StringIO(cleaned_content) if cleaned_content else open(file_path, "r", encoding="utf-8", errors="replace")
            sample = cleaned_content[:2048] if cleaned_content else ""
            dialect = csv.excel
            if sample:
                try:
                    dialect = csv.Sniffer().sniff(sample)
                except Exception:
                    dialect = csv.excel
            reader = csv.DictReader(target_stream, dialect=dialect)
            for row in reader:
                cleaned_row = {k: ("" if v is None else v) for k, v in row.items()}
                if any(str(v).strip() for v in cleaned_row.values() if v is not None and str(v).strip() != ""):
                    records.append(cleaned_row)
        except Exception:
            pass

        return records

    @classmethod
    def validate_schema(cls, headers: List[str], source_kind: SourceKind, file_path: str):
        """Validates that uploaded CSV has minimum viable financial columns for normalization."""
        norm_headers = {h.strip().lower() for h in headers if h}
        if not norm_headers:
            return

        if source_kind == SourceKind.GATEWAY:
            has_id = any(h in norm_headers for h in ("payment_id", "id", "order_id", "txn_id", "ref_no", "transaction_id", "reference", "doc_ref", "external_id", "payment", "txnid"))
            has_amt = any(any(k in h for k in ("amount", "gross", "net", "total", "value", "debit", "credit")) for h in norm_headers)
            if not has_id or not has_amt:
                raise ValueError(f"SCHEMA_VALIDATION_FAILED: Gateway CSV '{file_path}' is missing essential columns (requires payment_id/order_id and amount). Found: {list(norm_headers)}")

        elif source_kind == SourceKind.BANK:
            has_amt = any(h in norm_headers for h in ("credit", "debit", "amount", "withdrawal", "deposit", "net", "gross", "balance", "val", "dr", "cr"))
            has_ref = any(h in norm_headers for h in ("description", "desc", "memo", "ref_no", "utr", "txn_id", "narrative", "reference", "party", "beneficiary", "particulars", "remarks", "details", "id"))
            if not has_amt and not has_ref:
                raise ValueError(f"SCHEMA_VALIDATION_FAILED: Bank CSV '{file_path}' is missing essential columns (requires credit/debit and description/ref_no). Found: {list(norm_headers)}")

        elif source_kind == SourceKind.LEDGER:
            has_amt = any(h in norm_headers for h in ("debit", "credit", "amount", "debit_amount", "credit_amount", "net", "gross", "total"))
            has_ref = any(h in norm_headers for h in ("doc_ref", "je_id", "journal_id", "entry_id", "memo", "account_code", "account", "account_name", "reference", "description", "particulars", "id"))
            if not has_amt or not has_ref:
                raise ValueError(f"SCHEMA_VALIDATION_FAILED: General Ledger CSV '{file_path}' is missing essential columns (requires debit/credit and doc_ref/memo/account_code). Found: {list(norm_headers)}")

    @classmethod
    def ingest_and_normalize(
        cls,
        file_path: str,
        source_kind: SourceKind,
        org_id: str,
        batch_id: str,
        amount_scale: Optional[int] = None
    ) -> Tuple[List[CanonicalTransaction], int]:
        """
        Parses a file, validates schema, and converts rows into CanonicalTransactions.

        ``amount_scale`` overrides the per-source minor-unit multiplier; leave it
        None to use the documented default for this source kind.
        """
        raw_rows = cls.parse_file(file_path, source_kind)
        if raw_rows:
            headers = list(raw_rows[0].keys())
            cls.validate_schema(headers, source_kind, file_path)

        canonical_txns: List[CanonicalTransaction] = []
        for idx, row in enumerate(raw_rows, start=2):
            row["__row_num__"] = idx

        if source_kind == SourceKind.LEDGER:
            # Group multi-line journal entries by je_id so each JE is ONE CanonicalTransaction
            je_groups: Dict[str, List[Dict[str, Any]]] = {}
            for row in raw_rows:
                if not any(str(v).strip() for k, v in row.items() if v is not None and not k.startswith("__")):
                    continue
                je_id = str(NormalizerService._first_present(row, "transaction_id", "je_id", "journal_id", "entry_id", "journal_line_id", "document_id", "id") or f"JE-{len(je_groups)+1:04d}")
                je_groups.setdefault(je_id, []).append(row)

            for je_id, group in je_groups.items():
                txn = NormalizerService.normalize_journal_entry(
                    group, org_id, batch_id, amount_scale=amount_scale
                )
                canonical_txns.append(txn)
        else:
            for row in raw_rows:
                if not any(str(v).strip() for k, v in row.items() if v is not None and not k.startswith("__")):
                    continue
                txn = NormalizerService.normalize_row(
                    row, source_kind, org_id, batch_id, amount_scale=amount_scale
                )
                canonical_txns.append(txn)

        return canonical_txns, len(raw_rows)
