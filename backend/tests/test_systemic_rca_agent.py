"""
Systemic Root Cause Analysis (RCA) Agent Test Suite.
Verifies:
1. The RCA agent analyzes ONLY verified exceptions from the current batch.
2. Every systemic finding returns all 11 required schema fields.
3. root_cause_status is strictly one of CONFIRMED, SUPPORTED_HYPOTHESIS, UNKNOWN.
4. Operational root causes (e.g. API timeouts, DB crashes) are never inferred as confirmed facts without explicit proof.
5. Affected counts must be calculated from the current batch with sum reconciling to current exception set.
6. Assertions prevent RCA counts from exceeding applicable exceptions.
"""

import unittest
import uuid
from typing import Any, Dict, List

from app.models.schemas import RootCauseStatus
from app.services.agents.rca_agent import RootCauseAnalysisAgent


class TestSystemicRCAAgent(unittest.TestCase):

    def setUp(self):
        self.agent = RootCauseAnalysisAgent()
        self.batch_id = f"BATCH-RCA-{uuid.uuid4().hex[:6]}"

    def _make_exc(self, exc_id: str, e_type: str, impact_minor: int, primary_id: str, b_id: str = None) -> Dict[str, Any]:
        return {
            "id": exc_id,
            "batch_id": b_id or self.batch_id,
            "exception_type": e_type,
            "severity": "HIGH",
            "impact_minor": impact_minor,
            "primary_txn_id": primary_id,
            "counterpart_txn_id": None,
            "findings": [f"{e_type} observed on record {primary_id}"]
        }

    def test_01_rca_analyzes_only_verified_exceptions_from_current_batch(self):
        """1. RCA agent filters strictly to the current batch and ignores exceptions from other batches."""
        # 3 exceptions in current batch
        e1 = self._make_exc("EXC-1", "MISSING_BANK_SETTLEMENT", 500000, "TXN-1")
        e2 = self._make_exc("EXC-2", "MISSING_BANK_SETTLEMENT", 250000, "TXN-2")
        e3 = self._make_exc("EXC-3", "MDR_FEE_MISMATCH", 11800, "TXN-3")
        # 1 exception from another batch
        e_other = self._make_exc("EXC-OTHER", "MISSING_BANK_SETTLEMENT", 999900, "TXN-OTHER", b_id="BATCH-OLD")

        all_excs = [e1, e2, e3, e_other]
        res = self.agent.analyze_batch_exceptions(
            batch_id=self.batch_id,
            exceptions=all_excs,
            safeguards=[],
            batch_summary={"total_records": 10, "match_rate": 70.0}
        )

        self.assertEqual(res["total_exceptions_analyzed"], 3, "Must only analyze 3 exceptions from current batch")
        all_affected_exc_ids = []
        for f in res["systemic_findings"]:
            all_affected_exc_ids.extend(f["affected_exception_ids"])
        self.assertNotIn("EXC-OTHER", all_affected_exc_ids, "Exceptions from other batches must never appear in RCA")
        self.assertEqual(len(all_affected_exc_ids), 3)

    def test_02_all_findings_return_required_fields(self):
        """2. For every systemic finding return all 11 required contract fields."""
        e1 = self._make_exc("EXC-10", "MISSING_BANK_SETTLEMENT", 500000, "TXN-10")
        e2 = self._make_exc("EXC-20", "MDR_FEE_MISMATCH", 2360, "TXN-20")

        res = self.agent.analyze_batch_exceptions(
            batch_id=self.batch_id,
            exceptions=[e1, e2],
            safeguards=[],
            batch_summary={"total_records": 5, "match_rate": 60.0}
        )

        findings = res["systemic_findings"]
        self.assertEqual(len(findings), 2)

        required_fields = [
            "pattern_name",
            "affected_count",
            "impact_inr",
            "affected_exception_ids",
            "affected_record_ids",
            "observed_evidence",
            "root_cause_status",
            "root_cause_explanation",
            "confidence",
            "recommended_remediation",
            "remediation_owner"
        ]

        for f in findings:
            for field in required_fields:
                self.assertIn(field, f, f"Finding missing required field: {field}")
                self.assertIsNotNone(f[field], f"Field {field} cannot be None")

    def test_03_root_cause_status_enum_strictly_enforced(self):
        """3. root_cause_status must be one of: CONFIRMED, SUPPORTED_HYPOTHESIS, UNKNOWN."""
        e_timing = self._make_exc("EXC-T", "CUTOFF_DATE_MISMATCH", 100000, "TXN-T")
        e_mdr = self._make_exc("EXC-M", "MDR_FEE_MISMATCH", 5000, "TXN-M")
        e_unk = self._make_exc("EXC-U", "UNKNOWN_BANK_CREDIT", 75000, "TXN-U")

        res = self.agent.analyze_batch_exceptions(
            batch_id=self.batch_id,
            exceptions=[e_timing, e_mdr, e_unk],
            safeguards=[],
            batch_summary={"total_records": 10, "match_rate": 70.0}
        )

        valid_statuses = {"CONFIRMED", "SUPPORTED_HYPOTHESIS", "UNKNOWN"}
        for f in res["systemic_findings"]:
            self.assertIn(f["root_cause_status"], valid_statuses)

        # MDR fee with exact calculation is CONFIRMED
        mdr_f = next(f for f in res["systemic_findings"] if "MDR" in f["pattern_name"] or "Gateway" in f["pattern_name"])
        self.assertEqual(mdr_f["root_cause_status"], "CONFIRMED")

        # Timing difference is SUPPORTED_HYPOTHESIS
        timing_f = next(f for f in res["systemic_findings"] if "Timing" in f["pattern_name"] or "Period" in f["pattern_name"])
        self.assertEqual(timing_f["root_cause_status"], "SUPPORTED_HYPOTHESIS")

        # Unknown deposit is UNKNOWN
        unk_f = next(f for f in res["systemic_findings"] if "Unallocated" in f["pattern_name"] or "UNKNOWN" in f["pattern_name"])
        self.assertEqual(unk_f["root_cause_status"], "UNKNOWN")

    def test_04_anti_hallucination_never_infers_operational_causes_as_facts(self):
        """4. AI must not claim operational failures (e.g. Bank API timeout) as CONFIRMED facts without explicit logs."""
        e1 = self._make_exc("EXC-MISSING", "MISSING_BANK_SETTLEMENT", 48722, "TXN-MISSING")

        res = self.agent.analyze_batch_exceptions(
            batch_id=self.batch_id,
            exceptions=[e1],
            safeguards=[],
            batch_summary={"total_records": 1, "match_rate": 0.0}
        )

        finding = res["systemic_findings"][0]
        # Status for missing bank settlement must NOT be CONFIRMED (must be SUPPORTED_HYPOTHESIS or UNKNOWN)
        self.assertNotEqual(finding["root_cause_status"], "CONFIRMED")
        self.assertNotIn("API timeout", finding["root_cause_explanation"])
        self.assertIn("Bank settlement is missing", finding["observed_evidence"][0])

    def test_05_sum_of_affected_counts_reconciles_with_exception_set(self):
        """5. The sum of affected exception counts must exactly reconcile with the current exception set."""
        excs = [
            self._make_exc(f"EXC-{i}", "MISSING_BANK_SETTLEMENT" if i % 2 == 0 else "MDR_FEE_MISMATCH", 10000 * i, f"TXN-{i}")
            for i in range(1, 9)
        ]
        self.assertEqual(len(excs), 8)

        res = self.agent.analyze_batch_exceptions(
            batch_id=self.batch_id,
            exceptions=excs,
            safeguards=[],
            batch_summary={"total_records": 20, "match_rate": 60.0}
        )

        sum_affected = sum(f["affected_count"] for f in res["systemic_findings"])
        self.assertEqual(sum_affected, 8, "Sum of affected counts must equal 8")

    def test_06_assertions_prevent_counts_exceeding_applicable_exceptions(self):
        """6. Assertions prevent RCA counts from exceeding the number of applicable exceptions."""
        e1 = self._make_exc("EXC-1", "MISSING_BANK_SETTLEMENT", 10000, "TXN-1")
        # Direct call to internal integrity assertion with invalid inflated count
        invalid_finding = [
            self.agent._build_deterministic_findings(self.batch_id, {"MISSING_BANK_SETTLEMENT": [e1]})[0]
        ]
        invalid_finding[0].affected_count = 999  # Inflated

        with self.assertRaises(ValueError):
            self.agent._assert_findings_integrity(invalid_finding, total_exceptions=1, valid_exception_ids={"EXC-1"})

    def test_07_zero_exceptions_clean_batch_handling(self):
        """7. Clean batch with zero exceptions returns a valid, reconciled zero-count result."""
        res = self.agent.analyze_batch_exceptions(
            batch_id=self.batch_id,
            exceptions=[],
            safeguards=[],
            batch_summary={"total_records": 50, "match_rate": 100.0}
        )

        self.assertEqual(res["total_exceptions_analyzed"], 0)
        self.assertEqual(len(res["systemic_findings"]), 0)
        self.assertEqual(res["total_impact_inr"], 0.0)


if __name__ == "__main__":
    unittest.main()
