import os
import sys
import unittest
import uuid
from datetime import date, datetime, timezone

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.models.schemas import (
    CanonicalTransaction, SourceKind, TxnDirection, MatchSchema, MatchLegSchema,
    MatchTypeEnum, MatchMethodEnum, LegRoleEnum, DecisionTier, ReferenceKeys
)
from app.services.matching_engine import AccountingSemanticGate, ReconciliationGraphBuilder, ReconciliationEngine


class TestAccountingSemantics(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        from app.db.database import init_db
        init_db()

    def setUp(self):
        self.org_id = "00000000-0000-0000-0000-000000000001"
        self.batch_id = "BATCH-SEMANTICS-TEST"

    def _make_txn(self, source_kind, direction, amount_minor=100000, external_id="TXN-001", account_code="1010", currency="INR", val_date=date(2026, 8, 15)):
        return CanonicalTransaction(
            id=str(uuid.uuid4()),
            org_id=self.org_id,
            batch_id=self.batch_id,
            source_kind=source_kind,
            external_id=external_id,
            direction=direction,
            amount_minor=amount_minor,
            currency=currency,
            occurred_at=datetime(2026, 8, 15, 12, 0, 0, tzinfo=timezone.utc),
            value_date=val_date,
            description_raw=f"Test {source_kind.value} {direction.value}",
            description_norm=f"test {source_kind.value.lower()} {direction.value.lower()}",
            account_code=account_code,
            reference_keys=ReferenceKeys(payment=[external_id], invoice=[external_id])
        )

    def test_gateway_inflow_matches_bank_credit(self):
        gw = self._make_txn(SourceKind.GATEWAY, TxnDirection.INFLOW, amount_minor=100000, external_id="PAY-01")
        bk = self._make_txn(SourceKind.BANK, TxnDirection.CREDIT, amount_minor=100000, external_id="PAY-01")
        ok, reason = AccountingSemanticGate.can_match(gw, bk)
        self.assertTrue(ok, f"Expected match but failed with reason: {reason}")

    def test_gateway_inflow_rejects_bank_debit_polarity_mismatch(self):
        gw = self._make_txn(SourceKind.GATEWAY, TxnDirection.INFLOW, amount_minor=100000, external_id="PAY-02")
        bk = self._make_txn(SourceKind.BANK, TxnDirection.DEBIT, amount_minor=100000, external_id="PAY-02")
        ok, reason = AccountingSemanticGate.can_match(gw, bk)
        self.assertFalse(ok)
        self.assertIn("Polarity Mismatch", reason)

    def test_cross_currency_rejection(self):
        gw = self._make_txn(SourceKind.GATEWAY, TxnDirection.INFLOW, amount_minor=100000, currency="INR")
        bk = self._make_txn(SourceKind.BANK, TxnDirection.CREDIT, amount_minor=100000, currency="USD")
        ok, reason = AccountingSemanticGate.can_match(gw, bk)
        self.assertFalse(ok)
        self.assertIn("Currency mismatch", reason)

    def test_chronology_date_violation_rejection(self):
        gw = self._make_txn(SourceKind.GATEWAY, TxnDirection.INFLOW, val_date=date(2026, 8, 20))
        bk = self._make_txn(SourceKind.BANK, TxnDirection.CREDIT, val_date=date(2026, 8, 10))  # 10 days before capture!
        ok, reason = AccountingSemanticGate.can_match(gw, bk)
        self.assertFalse(ok)
        self.assertIn("Chronology Violation", reason)

    def test_three_way_reconciliation_graph_builder(self):
        gw = self._make_txn(SourceKind.GATEWAY, TxnDirection.INFLOW, amount_minor=100000, external_id="PAY-100")
        bk = self._make_txn(SourceKind.BANK, TxnDirection.CREDIT, amount_minor=100000, external_id="PAY-100")
        gl = self._make_txn(SourceKind.LEDGER, TxnDirection.DEBIT, amount_minor=100000, external_id="PAY-100", account_code="1010")

        # Create 2 pairwise matches forming a 3-way triangle (GW <-> BK, BK <-> GL)
        m1 = MatchSchema(
            id=str(uuid.uuid4()),
            batch_id=self.batch_id,
            match_type=MatchTypeEnum.ONE_TO_ONE,
            method=MatchMethodEnum.EXACT_ID,
            score=1.0,
            confidence=1.0,
            decision_tier=DecisionTier.RESOLVED,
            legs=[
                MatchLegSchema(transaction_id=gw.id, role=LegRoleEnum.PRIMARY, signed_amount_minor=gw.amount_minor),
                MatchLegSchema(transaction_id=bk.id, role=LegRoleEnum.COUNTERPART, signed_amount_minor=-bk.amount_minor)
            ]
        )
        m2 = MatchSchema(
            id=str(uuid.uuid4()),
            batch_id=self.batch_id,
            match_type=MatchTypeEnum.ONE_TO_ONE,
            method=MatchMethodEnum.EXACT_ID,
            score=1.0,
            confidence=1.0,
            decision_tier=DecisionTier.RESOLVED,
            legs=[
                MatchLegSchema(transaction_id=bk.id, role=LegRoleEnum.PRIMARY, signed_amount_minor=bk.amount_minor),
                MatchLegSchema(transaction_id=gl.id, role=LegRoleEnum.COUNTERPART, signed_amount_minor=-gl.amount_minor)
            ]
        )

        raw_txns = [gw, bk, gl]
        graph = ReconciliationGraphBuilder.build_reconciliation_graph(raw_txns, [m1, m2])

        self.assertEqual(graph["three_way_matches_count"], 1)
        self.assertEqual(graph["three_way_records_count"], 3)
        self.assertEqual(graph["three_way_match_rate"], 1.0)
        self.assertEqual(graph["pairwise_matches_count"], 0)
        self.assertEqual(graph["source_breakdown"]["gateway"]["rate"], 1.0)
        self.assertEqual(graph["source_breakdown"]["bank"]["rate"], 1.0)
        self.assertEqual(graph["source_breakdown"]["ledger"]["rate"], 1.0)

    def test_bank_credit_rejects_gl_revenue_credit_adversarial(self):
        """
        ADVERSARIAL REGRESSION TEST:
        Ensures a Bank Credit (Deposit) with identical reference and amount as a GL Revenue Credit
        is strictly REJECTED by the accounting-semantic gate and NOT matched by the reconciliation engine.
        Bank deposits must balance against Cash/Bank Asset Debit (1010) or Clearing Credit (1290), not Revenue (4010).
        """
        bk_credit = self._make_txn(
            SourceKind.BANK,
            TxnDirection.CREDIT,
            amount_minor=500000,
            external_id="INV-ADV-999"
        )
        gl_revenue_credit = self._make_txn(
            SourceKind.LEDGER,
            TxnDirection.CREDIT,
            amount_minor=500000,
            external_id="INV-ADV-999",
            account_code="4010"
        )

        ok, reason = AccountingSemanticGate.can_match(bk_credit, gl_revenue_credit)
        self.assertFalse(ok, "AccountingSemanticGate must reject Bank Credit <-> Revenue Credit match!")
        self.assertIn("Revenue account", reason)

        # Full Engine Execution verification
        engine = ReconciliationEngine(org_id=self.org_id, batch_id=self.batch_id)
        res = engine.run_full_pipeline([bk_credit, gl_revenue_credit])
        self.assertEqual(len(engine.matches), 0, "Engine must produce 0 matches for Bank Credit <-> Revenue Credit!")
        self.assertEqual(res["matched_records"], 0)
        self.assertEqual(len(engine.exceptions), 2)

    def test_gateway_inflow_rejects_gl_bank_asset_direct_match(self):
        """
        ADVERSARIAL TEST:
        Gateway Inflow cannot directly match to GL Cash/Bank Asset account (1010),
        since only Bank statement deposits balance against Bank Asset accounts.
        """
        gw = self._make_txn(SourceKind.GATEWAY, TxnDirection.INFLOW, amount_minor=200000, external_id="PAY-ADV-01")
        gl_bank = self._make_txn(SourceKind.LEDGER, TxnDirection.DEBIT, amount_minor=200000, external_id="PAY-ADV-01", account_code="1010")

        ok, reason = AccountingSemanticGate.can_match(gw, gl_bank)
        self.assertFalse(ok)
        self.assertIn("GL Bank Asset account", reason)

    def test_multi_batch_audit_persistence_and_scoped_verification(self):
        """
        MULTI-BATCH AUDIT PERSISTENCE & SCOPED INTEGRITY TEST:
        Verifies that consecutive batch runs persist distinct audit events into the database
        without sequence collision suppression, and /verify-chain accurately verifies per batch.
        """
        from app.db.database_service import DatabaseService
        from app.db.database import get_db_context, init_db
        from app.db import schema
        from app.api.v1.audit import verify_audit_chain
        from app.services.audit_chain import AuditHashChain

        init_db()

        batch_1_id = f"BATCH-MULTI-{uuid.uuid4().hex[:6]}"
        batch_2_id = f"BATCH-MULTI-{uuid.uuid4().hex[:6]}"

        t1 = self._make_txn(SourceKind.GATEWAY, TxnDirection.INFLOW, external_id="TXN-B1")
        t2 = self._make_txn(SourceKind.GATEWAY, TxnDirection.INFLOW, external_id="TXN-B2")

        now_dt = datetime(2026, 8, 26, 12, 0, 0, tzinfo=timezone.utc)

        # Build audit events for batch 1
        ev1 = {
            "event_seq": 1,
            "event_type": "BATCH_INITIATED",
            "entity_id": batch_1_id,
            "actor_id": "usr_system",
            "payload": {"batch_id": batch_1_id},
            "prev_hash": AuditHashChain.GENESIS_HASH,
            "event_hash": AuditHashChain.compute_event_hash(
                AuditHashChain.GENESIS_HASH, self.org_id, 1, "BATCH_INITIATED", batch_1_id, "usr_system", {"batch_id": batch_1_id}, now_dt
            ),
            "created_at": now_dt
        }

        # Build audit events for batch 2 (starts at event_seq 1 as well)
        ev2 = {
            "event_seq": 1,
            "event_type": "BATCH_INITIATED",
            "entity_id": batch_2_id,
            "actor_id": "usr_system",
            "payload": {"batch_id": batch_2_id},
            "prev_hash": AuditHashChain.GENESIS_HASH,
            "event_hash": AuditHashChain.compute_event_hash(
                AuditHashChain.GENESIS_HASH, self.org_id, 1, "BATCH_INITIATED", batch_2_id, "usr_system", {"batch_id": batch_2_id}, now_dt
            ),
            "created_at": now_dt
        }

        # Save batch 1
        DatabaseService.save_batch_run(
            batch_id=batch_1_id,
            org_id=self.org_id,
            canonical_txns=[t1],
            matches=[],
            exceptions=[],
            proposals=[],
            decisions={},
            audit_events=[ev1],
            summary={"match_rate": 0.0, "wall_clock_seconds": 0.1},
            cash_forecast={}
        )

        # Save batch 2
        DatabaseService.save_batch_run(
            batch_id=batch_2_id,
            org_id=self.org_id,
            canonical_txns=[t2],
            matches=[],
            exceptions=[],
            proposals=[],
            decisions={},
            audit_events=[ev2],
            summary={"match_rate": 0.0, "wall_clock_seconds": 0.1},
            cash_forecast={}
        )

        # Verify both batches persisted their audit events
        with get_db_context() as db:
            b1_events = db.query(schema.AuditEvent).filter_by(batch_id=batch_1_id).all()
            b2_events = db.query(schema.AuditEvent).filter_by(batch_id=batch_2_id).all()
            self.assertGreaterEqual(len(b1_events), 1, "Batch 1 audit events must be persisted!")
            self.assertGreaterEqual(len(b2_events), 1, "Batch 2 audit events must NOT be suppressed by Batch 1!")

        # Verify scoped chain verification
        v1 = verify_audit_chain(batch_id=batch_1_id)
        self.assertEqual(v1["status"], "VERIFIED")
        self.assertEqual(v1["total_events_checked"], 1)

        v2 = verify_audit_chain(batch_id=batch_2_id)
        self.assertEqual(v2["status"], "VERIFIED")
        self.assertEqual(v2["total_events_checked"], 1)

        v_empty = verify_audit_chain(batch_id="NON-EXISTENT-BATCH-999")
        self.assertEqual(v_empty["status"], "NO_AUDIT_EVENTS")
        self.assertEqual(v_empty["total_events_checked"], 0)

    def test_immutable_completed_batch_rejection(self):
        """
        IMMUTABILITY TEST:
        Verifies that attempting to overwrite an already COMPLETED batch raises IMMUTABLE_BATCH_VIOLATION.
        """
        from app.db.database_service import DatabaseService

        immutable_batch_id = f"BATCH-IMMUTABLE-{uuid.uuid4().hex[:6]}"
        t = self._make_txn(SourceKind.GATEWAY, TxnDirection.INFLOW, external_id="TXN-IMMUTABLE")

        # 1st run: Successfully saves
        DatabaseService.save_batch_run(
            batch_id=immutable_batch_id,
            org_id=self.org_id,
            canonical_txns=[t],
            matches=[],
            exceptions=[],
            proposals=[],
            decisions={},
            audit_events=[],
            summary={"match_rate": 0.0, "wall_clock_seconds": 0.1},
            cash_forecast={}
        )

        # 2nd run with same batch ID: Must be rejected to preserve immutable history
        with self.assertRaises(ValueError) as ctx:
            DatabaseService.save_batch_run(
                batch_id=immutable_batch_id,
                org_id=self.org_id,
                canonical_txns=[t],
                matches=[],
                exceptions=[],
                proposals=[],
                decisions={},
                audit_events=[],
                summary={"match_rate": 0.0, "wall_clock_seconds": 0.1},
                cash_forecast={}
            )
        self.assertIn("IMMUTABLE_BATCH_VIOLATION", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
