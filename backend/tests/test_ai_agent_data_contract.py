"""
Automated Test Suite for AI Agent Data Contract & Deterministic Immutability Gates.
Verifies:
1. Deterministic reconciliation engine runs first and acts as authoritative source of truth.
2. AIExceptionContext structured envelope contains all required fields with non-null values.
3. Every ToolEvidence item has a non-null, real record_id (NEVER record_id: null).
4. Investigation results separate FACT, OBSERVATION, POSSIBLE_CAUSE, RECOMMENDATION.
5. Anti-hallucination gates reject invented API/DB/gateway/treasury/ingestion failures.
6. Fallback says 'Cause cannot be determined from the supplied evidence.' when unevidenced.
7. AI cannot override amounts, dates, transaction IDs, match status, exception classification, or expected settlement.
"""

import unittest
from datetime import date, datetime, timezone
from typing import Any, Dict, List

from app.models.schemas import (
    CanonicalTransaction,
    SourceKind,
    TxnDirection,
    InvestigationResult,
    ToolEvidence,
    AIExceptionContext,
    ExceptionSchema,
    ExceptionSeverity,
    ExceptionState
)
from app.services.agent_runtime import DeterministicVerifier, AIAgentRuntime
from app.services.agents.investigation_agent import ExceptionInvestigationAgent
from app.services.fee_policy import FeePolicyRegistry


