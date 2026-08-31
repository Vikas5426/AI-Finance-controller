import os
import sys
import unittest
from datetime import datetime, date

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.models.schemas import SourceKind, TxnDirection
from app.services.normalizer import NormalizerService
from app.services.batch_orchestrator import WindowedBatchOrchestrator
from app.db.database import init_db
from app.db.database_service import DatabaseService

class TestQualityMetricsTruthfulness(unittest.TestCase):
    def setUp(self):
        self.org_id = "00000000-0000-0000-0000-000000000001"
        self.batch_id = "BATCH-TEST-TRUTHFUL-METRICS-01"

    def test_dynamic_metrics_computation(self):
        """Validates metrics are computed from actual runtime matches, not hardcoded 0.985."""
        # 1 Gateway payment and 1 matching Bank line
        gw = NormalizerService.normalize_row({
            "payment_id": "pay_TRUTH_01",
            "gross_amount": 500000,
            "created_at": "2026-08-20T10:00:00",
            "description": "Invoice INV-TRUTH-01"
        }, SourceKind.GATEWAY, self.org_id, self.batch_id)

        bank = NormalizerService.normalize_row({
            "bank_transaction_id": "UTR-TRUTH-01",
            "amount": 5000.00,
            "date": "2026-08-20",
            "description": "Direct deposit INV-TRUTH-01",
            "type": "Credit"
        }, SourceKind.BANK, self.org_id, self.batch_id)

        orchestrator = WindowedBatchOrchestrator(self.org_id, self.batch_id, window_size=10)
        summary = orchestrator.run_windowed_pipeline([gw, bank])

        # Exact match confidence is 1.0, so average_match_confidence should be 1.0, false_match_risk = 0.0
        self.assertEqual(summary["exact_matches"], 1)
        self.assertEqual(summary["match_rate"], 1.0)
        self.assertEqual(summary["average_match_confidence"], 1.0)
        self.assertEqual(summary["false_match_risk"], 0.0)
        # Truthful metrics: ground truth metrics must not be present in live operational run
        self.assertNotIn("precision_rate", summary)
        self.assertNotIn("recall_rate", summary)
        self.assertNotIn("f1_score", summary)

    def test_unmatched_batch_metrics(self):
        """Validates that a batch with no matches reports 0.0 match_rate and 0.0 average_match_confidence."""
        # 2 completely unrelated transactions
        gw = NormalizerService.normalize_row({
            "payment_id": "pay_NOMATCH_01",
            "gross_amount": 1234.00,
            "created_at": "2026-08-20T10:00:00",
            "description": "Invoice INV-ALPHA"
        }, SourceKind.GATEWAY, self.org_id, self.batch_id)

        bank = NormalizerService.normalize_row({
            "bank_transaction_id": "UTR-NOMATCH_02",
            "amount": 9999.00,
            "date": "2026-08-20",
            "description": "Unknown transfer BETA",
            "type": "Credit"
        }, SourceKind.BANK, self.org_id, self.batch_id)

        orchestrator = WindowedBatchOrchestrator(self.org_id, self.batch_id, window_size=10)
        summary = orchestrator.run_windowed_pipeline([gw, bank])

        self.assertEqual(summary["exact_matches"], 0)
        self.assertEqual(summary["matched_records"], 0)
        self.assertEqual(summary["match_rate"], 0.0)
        # average_match_confidence must be 0.0 when there are no matches
        self.assertEqual(summary["average_match_confidence"], 0.0)

if __name__ == "__main__":
    unittest.main()
