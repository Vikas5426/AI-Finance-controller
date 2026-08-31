"""
Layer 1: Data Validation & Integrity Gate
Validates canonical transactions before matching. Flags missing IDs, duplicate keys,
timestamp anomalies, and sign/currency inconsistencies.
"""

from typing import Dict, List, Set, Tuple
from app.models.schemas import CanonicalTransaction, SourceKind

class ValidationResult:
    def __init__(self, status: str, errors: List[str], warnings: List[str]):
        self.status = status # VALID, WARNING, INVALID
        self.errors = errors
        self.warnings = warnings

class DataValidationService:
    """Pre-flight financial validation gate."""

    @staticmethod
    def validate_batch(transactions: List[CanonicalTransaction]) -> Dict[str, ValidationResult]:
        results: Dict[str, ValidationResult] = {}
        seen_external_ids: Dict[Tuple[str, str], str] = {}

        for txn in transactions:
            errors: List[str] = []
            warnings: List[str] = []

            # 1. External ID & Primary Key check
            if not txn.external_id or txn.external_id.strip() == "":
                errors.append("MISSING_EXTERNAL_ID")

            # 2. Duplicate ID within same source
            src_key = (txn.source_kind.value, txn.external_id)
            if src_key in seen_external_ids:
                errors.append(f"DUPLICATE_SOURCE_RECORD (matches {seen_external_ids[src_key]})")
            else:
                seen_external_ids[src_key] = txn.id

            # 3. Monetary value integrity
            if txn.amount_minor == 0:
                warnings.append("ZERO_AMOUNT_TRANSACTION")
            elif txn.amount_minor < 0:
                warnings.append("NEGATIVE_AMOUNT_REVERSAL")

            # 4. Currency validation
            if not txn.currency or len(txn.currency) != 3:
                errors.append("INVALID_CURRENCY_CODE")

            # 5. Timestamp bounds
            if txn.occurred_at.year < 2020 or txn.occurred_at.year > 2030:
                errors.append("OUT_OF_BOUNDS_TIMESTAMP")

            # Determine status
            if errors:
                status = "INVALID"
            elif warnings:
                status = "WARNING"
            else:
                status = "VALID"

            results[txn.id] = ValidationResult(status, errors, warnings)

        return results
