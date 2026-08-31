import os
import sys
import unittest
from datetime import datetime, date

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.models.schemas import SourceKind, TxnDirection, MatchTypeEnum, MatchMethodEnum, DecisionTier
from app.services.normalizer import NormalizerService
from app.services.matching_engine import ReconciliationEngine

class TestN1SettlementSolver(unittest.TestCase):
    def setUp(self):
        self.org_id = "00000000-0000-0000-0000-000000000001"
        self.batch_id = "BATCH-TEST-N1-01"

    def test_n1_declared_settlement_grouping(self):
        """Validates N:1 solver decomposes bank wire into multiple gateway payments using declared settlement key."""
        # 3 Gateway payments of Rs 1000, 2000, 3000 (total gross = Rs 6000)
        # 2% MDR = 120, 18% GST on MDR = 21.60 -> Total fee = 141.60 -> Net = 5858.40 (585840 paise)
        # Per row:
        # 100000: fee=2000, tax=360 -> net = 97640
        # 200000: fee=4000, tax=720 -> net = 195280
        # 300000: fee=6000, tax=1080 -> net = 292920
        # Total net = 97640 + 195280 + 292920 = 585840 paise (Rs 5858.40)
        gw1 = NormalizerService.normalize_row({
            "payment_id": "pay_N1_01",
            "gross_amount": 100000,
            "created_at": "2026-08-20T10:00:00",
            "description": "Invoice INV-2001 SETTLE_BATCH_8821"
        }, SourceKind.GATEWAY, self.org_id, self.batch_id)

        gw2 = NormalizerService.normalize_row({
            "payment_id": "pay_N1_02",
            "gross_amount": 200000,
            "created_at": "2026-08-20T10:05:00",
            "description": "Invoice INV-2002 SETTLE_BATCH_8821"
        }, SourceKind.GATEWAY, self.org_id, self.batch_id)

        gw3 = NormalizerService.normalize_row({
            "payment_id": "pay_N1_03",
            "gross_amount": 300000,
            "created_at": "2026-08-20T10:10:00",
            "description": "Invoice INV-2003 SETTLE_BATCH_8821"
        }, SourceKind.GATEWAY, self.org_id, self.batch_id)

        # Single bank settlement credit of Rs 5858.40
        bank = NormalizerService.normalize_row({
            "bank_transaction_id": "UTR-SETTLE-8821",
            "amount": 5858.40,
            "date": "2026-08-21",
            "description": "Processor Settlement Payout SETTLE_BATCH_8821",
            "type": "Credit"
        }, SourceKind.BANK, self.org_id, self.batch_id)

        engine = ReconciliationEngine(self.org_id, self.batch_id)
        res = engine.run_full_pipeline([gw1, gw2, gw3, bank])

        # All 4 records should be matched in a single N:1 MatchSchema
        self.assertEqual(len(engine.matches), 1)
        m = engine.matches[0]
        self.assertEqual(m.match_type, MatchTypeEnum.MANY_TO_ONE)
        self.assertEqual(m.method, MatchMethodEnum.SETTLEMENT_NET_DP)
        self.assertEqual(m.decision_tier, DecisionTier.RESOLVED_WITH_EXPLANATION)
        self.assertEqual(len(m.legs), 4) # 3 primary + 1 counterpart
        self.assertEqual(m.solver_evidence["payment_count"], 3)
        self.assertEqual(m.solver_evidence["settlement_type"], "DECLARED_SETTLEMENT_BATCH")
        self.assertEqual(res["matched_records"], 4)

    def test_n1_subset_sum_dp_solver(self):
        """Validates N:1 subset-sum DP solver finds the unique combination of gateway payments equaling a bank credit."""
        # 4 Gateway payments; only 3 of them belong to this settlement wire
        # gw1: 1000.00 -> net = 976.40
        # gw2: 2000.00 -> net = 1952.80
        # gw3: 1500.00 -> net = 1464.60 (gross 150000, fee 3000, tax 540 -> net 146460)
        # gw4: 5000.00 -> net = 4882.00 (not part of this batch)
        # Target = 976.40 + 1952.80 + 1464.60 = 4393.80 (439380 paise)
        gw1 = NormalizerService.normalize_row({
            "payment_id": "pay_DP_01",
            "gross_amount": 100000,
            "created_at": "2026-08-20T10:00:00",
            "description": "Payment Order A"
        }, SourceKind.GATEWAY, self.org_id, self.batch_id)

        gw2 = NormalizerService.normalize_row({
            "payment_id": "pay_DP_02",
            "gross_amount": 200000,
            "created_at": "2026-08-20T11:00:00",
            "description": "Payment Order B"
        }, SourceKind.GATEWAY, self.org_id, self.batch_id)

        gw3 = NormalizerService.normalize_row({
            "payment_id": "pay_DP_03",
            "gross_amount": 150000,
            "created_at": "2026-08-20T12:00:00",
            "description": "Payment Order C"
        }, SourceKind.GATEWAY, self.org_id, self.batch_id)

        gw4 = NormalizerService.normalize_row({
            "payment_id": "pay_DP_04",
            "gross_amount": 500000,
            "created_at": "2026-08-20T13:00:00",
            "description": "Payment Order D"
        }, SourceKind.GATEWAY, self.org_id, self.batch_id)

        bank = NormalizerService.normalize_row({
            "bank_transaction_id": "UTR-DP-WIRE-01",
            "amount": 4393.80,
            "date": "2026-08-22",
            "description": "Razorpay Net Settlement Payout",
            "type": "Credit"
        }, SourceKind.BANK, self.org_id, self.batch_id)

        engine = ReconciliationEngine(self.org_id, self.batch_id)
        res = engine.run_full_pipeline([gw1, gw2, gw3, gw4, bank])

        self.assertEqual(len(engine.matches), 1)
        m = engine.matches[0]
        self.assertEqual(m.match_type, MatchTypeEnum.MANY_TO_ONE)
        self.assertEqual(m.method, MatchMethodEnum.SETTLEMENT_NET_DP)
        self.assertEqual(m.solver_evidence["settlement_type"], "BOUNDED_SUBSET_SUM_DP")
        self.assertEqual(m.solver_evidence["payment_count"], 3)
        # gw4 should remain unmatched
        self.assertNotIn(gw4.id, engine.matched_txn_ids)

    def test_n1_declared_settlement_1_5_percent_fee(self):
        """Validates N:1 solver correctly matches and generates evidence for 1.5% Enterprise fee settlement batches."""
        # 3 Gateway payments of Rs 1000, 2000, 3000 (total gross = Rs 6000)
        # 1.5% MDR + 18% GST:
        # 1000: fee=1500, tax=270 -> net=98230
        # 2000: fee=3000, tax=540 -> net=196460
        # 3000: fee=4500, tax=810 -> net=294690
        # Total net = 98230 + 196460 + 294690 = 589380 paise (Rs 5893.80)
        gw1 = NormalizerService.normalize_row({
            "payment_id": "pay_ENT_01",
            "gross_amount": 100000,
            "created_at": "2026-08-20T10:00:00",
            "description": "Invoice INV-ENT-01 SETTLE_BATCH_ENT99"
        }, SourceKind.GATEWAY, self.org_id, self.batch_id)

        gw2 = NormalizerService.normalize_row({
            "payment_id": "pay_ENT_02",
            "gross_amount": 200000,
            "created_at": "2026-08-20T10:05:00",
            "description": "Invoice INV-ENT-02 SETTLE_BATCH_ENT99"
        }, SourceKind.GATEWAY, self.org_id, self.batch_id)

        gw3 = NormalizerService.normalize_row({
            "payment_id": "pay_ENT_03",
            "gross_amount": 300000,
            "created_at": "2026-08-20T10:10:00",
            "description": "Invoice INV-ENT-03 SETTLE_BATCH_ENT99"
        }, SourceKind.GATEWAY, self.org_id, self.batch_id)

        # Bank credit of Rs 5893.80 (589380 paise)
        bank = NormalizerService.normalize_row({
            "bank_transaction_id": "UTR-ENT-99",
            "amount": 5893.80,
            "date": "2026-08-21",
            "description": "Enterprise Processor Settlement SETTLE_BATCH_ENT99",
            "type": "Credit"
        }, SourceKind.BANK, self.org_id, self.batch_id)

        engine = ReconciliationEngine(self.org_id, self.batch_id)
        res = engine.run_full_pipeline([gw1, gw2, gw3, bank])

        self.assertEqual(len(engine.matches), 1)
        m = engine.matches[0]
        self.assertEqual(m.match_type, MatchTypeEnum.MANY_TO_ONE)
        self.assertEqual(m.decision_tier, DecisionTier.RESOLVED_WITH_EXPLANATION)
        # Evidence must reflect the exact 1.5% rate and zero variance
        self.assertEqual(m.solver_evidence["fee_pct"], 0.015)
        self.assertEqual(m.solver_evidence["calculated_net_minor"], 589380)
        self.assertEqual(m.solver_evidence["bank_credit_minor"], 589380)
        self.assertEqual(m.solver_evidence["variance_minor"], 0)
        self.assertIn("1.5% Enterprise MDR", m.solver_evidence["arithmetic_proof"])

    def test_n1_declared_settlement_0_percent_gross_wire(self):
        """Validates N:1 solver correctly matches and generates evidence for 0% direct gross settlement batches."""
        gw1 = NormalizerService.normalize_row({
            "payment_id": "pay_ZERO_01",
            "gross_amount": 100000,
            "created_at": "2026-08-20T10:00:00",
            "description": "Direct Transfer SETTLE_BATCH_ZERO01"
        }, SourceKind.GATEWAY, self.org_id, self.batch_id)

        gw2 = NormalizerService.normalize_row({
            "payment_id": "pay_ZERO_02",
            "gross_amount": 200000,
            "created_at": "2026-08-20T10:05:00",
            "description": "Direct Transfer SETTLE_BATCH_ZERO01"
        }, SourceKind.GATEWAY, self.org_id, self.batch_id)

        bank = NormalizerService.normalize_row({
            "bank_transaction_id": "UTR-ZERO-01",
            "amount": 3000.00,
            "date": "2026-08-21",
            "description": "Gross Direct Settlement SETTLE_BATCH_ZERO01",
            "type": "Credit"
        }, SourceKind.BANK, self.org_id, self.batch_id)

        engine = ReconciliationEngine(self.org_id, self.batch_id)
        res = engine.run_full_pipeline([gw1, gw2, bank])

        self.assertEqual(len(engine.matches), 1)
        m = engine.matches[0]
        self.assertEqual(m.solver_evidence["fee_pct"], 0.0)
        self.assertEqual(m.solver_evidence["calculated_net_minor"], 300000)
        self.assertEqual(m.solver_evidence["bank_credit_minor"], 300000)
        self.assertEqual(m.solver_evidence["variance_minor"], 0)

    def test_n1_ambiguous_subset_safeguard(self):
        """Validates ambiguity guard triggers and routes to Tier 3 when multiple subset combinations equal the wire."""
        # Two distinct combinations of payments equal the exact same total:
        # Combo A: gw1 (1000) + gw2 (2000) = 3000 gross
        # Combo B: gw3 (1000) + gw4 (2000) = 3000 gross (same net)
        gw1 = NormalizerService.normalize_row({
            "payment_id": "pay_AMB_01",
            "gross_amount": 100000,
            "created_at": "2026-08-20T10:00:00",
            "description": "Payment Order 1"
        }, SourceKind.GATEWAY, self.org_id, self.batch_id)

        gw2 = NormalizerService.normalize_row({
            "payment_id": "pay_AMB_02",
            "gross_amount": 200000,
            "created_at": "2026-08-20T11:00:00",
            "description": "Payment Order 2"
        }, SourceKind.GATEWAY, self.org_id, self.batch_id)

        gw3 = NormalizerService.normalize_row({
            "payment_id": "pay_AMB_03",
            "gross_amount": 100000,
            "created_at": "2026-08-20T12:00:00",
            "description": "Payment Order 3"
        }, SourceKind.GATEWAY, self.org_id, self.batch_id)

        gw4 = NormalizerService.normalize_row({
            "payment_id": "pay_AMB_04",
            "gross_amount": 200000,
            "created_at": "2026-08-20T13:00:00",
            "description": "Payment Order 4"
        }, SourceKind.GATEWAY, self.org_id, self.batch_id)

        # Wire for net of 3000 (976.40 + 1952.80 = 2929.20)
        bank = NormalizerService.normalize_row({
            "bank_transaction_id": "UTR-AMB-WIRE",
            "amount": 2929.20,
            "date": "2026-08-22",
            "description": "Ambiguous Settlement Wire",
            "type": "Credit"
        }, SourceKind.BANK, self.org_id, self.batch_id)

        engine = ReconciliationEngine(self.org_id, self.batch_id)
        res = engine.run_full_pipeline([gw1, gw2, gw3, gw4, bank])

        # Ambiguity guard should have caught this
        safeguards = [s["safeguard"] for s in engine.safeguards_triggered]
        self.assertIn("AMBIGUOUS_SETTLEMENT_GROUP_SAFEGUARD", safeguards)
        # Bank should NOT be falsely matched
        self.assertEqual(bank.match_status, "NEEDS_REVIEW")

if __name__ == "__main__":
    unittest.main()
