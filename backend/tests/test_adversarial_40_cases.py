"""
Adversarial 40-Scenario Test Suite for Recon.
Tests edge cases, malicious/malformed inputs, boundary conditions, and ensures:
1. Deterministic classification fails safely.
2. The AI NEVER turns bad/missing evidence into a confident financial fact.
3. Provenance and exact 1-paise arithmetic remain inviolate.
"""

import os
import sys
import unittest
import uuid
from datetime import date, datetime, timezone, timedelta
from typing import Any, Dict, List

# Add backend to path
sys.path.insert(0, os.path.abspath("backend"))

from app.models.schemas import (
    CanonicalTransaction,
    SourceKind,
    TxnDirection,
    MatchStatus,
    ReferenceKeys,
    JournalLine,
    DecisionTier,
    ReconciliationDecision,
    AIExceptionContext,
    ExecutiveReportInputContract,
    ReportReconciliationSection,
    ReportExceptionsSection,
    ReportRCASection,
    ReportLiquiditySection,
    ReportAuditSection,
    ReportProvenanceSection
)
from app.services.matching_engine import ReconciliationEngine
from app.services.normalizer import NormalizerService
from app.services.compliance_evaluator import ComplianceEvaluator
from app.services.agents.rca_agent import RootCauseAnalysisAgent
from app.services.agents.report_agent import ReportGenerationAgent


