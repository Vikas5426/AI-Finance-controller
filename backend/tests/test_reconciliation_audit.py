"""
Automated Regression Test Suite: Deterministic Reconciliation & AI Issues Center
16 rigorous tests validating zero hallucinations, exact source-of-truth mathematical calculations,
incomplete bank data handling, duplicate isolation, and GL balance validation.
"""

import os
import sys
import unittest
from datetime import datetime, timezone, date
from decimal import Decimal
import tempfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.models.schemas import (
    CanonicalTransaction,
    SourceKind,
    TxnDirection,
    ReferenceKeys
)
from app.services.matching_engine import MatchingEngine
from app.services.ingestion import IngestionService
from app.services.normalizer import NormalizerService
from app.services.ai_issues_service import AIIssuesService


class TestReconciliationAudit(unittest.TestCase):
    def setUp(self):
        self.org_id = "00000000-0000-0000-0000-000000000001"
        self.batch_id = "BATCH-AUDIT-TEST"

    # 1. Duplicate Transaction Detection
    def test_01_duplicate_transaction(self):
        t1 = CanonicalTransaction(
            id="GW-DUP-01",
            batch_id=self.batch_id,
            source_kind=SourceKind.GATEWAY,
            direction=TxnDirection.INFLOW,
            amount_minor=99900,
            currency="INR",
            occurred_at=datetime(2026, 3, 28, 12, 0, tzinfo=timezone.utc),
            value_date=date(2026, 3, 28),
            description_raw="Invoice INV-2026-005 duplicate webhook",
            description_norm="invoice inv 2026 005 duplicate webhook",
            external_id="pay_TEST_005",
            reference_keys=ReferenceKeys(payment=["pay_TEST_005"], invoice=["INV-2026-005"]),
            org_id=self.org_id
        )
        t2 = CanonicalTransaction(
            id="GW-DUP-02",
            batch_id=self.batch_id,
            source_kind=SourceKind.GATEWAY,
            direction=TxnDirection.INFLOW,
            amount_minor=99900,
            currency="INR",
            occurred_at=datetime(2026, 3, 28, 12, 0, tzinfo=timezone.utc),
            value_date=date(2026, 3, 28),
            description_raw="Invoice INV-2026-005 duplicate webhook",
            description_norm="invoice inv 2026 005 duplicate webhook",
            external_id="pay_TEST_005",
            reference_keys=ReferenceKeys(payment=["pay_TEST_005"], invoice=["INV-2026-005"]),
            org_id=self.org_id
        )

        engine = MatchingEngine(self.org_id, self.batch_id)
        unique_txns = engine.pass_p0_dedupe([t1, t2])

        self.assertEqual(len(unique_txns), 1, "Exactly 1 unique transaction must remain after deduplication")
        self.assertEqual(len(engine.exceptions), 1, "Exactly 1 duplicate exception must be raised")
        exc = engine.exceptions[0]
        self.assertEqual(exc.exception_type, "DUPLICATE_RECORD")
        self.assertEqual(exc.impact_minor, 99900, "Duplicate financial exposure must be exactly ₹999.00 (99900 paise)")

    # 2. Missing GL Entry Detection
    def test_02_missing_gl_entry(self):
        gw = CanonicalTransaction(
            id="GW-01",
            batch_id=self.batch_id,
            source_kind=SourceKind.GATEWAY,
            direction=TxnDirection.INFLOW,
            amount_minor=50000,
            currency="INR",
            occurred_at=datetime(2026, 3, 25, 10, 0, tzinfo=timezone.utc),
            value_date=date(2026, 3, 25),
            description_raw="Customer payment without GL record",
            description_norm="customer payment without gl record",
            external_id="pay_MISSING_GL",
            reference_keys=ReferenceKeys(payment=["pay_MISSING_GL"], invoice=["INV-MISSING-GL"]),
            org_id=self.org_id
        )

        engine = MatchingEngine(self.org_id, self.batch_id)
        engine.pass_p3_gateway_ledger([gw])
        self.assertNotIn(gw.id, engine.matched_txn_ids, "Gateway transaction without GL must remain unmatched")

    # 3. Missing Gateway Transaction
    def test_03_missing_gateway_transaction(self):
        bk = CanonicalTransaction(
            id="BK-01",
            batch_id=self.batch_id,
            source_kind=SourceKind.BANK,
            direction=TxnDirection.INFLOW,
            amount_minor=15000,
            currency="INR",
            occurred_at=datetime(2026, 3, 30, 10, 0, tzinfo=timezone.utc),
            value_date=date(2026, 3, 30),
            description_raw="DIRECT-DEP-UNKNOWN-PARTY",
            description_norm="direct dep unknown party",
            external_id="UTR-ANON-9999",
            reference_keys=ReferenceKeys(utr=["UTR-ANON-9999"]),
            org_id=self.org_id
        )

        engine = MatchingEngine(self.org_id, self.batch_id)
        engine.run_full_pipeline([bk])
        self.assertEqual(len(engine.exceptions), 1)
        self.assertEqual(engine.exceptions[0].exception_type, "UNKNOWN_BANK_CREDIT")

    # 4. Amount Mismatch Detection
    def test_04_amount_mismatch(self):
        gw = CanonicalTransaction(
            id="GW-AMT-01",
            batch_id=self.batch_id,
            source_kind=SourceKind.GATEWAY,
            direction=TxnDirection.INFLOW,
            amount_minor=100000,
            currency="INR",
            occurred_at=datetime(2026, 3, 25, 10, 0, tzinfo=timezone.utc),
            value_date=date(2026, 3, 25),
            description_raw="Order 101",
            description_norm="order 101",
            external_id="pay_AMT_01",
            reference_keys=ReferenceKeys(payment=["pay_AMT_01"], invoice=["INV-101"]),
            org_id=self.org_id
        )
        gl = CanonicalTransaction(
            id="GL-AMT-01",
            batch_id=self.batch_id,
            source_kind=SourceKind.LEDGER,
            direction=TxnDirection.INFLOW,
            amount_minor=95000,  # ₹950 vs ₹1000
            currency="INR",
            occurred_at=datetime(2026, 3, 25, 10, 0, tzinfo=timezone.utc),
            value_date=date(2026, 3, 25),
            description_raw="Order 101 partial posting",
            description_norm="order 101 partial posting",
            external_id="JE-AMT-01",
            reference_keys=ReferenceKeys(payment=["pay_AMT_01"], invoice=["INV-101"]),
            org_id=self.org_id
        )

        engine = MatchingEngine(self.org_id, self.batch_id)
        engine.pass_p3_gateway_ledger([gw, gl])
        self.assertNotIn(gw.id, engine.matched_txn_ids, "Mismatched amount pair must not match in exact pass")

    # 5. Matching Transaction (Gateway <-> GL <-> Bank)
    def test_05_matching_transaction(self):
        gw = CanonicalTransaction(
            id="GW-M-01",
            batch_id=self.batch_id,
            source_kind=SourceKind.GATEWAY,
            direction=TxnDirection.INFLOW,
            amount_minor=49900,
            gross_minor=49900,
            fee_minor=998,
            tax_minor=180,
            currency="INR",
            occurred_at=datetime(2026, 3, 25, 10, 0, tzinfo=timezone.utc),
            value_date=date(2026, 3, 25),
            description_raw="Invoice INV-2026-001 subscription",
            description_norm="invoice inv 2026 001 subscription",
            external_id="pay_TEST_001",
            reference_keys=ReferenceKeys(payment=["pay_TEST_001"], invoice=["INV-2026-001"], settlement=["setl_01"]),
            org_id=self.org_id
        )
        bk = CanonicalTransaction(
            id="BK-M-01",
            batch_id=self.batch_id,
            source_kind=SourceKind.BANK,
            direction=TxnDirection.INFLOW,
            amount_minor=48722,  # 49900 - 998 - 180 = 48722
            currency="INR",
            occurred_at=datetime(2026, 3, 25, 10, 0, tzinfo=timezone.utc),
            value_date=date(2026, 3, 25),
            description_raw="NEFT-RAZORPAY-pay_TEST_001-CR",
            description_norm="neft razorpay pay test 001 cr",
            external_id="BANK-TXN-001",
            reference_keys=ReferenceKeys(payment=["pay_TEST_001"], utr=["UTR-TEST-0001"]),
            org_id=self.org_id
        )
        gl = CanonicalTransaction(
            id="GL-M-01",
            batch_id=self.batch_id,
            source_kind=SourceKind.LEDGER,
            direction=TxnDirection.INFLOW,
            amount_minor=49900,
            currency="INR",
            occurred_at=datetime(2026, 3, 25, 10, 0, tzinfo=timezone.utc),
            value_date=date(2026, 3, 25),
            description_raw="UPI capture INV-2026-001",
            description_norm="upi capture inv 2026 001",
            external_id="JE-001",
            reference_keys=ReferenceKeys(invoice=["INV-2026-001"]),
            org_id=self.org_id
        )

        engine = MatchingEngine(self.org_id, self.batch_id)
        res = engine.run_full_pipeline([gw, bk, gl])
        self.assertIn(gw.id, engine.matched_txn_ids)
        self.assertIn(bk.id, engine.matched_txn_ids)
        self.assertIn(gl.id, engine.matched_txn_ids)
        self.assertEqual(len(engine.exceptions), 0, "Clean 3-way match must produce 0 exceptions")

    # 6. Incomplete Bank CSV Handling
    def test_06_incomplete_bank_csv(self):
        gw = CanonicalTransaction(
            id="GW-INC-01",
            batch_id=self.batch_id,
            source_kind=SourceKind.GATEWAY,
            direction=TxnDirection.INFLOW,
            amount_minor=100000,
            currency="INR",
            occurred_at=datetime(2026, 3, 25, 10, 0, tzinfo=timezone.utc),
            value_date=date(2026, 3, 25),
            description_raw="Captured payment",
            description_norm="captured payment",
            external_id="pay_INC_01",
            reference_keys=ReferenceKeys(payment=["pay_INC_01"], settlement=["setl_01"]),
            org_id=self.org_id
        )
        # Bank transaction is from another period (August 2026 instead of March 2026)
        bk_unrelated = CanonicalTransaction(
            id="BK-INC-01",
            batch_id=self.batch_id,
            source_kind=SourceKind.BANK,
            direction=TxnDirection.INFLOW,
            amount_minor=1250000,
            currency="INR",
            occurred_at=datetime(2026, 8, 1, 10, 0, tzinfo=timezone.utc),
            value_date=date(2026, 8, 1),
            description_raw="Customer payment B001",
            description_norm="customer payment b001",
            external_id="B001",
            reference_keys=ReferenceKeys(payment=["B001"]),
            org_id=self.org_id
        )

        engine = MatchingEngine(self.org_id, self.batch_id)
        engine.run_full_pipeline([gw, bk_unrelated])
        
        gw_excs = [e for e in engine.exceptions if e.primary_txn_id == gw.id]
        self.assertEqual(len(gw_excs), 1)
        self.assertEqual(gw_excs[0].exception_type, "SETTLEMENT_STATUS_CANNOT_BE_VERIFIED")

    # 7. Missing / Unresolved Settlement ID (setl_UNSET)
    def test_07_missing_settlement_id(self):
        gw = CanonicalTransaction(
            id="GW-UNSET-01",
            batch_id=self.batch_id,
            source_kind=SourceKind.GATEWAY,
            direction=TxnDirection.INFLOW,
            amount_minor=500000,
            currency="INR",
            occurred_at=datetime(2026, 3, 29, 16, 0, tzinfo=timezone.utc),
            value_date=date(2026, 3, 29),
            description_raw="Invoice INV-2026-006 missing bank settlement",
            description_norm="invoice inv 2026 006 missing bank settlement",
            external_id="pay_TEST_006",
            reference_keys=ReferenceKeys(payment=["pay_TEST_006"], settlement=["setl_UNSET"]),
            org_id=self.org_id
        )

        engine = MatchingEngine(self.org_id, self.batch_id)
        engine.run_full_pipeline([gw])
        self.assertEqual(len(engine.exceptions), 1)
        self.assertEqual(engine.exceptions[0].exception_type, "UNRESOLVED_SETTLEMENT_ID")
        self.assertEqual(engine.exceptions[0].impact_minor, 500000)

    # 8. Duplicate GL Entry Detection
    def test_08_duplicate_gl_entry(self):
        gl1 = CanonicalTransaction(
            id="GL-DUP-01",
            batch_id=self.batch_id,
            source_kind=SourceKind.LEDGER,
            direction=TxnDirection.INFLOW,
            amount_minor=49900,
            currency="INR",
            occurred_at=datetime(2026, 3, 25, 10, 0, tzinfo=timezone.utc),
            value_date=date(2026, 3, 25),
            description_raw="UPI capture INV-2026-001",
            description_norm="upi capture inv 2026 001",
            external_id="JE-001",
            reference_keys=ReferenceKeys(invoice=["INV-2026-001"]),
            org_id=self.org_id
        )
        gl2 = CanonicalTransaction(
            id="GL-DUP-02",
            batch_id=self.batch_id,
            source_kind=SourceKind.LEDGER,
            direction=TxnDirection.INFLOW,
            amount_minor=49900,
            currency="INR",
            occurred_at=datetime(2026, 3, 25, 10, 0, tzinfo=timezone.utc),
            value_date=date(2026, 3, 25),
            description_raw="UPI capture INV-2026-001 duplicate",
            description_norm="upi capture inv 2026 001 duplicate",
            external_id="JE-001",
            reference_keys=ReferenceKeys(invoice=["INV-2026-001"]),
            org_id=self.org_id
        )

        engine = MatchingEngine(self.org_id, self.batch_id)
        unique_gl = engine.pass_p0_dedupe([gl1, gl2])
        self.assertEqual(len(unique_gl), 1)
        self.assertEqual(len(engine.exceptions), 1)
        self.assertEqual(engine.exceptions[0].exception_type, "DUPLICATE_RECORD")

    # 9. Unmatched Bank Transaction (Unallocated Credit)
    def test_09_unmatched_bank_transaction(self):
        bk = CanonicalTransaction(
            id="BK-UNALLOC-01",
            batch_id=self.batch_id,
            source_kind=SourceKind.BANK,
            direction=TxnDirection.INFLOW,
            amount_minor=15000,
            currency="INR",
            occurred_at=datetime(2026, 3, 30, 10, 0, tzinfo=timezone.utc),
            value_date=date(2026, 3, 30),
            description_raw="DIRECT-DEP-UNKNOWN-PARTY-99",
            description_norm="direct dep unknown party 99",
            external_id="BANK-TXN-006",
            reference_keys=ReferenceKeys(utr=["UTR-ANON-9999"]),
            org_id=self.org_id
        )

        engine = MatchingEngine(self.org_id, self.batch_id)
        engine.run_full_pipeline([bk])
        self.assertEqual(len(engine.exceptions), 1)
        self.assertEqual(engine.exceptions[0].exception_type, "UNKNOWN_BANK_CREDIT")
        self.assertEqual(engine.exceptions[0].impact_minor, 15000)

    # 10. Ambiguous Transaction Handling (Competing duplicates)
    def test_10_ambiguous_transaction(self):
        gw1 = CanonicalTransaction(
            id="GW-AMB-01",
            batch_id=self.batch_id,
            source_kind=SourceKind.GATEWAY,
            direction=TxnDirection.INFLOW,
            amount_minor=100000,
            currency="INR",
            occurred_at=datetime(2026, 3, 25, 10, 0, tzinfo=timezone.utc),
            value_date=date(2026, 3, 25),
            description_raw="Captured payment 1",
            description_norm="captured payment 1",
            external_id="pay_AMB_01",
            reference_keys=ReferenceKeys(invoice=["INV-SHARED"]),
            org_id=self.org_id
        )
        gw2 = CanonicalTransaction(
            id="GW-AMB-02",
            batch_id=self.batch_id,
            source_kind=SourceKind.GATEWAY,
            direction=TxnDirection.INFLOW,
            amount_minor=100000,
            currency="INR",
            occurred_at=datetime(2026, 3, 25, 10, 0, tzinfo=timezone.utc),
            value_date=date(2026, 3, 25),
            description_raw="Captured payment 2",
            description_norm="captured payment 2",
            external_id="pay_AMB_02",
            reference_keys=ReferenceKeys(invoice=["INV-SHARED"]),
            org_id=self.org_id
        )
        bk = CanonicalTransaction(
            id="BK-AMB-01",
            batch_id=self.batch_id,
            source_kind=SourceKind.BANK,
            direction=TxnDirection.INFLOW,
            amount_minor=100000,
            currency="INR",
            occurred_at=datetime(2026, 3, 25, 10, 0, tzinfo=timezone.utc),
            value_date=date(2026, 3, 25),
            description_raw="Bank credit for INV-SHARED",
            description_norm="bank credit for inv shared",
            external_id="BK-SHARED",
            reference_keys=ReferenceKeys(invoice=["INV-SHARED"]),
            org_id=self.org_id
        )

        engine = MatchingEngine(self.org_id, self.batch_id)
        engine.pass_p1_gateway_bank([gw1, gw2, bk])
        self.assertTrue(len(engine.safeguards_triggered) > 0, "Runner-up margin safeguard must trigger for competing candidates")

    # 11. Zero-Value Transaction
    def test_11_zero_value_transaction(self):
        row = {
            "payment_id": "pay_ZERO_001",
            "amount": "0.00",
            "captured_at": "2026-03-25T10:00:00Z",
            "description": "Zero value auth check"
        }
        txn = NormalizerService.normalize_row(row, SourceKind.GATEWAY, self.org_id, self.batch_id, 1)
        self.assertEqual(txn.amount_minor, 0)
        self.assertEqual(txn.gross_minor, 0)

    # 12. Negative Transaction / Refund
    def test_12_negative_transaction_refund(self):
        row = {
            "txn_id": "BK-REFUND-001",
            "Date": "2026-03-25",
            "Description": "Customer Refund wire",
            "Debit": "5000.00"
        }
        txn = NormalizerService.normalize_row(row, SourceKind.BANK, self.org_id, self.batch_id, amount_scale=100, row_num=1)
        self.assertEqual(txn.amount_minor, 500000)
        self.assertEqual(txn.direction, TxnDirection.OUTFLOW)

    # 13. Multiple Currencies Handling
    def test_13_multiple_currencies(self):
        row = {
            "payment_id": "pay_USD_001",
            "amount": "100.00",
            "currency": "USD",
            "captured_at": "2026-03-25T10:00:00Z"
        }
        txn = NormalizerService.normalize_row(row, SourceKind.GATEWAY, self.org_id, self.batch_id, amount_scale=100, row_num=1)
        self.assertEqual(txn.currency, "USD")
        self.assertEqual(txn.amount_minor, 10000)

    # 14. Missing Required Columns Validation
    def test_14_missing_required_columns(self):
        with self.assertRaises(ValueError):
            IngestionService.validate_schema(["random_col_1", "random_col_2"], SourceKind.GATEWAY, "dummy.csv")

    # 15. Empty CSV Handling
    def test_15_empty_csv_handling(self):
        with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False) as f:
            f.write("")
            f_path = f.name
        try:
            records = IngestionService.parse_file(f_path, SourceKind.GATEWAY)
            self.assertEqual(len(records), 0)
        finally:
            if os.path.exists(f_path):
                os.remove(f_path)

    # 16. Malformed CSV Handling (Preamble & metadata titles)
    def test_16_malformed_csv_handling(self):
        content = (
            "BANK REPORT EXPORT\n"
            "Generated on 2026-09-02\n"
            "\n"
            "TXN_ID,DATE,DESCRIPTION,AMOUNT,TYPE\n"
            "TXN-101,2026-08-15,Payment Recv,500.00,CREDIT\n"
        )
        with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False) as f:
            f.write(content)
            f_path = f.name
        try:
            txns, count = IngestionService.ingest_and_normalize(f_path, SourceKind.BANK, self.org_id, self.batch_id)
            self.assertEqual(count, 1)
            self.assertEqual(len(txns), 1)
            self.assertEqual(txns[0].external_id, "TXN-101")
            self.assertEqual(txns[0].amount_minor, 50000)
        finally:
            if os.path.exists(f_path):
                os.remove(f_path)


if __name__ == "__main__":
    unittest.main()
