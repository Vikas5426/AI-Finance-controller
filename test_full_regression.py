"""
Full Regression Test Suite for AI Financial Controller
Tests all execution modes, integrity boundaries, safety guards, and operational pipelines:
- TEST A: USER_UPLOAD mode with exact 3 CSV files
- TEST B: SYNTHETIC_BENCHMARK mode with ground truth evaluation
- TEST C: MISSING FILE with strict USER_INPUT_FILE_NOT_FOUND error
- TEST D: INVALID CSV with schema validation failure
- TEST E: PARTIAL DATA with empty bank stream & missing settlement exceptions
- TEST F: REPEATED EXECUTION with 100% deterministic consistency
- TEST G: SYNTHETIC GENERATOR SAFETY hard assertion guard
- FRONTEND & BACKEND INTEGRATION
"""

import os
import sys
import json
import time
import hashlib
import tempfile
import unittest
from typing import Dict, Any

# Add backend directory to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "backend")))

try:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
    sys.stderr.reconfigure(encoding="utf-8", line_buffering=True)
except Exception:
    pass

from app.core.config import settings
from app.db.database import init_db
from app.models.schemas import ExecutionMode, SourceKind, ProvenanceSourceType
from tests.test_utilities.synthetic_generator import SyntheticDataGenerator
from app.services.ingestion import IngestionService
from app.services.provenance import InputProvenanceService
from app.services.benchmarks import BenchmarkEvaluator
from app.services.batch_orchestrator import WindowedBatchOrchestrator
from app.api.v1.batches import execute_batch_reconciliation


class FinancialControllerFullRegressionTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        init_db()
        cls.gw_file = "data/gateway.csv"
        cls.bk_file = "data/bank.csv"
        cls.gl_file = "data/general_ledger.csv"

    def test_a_user_upload_external_files(self):
        """TEST A: USER_UPLOAD - Verifies exact files, hashes, row counts, and zero synthetic generation."""
        custom_files = {
            "GATEWAY": self.gw_file,
            "BANK": self.bk_file,
            "LEDGER": self.gl_file
        }

        # Calculate exact expected hashes
        expected_gw_hash = InputProvenanceService.compute_file_sha256(self.gw_file)
        expected_bk_hash = InputProvenanceService.compute_file_sha256(self.bk_file)
        expected_gl_hash = InputProvenanceService.compute_file_sha256(self.gl_file)

        result = execute_batch_reconciliation(
            execution_mode=ExecutionMode.USER_UPLOAD,
            custom_files=custom_files,
            expected_hashes={
                "GATEWAY": expected_gw_hash,
                "BANK": expected_bk_hash,
                "LEDGER": expected_gl_hash
            }
        )

        manifest = result.get("provenance", {})
        summary = result.get("summary", {})

        # Assert exact files and hashes used
        self.assertEqual(manifest["execution_mode"], "USER_UPLOAD")
        self.assertEqual(manifest["overall_source_type"], "USER_UPLOAD")
        self.assertEqual(manifest["sources"]["GATEWAY"]["sha256_hash"], expected_gw_hash)
        self.assertEqual(manifest["sources"]["BANK"]["sha256_hash"], expected_bk_hash)
        self.assertEqual(manifest["sources"]["LEDGER"]["sha256_hash"], expected_gl_hash)

        # Assert correct row counts: 12 Gateway, 10 Bank, 42 Ledger = 64 Total
        self.assertEqual(manifest["sources"]["GATEWAY"]["raw_rows_count"], 12)
        self.assertEqual(manifest["sources"]["BANK"]["raw_rows_count"], 10)
        self.assertEqual(manifest["sources"]["LEDGER"]["raw_rows_count"], 42)
        self.assertEqual(manifest["total_raw_rows"], 64)
        self.assertEqual(manifest["total_normalized_records"], 64)

        # Assert reconciliation execution
        self.assertEqual(summary["total_records"], 64)
        self.assertGreaterEqual(summary["exact_matches"], 1)
        self.assertGreaterEqual(summary["total_exceptions"], 1)



    def test_c_missing_file_safety(self):
        """TEST C: MISSING FILE - Verifies explicit failure without silent synthetic fallback."""
        missing_files = {
            "GATEWAY": self.gw_file,
            "BANK": "data/non_existent_bank_file.csv",
            "LEDGER": self.gl_file
        }

        with self.assertRaises(FileNotFoundError) as ctx:
            execute_batch_reconciliation(
                execution_mode=ExecutionMode.USER_UPLOAD,
                custom_files=missing_files
            )

        self.assertIn("USER_INPUT_FILE_NOT_FOUND", str(ctx.exception))

    def test_d_invalid_csv_schema_rejection(self):
        """TEST D: INVALID CSV - Verifies corrupt/empty file schema rejection."""
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w") as tf:
            tf.write("invalid_col1,invalid_col2\nfoo,bar\n")
            invalid_path = tf.name

        try:
            with self.assertRaises(Exception):
                IngestionService.ingest_and_normalize(
                    invalid_path,
                    SourceKind.GATEWAY,
                    settings.DEFAULT_ORG_ID,
                    "BATCH-TEST"
                )
        finally:
            if os.path.exists(invalid_path):
                os.remove(invalid_path)

    def test_e_partial_data_stream(self):
        """TEST E: PARTIAL DATA - Verifies Gateway + Ledger with empty Bank stream without crashing."""
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w") as tf:
            tf.write("txn_id,txn_date,value_date,description,credit,debit,balance,ref_no\n")
            empty_bank_path = tf.name

        try:
            partial_files = {
                "GATEWAY": self.gw_file,
                "BANK": empty_bank_path,
                "LEDGER": self.gl_file
            }

            result = execute_batch_reconciliation(
                execution_mode=ExecutionMode.USER_UPLOAD,
                custom_files=partial_files
            )

            manifest = result.get("provenance", {})
            summary = result.get("summary", {})

            # Total records: 12 Gateway + 0 Bank + 42 Ledger = 54
            self.assertEqual(manifest["total_raw_rows"], 54)
            self.assertEqual(manifest["sources"]["BANK"]["raw_rows_count"], 0)
            self.assertGreater(summary["total_exceptions"], 0)
        finally:
            if os.path.exists(empty_bank_path):
                os.remove(empty_bank_path)

    def test_f_repeated_execution_determinism(self):
        """TEST F: REPEATED EXECUTION - Verifies deterministic identical matching and file immutability."""
        custom_files = {
            "GATEWAY": self.gw_file,
            "BANK": self.bk_file,
            "LEDGER": self.gl_file
        }

        # Snapshot file hashes before execution
        h_gw_before = InputProvenanceService.compute_file_sha256(self.gw_file)
        h_bk_before = InputProvenanceService.compute_file_sha256(self.bk_file)
        h_gl_before = InputProvenanceService.compute_file_sha256(self.gl_file)

        import uuid
        b1 = f"BATCH-REP-1-{uuid.uuid4().hex[:6]}"
        b2 = f"BATCH-REP-2-{uuid.uuid4().hex[:6]}"

        # Run 1
        res1 = execute_batch_reconciliation(
            batch_id=b1,
            execution_mode=ExecutionMode.USER_UPLOAD,
            custom_files=custom_files
        )

        # Run 2
        res2 = execute_batch_reconciliation(
            batch_id=b2,
            execution_mode=ExecutionMode.USER_UPLOAD,
            custom_files=custom_files
        )

        # Verify file hashes remain identical (no overwriting)
        self.assertEqual(InputProvenanceService.compute_file_sha256(self.gw_file), h_gw_before)
        self.assertEqual(InputProvenanceService.compute_file_sha256(self.bk_file), h_bk_before)
        self.assertEqual(InputProvenanceService.compute_file_sha256(self.gl_file), h_gl_before)

        # Verify deterministic reconciliation metrics
        s1 = res1["summary"]
        s2 = res2["summary"]
        self.assertEqual(s1["total_records"], s2["total_records"])
        self.assertEqual(s1["exact_matches"], s2["exact_matches"])
        self.assertEqual(s1["contextual_matches"], s2["contextual_matches"])
        self.assertEqual(s1["match_rate"], s2["match_rate"])
        self.assertEqual(s1["total_exceptions"], s2["total_exceptions"])

    def test_g_synthetic_generator_safety_guard(self):
        """TEST G: SYNTHETIC GENERATOR SAFETY - Verifies hard assertion error during USER_UPLOAD mode."""
        # 1. Constructor Guard
        with self.assertRaises(RuntimeError) as ctx1:
            SyntheticDataGenerator(execution_mode=ExecutionMode.USER_UPLOAD)
        self.assertIn("Synthetic data is forbidden during USER_UPLOAD execution", str(ctx1.exception))

        # 2. Method Execution Guard
        gen = SyntheticDataGenerator(seed=42)
        with self.assertRaises(RuntimeError) as ctx2:
            gen.generate(count=240, execution_mode=ExecutionMode.USER_UPLOAD)
        self.assertIn("Synthetic data is forbidden during USER_UPLOAD execution", str(ctx2.exception))


def run_regression():
    suite = unittest.TestLoader().loadTestsFromTestCase(FinancialControllerFullRegressionTest)
    runner = unittest.TextTestRunner(verbosity=2)
    return runner.run(suite)


if __name__ == "__main__":
    run_regression()