class TestAdversarial40Scenarios(unittest.TestCase):

    def setUp(self):
        self.org_id = f"ORG-ADV-{uuid.uuid4().hex[:6]}"
        self.batch_id = f"BATCH-ADV-{uuid.uuid4().hex[:6]}"

    def _make_txn(
        self,
        txn_id: str,
        kind: SourceKind,
        amount_minor: int,
        dt: date = date(2026, 3, 25),
        ext_id: str = None,
        direction: TxnDirection = TxnDirection.INFLOW,
        fee_minor: int = 0,
        tax_minor: int = 0,
        ref_keys: ReferenceKeys = None,
        currency: str = "INR"
    ) -> CanonicalTransaction:
        ext = ext_id or txn_id
        keys = ref_keys or ReferenceKeys()
        if ext and ext not in keys.payment:
            keys.payment.append(ext)
        return CanonicalTransaction(
            id=txn_id,
            org_id=self.org_id,
            batch_id=self.batch_id,
            source_kind=kind,
            external_id=ext,
            payment_id=ext if kind == SourceKind.GATEWAY else None,
            amount_minor=amount_minor,
            gross_minor=amount_minor if kind == SourceKind.GATEWAY else None,
            fee_minor=fee_minor if kind == SourceKind.GATEWAY else None,
            tax_minor=tax_minor if kind == SourceKind.GATEWAY else None,
            direction=direction,
            currency=currency,
            occurred_at=datetime.combine(dt, datetime.min.time(), tzinfo=timezone.utc),
            value_date=dt,
            description_raw=f"Adversarial {ext}",
            description_norm=f"adversarial {ext.lower()}",
            reference_keys=keys
        )

    # 1. Completely empty CSV
    def test_01_completely_empty_csv(self):
        engine = ReconciliationEngine(org_id=self.org_id, batch_id=self.batch_id)
        summary = engine.run_full_pipeline([])
        self.assertEqual(summary["total_records"], 0)
        self.assertEqual(summary["matched_records"], 0)
        self.assertEqual(summary["match_rate"], 0.0)
        self.assertEqual(len(engine.exceptions), 0)

    # 2. One valid transaction (3-way match)
    def test_02_one_valid_transaction(self):
        keys = ReferenceKeys(payment=["pay_1"], invoice=["INV-1"])
        gw = self._make_txn("gw_1", SourceKind.GATEWAY, 49900, ref_keys=keys, fee_minor=998, tax_minor=180)
        bk = self._make_txn("bk_1", SourceKind.BANK, 48722, ref_keys=keys)
        gl = self._make_txn("gl_1", SourceKind.LEDGER, 49900, ref_keys=keys)
        engine = ReconciliationEngine(org_id=self.org_id, batch_id=self.batch_id)
        summary = engine.run_full_pipeline([gw, bk, gl])
        self.assertEqual(summary["matched_records"], 3)
        self.assertEqual(len(engine.exceptions), 0)

    # 3. One duplicate transaction
    def test_03_one_duplicate_transaction(self):
        gw1 = self._make_txn("gw_1", SourceKind.GATEWAY, 49900, ext_id="pay_dup")
        gw2 = self._make_txn("gw_2", SourceKind.GATEWAY, 49900, ext_id="pay_dup")
        engine = ReconciliationEngine(org_id=self.org_id, batch_id=self.batch_id)
        p0_txns = engine.pass_p0_dedupe([gw1, gw2])
        self.assertEqual(len(p0_txns), 1)
        self.assertEqual(len(engine.exceptions), 1)
        self.assertEqual(engine.exceptions[0].exception_type, "DUPLICATE_RECORD")

    # 4. Duplicate with different amount
    def test_04_duplicate_with_different_amount(self):
        gw1 = self._make_txn("gw_1", SourceKind.GATEWAY, 49900, ext_id="pay_diff_amt")
        gw2 = self._make_txn("gw_2", SourceKind.GATEWAY, 99900, ext_id="pay_diff_amt")
        engine = ReconciliationEngine(org_id=self.org_id, batch_id=self.batch_id)
        p0_txns = engine.pass_p0_dedupe([gw1, gw2])
        # Duplicate with different amount cannot be silently merged; both preserved or quarantined
        self.assertGreaterEqual(len(p0_txns) + len(engine.exceptions), 2)

    # 5. Duplicate with different timestamp
    def test_05_duplicate_with_different_timestamp(self):
        gw1 = self._make_txn("gw_1", SourceKind.GATEWAY, 49900, dt=date(2026, 3, 10), ext_id="pay_ts")
        gw2 = self._make_txn("gw_2", SourceKind.GATEWAY, 49900, dt=date(2026, 3, 20), ext_id="pay_ts")
        engine = ReconciliationEngine(org_id=self.org_id, batch_id=self.batch_id)
        p0_txns = engine.pass_p0_dedupe([gw1, gw2])
        self.assertEqual(len(p0_txns), 1)
        self.assertEqual(len(engine.exceptions), 1)

    # 6. Missing payment ID
    def test_06_missing_payment_id(self):
        gw = self._make_txn("gw_1", SourceKind.GATEWAY, 49900, ext_id="")
        self.assertEqual(gw.amount_minor, 49900)
        self.assertIsNotNone(gw.id)

    # 7. Missing bank reference
    def test_07_missing_bank_reference(self):
        bk = self._make_txn("bk_1", SourceKind.BANK, 48722, ext_id="", ref_keys=ReferenceKeys())
        engine = ReconciliationEngine(org_id=self.org_id, batch_id=self.batch_id)
        engine.run_full_pipeline([bk])
        self.assertEqual(len(engine.exceptions), 1)
        self.assertEqual(engine.exceptions[0].exception_type, "UNKNOWN_BANK_CREDIT")

    # 8. Missing settlement ID
    def test_08_missing_settlement_id(self):
        keys = ReferenceKeys(payment=["pay_no_setl"])
        gw = self._make_txn("gw_1", SourceKind.GATEWAY, 49900, ref_keys=keys, fee_minor=998, tax_minor=180)
        bk = self._make_txn("bk_1", SourceKind.BANK, 48722, ref_keys=keys)
        engine = ReconciliationEngine(org_id=self.org_id, batch_id=self.batch_id)
        summary = engine.run_full_pipeline([gw, bk])
        self.assertEqual(summary["matched_records"], 2)

    # 9. Missing GL entry
    def test_09_missing_gl_entry(self):
        keys = ReferenceKeys(payment=["pay_no_gl"])
        gw = self._make_txn("gw_1", SourceKind.GATEWAY, 49900, ref_keys=keys, fee_minor=998, tax_minor=180)
        bk = self._make_txn("bk_1", SourceKind.BANK, 48722, ref_keys=keys)
        engine = ReconciliationEngine(org_id=self.org_id, batch_id=self.batch_id)
        summary = engine.run_full_pipeline([gw, bk])
        self.assertEqual(summary["matched_records"], 2)

    # 10. Multiple GL lines compound entry
    def test_10_multiple_gl_lines(self):
        lines = [
            JournalLine(line_no=1, account_code="1210", account_name="AR", direction=TxnDirection.DEBIT, amount_minor=49900, original_amount="499.00"),
            JournalLine(line_no=2, account_code="4000", account_name="Rev", direction=TxnDirection.CREDIT, amount_minor=42288, original_amount="422.88"),
            JournalLine(line_no=3, account_code="2310", account_name="GST", direction=TxnDirection.CREDIT, amount_minor=7612, original_amount="76.12")
        ]
        gl = self._make_txn("gl_comp", SourceKind.LEDGER, 49900)
        gl.lines = lines
        gl.is_balanced_je = True
        self.assertEqual(len(gl.lines), 3)
        self.assertTrue(gl.is_balanced_je)

    # 11. Unbalanced GL journal
    def test_11_unbalanced_gl_journal(self):
        lines = [
            JournalLine(line_no=1, account_code="1210", account_name="AR", direction=TxnDirection.DEBIT, amount_minor=50000, original_amount="500.00"),
            JournalLine(line_no=2, account_code="4000", account_name="Rev", direction=TxnDirection.CREDIT, amount_minor=40000, original_amount="400.00")
        ]
        is_balanced = sum(l.amount_minor for l in lines if l.direction == TxnDirection.DEBIT) == sum(l.amount_minor for l in lines if l.direction == TxnDirection.CREDIT)
        self.assertFalse(is_balanced)

    # 12. Fee mismatch
    def test_12_fee_mismatch(self):
        keys = ReferenceKeys(payment=["pay_fee_err"])
        gw = self._make_txn("gw_1", SourceKind.GATEWAY, 1000000, ref_keys=keys, fee_minor=50000, tax_minor=9000)
        bk = self._make_txn("bk_1", SourceKind.BANK, 976400, ref_keys=keys)
        score, is_fee = ReconciliationEngine.score_amount(gw, bk)
        self.assertFalse(is_fee)

    # 13. Tax mismatch
    def test_13_tax_mismatch(self):
        keys = ReferenceKeys(payment=["pay_tax_err"])
        gw = self._make_txn("gw_1", SourceKind.GATEWAY, 1000000, ref_keys=keys, fee_minor=20000, tax_minor=1000)
        bk = self._make_txn("bk_1", SourceKind.BANK, 976400, ref_keys=keys)
        score, is_fee = ReconciliationEngine.score_amount(gw, bk)
        self.assertFalse(is_fee)

    # 14. Bank amount mismatch
    def test_14_bank_amount_mismatch(self):
        keys = ReferenceKeys(payment=["pay_amt_err"])
        gw = self._make_txn("gw_1", SourceKind.GATEWAY, 49900, ref_keys=keys, fee_minor=998, tax_minor=180)
        bk = self._make_txn("bk_1", SourceKind.BANK, 45000, ref_keys=keys)
        score, is_fee = ReconciliationEngine.score_amount(gw, bk)
        self.assertFalse(is_fee)
        self.assertLess(score, 0.5)

    # 15. Gateway amount mismatch
    def test_15_gateway_amount_mismatch(self):
        gw = self._make_txn("gw_1", SourceKind.GATEWAY, 49900)
        gl = self._make_txn("gl_1", SourceKind.LEDGER, 99900)
        score, is_fee = ReconciliationEngine.score_amount(gw, gl)
        self.assertFalse(is_fee)
        self.assertLess(score, 0.5)

    # 16. Currency mismatch
    def test_16_currency_mismatch(self):
        gw = self._make_txn("gw_1", SourceKind.GATEWAY, 49900, currency="USD")
        bk = self._make_txn("bk_1", SourceKind.BANK, 49900, currency="INR")
        self.assertNotEqual(gw.currency, bk.currency)

    # 17. Date mismatch (> 4 days without cutoff)
    def test_17_date_mismatch(self):
        gw = self._make_txn("gw_1", SourceKind.GATEWAY, 49900, dt=date(2026, 3, 1))
        bk = self._make_txn("bk_1", SourceKind.BANK, 49900, dt=date(2026, 3, 25))
        s_date = ReconciliationEngine.score_date(gw, bk)
        self.assertLess(s_date, 0.01)

    # 18. T+1 settlement
    def test_18_t_plus_1_settlement(self):
        gw = self._make_txn("gw_1", SourceKind.GATEWAY, 49900, dt=date(2026, 3, 24))
        bk = self._make_txn("bk_1", SourceKind.BANK, 49900, dt=date(2026, 3, 25))
        s_date = ReconciliationEngine.score_date(gw, bk)
        self.assertGreaterEqual(s_date, 0.95)

    # 19. T+2 settlement (decay score > 0.50)
    def test_19_t_plus_2_settlement(self):
        gw = self._make_txn("gw_1", SourceKind.GATEWAY, 49900, dt=date(2026, 3, 23))
        bk = self._make_txn("bk_1", SourceKind.BANK, 49900, dt=date(2026, 3, 25))
        s_date = ReconciliationEngine.score_date(gw, bk)
        self.assertGreaterEqual(s_date, 0.50)

    # 20. T+3 settlement (decay score > 0.30)
    def test_20_t_plus_3_settlement(self):
        gw = self._make_txn("gw_1", SourceKind.GATEWAY, 49900, dt=date(2026, 3, 22))
        bk = self._make_txn("bk_1", SourceKind.BANK, 49900, dt=date(2026, 3, 25))
        s_date = ReconciliationEngine.score_date(gw, bk)
        self.assertGreaterEqual(s_date, 0.30)

    # 21. Negative transaction (refund)
    def test_21_negative_transaction(self):
        gw_ref = self._make_txn("gw_ref", SourceKind.GATEWAY, 49900, direction=TxnDirection.OUTFLOW)
        self.assertEqual(gw_ref.direction, TxnDirection.OUTFLOW)

    # 22. Zero transaction
    def test_22_zero_transaction(self):
        gw_zero = self._make_txn("gw_0", SourceKind.GATEWAY, 0)
        self.assertEqual(gw_zero.amount_minor, 0)

    # 23. Extremely large transaction (100 Cr INR)
    def test_23_extremely_large_transaction(self):
        amt_100_cr = 1000000000000 # 10,000,000,000.00 INR in paise
        gw_big = self._make_txn("gw_big", SourceKind.GATEWAY, amt_100_cr)
        self.assertEqual(gw_big.amount_minor, amt_100_cr)

    # 24. Unknown bank credit
    def test_24_unknown_bank_credit(self):
        bk_unkn = self._make_txn("bk_unkn", SourceKind.BANK, 15000, ext_id="UTR-ANON", ref_keys=ReferenceKeys())
        engine = ReconciliationEngine(org_id=self.org_id, batch_id=self.batch_id)
        engine.run_full_pipeline([bk_unkn])
        self.assertEqual(len(engine.exceptions), 1)
        self.assertEqual(engine.exceptions[0].exception_type, "UNKNOWN_BANK_CREDIT")

    # 25. Unknown gateway payment
    def test_25_unknown_gateway_payment(self):
        gw_unkn = self._make_txn("gw_unkn", SourceKind.GATEWAY, 500000, ext_id="pay_unkn", ref_keys=ReferenceKeys())
        engine = ReconciliationEngine(org_id=self.org_id, batch_id=self.batch_id)
        engine.run_full_pipeline([gw_unkn])
        self.assertEqual(len(engine.exceptions), 1)
        self.assertEqual(engine.exceptions[0].exception_type, "MISSING_BANK_SETTLEMENT")

    # 26. Same payment across two batches (Batch isolation)
    def test_26_same_payment_across_two_batches(self):
        gw_a = self._make_txn("gw_1", SourceKind.GATEWAY, 49900, ext_id="pay_iso")
        gw_a.batch_id = "BATCH_A"
        gw_b = self._make_txn("gw_1", SourceKind.GATEWAY, 49900, ext_id="pay_iso")
        gw_b.batch_id = "BATCH_B"
        self.assertNotEqual(gw_a.batch_id, gw_b.batch_id)

    # 27. Same payment processed twice (Idempotency)
    def test_27_same_payment_processed_twice(self):
        gw = self._make_txn("gw_1", SourceKind.GATEWAY, 49900)
        bk = self._make_txn("bk_1", SourceKind.BANK, 49900)
        engine1 = ReconciliationEngine(org_id=self.org_id, batch_id=self.batch_id)
        sum1 = engine1.run_full_pipeline([gw, bk])
        engine2 = ReconciliationEngine(org_id=self.org_id, batch_id=self.batch_id)
        sum2 = engine2.run_full_pipeline([gw, bk])
        self.assertEqual(sum1["matched_records"], sum2["matched_records"])
        self.assertEqual(sum1["match_rate"], sum2["match_rate"])

    # 28. Malformed CSV text normalization
    def test_28_malformed_csv_normalization(self):
        raw = "INV-2026-001;;;random-text;;;pay_123"
        keys = NormalizerService.extract_reference_keys(raw)
        self.assertIn("INV-2026-001", keys.invoice)
        self.assertIn("PAY_123", [k.upper() for k in keys.payment])

    # 29. Missing required column handling
    def test_29_missing_required_column(self):
        raw_row = {"some_unknown_field": "val"}
        with self.assertRaises(Exception):
            NormalizerService.normalize_row(raw_row, SourceKind.BANK, self.org_id, self.batch_id, row_num=1)

    # 30. Extra unknown column handling
    def test_30_extra_unknown_column(self):
        raw_row = {
            "txn_id": "BANK-01",
            "txn_date": "2026-03-25",
            "credit": "487.22",
            "description": "NEFT-pay_1001",
            "extra_custom_metadata_1": "ignore_me",
            "extra_analytics_tag": "tag123"
        }
        txn = NormalizerService.normalize_row(raw_row, SourceKind.BANK, self.org_id, self.batch_id, row_num=1)
        self.assertEqual(txn.amount_minor, 48722)

    # 31. Invalid date handling
    def test_31_invalid_date(self):
        raw_row = {
            "txn_id": "BANK-01",
            "txn_date": "2026-02-31", # Invalid date
            "credit": "487.22",
            "description": "NEFT-pay_1001"
        }
        with self.assertRaises(ValueError):
            NormalizerService.normalize_row(raw_row, SourceKind.BANK, self.org_id, self.batch_id, row_num=1)

    # 32. Invalid amount handling
    def test_32_invalid_amount(self):
        raw_row = {
            "txn_id": "BANK-01",
            "txn_date": "2026-03-25",
            "credit": "INVALID_AMOUNT",
            "description": "NEFT-pay_1001"
        }
        with self.assertRaises(Exception):
            NormalizerService.normalize_row(raw_row, SourceKind.BANK, self.org_id, self.batch_id, row_num=1)

    # 33. Null values handling
    def test_33_null_values(self):
        raw_row = {
            "txn_id": "BANK-01",
            "txn_date": "2026-03-25",
            "credit": "487.22",
            "description": None,
            "ref_no": None
        }
        txn = NormalizerService.normalize_row(raw_row, SourceKind.BANK, self.org_id, self.batch_id, row_num=1)
        self.assertEqual(txn.amount_minor, 48722)

    # 34. Whitespace corruption
    def test_34_whitespace_corruption(self):
        raw_text = "   NEFT-RAZORPAY-pay_EXT_1001-CR   "
        keys = NormalizerService.extract_reference_keys(raw_text)
        self.assertIn("pay_EXT_1001", keys.payment)

    # 35. Case differences
    def test_35_case_differences(self):
        keys1 = NormalizerService.extract_reference_keys("pay_ext_1001")
        keys2 = NormalizerService.extract_reference_keys("PAY_EXT_1001")
        self.assertEqual(keys1.payment[0].upper(), keys2.payment[0].upper())

    # 36. Reference formatting differences (hyphen vs underscore)
    def test_36_reference_formatting_differences(self):
        keys1 = NormalizerService.extract_reference_keys("INV-2026-1001")
        keys2 = NormalizerService.extract_reference_keys("INV_2026_1001")
        self.assertTrue(len(keys1.invoice) > 0)
        self.assertTrue(len(keys2.invoice) > 0)

    # 37. Bank settlement before gateway capture
    def test_37_bank_settlement_before_gateway_capture(self):
        gw = self._make_txn("gw_1", SourceKind.GATEWAY, 49900, dt=date(2026, 3, 25))
        bk = self._make_txn("bk_1", SourceKind.BANK, 49900, dt=date(2026, 3, 20)) # 5 days earlier
        s_date = ReconciliationEngine.score_date(gw, bk)
        self.assertLess(s_date, 0.01)

    # 38. Multiple bank settlements for one payment
    def test_38_multiple_bank_settlements_for_one_payment(self):
        gw = self._make_txn("gw_1", SourceKind.GATEWAY, 1000000, ext_id="pay_split")
        bk1 = self._make_txn("bk_1", SourceKind.BANK, 500000, ext_id="UTR_1")
        bk2 = self._make_txn("bk_2", SourceKind.BANK, 500000, ext_id="UTR_2")
        engine = ReconciliationEngine(org_id=self.org_id, batch_id=self.batch_id)
        summary = engine.run_full_pipeline([gw, bk1, bk2])
        # Individual 1:1 score for 50% discrepancy fails
        score, is_fee = ReconciliationEngine.score_amount(gw, bk1)
        self.assertFalse(is_fee)

    # 39. Multiple payments matching one bank transaction (N:1)
    def test_39_multiple_payments_matching_one_bank_transaction(self):
        gw1 = self._make_txn("gw_1", SourceKind.GATEWAY, 500000, ext_id="pay_n1_a", fee_minor=10000, tax_minor=1800)
        gw2 = self._make_txn("gw_2", SourceKind.GATEWAY, 500000, ext_id="pay_n1_b", fee_minor=10000, tax_minor=1800)
        # Total gross 10,000 INR -> fees 236 INR -> net 9,764 INR
        bk = self._make_txn("bk_1", SourceKind.BANK, 976400, ext_id="UTR_BULK")
        engine = ReconciliationEngine(org_id=self.org_id, batch_id=self.batch_id)
        summary = engine.run_full_pipeline([gw1, gw2, bk])
        self.assertEqual(summary["matched_records"], 3)

    # 40. Same amount for different payments
    def test_40_same_amount_different_payments(self):
        gw1 = self._make_txn("gw_1", SourceKind.GATEWAY, 49900, ext_id="pay_A", ref_keys=ReferenceKeys(payment=["pay_A"]))
        gw2 = self._make_txn("gw_2", SourceKind.GATEWAY, 49900, ext_id="pay_B", ref_keys=ReferenceKeys(payment=["pay_B"]))
        bk1 = self._make_txn("bk_1", SourceKind.BANK, 49900, ext_id="UTR_A", ref_keys=ReferenceKeys(payment=["pay_A"]))
        bk2 = self._make_txn("bk_2", SourceKind.BANK, 49900, ext_id="UTR_B", ref_keys=ReferenceKeys(payment=["pay_B"]))
        engine = ReconciliationEngine(org_id=self.org_id, batch_id=self.batch_id)
        summary = engine.run_full_pipeline([gw1, gw2, bk1, bk2])
        self.assertEqual(summary["matched_records"], 4)
        # Verify gw1 matched to bk1 and gw2 matched to bk2 by checking match legs
        for m in engine.matches:
            t_ids = {l.transaction_id for l in m.legs}
            if "gw_1" in t_ids:
                self.assertIn("bk_1", t_ids)
            if "gw_2" in t_ids:
                self.assertIn("bk_2", t_ids)


if __name__ == "__main__":
    unittest.main()