class TestAIAgentDataContract(unittest.TestCase):

    def setUp(self):
        self.batch_id = "BATCH-CONTRACT-TEST"
        self.org_id = "ORG-CONTRACT-TEST"
        self.runtime = AIAgentRuntime()
        self.agent = ExceptionInvestigationAgent()

        self.primary_txn = {
            "id": "TXN-GW-001",
            "batch_id": self.batch_id,
            "source_kind": "GATEWAY",
            "external_id": "pay_TEST_1001",
            "payment_id": "pay_TEST_1001",
            "amount_minor": 500000,
            "fee_minor": 10000,
            "tax_minor": 1800,
            "currency": "INR",
            "occurred_at": "2026-03-25T10:00:00Z",
            "description_raw": "Invoice INV-2026-001 license"
        }

        self.bank_txn = {
            "id": "TXN-BK-001",
            "batch_id": self.batch_id,
            "source_kind": "BANK",
            "external_id": "BANK-REC-001",
            "amount_minor": 488200,
            "currency": "INR",
            "occurred_at": "2026-03-25T14:00:00Z",
            "description_raw": "NEFT-SETTLE-pay_TEST_1001"
        }

    def test_01_deterministic_reconciliation_is_authoritative(self):
        """1. AI must NEVER be the source of truth for financial arithmetic or classification."""
        gross = self.primary_txn["amount_minor"]
        fee = self.primary_txn["fee_minor"]
        tax = self.primary_txn["tax_minor"]
        expected_net = gross - fee - tax

        self.assertEqual(expected_net, 488200, "Deterministic expected net must be 488200 paise (₹4,882.00)")
        
        # Build context from deterministic pipeline
        ctx = self.runtime.build_targeted_context(
            exception_id="EXC-TEST-001",
            exception_type="MISSING_BANK_SETTLEMENT",
            severity="HIGH",
            impact_minor=gross,
            primary_txn=self.primary_txn,
            counterpart_txn=None,
            all_txns=[self.primary_txn]
        )

        self.assertEqual(ctx["gross_amount"], 5000.00)
        self.assertEqual(ctx["fee"], 100.00)
        self.assertEqual(ctx["tax"], 18.00)
        self.assertEqual(ctx["expected_net_settlement"], 4882.00)
        self.assertEqual(ctx["classification"], "MISSING_BANK_SETTLEMENT")

    def test_02_structured_data_contract_fields_present(self):
        """2. For every AI exception request, provide all 17 required contract fields."""
        ctx = self.runtime.build_targeted_context(
            exception_id="EXC-TEST-002",
            exception_type="MISSING_BANK_SETTLEMENT",
            severity="HIGH",
            impact_minor=500000,
            primary_txn=self.primary_txn,
            counterpart_txn=self.bank_txn,
            all_txns=[self.primary_txn, self.bank_txn]
        )

        required_keys = [
            "batch_id",
            "exception_id",
            "classification",
            "payment_id",
            "source_records",
            "matched_records",
            "gross_amount",
            "fee",
            "tax",
            "expected_net_settlement",
            "actual_bank_settlement",
            "variance",
            "capture_date",
            "settlement_date",
            "timing_window",
            "deterministic_rules",
            "deterministic_result"
        ]

        for k in required_keys:
            self.assertIn(k, ctx, f"Missing required contract field: {k}")

        # Validate with AIExceptionContext Pydantic model
        contract_obj = AIExceptionContext(
            batch_id=ctx["batch_id"],
            exception_id=ctx["exception_id"],
            classification=ctx["classification"],
            payment_id=ctx["payment_id"],
            source_records=ctx["source_records"],
            matched_records=ctx["matched_records"],
            gross_amount=ctx["gross_amount"],
            fee=ctx["fee"],
            tax=ctx["tax"],
            expected_net_settlement=ctx["expected_net_settlement"],
            actual_bank_settlement=ctx["actual_bank_settlement"],
            variance=ctx["variance"],
            capture_date=ctx["capture_date"],
            settlement_date=ctx["settlement_date"],
            timing_window=ctx["timing_window"],
            deterministic_rules=ctx["deterministic_rules"],
            deterministic_result=ctx["deterministic_result"]
        )
        self.assertEqual(contract_obj.exception_id, "EXC-TEST-002")
        self.assertEqual(contract_obj.classification, "MISSING_BANK_SETTLEMENT")

    def test_03_no_null_record_ids_in_evidence(self):
        """3. Every evidence item must contain a real record ID, NEVER 'record_id': null."""
        inv = self.runtime._deterministic_investigate(
            exception_id="EXC-TEST-003",
            exception_type="AMOUNT_MISMATCH",
            impact_minor=11800,
            primary_txn=self.primary_txn,
            counterpart_txn=self.bank_txn
        )

        self.assertTrue(len(inv.evidence) > 0, "Evidence items must be generated")
        for ev in inv.evidence:
            self.assertIsNotNone(ev.record_id, f"ToolEvidence record_id cannot be None: {ev}")
            self.assertTrue(len(ev.record_id.strip()) > 0, "ToolEvidence record_id cannot be empty string")
            self.assertNotEqual(ev.record_id.lower(), "null", "ToolEvidence record_id cannot be literal 'null'")

    def test_04_ai_distinguishes_four_epistemic_layers(self):
        """4. The AI must distinguish FACT, OBSERVATION, POSSIBLE_CAUSE, RECOMMENDATION."""
        inv = self.runtime._deterministic_investigate(
            exception_id="EXC-TEST-004",
            exception_type="MISSING_BANK_SETTLEMENT",
            impact_minor=500000,
            primary_txn=self.primary_txn,
            counterpart_txn=None
        )

        self.assertTrue(len(inv.facts) > 0, "FACT layer must be populated")
        self.assertTrue(len(inv.observations) > 0, "OBSERVATION layer must be populated")
        self.assertIsNotNone(inv.possible_cause, "POSSIBLE_CAUSE layer must be populated")
        self.assertIsNotNone(inv.recommendation, "RECOMMENDATION layer must be populated")

        # Verify factual grounding
        self.assertTrue(any("TXN-GW-001" in f or "pay_TEST_1001" in f for f in inv.facts))
        self.assertTrue(any("5,000.00" in f or "4,882.00" in f for f in inv.facts))

    def test_05_anti_hallucination_prohibits_invented_failures(self):
        """5. AI must NOT invent API failures, DB crashes, or treasury outages unless in evidence."""
        hallucinated_proposal = InvestigationResult(
            exception_id="EXC-TEST-005",
            classification="MISSING_BANK_SETTLEMENT",
            likely_cause="Database crash occurred in treasury server causing API failure on payment gateway webhook ingestion.",
            possible_cause="Database failure caused API timeout.",
            candidate_match_ids=["TXN-GW-001"],
            recommended_action="Restart database and re-trigger API webhook",
            confidence=0.99,
            evidence=[ToolEvidence(tool="reconciliation_engine", record_id="TXN-GW-001", field="test", value=1)],
            requires_human_review=True,
            citations=["SOP-01"]
        )

        # Pass through DeterministicVerifier
        is_valid, reason = DeterministicVerifier.verify_proposal(
            hallucinated_proposal,
            {"impact_minor": 500000, "anomaly_flags": []},
            {"TXN-GW-001"}
        )

        self.assertTrue(is_valid)
        # Hallucination filter must strip invented failures
        self.assertEqual(
            hallucinated_proposal.possible_cause,
            "Cause cannot be determined from the supplied evidence.",
            "Invented database/API failure must be sanitized to 'Cause cannot be determined from the supplied evidence.'"
        )

    def test_06_insufficient_evidence_fallback(self):
        """6. If evidence is insufficient, the AI must explicitly state 'Cause cannot be determined...'"""
        inv = self.runtime._deterministic_investigate(
            exception_id="EXC-TEST-006",
            exception_type="UNRESOLVED_RESIDUAL",
            impact_minor=7500,
            primary_txn={"id": "TXN-UNKNOWN-99", "amount_minor": 7500},
            counterpart_txn=None
        )

        self.assertIn("Cause cannot be determined from the supplied evidence.", inv.likely_cause)
        self.assertEqual(inv.possible_cause, "Cause cannot be determined from the supplied evidence.")

    def test_07_ai_cannot_override_deterministic_classification(self):
        """7. The AI cannot change deterministic classification or override transaction data."""
        tampered_proposal = InvestigationResult(
            exception_id="EXC-TEST-007",
            classification="RESOLVED_PERFECT_MATCH", # AI trying to override MISSING_BANK_SETTLEMENT
            likely_cause="Everything looks matched to me",
            candidate_match_ids=["TXN-GW-001"],
            recommended_action="AUTO_RESOLVE",
            confidence=0.99,
            evidence=[ToolEvidence(tool="test", record_id="TXN-GW-001", field="test", value=1)],
            requires_human_review=False
        )

        is_valid, _ = DeterministicVerifier.verify_proposal(
            tampered_proposal,
            {"classification": "MISSING_BANK_SETTLEMENT", "impact_minor": 500000},
            {"TXN-GW-001"}
        )

        self.assertTrue(is_valid)
        self.assertEqual(
            tampered_proposal.classification,
            "MISSING_BANK_SETTLEMENT",
            "DeterministicVerifier must reset tampered classification back to authoritative pipeline classification."
        )

    def test_08_ai_cannot_invent_transaction_ids(self):
        """8. AI cannot invent non-existent transaction IDs."""
        hallucinated_ids_proposal = InvestigationResult(
            exception_id="EXC-TEST-008",
            classification="MISSING_BANK_SETTLEMENT",
            likely_cause="Found fake match",
            candidate_match_ids=["TXN-PHANTOM-9999"], # Fake ID not in active batch
            recommended_action="AUTO_MATCH",
            confidence=0.90,
            evidence=[ToolEvidence(tool="test", record_id="TXN-GW-001", field="test", value=1)],
            requires_human_review=True
        )

        is_valid, error = DeterministicVerifier.verify_proposal(
            hallucinated_ids_proposal,
            {"classification": "MISSING_BANK_SETTLEMENT", "impact_minor": 500000},
            {"TXN-GW-001", "TXN-BK-001"} # Valid IDs
        )

        self.assertFalse(is_valid)
        self.assertIn("TXN-PHANTOM-9999", error)


if __name__ == "__main__":
    unittest.main()
