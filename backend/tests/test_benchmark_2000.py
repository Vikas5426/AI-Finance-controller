"""
Empirical Accuracy, Recall, F1-Score & ECE Calibration Benchmark Test (2,000 Records)
Evaluates ReconciliationEngine and BenchmarkEvaluator against verifiable ground-truth dataset.
"""

import json
import os
import sys
import time
import unittest
from datetime import datetime, date

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.models.schemas import CanonicalTransaction, SourceKind, TxnDirection, ReferenceKeys
from app.services.matching_engine import ReconciliationEngine
from app.services.benchmarks import BenchmarkEvaluator


class Benchmark2000EmpiricalAccuracyTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        dataset_path = "data/benchmark_2000.json"
        if not os.path.exists(dataset_path):
            from backend.tests.generate_ground_truth_2000 import generate_dataset_2000
            generate_dataset_2000(dataset_path)

        with open(dataset_path, "r", encoding="utf-8") as f:
            cls.data = json.load(f)

        cls.transactions = []
        for t in cls.data["transactions"]:
            ref_dict = t.get("reference_keys", {})
            ref_keys = ReferenceKeys(
                invoice=ref_dict.get("invoice", []),
                payment=ref_dict.get("payment", []),
                utr=ref_dict.get("utr", []),
                order=ref_dict.get("order", []),
                je=ref_dict.get("je", []),
                settlement=ref_dict.get("settlement", [])
            )
            cls.transactions.append(CanonicalTransaction(
                id=t["id"],
                org_id="org_acme_default",
                batch_id="BATCH-BENCHMARK-2000",
                source_kind=SourceKind(t["source_kind"]),
                external_id=t["external_id"],
                amount_minor=t["amount_minor"],
                currency=t["currency"],
                direction=TxnDirection(t["direction"]),
                occurred_at=t["occurred_at"],
                value_date=date.fromisoformat(t["value_date"]),
                description_raw=t.get("description_raw", ""),
                description_norm=t.get("description_norm", ""),
                counterparty_raw=t.get("counterparty_raw", ""),
                counterparty_norm=t.get("counterparty_norm", ""),
                account_code=t.get("account_code", "1200"),
                reference_keys=ref_keys
            ))

        cls.gt_links = cls.data["ground_truth_links"]

    def test_empirical_precision_recall_f1_and_calibration_2000(self):
        """Runs full pipeline over 2,000 records and verifies measured metrics against ground truth."""
        t0 = time.time()
        engine = ReconciliationEngine(org_id="org_acme_default", batch_id="BATCH-BENCHMARK-2000")
        pipeline_summary = engine.run_full_pipeline(self.transactions)
        wall_clock = time.time() - t0

        # Evaluate against ground truth
        metrics = BenchmarkEvaluator.evaluate_synthetic_benchmark(
            matches=engine.matches,
            ground_truth=self.gt_links,
            wall_clock_seconds=wall_clock,
            total_records=len(self.transactions)
        )

        precision = metrics["synthetic_benchmark_precision"]
        recall = metrics["synthetic_benchmark_recall"]
        f1 = metrics["synthetic_benchmark_f1"]
        ece = metrics["expected_calibration_error"]
        rps = metrics["records_per_second"]

        print(f"\n" + "=" * 80)
        print("EMPIRICAL GROUND TRUTH EVALUATION RESULTS (2,000 RECORDS)")
        print("=" * 80)
        print(f"Total Transactions Processed: {len(self.transactions):,}")
        print(f"Matches Formed:              {len(engine.matches):,}")
        print(f"Wall Clock Time:             {wall_clock:.2f} seconds ({rps:.1f} records/sec)")
        print(f"Empirical Precision:         {precision * 100:.2f}%")
        print(f"Empirical Recall:            {recall * 100:.2f}%")
        print(f"Empirical F1-Score:          {f1 * 100:.2f}%")
        print(f"Expected Calibration Error:  {ece:.4f}")
        print("=" * 80)

        # Assert statistically significant enterprise thresholds
        self.assertIsNotNone(precision)
        self.assertGreaterEqual(precision, 0.97, f"Expected Precision >= 97%, got {precision}")
        self.assertGreaterEqual(recall, 0.90, f"Expected Recall >= 90%, got {recall}")
        self.assertGreaterEqual(f1, 0.93, f"Expected F1-Score >= 93%, got {f1}")
        self.assertLessEqual(ece, 0.08, f"Expected ECE <= 0.08, got {ece}")


if __name__ == "__main__":
    unittest.main()
