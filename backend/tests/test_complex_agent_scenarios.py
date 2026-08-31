"""
Complex & Adversarial Financial Agent Test Suite
Tests difficult real-world financial edge cases for reasoning agents, deterministic verifiers,
SOP tools, and maker-checker dual control gates.
"""

import os
import sys
import unittest
import uuid
from datetime import datetime, date, timezone
from decimal import Decimal
from typing import Any, Dict, List

# Ensure backend directory is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.config import settings
from app.db.database import init_db, get_db_context
from app.db import schema
from app.models.schemas import (
    CanonicalTransaction, SourceKind, TxnDirection, MatchStatus,
    InvestigationResult, ToolEvidence, DecisionTier, ReferenceKeys
)
from app.services.agent_tools import (
    tool_calculate_fee_split,
    tool_check_period_cutoff,
    tool_lookup_candidates,
    tool_evaluate_sop_rules,
    TransactionLookupIndex
)
from app.services.agent_runtime import DeterministicVerifier, AIAgentRuntime
from app.services.graph_orchestrator import LangGraphBatchOrchestrator
from app.services.audit_chain import AuditHashChain
import asyncio
from app.api.v1.approvals import decide_proposal, ApprovalActionRequest
from fastapi import HTTPException


class TestComplexAgentScenarios(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        init_db()

    def setUp(self):
        self.org_id = "00000000-0000-0000-0000-000000000001"
        self.batch_id = f"BATCH-COMPLEX-{uuid.uuid4().hex[:8]}"

    def _create_txn(self, txn_id: str, source_kind: SourceKind, amount_minor: int, ext_id: str, dt_str: str, val_date: date, direction: TxnDirection = TxnDirection.INFLOW) -> CanonicalTransaction:
        return CanonicalTransaction(
            id=txn_id,
            org_id=self.org_id,
            batch_id=self.batch_id,
            source_kind=source_kind,
            external_id=ext_id,
            direction=direction,
            amount_minor=amount_minor,
            currency="INR",
            occurred_at=dt_str,
            value_date=val_date,
            description_raw=f"Test {source_kind.value} {ext_id}",
            description_norm=f"test {source_kind.value.lower()} {ext_id.lower()}",
            account_code="1200" if source_kind == SourceKind.GATEWAY else "1010",
            reference_keys=ReferenceKeys(payment=[ext_id], invoice=[ext_id], utr=[ext_id] if source_kind == SourceKind.BANK else [])
        )

    # ==============================================================================
    # 1. Complex Multi-Leg Rounding & GST MDR Variance on Odd Amounts
    # ==============================================================================
    def test_complex_odd_amount_fee_split_with_1paise_rounding(self):
        """
        Gross: ₹1,333.33 (133,333 paise)
        2.0% MDR = 2666.66 paise -> rounds HALF_UP to 2667 paise
        18% GST on MDR = 480.06 paise -> rounds HALF_UP to 480 paise
        Total Deduction = 3147 paise (₹31.47)
        Expected Net = 130186 paise (₹1,301.86)
        """
        res = tool_calculate_fee_split(133333, policy_id="POL-MDR-STD-2026")
        self.assertEqual(res["fee_minor"], 2667)
        self.assertEqual(res["tax_minor"], 480)
        self.assertEqual(res["total_deduction_minor"], 3147)
        self.assertEqual(res["expected_net_minor"], 130186)
        self.assertEqual(res["policy_id"], "POL-MDR-STD-2026")
        self.assertIn("MDR 2.0% = ₹26.67", res["formula_proof"])
        self.assertIn("Net: ₹1301.86", res["formula_proof"])

        # Construct Agent Proposal
        inv = InvestigationResult(
            exception_id="EXC-ODD-01",
            classification="MDR_FEE_VARIANCE",
            likely_cause="MDR fee netting under standard 2.0% + 18% GST schedule",
            candidate_match_ids=["bk_odd_001"],
            recommended_action="SPLIT_AND_POST_FEE",
            confidence=0.98,
            evidence=[
                ToolEvidence(
                    tool="tool_calculate_fee_split",
                    rule_id="R02_STANDARD_2PCT_MDR_NETTING_FORMULA",
                    field="fee_breakup",
                    value=res
                )
            ],
            requires_human_review=False,
            citations=["SOP-04 §2: Merchant Discount Rate Accounting"]
        )

        valid_ids = {"gw_odd_001", "bk_odd_001"}
        is_valid, reason = DeterministicVerifier.verify_proposal(
            inv,
            {"impact_minor": 3147},
            valid_ids
        )
        self.assertTrue(is_valid, f"Expected verifier to accept proposal, but failed with: {reason}")

    # ==============================================================================
    # 2. Boundary Cutoff Timing Difference at Midnight on Month-End
    # ==============================================================================
    def test_boundary_cutoff_at_midnight_month_end(self):
        """
        Transaction occurred at 2026-03-31T23:59:58Z with value date 2026-03-31.
        Settlement SLA is T+2 -> Settlement expected on 2026-04-02 in next reporting period.
        """
        res = tool_check_period_cutoff(occurred_at="2026-03-31T23:59:58Z", value_date="2026-03-31")
        self.assertTrue(res["is_period_cutoff_timing_difference"])
        self.assertEqual(res["recommended_accounting_action"], "ACCRUE_TO_CLEARING_1290")
        self.assertEqual(res["settlement_delay_days"], 2)
        self.assertIn("1290 In-Transit Clearing", res["target_account"])

    # ==============================================================================
    # 3. Adversarial Candidate ID Hallucination Rejection
    # ==============================================================================
    def test_adversarial_candidate_id_hallucination_rejected_by_verifier(self):
        """
        Simulated LLM hallucinates an arbitrary candidate ID not present in active batch.
        DeterministicVerifier must catch and reject it immediately.
        """
        inv = InvestigationResult(
            exception_id="EXC-HALLUCINATE-01",
            classification="UNALLOCATED_BANK_CREDIT",
            likely_cause="Hallucinated match link",
            candidate_match_ids=["bk_hallucinated_fake_id_9999"],
            recommended_action="FORCE_PAIR",
            confidence=0.99,
            evidence=[],
            requires_human_review=False
        )

        valid_batch_ids = {"gw_real_001", "bk_real_001", "gl_real_001"}
        is_valid, reason = DeterministicVerifier.verify_proposal(
            inv,
            {"impact_minor": 100000},
            valid_batch_ids
        )
        self.assertFalse(is_valid, "Verifier MUST reject hallucinated candidate IDs!")
        self.assertIn("does not exist in the active batch", reason)

    # ==============================================================================
    # 4. Adversarial Arithmetic Fee Tampering Rejection
    # ==============================================================================
    def test_adversarial_arithmetic_fee_tampering_rejected_by_verifier(self):
        """
        Proposal evidence contains fee breakdown with total_deduction_minor = 5000,
        but actual exception impact is 2360 minor.
        DeterministicVerifier must reject the arithmetic mismatch.
        """
        tampered_evidence = {
            "fee_minor": 4237,
            "tax_minor": 763,
            "total_deduction_minor": 5000, # Tampered
            "expected_net_minor": 95000,
            "policy_id": "POL-MDR-STD-2026"
        }

        inv = InvestigationResult(
            exception_id="EXC-TAMPER-01",
            classification="MDR_FEE_VARIANCE",
            likely_cause="MDR fee netting",
            candidate_match_ids=["bk_real_001"],
            recommended_action="SPLIT_AND_POST_FEE",
            confidence=0.95,
            evidence=[
                ToolEvidence(
                    tool="tool_calculate_fee_split",
                    rule_id="R02_STANDARD_2PCT_MDR_NETTING_FORMULA",
                    field="fee_breakup",
                    value=tampered_evidence
                )
            ],
            requires_human_review=False
        )

        valid_ids = {"gw_real_001", "bk_real_001"}
        is_valid, reason = DeterministicVerifier.verify_proposal(
            inv,
            {"impact_minor": 2360}, # Actual difference
            valid_ids
        )
        self.assertFalse(is_valid, "Verifier MUST reject arithmetic discrepancy!")
        self.assertIn("Arithmetic mismatch", reason)

    # ==============================================================================
    # 5. Dual-Control Maker-Checker Segregation Enforcement
    # ==============================================================================
    def test_dual_control_maker_checker_authorization_gate(self):
        """
        Maker (Analyst) cannot approve proposals (HTTP 403).
        Checker (Approver) successfully approves with SHA-256 audit block generation.
        """
        prop_id = f"PROP-{uuid.uuid4().hex[:6]}"
        exc_id = f"EXC-{uuid.uuid4().hex[:6]}"

        # Seed proposal in database
        with get_db_context() as db:
            prop = schema.ResolutionProposal(
                id=prop_id,
                org_id=self.org_id,
                exception_id=exc_id,
                action="ADJUST_LEDGER_FEE_SPLIT",
                recommended_parameters={"fee_minor": 2000, "tax_minor": 360},
                justification="Post fee split journal entry under standard MDR",
                status="PENDING_APPROVAL",
                confidence=Decimal("0.98")
            )
            exc = schema.ExceptionRecord(
                id=exc_id,
                org_id=self.org_id,
                batch_id=self.batch_id,
                exception_type="MDR_FEE_VARIANCE",
                severity="MEDIUM",
                state="OPEN",
                impact_minor=2360,
                currency="INR"
            )
            db.add(prop)
            db.add(exc)
            db.commit()

        # 1. Analyst attempts approval -> MUST fail with 403
        analyst_user = {
            "id": "usr_analyst_01",
            "role": "analyst",
            "full_name": "Financial Analyst (Maker)",
            "org_id": self.org_id
        }
        req = ApprovalActionRequest(proposal_id=prop_id, action="APPROVED", decision_notes="Self-approval attempt")

        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(decide_proposal(req, current_user=analyst_user))
        self.assertEqual(ctx.exception.status_code, 403)
        self.assertIn("Maker-Checker Segregation Breach", ctx.exception.detail)

        # 2. Approver attempts approval -> MUST succeed with 200 and SHA-256 seal
        approver_user = {
            "id": "usr_approver_01",
            "role": "approver",
            "full_name": "Controller & Dual Approver",
            "org_id": self.org_id
        }
        res = asyncio.run(decide_proposal(req, current_user=approver_user))
        self.assertEqual(res["status"], "SUCCESS")
        self.assertEqual(res["proposal_id"], prop_id)
        self.assertEqual(res["decision"], "APPROVED")
        self.assertIsNotNone(res["audit_event_hash"])
        self.assertEqual(len(res["audit_event_hash"]), 64)

    # ==============================================================================
    # 6. Full LangGraph Orchestrator Execution on Complex Mixed Batch
    # ==============================================================================
    def test_langgraph_full_orchestration_on_ambiguous_batch(self):
        """
        Runs LangGraphBatchOrchestrator through all 7 nodes on a mixed feed containing:
        - 1:1 exact match
        - 2.0% MDR fee variance
        - Month-end cutoff timing difference
        - Unallocated bank credit
        """
        gw_exact = self._create_txn("gw_c_01", SourceKind.GATEWAY, 50000, "PAY-C-01", "2026-03-10T10:00:00Z", date(2026, 3, 10))
        bk_exact = self._create_txn("bk_c_01", SourceKind.BANK, 50000, "PAY-C-01", "2026-03-10T10:00:00Z", date(2026, 3, 10))

        # Fee variance: Gateway ₹1,000 (100,000 paise) vs Bank Net ₹976.40 (97,640 paise)
        gw_fee = self._create_txn("gw_c_02", SourceKind.GATEWAY, 100000, "PAY-C-02", "2026-03-15T12:00:00Z", date(2026, 3, 15))
        bk_fee = self._create_txn("bk_c_02", SourceKind.BANK, 97640, "PAY-C-02", "2026-03-15T12:00:00Z", date(2026, 3, 15))

        # Cutoff: Gateway at 2026-03-31T23:50:00Z
        gw_cut = self._create_txn("gw_c_03", SourceKind.GATEWAY, 75000, "PAY-C-03", "2026-03-31T23:50:00Z", date(2026, 3, 31))

        # Unallocated bank credit
        bk_anon = self._create_txn("bk_c_04", SourceKind.BANK, 25000, "UTR-ANON-01", "2026-03-20T14:00:00Z", date(2026, 3, 20))

        all_txns = [gw_exact, bk_exact, gw_fee, bk_fee, gw_cut, bk_anon]

        orchestrator = LangGraphBatchOrchestrator(org_id=self.org_id, batch_id=self.batch_id)
        summary = orchestrator.run_windowed_pipeline(all_txns)

        self.assertIsNotNone(summary)
        self.assertGreaterEqual(summary["total_records"], 6)
        self.assertGreaterEqual(len(orchestrator.matches), 2) # Exact match + Fee match
        self.assertGreaterEqual(len(orchestrator.exceptions), 2) # Cutoff + Unallocated bank credit
        self.assertGreaterEqual(len(orchestrator.audit_events), 2)

        # Verify cryptographic hash chain continuity
        prev_hash = AuditHashChain.GENESIS_HASH
        for ev in orchestrator.audit_events:
            self.assertEqual(ev["prev_hash"], prev_hash)
            prev_hash = ev["event_hash"]


if __name__ == "__main__":
    unittest.main()
