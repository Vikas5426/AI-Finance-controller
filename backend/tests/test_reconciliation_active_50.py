import os
import sys
import json
import unittest

# Ensure backend path is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.models.schemas import SourceKind, MatchTypeEnum
from app.services.ingestion import IngestionService
from app.services.matching_engine import ReconciliationEngine


class TestReconciliationActive50(unittest.TestCase):
    """
    Verification suite for the active 50-record dataset:
    data/gateway.csv, data/bank.csv, data/general_ledger.csv, and data/ground_truth_links.json.
    """

    @classmethod
    def setUpClass(cls):
        cls.org_id = "00000000-0000-0000-0000-000000000001"
        cls.batch_id = "BATCH-VERIFY-50-DATASET"
        cls.root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

        cls.gw_path = os.path.join(cls.root_dir, "data", "gateway.csv")
        cls.bk_path = os.path.join(cls.root_dir, "data", "bank.csv")
        cls.gl_path = os.path.join(cls.root_dir, "data", "general_ledger.csv")
        cls.gt_path = os.path.join(cls.root_dir, "data", "ground_truth_links.json")

        assert os.path.exists(cls.gw_path), f"Missing {cls.gw_path}"
        assert os.path.exists(cls.bk_path), f"Missing {cls.bk_path}"
        assert os.path.exists(cls.gl_path), f"Missing {cls.gl_path}"
        assert os.path.exists(cls.gt_path), f"Missing {cls.gt_path}"

        # Ingest and normalize raw CSV records
        cls.gw_txns, _ = IngestionService.ingest_and_normalize(
            cls.gw_path, SourceKind.GATEWAY, cls.org_id, cls.batch_id
        )
        cls.bk_txns, _ = IngestionService.ingest_and_normalize(
            cls.bk_path, SourceKind.BANK, cls.org_id, cls.batch_id
        )
        cls.gl_txns, _ = IngestionService.ingest_and_normalize(
            cls.gl_path, SourceKind.LEDGER, cls.org_id, cls.batch_id
        )
        cls.all_txns = cls.gw_txns + cls.bk_txns + cls.gl_txns

        # Load ground truth links
        with open(cls.gt_path, "r", encoding="utf-8") as f:
            cls.ground_truth = json.load(f)

        # Run full reconciliation pipeline
        cls.engine = ReconciliationEngine(org_id=cls.org_id, batch_id=cls.batch_id)
        cls.summary = cls.engine.run_full_pipeline(cls.all_txns)

    def test_01_ingestion_counts(self):
        """Verifies exactly 50 Gateway, 50 Bank, and 50 GL transactions ingested."""
        self.assertEqual(len(self.gw_txns), 50, "Should ingest exactly 50 gateway records")
        self.assertEqual(len(self.bk_txns), 50, "Should ingest exactly 50 bank records")
        self.assertEqual(len(self.gl_txns), 50, "Should ingest exactly 50 journal entries (100 physical lines)")
        self.assertEqual(len(self.all_txns), 150, "Total ingested transactions must be 150")

    def test_02_matches_and_exceptions_counts(self):
        """Verifies deterministic reconciliation metrics."""
        self.assertEqual(len(self.engine.matches), 84, "Should produce exactly 84 pairwise match legs")
        self.assertEqual(len(self.engine.exceptions), 22, "Should detect exactly 22 quarantined exceptions")
        self.assertEqual(self.summary.get("matched_records"), 128)
        self.assertEqual(self.summary.get("total_records"), 150)
        self.assertAlmostEqual(self.summary.get("match_rate", 0), 128 / 150, places=4)

    def test_03_reconciliation_graph_structure(self):
        """Verifies 3-way and pairwise structure of the reconciliation graph."""
        graph = self.summary.get("reconciliation_graph", {})
        self.assertEqual(graph.get("three_way_matches_count"), 40)
        self.assertEqual(graph.get("three_way_records_count"), 120)
        self.assertEqual(graph.get("pairwise_matches_count"), 4)
        self.assertEqual(graph.get("pairwise_records_count"), 8)
        self.assertEqual(graph.get("overall_reconciled_records"), 128)

    def test_04_ground_truth_link_conformance(self):
        """Verifies that ground_truth_links.json matches the 84 engine match links."""
        self.assertEqual(len(self.ground_truth), 84, "Ground truth links must have exactly 84 entries")
        clean_links = [l for l in self.ground_truth if l["type"] == "1:1_CLEAN"]
        partial_links = [l for l in self.ground_truth if l["type"] == "1:1_PARTIAL_GW_BANK"]
        refund_links = [l for l in self.ground_truth if l["type"] == "1:1_REFUND"]

        self.assertEqual(len(clean_links), 78)  # 39 cohorts * 2 links
        self.assertEqual(len(partial_links), 4) # 4 partial cohorts (TXN022, TXN023, TXN030, TXN033)
        self.assertEqual(len(refund_links), 2)  # 1 refund cohort * 2 links (TXN046)

    def test_05_quarantined_financial_exceptions(self):
        """Verifies specific financial integrity exception types and cohorts."""
        exc_types = [e.exception_type for e in self.engine.exceptions]
        self.assertIn("PENDING_SETTLEMENT", exc_types)
        self.assertIn("GATEWAY_FEE_CALCULATION_ERROR", exc_types)
        self.assertIn("VOIDED_ZERO_ENTRY", exc_types)
        self.assertIn("MATERIAL_TRANSACTION_REVIEW", exc_types)
        self.assertIn("FAILED_PAYMENT_REVERSAL", exc_types)
        self.assertIn("UNBALANCED_JOURNAL_ENTRY", exc_types)
        self.assertIn("MISSING_APPROVAL_REFERENCE", exc_types)
        self.assertIn("FUTURE_DATED_POSTING", exc_types)

        # High-value material transaction TXN015 (Rs. 150,000) must be flagged CRITICAL
        mat_excs = [e for e in self.engine.exceptions if e.exception_type == "MATERIAL_TRANSACTION_REVIEW"]
        self.assertGreaterEqual(len(mat_excs), 1)
        for me in mat_excs:
            self.assertEqual(me.severity.value, "CRITICAL")
            self.assertEqual(me.impact_minor, 15000000)


if __name__ == "__main__":
    unittest.main()
