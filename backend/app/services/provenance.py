"""
Diagnostic Input Provenance Tracker for AI Financial Controller
Tracks, verifies, and logs the complete audit trail of data entering the pipeline:
- Exact file paths, SHA-256 hashes, byte sizes
- Raw line/row counts, parsed row counts, normalized transaction counts
- Record identifiers (first 3 and last 3)
- Explicit classification: USER_UPLOAD vs SYNTHETIC vs TEST_FIXTURE
- Strict safety guard: Raises USER_INPUT_FILE_NOT_FOUND when expected user files are missing
"""

import os
import csv
import hashlib
from typing import Any, Dict, List, Optional, Tuple
from app.core.config import settings
from app.models.schemas import (
    SourceKind, CanonicalTransaction, ProvenanceSourceType,
    SourceProvenance, BatchProvenanceManifest
)


class InputProvenanceService:
    @staticmethod
    def compute_file_sha256(file_path: str) -> str:
        """Computes SHA-256 hash of the exact file on disk."""
        sha = hashlib.sha256()
        with open(file_path, "rb") as f:
            while chunk := f.read(65536):
                sha.update(chunk)
        return sha.hexdigest()

    @staticmethod
    def count_raw_csv_rows(file_path: str) -> int:
        """Counts raw non-empty data rows in a CSV file (excluding header)."""
        count = 0
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            reader = csv.reader(f)
            try:
                next(reader) # Skip header
            except StopIteration:
                return 0
            for row in reader:
                if row and any(field.strip() for field in row):
                    count += 1
        return count

    @classmethod
    def assert_user_upload_file_exists(cls, file_path: str) -> str:
        """Strict safety check: If file is missing, fail immediately without generating fallback data."""
        candidates = [
            os.path.abspath(file_path),
            os.path.abspath(os.path.join(os.getcwd(), file_path)),
            os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../", file_path)),
            os.path.abspath(os.path.join(os.path.dirname(__file__), "../../", file_path)),
            os.path.abspath(os.path.join(settings.DATA_DIR, os.path.basename(file_path)))
        ]
        for p in candidates:
            if os.path.exists(p) and os.path.isfile(p):
                return p
        raise FileNotFoundError(f"USER_INPUT_FILE_NOT_FOUND: The required input file does not exist at '{candidates[0]}'. Synthetic fallback is strictly blocked.")

    @classmethod
    def track_file_provenance(
        cls,
        batch_id: str,
        source_kind: SourceKind,
        file_path: str,
        source_type: ProvenanceSourceType,
        normalized_txns: List[CanonicalTransaction],
        parsed_count: int,
        original_filename: Optional[str] = None
    ) -> SourceProvenance:
        """Constructs a cryptographic provenance record for a real file source."""
        abs_path = os.path.abspath(file_path)
        cls.assert_user_upload_file_exists(abs_path)

        sha = cls.compute_file_sha256(abs_path)
        file_size = os.path.getsize(abs_path)
        raw_rows = cls.count_raw_csv_rows(abs_path)

        ids = [t.external_id for t in normalized_txns]
        first_3 = ids[:3]
        last_3 = ids[-3:] if len(ids) > 3 else ids

        return SourceProvenance(
            batch_id=batch_id,
            source_kind=source_kind,
            source_type=source_type,
            original_filename=original_filename or os.path.basename(abs_path),
            absolute_file_path=abs_path,
            sha256_hash=sha,
            file_size_bytes=file_size,
            raw_rows_count=raw_rows,
            parsed_rows_count=parsed_count,
            normalized_rows_count=len(normalized_txns),
            first_3_record_ids=first_3,
            last_3_record_ids=last_3
        )

    @classmethod
    def track_synthetic_provenance(
        cls,
        batch_id: str,
        source_kind: SourceKind,
        synthetic_records: List[Dict[str, Any]],
        normalized_txns: List[CanonicalTransaction]
    ) -> SourceProvenance:
        """Constructs a provenance record for in-memory synthetic data."""
        ids = [t.external_id for t in normalized_txns]
        first_3 = ids[:3]
        last_3 = ids[-3:] if len(ids) > 3 else ids

        # Compute synthetic payload fingerprint
        preimage = f"SYNTHETIC:{batch_id}:{source_kind.value}:{len(synthetic_records)}:{str(ids[:5])}"
        sha = hashlib.sha256(preimage.encode("utf-8")).hexdigest()

        return SourceProvenance(
            batch_id=batch_id,
            source_kind=source_kind,
            source_type=ProvenanceSourceType.SYNTHETIC,
            original_filename=f"synthetic_{source_kind.value.lower()}_stream",
            absolute_file_path="IN_MEMORY_SYNTHETIC_GENERATOR",
            sha256_hash=sha,
            file_size_bytes=len(str(synthetic_records).encode("utf-8")),
            raw_rows_count=len(synthetic_records),
            parsed_rows_count=len(synthetic_records),
            normalized_rows_count=len(normalized_txns),
            first_3_record_ids=first_3,
            last_3_record_ids=last_3
        )

    @classmethod
    def verify_uploaded_hashes(cls, expected_hashes: Dict[str, str], file_paths: Dict[str, str]) -> bool:
        """
        Final pre-reconciliation integrity verification:
        Verifies that the computed SHA-256 hash of each file opened on disk
        matches the expected uploaded hash. If any mismatch is found, stops processing immediately.
        """
        for source_key, expected_hash in expected_hashes.items():
            if source_key in file_paths:
                f_path = file_paths[source_key]
                cls.assert_user_upload_file_exists(f_path)
                actual_hash = cls.compute_file_sha256(f_path)
                if actual_hash.lower() != expected_hash.lower():
                    raise ValueError(
                        f"HASH_VERIFICATION_FAILED: Hash mismatch for source '{source_key}'. "
                        f"Expected hash: '{expected_hash}', but actual disk file '{f_path}' hash is '{actual_hash}'. "
                        f"Reconciliation halted immediately."
                    )
        return True

    @classmethod
    def build_batch_manifest(
        cls,
        batch_id: str,
        overall_source_type: ProvenanceSourceType,
        source_provenances: List[SourceProvenance],
        execution_mode: Optional[Any] = None
    ) -> BatchProvenanceManifest:
        from app.models.schemas import ExecutionMode
        mode = ExecutionMode.USER_UPLOAD
        if execution_mode:
            mode = execution_mode if isinstance(execution_mode, ExecutionMode) else ExecutionMode(str(execution_mode))
        elif overall_source_type == ProvenanceSourceType.SYNTHETIC:
            mode = ExecutionMode.SYNTHETIC_BENCHMARK
        elif overall_source_type == ProvenanceSourceType.TEST_FIXTURE:
            mode = ExecutionMode.INTERNAL_TEST

        manifest = BatchProvenanceManifest(
            batch_id=batch_id,
            execution_mode=mode,
            overall_source_type=overall_source_type,
            sources={p.source_kind.value: p for p in source_provenances},
            total_raw_rows=sum(p.raw_rows_count for p in source_provenances),
            total_normalized_records=sum(p.normalized_rows_count for p in source_provenances)
        )
        return manifest

    @classmethod
    def format_console_provenance(cls, manifest: BatchProvenanceManifest) -> str:
        """Formats human-readable diagnostic provenance block."""
        lines = []
        lines.append("=" * 80)
        lines.append("INPUT PROVENANCE")
        lines.append("=" * 80)

        order = ["GATEWAY", "BANK", "LEDGER", "SETTLEMENT"]
        for sk in order:
            if sk in manifest.sources:
                p = manifest.sources[sk]
                title = "Gateway" if sk == "GATEWAY" else ("Bank" if sk == "BANK" else ("Ledger" if sk == "LEDGER" else "Settlement"))
                lines.append(f"{title}:")
                lines.append(f"source_type={p.source_type.value}")
                lines.append(f"filename={p.original_filename}")
                lines.append(f"path={p.absolute_file_path}")
                lines.append(f"sha256={p.sha256_hash}")
                lines.append(f"file_size_bytes={p.file_size_bytes}")
                lines.append(f"raw_rows={p.raw_rows_count}")
                lines.append(f"parsed_rows={p.parsed_rows_count}")
                lines.append(f"normalized_rows={p.normalized_rows_count}")
                lines.append(f"first_3_ids={p.first_3_record_ids}")
                lines.append(f"last_3_ids={p.last_3_record_ids}")
                lines.append("")

        lines.append(f"OVERALL SOURCE TYPE: {manifest.overall_source_type.value}")
        lines.append(f"TOTAL RAW ROWS:      {manifest.total_raw_rows}")
        lines.append(f"TOTAL NORMALIZED:    {manifest.total_normalized_records}")
        lines.append("=" * 80)
        return "\n".join(lines)
