"""
Unit tests verifying audit fixes:
- Agent tools (fee split, period cutoff, candidate lookup, SOP rules)
- DeterministicVerifier arithmetic & policy ID parsing
- Approvals batch-scoped audit chain
"""

import unittest
from datetime import datetime, date, timezone
from decimal import Decimal

from app.models.schemas import (
    CanonicalTransaction,
    SourceKind,
    TxnDirection,
    InvestigationResult,
    ToolEvidence,
    DecisionTier
)
from app.services.agent_tools import (
    tool_calculate_fee_split,
    tool_check_period_cutoff,
    tool_lookup_candidates,
    tool_evaluate_sop_rules,
    TransactionLookupIndex
)
from app.services.agent_runtime import DeterministicVerifier
from app.services.fee_policy import FeePolicyRegistry, TaxJurisdiction
from app.services.period import ReportingPeriod


class AuditFixesUnitTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        from app.db.database import init_db
        init_db()

    def test_tool_calculate_fee_split_versioned(self):
        """Validates tool_calculate_fee_split computes exact MDR and GST and preserves policy ID."""
        # 1. Standard 2.0% MDR + 18% GST on ₹1000 (100000 paise)
        # Gross = 100000 -> MDR = 2000, GST = 360 -> Total Deduction = 2360, Net = 97640
        res = tool_calculate_fee_split(100000, policy_id="POL-MDR-STD-2026")
        self.assertEqual(res["fee_minor"], 2000)
        self.assertEqual(res["tax_minor"], 360)
        self.assertEqual(res["total_deduction_minor"], 2360)
        self.assertEqual(res["expected_net_minor"], 97640)
        self.assertEqual(res["policy_id"], "POL-MDR-STD-2026")

        # 2. Enterprise 1.5% MDR + 18% GST on ₹1000 (100000 paise)
        # Gross = 100000 -> MDR = 1500, GST = 270 -> Total Deduction = 1770, Net = 98230
        res_ent = tool_calculate_fee_split(100000, fee_tier="1.5% Enterprise MDR")
        self.assertEqual(res_ent["fee_minor"], 1500)
        self.assertEqual(res_ent["tax_minor"], 270)
        self.assertEqual(res_ent["total_deduction_minor"], 1770)
        self.assertEqual(res_ent["expected_net_minor"], 98230)
        self.assertEqual(res_ent["policy_id"], "POL-MDR-ENT-2026")

    def test_tool_check_period_cutoff_dynamic(self):
        """Validates tool_check_period_cutoff detects cutoff timing differences dynamically."""
        period = ReportingPeriod(
            start=date(2026, 8, 1),
            end=date(2026, 8, 31),
            source="TEST"
        )
        # Date on cutoff boundary: Aug 30
        res = tool_check_period_cutoff(
            occurred_at="2026-08-30T18:00:00",
            value_date=date(2026, 8, 30),
            bank_sla_days=2,
            reporting_period=period
        )
        self.assertTrue(res["is_period_cutoff_timing_difference"])
        self.assertEqual(res["recommended_accounting_action"], "ACCRUE_TO_CLEARING_1290")

        # Date mid-month: Aug 10
        res_mid = tool_check_period_cutoff(
            occurred_at="2026-08-10T10:00:00",
            value_date=date(2026, 8, 10),
            bank_sla_days=2,
            reporting_period=period
        )
        self.assertFalse(res_mid["is_period_cutoff_timing_difference"])
        self.assertEqual(res_mid["recommended_accounting_action"], "STANDARD_CLEARING")

    def test_deterministic_verifier_with_string_policy_evidence(self):
        """Validates DeterministicVerifier does not crash when evidence dict contains string policy metadata."""
        inv = InvestigationResult(
            exception_id="EXC-TEST-01",
            classification="MDR_FEE_VARIANCE",
            likely_cause="2.0% MDR + GST deduction by Razorpay processor",
            candidate_match_ids=["bk_001"],
            recommended_action="ADJUST_LEDGER_FEE_SPLIT",
            confidence=0.95,
            evidence=[
                ToolEvidence(
                    tool="tool_calculate_fee_split",
                    rule_id="R02_STANDARD_2PCT_MDR_NETTING_FORMULA",
                    field="fee_breakup",
                    value={
                        "fee_minor": 2000,
                        "tax_minor": 360,
                        "total_deduction_minor": 2360,
                        "policy_id": "POL-MDR-STD-2026",
                        "policy_name": "2.0% Standard MDR + 18% GST",
                        "formula_proof": "Gross Rs. 1000.00 - Fee Rs. 20.00 - Tax Rs. 3.60 = Net Rs. 976.40"
                    }
                )
            ],
            requires_human_review=False,
            citations=["SOP-04 §2: Merchant Discount Rate Accounting"]
        )

        valid_ids = {"bk_001", "gw_001"}
        is_valid, reason = DeterministicVerifier.verify_proposal(
            inv,
            {"impact_minor": 2360},
            valid_ids
        )
        self.assertTrue(is_valid, f"Expected verification to pass, but got: {reason}")

    def test_deterministic_verifier_arithmetic_rejection(self):
        """Validates DeterministicVerifier rejects proposal if fee breakdown sum != actual impact."""
        inv = InvestigationResult(
            exception_id="EXC-TEST-02",
            classification="MDR_FEE_VARIANCE",
            likely_cause="Incorrect fee calculation",
            candidate_match_ids=["bk_002"],
            recommended_action="ADJUST_LEDGER_FEE_SPLIT",
            confidence=0.90,
            evidence=[
                ToolEvidence(
                    tool="tool_calculate_fee_split",
                    rule_id="R02_STANDARD_2PCT_MDR_NETTING_FORMULA",
                    field="fee_breakup",
                    value={
                        "fee_minor": 1500,
                        "tax_minor": 270,
                        "total_deduction_minor": 1770,
                        "policy_id": "POL-MDR-ENT-2026"
                    }
                )
            ],
            requires_human_review=False
        )

        valid_ids = {"bk_002"}
        # Actual diff is 2360 but claimed sum is 1770
        is_valid, reason = DeterministicVerifier.verify_proposal(
            inv,
            {"impact_minor": 2360},
            valid_ids
        )
        self.assertFalse(is_valid)
        self.assertIn("Arithmetic mismatch", str(reason))

    def test_multi_batch_audit_chain_verification(self):
        """Validates that audit chain verification succeeds for both scoped batch and all batches."""
        from app.services.audit_chain import AuditHashChain
        from app.api.v1.audit import verify_audit_chain
        from app.db.database import get_db_context
        from app.db import schema
        import uuid

        org_id = f"org_test_{uuid.uuid4().hex[:6]}"
        b1 = f"BATCH-TEST-01-{uuid.uuid4().hex[:4]}"
        b2 = f"BATCH-TEST-02-{uuid.uuid4().hex[:4]}"

        # Create two separate batches of audit events
        with get_db_context() as db:
            # Batch 1 Event 1
            h1_1 = AuditHashChain.compute_event_hash(
                prev_hash=AuditHashChain.GENESIS_HASH,
                org_id=org_id, event_seq=1, event_type="INGESTION",
                entity_id=b1, actor_id="sys", payload={"count": 10},
                created_at="2026-08-29T10:00:00+00:00"
            )
            ev1_1 = schema.AuditEvent(
                id=str(uuid.uuid4()), org_id=org_id, batch_id=b1, event_seq=1,
                event_type="INGESTION", entity_type="BATCH", entity_id=b1,
                actor_id="sys", actor_type="SYSTEM", action="INGEST",
                payload={"count": 10}, prev_hash=AuditHashChain.GENESIS_HASH,
                event_hash=h1_1, created_at=datetime(2026, 8, 29, 10, 0, 0, tzinfo=timezone.utc)
            )
            # Batch 1 Event 2
            h1_2 = AuditHashChain.compute_event_hash(
                prev_hash=h1_1,
                org_id=org_id, event_seq=2, event_type="MATCHING",
                entity_id=b1, actor_id="sys", payload={"matches": 5},
                created_at="2026-08-29T10:01:00+00:00"
            )
            ev1_2 = schema.AuditEvent(
                id=str(uuid.uuid4()), org_id=org_id, batch_id=b1, event_seq=2,
                event_type="MATCHING", entity_type="BATCH", entity_id=b1,
                actor_id="sys", actor_type="SYSTEM", action="MATCH",
                payload={"matches": 5}, prev_hash=h1_1,
                event_hash=h1_2, created_at=datetime(2026, 8, 29, 10, 1, 0, tzinfo=timezone.utc)
            )

            # Batch 2 Event 1 (Starts from GENESIS)
            h2_1 = AuditHashChain.compute_event_hash(
                prev_hash=AuditHashChain.GENESIS_HASH,
                org_id=org_id, event_seq=1, event_type="INGESTION",
                entity_id=b2, actor_id="sys", payload={"count": 20},
                created_at="2026-08-29T11:00:00+00:00"
            )
            ev2_1 = schema.AuditEvent(
                id=str(uuid.uuid4()), org_id=org_id, batch_id=b2, event_seq=1,
                event_type="INGESTION", entity_type="BATCH", entity_id=b2,
                actor_id="sys", actor_type="SYSTEM", action="INGEST",
                payload={"count": 20}, prev_hash=AuditHashChain.GENESIS_HASH,
                event_hash=h2_1, created_at=datetime(2026, 8, 29, 11, 0, 0, tzinfo=timezone.utc)
            )

            db.add_all([ev1_1, ev1_2, ev2_1])
            db.commit()

        user_mock = {"user_id": "usr_test", "org_id": org_id, "role": "approver"}

        # 1. Verify scoped by Batch 1
        res_b1 = verify_audit_chain(batch_id=b1, current_user=user_mock)
        self.assertEqual(res_b1["status"], "VERIFIED")
        self.assertEqual(res_b1["total_events_checked"], 2)

        # 2. Verify scoped by Batch 2
        res_b2 = verify_audit_chain(batch_id=b2, current_user=user_mock)
        self.assertEqual(res_b2["status"], "VERIFIED")
        self.assertEqual(res_b2["total_events_checked"], 1)

        # 3. Verify all batches without batch_id (must not report false tampering)
        res_all = verify_audit_chain(batch_id=None, current_user=user_mock)
        self.assertEqual(res_all["status"], "VERIFIED")
        self.assertEqual(res_all["total_events_checked"], 3)
        self.assertEqual(res_all["total_batches_checked"], 2)

    def test_batch_scoped_query_endpoints(self):
        """Validates that transactions, exceptions, and approvals filter strictly by batch_id."""
        from app.api.v1.transactions import get_transactions
        from app.api.v1.exceptions import get_exceptions
        from app.api.v1.approvals import get_pending_approvals
        from app.db.database import get_db_context
        from app.db import schema
        import uuid

        org_id = f"org_test_{uuid.uuid4().hex[:6]}"
        b1 = f"BATCH-S1-{uuid.uuid4().hex[:4]}"
        b2 = f"BATCH-S2-{uuid.uuid4().hex[:4]}"

        with get_db_context() as db:
            # Add transactions to b1 and b2
            t1 = schema.Transaction(
                id=f"t1_{uuid.uuid4().hex[:6]}", org_id=org_id, batch_id=b1,
                source_kind="GATEWAY", external_id="PAY-B1-01", txn_type="PAYMENT",
                direction="INFLOW", amount_minor=10000, amount=Decimal("100.00"),
                occurred_at=datetime.now(timezone.utc),
                value_date=date(2026, 8, 1), description_raw="Test b1",
                description_norm="test b1", match_status="MATCHED"
            )
            t2 = schema.Transaction(
                id=f"t2_{uuid.uuid4().hex[:6]}", org_id=org_id, batch_id=b2,
                source_kind="BANK", external_id="UTR-B2-01", txn_type="SETTLEMENT_CREDIT",
                direction="INFLOW", amount_minor=20000, amount=Decimal("200.00"),
                occurred_at=datetime.now(timezone.utc),
                value_date=date(2026, 8, 2), description_raw="Test b2",
                description_norm="test b2", match_status="UNMATCHED"
            )

            # Add exceptions to b1 and b2
            e1 = schema.ExceptionRecord(
                id=f"exc1_{uuid.uuid4().hex[:6]}", org_id=org_id, batch_id=b1,
                exception_type="PERIOD_CUTOFF_TIMING_LAG", severity="HIGH", state="OPEN",
                impact_minor=10000
            )
            e2 = schema.ExceptionRecord(
                id=f"exc2_{uuid.uuid4().hex[:6]}", org_id=org_id, batch_id=b2,
                exception_type="FEE_AND_TAX_BOOKED_NET", severity="MEDIUM", state="OPEN",
                impact_minor=20000
            )

            # Add proposal to e1
            p1 = schema.ResolutionProposal(
                id=f"prop1_{uuid.uuid4().hex[:6]}", org_id=org_id, exception_id=e1.id,
                action="ACCRUE_TO_CLEARING", recommended_parameters={"account": "1290"},
                justification="Timing difference accrual", confidence=0.95, status="PENDING_APPROVAL"
            )

            db.add_all([t1, t2, e1, e2, p1])
            db.commit()

        user_mock = {"user_id": "usr_test", "org_id": org_id, "role": "approver"}

        # Scoped transactions
        tx_b1 = get_transactions(batch_id=b1, current_user=user_mock)
        self.assertEqual(tx_b1["total"], 1)
        self.assertEqual(tx_b1["items"][0]["external_id"], "PAY-B1-01")

        tx_b2 = get_transactions(batch_id=b2, current_user=user_mock)
        self.assertEqual(tx_b2["total"], 1)
        self.assertEqual(tx_b2["items"][0]["external_id"], "UTR-B2-01")

        # Scoped exceptions
        ex_b1 = get_exceptions(batch_id=b1, current_user=user_mock)
        self.assertEqual(ex_b1["total"], 1)
        self.assertEqual(ex_b1["items"][0]["exception_type"], "PERIOD_CUTOFF_TIMING_LAG")

        # Scoped approvals
        app_b1 = get_pending_approvals(batch_id=b1, current_user=user_mock)
        self.assertEqual(app_b1["total"], 1)

        app_b2 = get_pending_approvals(batch_id=b2, current_user=user_mock)
        self.assertEqual(app_b2["total"], 0)


if __name__ == "__main__":
    unittest.main()
