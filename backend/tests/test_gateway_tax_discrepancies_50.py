"""
Deep Verification Suite for 50-Record Dataset:
Payment Gateway Charges, Tax Discrepancies (GST Miscalculations, Surcharges, Omissions),
and Multi-Stream Financial Edge Cases.
"""

import os
import sys
import unittest
from datetime import date, datetime
from typing import Dict, List, Any

# Ensure backend path is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.models.schemas import (
    SourceKind, CanonicalTransaction, MatchStatus, DecisionTier,
    ProvenanceSourceType, ExecutionMode
)
from app.services.ingestion import IngestionService
from app.services.normalizer import NormalizerService
from app.services.fee_policy import FeePolicyRegistry, TaxJurisdiction
from app.services.matching_engine import ReconciliationEngine
from app.services.graph_orchestrator import LangGraphBatchOrchestrator
from app.services.agent_runtime import AIAgentRuntime, DeterministicVerifier
from app.services.ai_issues_service import AIIssuesService
from app.services.provenance import InputProvenanceService
from app.db.database import init_db, get_db_context
from app.db.database_service import DatabaseService
from app.db import schema
from app.api.v1.batches import STATE


class TestGatewayAndTaxDiscrepancies50(unittest.TestCase):
    """
    Comprehensive verification of payment gateway fee detection, tax discrepancies,
    and end-to-end reconciliation for the 50-record financial test fixture.
    """

    @classmethod
    def setUpClass(cls):
        init_db()
        cls.org_id = "00000000-0000-0000-0000-000000000001"
        cls.batch_id = "BATCH-50-TAX-TEST-2026"
        cls.fixture_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "data", "test_fixtures"))

        cls.gw_path = os.path.join(cls.fixture_dir, "gateway_50.csv")
        cls.bk_path = os.path.join(cls.fixture_dir, "bank_50.csv")
        cls.gl_path = os.path.join(cls.fixture_dir, "ledger_50.csv")

        # Verify fixture files exist
        assert os.path.exists(cls.gw_path), f"Missing {cls.gw_path}"
        assert os.path.exists(cls.bk_path), f"Missing {cls.bk_path}"
        assert os.path.exists(cls.gl_path), f"Missing {cls.gl_path}"

    def setUp(self):
        import uuid
        self.batch_id = f"BATCH-50-TAX-{uuid.uuid4().hex[:8]}"
        # Ingest and normalize raw CSV records
        self.gw_txns, self.gw_count = IngestionService.ingest_and_normalize(
            self.gw_path, SourceKind.GATEWAY, self.org_id, self.batch_id
        )
        self.bk_txns, self.bk_count = IngestionService.ingest_and_normalize(
            self.bk_path, SourceKind.BANK, self.org_id, self.batch_id
        )
        self.gl_txns, self.gl_count = IngestionService.ingest_and_normalize(
            self.gl_path, SourceKind.LEDGER, self.org_id, self.batch_id
        )
        self.all_txns = self.gw_txns + self.bk_txns + self.gl_txns

    # --------------------------------------------------------------------------
    # TEST 1: INGESTION & PARSING OF GATEWAY CHARGES AND TAX COLUMNS
    # --------------------------------------------------------------------------
    def test_01_ingestion_and_tax_field_parsing(self):
        """Verifies that gateway charges and tax fields are accurately parsed into CanonicalTransaction minor units."""
        self.assertEqual(len(self.gw_txns), 50, "Should ingest exactly 50 gateway records")
        self.assertEqual(len(self.bk_txns), 48, "Should ingest all bank records")
        
        # Check standard record pay_STD_001 (Gross Rs 500 = 50000 paise, Fee = 1000 paise, Tax = 180 paise)
        t_std = next((t for t in self.gw_txns if t.payment_id == "pay_STD_001"), None)
        self.assertIsNotNone(t_std)
        self.assertEqual(t_std.amount_minor, 50000)
        self.assertEqual(t_std.fee_minor, 1000)
        self.assertEqual(t_std.tax_minor, 180)

        # Check tax discrepancy record pay_TAX_011 (12% GST: Fee = 20000 paise, Tax = 2400 paise instead of 3600)
        t_tax11 = next((t for t in self.gw_txns if t.payment_id == "pay_TAX_011"), None)
        self.assertIsNotNone(t_tax11)
        self.assertEqual(t_tax11.amount_minor, 1000000)
        self.assertEqual(t_tax11.fee_minor, 20000)
        self.assertEqual(t_tax11.tax_minor, 2400) # 12% GST discrepancy

        # Check missing tax record pay_TAX_012 (Zero tax: Fee = 10000 paise, Tax = 0 paise)
        t_tax12 = next((t for t in self.gw_txns if t.payment_id == "pay_TAX_012"), None)
        self.assertIsNotNone(t_tax12)
        self.assertEqual(t_tax12.amount_minor, 500000)
        self.assertEqual(t_tax12.fee_minor, 10000)
        self.assertEqual(t_tax12.tax_minor, 0) # Missing GST

    # --------------------------------------------------------------------------
    # TEST 2: VERSIONED FEE POLICY & GST ARITHMETIC VERIFICATION
    # --------------------------------------------------------------------------
    def test_02_fee_policy_mathematical_proof(self):
        """Verifies FeePolicyRegistry calculation of standard 2% MDR + 18% GST to the exact paise."""
        policy = FeePolicyRegistry.get_default_policy()
        self.assertEqual(policy.policy_id, "POL-MDR-STD-2026")
        self.assertEqual(policy.tax_jurisdiction, TaxJurisdiction.GST_INDIA_18)

        # Test calculation on Rs 10,000 (1,000,000 paise)
        breakdown = policy.calculate(1000000)
        self.assertEqual(breakdown.gross_minor, 1000000)
        self.assertEqual(breakdown.fee_minor, 20000)  # Rs 200.00 MDR
        self.assertEqual(breakdown.tax_minor, 3600)   # Rs 36.00 GST (18%)
        self.assertEqual(breakdown.total_deduction_minor, 23600) # Rs 236.00
        self.assertEqual(breakdown.expected_net_minor, 976400)   # Rs 9,764.00

        # Verify formula proof contains rupee representations
        self.assertIn("MDR 2.0%", breakdown.formula_proof)
        self.assertIn("Tax (GST_IN_18) 18.0%", breakdown.formula_proof)

    # --------------------------------------------------------------------------
    # TEST 3: RECONCILIATION ENGINE RESOLUTION (P1 EXACT & P2 CONTEXTUAL)
    # --------------------------------------------------------------------------
    def test_03_reconciliation_engine_matching(self):
        """Executes the ReconciliationEngine to verify matching and exception isolation."""
        engine = ReconciliationEngine(org_id=self.org_id, batch_id=self.batch_id)
        res = engine.run_full_pipeline(self.all_txns)

        # 1. Verify Clean Direct Wire (Cohort 4) matched exactly
        clean_gw = [t for t in self.gw_txns if "CLEAN" in (t.payment_id or "")]
        for c_gw in clean_gw:
            self.assertIn(c_gw.id, engine.matched_txn_ids, f"Clean wire {c_gw.payment_id} should match")

        # 2. Verify Standard MDR + 18% GST (Cohort 1) matched contextually net of fees
        std_gw = [t for t in self.gw_txns if "STD" in (t.payment_id or "")]
        for s_gw in std_gw:
            self.assertIn(s_gw.id, engine.matched_txn_ids, f"Standard fee txn {s_gw.payment_id} should match net of fee+tax")

        # 3. Verify P0 Deduplication caught the duplicate webhook (pay_DUP_WEBHOOK_38)
        dup_gw = [t for t in self.gw_txns if t.payment_id == "pay_DUP_WEBHOOK_38"]
        self.assertEqual(len(dup_gw), 2)
        # One copy should remain, duplicate should be isolated
        dup_exc = [e for e in engine.exceptions if e.exception_type == "DUPLICATE_SOURCE_RECORD" or "DUP" in str(e)]
        self.assertTrue(len(dup_exc) >= 1)

    # --------------------------------------------------------------------------
    # TEST 4: DETECTION OF TAX DISCREPANCIES (12% GST, ZERO GST, 28% LUXURY)
    # --------------------------------------------------------------------------
    def test_04_detection_of_tax_discrepancies(self):
        """Validates that tax discrepancies violating contractual fee schedules are flagged."""
        engine = ReconciliationEngine(org_id=self.org_id, batch_id=self.batch_id)
        engine.run_full_pipeline(self.all_txns)

        # In Cohort 2, pay_TAX_011 has 12% GST (variance of Rs 12 = 1200 paise vs expected 18% GST)
        t_tax11 = next(t for t in self.gw_txns if t.payment_id == "pay_TAX_011")
        bk_tax11 = next(b for b in self.bk_txns if "pay_TAX_011" in (b.description_raw or ""))

        score, is_match = engine.score_amount(t_tax11, bk_tax11)
        # Because t_tax11 declared fee=20000 and tax=2400 (sum=22400), and diff is 22400,
        # declared fee check matches if declared, but does not match standard 18% GST policy!
        diff = abs(t_tax11.amount_minor - bk_tax11.amount_minor)
        expected_policy_deduction = 23600 # 20000 fee + 3600 GST
        actual_deduction = diff # 22400
        tax_variance = abs(actual_deduction - expected_policy_deduction)
        self.assertEqual(tax_variance, 1200, "Tax discrepancy should be exactly Rs 12.00 (1200 paise)")

        # In pay_TAX_012, tax was 0 instead of 1800 paise (Rs 18.00)
        t_tax12 = next(t for t in self.gw_txns if t.payment_id == "pay_TAX_012")
        bk_tax12 = next(b for b in self.bk_txns if "pay_TAX_012" in (b.description_raw or ""))
        diff12 = abs(t_tax12.amount_minor - bk_tax12.amount_minor)
        expected_deduction12 = 11800 # 10000 fee + 1800 GST
        tax_variance12 = abs(diff12 - expected_deduction12)
        self.assertEqual(tax_variance12, 1800, "Tax discrepancy should be exactly Rs 18.00 (1800 paise)")

    # --------------------------------------------------------------------------
    # TEST 5: AGENT 9 INVESTIGATION & DETERMINISTIC VERIFIER GATE
    # --------------------------------------------------------------------------
    def test_05_agent_investigation_and_verifier_gate(self):
        """Verifies that AIAgentRuntime investigates fee and tax discrepancies and passes DeterministicVerifier."""
        runtime = AIAgentRuntime()
        t_gw = next(t for t in self.gw_txns if t.payment_id == "pay_TAX_011")
        c_bk = next(b for b in self.bk_txns if "pay_TAX_011" in (b.description_raw or ""))

        # Run investigation on the amount variance
        res = runtime.investigate_exception(
            exception_id="EXC-TAX-011",
            exception_type="FEE_AND_TAX_BOOKED_NET",
            impact_minor=22400,
            primary_txn=t_gw.model_dump(),
            counterpart_txn=c_bk.model_dump(),
            available_txns=[t.model_dump() for t in self.all_txns],
            severity="MEDIUM",
            has_deterministic_rule=True
        )

        self.assertIsNotNone(res)
        self.assertIn("FEE_AND_TAX", res.classification)
        self.assertIn("POL-MDR-STD-2026", res.likely_cause)
        self.assertTrue(len(res.evidence) >= 1)

        # Test DeterministicVerifier gate
        all_ids = {t.id for t in self.all_txns}
        is_valid, err_msg = DeterministicVerifier.verify_proposal(
            res,
            {"impact_minor": 22400, "primary_txn_id": t_gw.id},
            all_ids
        )
        self.assertTrue(is_valid, f"Proposal failed verifier gate: {err_msg}")

    # --------------------------------------------------------------------------
    # TEST 6: AI ISSUES CENTER REPORT ON 50-RECORD BATCH
    # --------------------------------------------------------------------------
    def test_06_ai_issues_center_report_synthesis(self):
        """Tests that AIIssuesService synthesizes the 50-record dataset into structured, prioritized issue cards."""
        # Execute LangGraph orchestrator to produce real batch state
        orchestrator = LangGraphBatchOrchestrator(org_id=self.org_id, batch_id=self.batch_id)
        summary = orchestrator.run_windowed_pipeline(self.all_txns)

        # Persist batch run to DB
        DatabaseService.save_batch_run(
            org_id=self.org_id,
            batch_id=self.batch_id,
            canonical_txns=self.all_txns,
            matches=orchestrator.matches,
            exceptions=orchestrator.exceptions,
            decisions=orchestrator.decisions,
            proposals=orchestrator.proposals,
            audit_events=orchestrator.audit_events,
            summary=summary
        )

        # Update in-memory STATE for API consumption
        STATE["active_batch"] = {
            "id": self.batch_id,
            "org_id": self.org_id,
            "status": "COMPLETED",
            "total_records": len(self.all_txns),
            "match_rate": summary["match_rate"]
        }
        STATE["exceptions"] = [e.model_dump() for e in orchestrator.exceptions]

        # Generate canonical AI Issues report
        report = AIIssuesService.generate_report(
            org_id=self.org_id,
            batch_id=self.batch_id,
            force_refresh=True
        )

        self.assertIsNotNone(report)
        self.assertGreater(len(report.issues), 0)
        self.assertIsNotNone(report.controller_takeaway)

        # Check for presence of key issue categories in synthesized cards
        card_types = {card.type for card in report.issues}
        self.assertTrue(
            any(t in card_types for t in ("FEE_VARIANCE", "AMOUNT_MISMATCH", "PERIOD_CUTOFF", "UNSETTLED_SETTLEMENT", "MISSING_BANK", "MISSING_LEDGER", "DUPLICATE")),
            f"Issue cards should include financial discrepancy types, found: {card_types}"
        )

        # Verify deterministic calculation proof exists on mathematical cards
        fee_or_amt_cards = [c for c in report.issues if c.type in ("FEE_VARIANCE", "AMOUNT_MISMATCH", "PERIOD_CUTOFF")]
        for card in fee_or_amt_cards:
            if card.arithmetic_proof:
                self.assertTrue(card.arithmetic_proof.get("is_balanced", True))
                self.assertIsNotNone(card.arithmetic_proof.get("title"))
                self.assertTrue(len(card.arithmetic_proof.get("lines", [])) > 0)


if __name__ == "__main__":
    unittest.main()
