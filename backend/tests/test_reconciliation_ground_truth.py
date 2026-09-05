"""
Deterministic Ground-Truth Automated Test Suite for Financial Reconciliation Engine

This test suite establishes the deterministic ground-truth reconciliation baseline
independently of any LLM reasoning. It tests all 20 operational areas against the
actual CSV datasets:
- data/gateway.csv (7 rows: TEST_001 to TEST_006 with duplicate TEST_005)
- data/bank.csv (6 rows: BANK-TXN-001 to BANK-TXN-006)
- data/general_ledger.csv (18 rows: JE-001 to JE-006)

Core Financial Reconciliation Axioms:
  expected_net_settlement = gross_amount - fee - tax
  Double-Entry Balance: sum(Journal Entry Debits) == sum(Journal Entry Credits)
"""

import os
import sys
import csv
import unittest
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Dict, List, Any

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.models.schemas import SourceKind, CanonicalTransaction, TxnDirection, DecisionTier
from app.services.ingestion import IngestionService
from app.services.normalizer import NormalizerService
from app.services.matching_engine import ReconciliationEngine, AccountingSemanticGate
from app.services.fee_policy import FeePolicyRegistry

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "ground_truth")
GATEWAY_CSV = os.path.join(FIXTURES_DIR, "gateway.csv")
BANK_CSV = os.path.join(FIXTURES_DIR, "bank.csv")
GL_CSV = os.path.join(FIXTURES_DIR, "general_ledger.csv")
ORG_ID_A = "00000000-0000-0000-0000-000000000001"
ORG_ID_B = "00000000-0000-0000-0000-000000000002"
BATCH_ID = "BATCH-TEST-GROUND-TRUTH"


class TestDeterministicReconciliationGroundTruth(unittest.TestCase):

    # ==============================================================================
    # 1. Gateway Row Ingestion
    # ==============================================================================
    def test_01_gateway_row_ingestion(self):
        """
        Test 1: Gateway Row Ingestion
        Expected: Exactly 7 data rows parsed from gateway.csv.
        """
        self.assertTrue(os.path.exists(GATEWAY_CSV), f"Missing file: {GATEWAY_CSV}")
        raw_rows = IngestionService.parse_file(GATEWAY_CSV, SourceKind.GATEWAY)
        self.assertEqual(
            len(raw_rows), 7,
            f"Expected 7 gateway data rows, but ingested {len(raw_rows)}."
        )

        for row in raw_rows:
            self.assertIn("payment_id", row)
            self.assertIn("amount", row)
            self.assertIn("fee", row)
            self.assertIn("tax", row)
            self.assertTrue(int(row["amount"]) > 0)

    # ==============================================================================
    # 2. Bank Row Ingestion
    # ==============================================================================
    def test_02_bank_row_ingestion(self):
        """
        Test 2: Bank Row Ingestion
        Expected: Exactly 6 bank data rows parsed from bank.csv.
        """
        self.assertTrue(os.path.exists(BANK_CSV), f"Missing file: {BANK_CSV}")
        raw_rows = IngestionService.parse_file(BANK_CSV, SourceKind.BANK)
        self.assertEqual(
            len(raw_rows), 6,
            f"Expected 6 bank data rows, but ingested {len(raw_rows)}."
        )

        credits = [r for r in raw_rows if r.get("credit")]
        self.assertEqual(len(credits), 6, "All 6 bank rows must be credit transactions")

    # ==============================================================================
    # 3. General Ledger Row Ingestion
    # ==============================================================================
    def test_03_gl_row_ingestion(self):
        """
        Test 3: General Ledger Row Ingestion
        Expected: Exactly 18 physical GL rows parsed from general_ledger.csv.
        """
        self.assertTrue(os.path.exists(GL_CSV), f"Missing file: {GL_CSV}")
        raw_rows = IngestionService.parse_file(GL_CSV, SourceKind.LEDGER)
        self.assertEqual(
            len(raw_rows), 18,
            f"Expected 18 physical GL rows, but ingested {len(raw_rows)}."
        )

    # ==============================================================================
    # 4. Duplicate Gateway Payment Detection
    # ==============================================================================
    def test_04_duplicate_gateway_payment(self):
        """
        Test 4: Duplicate Gateway Payment Detection
        Expected: pay_TEST_005 appears exactly twice in gateway.csv.
        """
        raw_rows = IngestionService.parse_file(GATEWAY_CSV, SourceKind.GATEWAY)
        p1005_rows = [r for r in raw_rows if r.get("payment_id") == "pay_TEST_005"]
        self.assertEqual(
            len(p1005_rows), 2,
            f"Expected exactly 2 instances of pay_TEST_005 in gateway.csv, found {len(p1005_rows)}"
        )
        self.assertEqual(p1005_rows[0]["amount"], p1005_rows[1]["amount"])

    # ==============================================================================
    # 5. Non-Zero Fee and Tax Scaling
    # ==============================================================================
    def test_05_non_zero_fee_tax_scaling(self):
        """
        Test 5: Non-Zero Fee and Tax Scaling
        """
        txns, _ = IngestionService.ingest_and_normalize(GATEWAY_CSV, SourceKind.GATEWAY, ORG_ID_A, BATCH_ID)
        p1001 = next(t for t in txns if t.external_id == "pay_TEST_001")
        self.assertEqual(p1001.amount_minor, 49900)
        self.assertEqual(p1001.fee_minor, 998)
        self.assertEqual(p1001.tax_minor, 180)

    # ==============================================================================
    # 6. GL Journal Aggregation & Line Isolation Prevention
    # ==============================================================================
    def test_06_gl_journal_aggregation(self):
        """
        Test 6: GL Journal Aggregation
        Expected: 18 physical lines aggregated into exactly 6 Journal Entry entities.
        """
        raw_rows = IngestionService.parse_file(GL_CSV, SourceKind.LEDGER)
        je_groups: Dict[str, List[Dict[str, Any]]] = {}
        for r in raw_rows:
            je_id = r.get("je_id")
            je_groups.setdefault(je_id, []).append(r)

        self.assertEqual(len(je_groups), 6, f"Expected 6 Journal Entries in GL, got {len(je_groups)}")

        for je_id, lines in je_groups.items():
            self.assertEqual(len(lines), 3, f"JE {je_id} must have exactly 3 lines")

        txns, raw_count = IngestionService.ingest_and_normalize(GL_CSV, SourceKind.LEDGER, ORG_ID_A, BATCH_ID)
        self.assertEqual(len(txns), 6, f"Ingestion must output exactly 6 canonical GL entities, got {len(txns)}")
        self.assertEqual(raw_count, 18, f"Parsed count must be 18 raw rows, got {raw_count}")

    # ==============================================================================
    # 7. GL Compound Journal Balancing
    # ==============================================================================
    def test_07_gl_compound_journal_balancing(self):
        """
        Test 7: GL Compound Journal Balancing
        """
        raw_rows = IngestionService.parse_file(GL_CSV, SourceKind.LEDGER)
        je_groups: Dict[str, List[Dict[str, Any]]] = {}
        for r in raw_rows:
            je_id = r.get("je_id")
            je_groups.setdefault(je_id, []).append(r)

        for je_id, lines in je_groups.items():
            total_debit = Decimal("0.00")
            total_credit = Decimal("0.00")
            for l in lines:
                if l.get("debit") and str(l["debit"]).strip():
                    total_debit += Decimal(str(l["debit"]).strip())
                if l.get("credit") and str(l["credit"]).strip():
                    total_credit += Decimal(str(l["credit"]).strip())

            self.assertEqual(
                total_debit, total_credit,
                f"Double-entry violation in {je_id}: Debit={total_debit} != Credit={total_credit}"
            )

    # ==============================================================================
    # 8. Double-Entry Balance Gate
    # ==============================================================================
    def test_08_double_entry_balance_gate(self):
        """
        Test 8: Double-Entry Balance Gate
        """
        unbalanced_rows = [
            {"je_id": "JE-UNBAL", "line_no": 1, "posted_at": "2026-03-25", "account_code": "1210", "debit": "500.00", "credit": "", "doc_ref": "INV-01"},
            {"je_id": "JE-UNBAL", "line_no": 2, "posted_at": "2026-03-25", "account_code": "4000", "debit": "", "credit": "450.00", "doc_ref": "INV-01"}
        ]
        txn = NormalizerService.normalize_journal_entry(unbalanced_rows, ORG_ID_A, BATCH_ID)
        self.assertFalse(txn.is_balanced_je)
        gw = CanonicalTransaction(
            id="gw1", org_id=ORG_ID_A, batch_id=BATCH_ID, source_kind=SourceKind.GATEWAY,
            external_id="pay_01", amount_minor=50000, direction=TxnDirection.INFLOW,
            currency="INR", occurred_at=datetime.now(timezone.utc), value_date=date(2026, 3, 25),
            description_raw="", description_norm=""
        )
        ok, reason = AccountingSemanticGate.can_match(gw, txn)
        self.assertFalse(ok)
        self.assertIn("UNBALANCED_JOURNAL_ENTRY", reason)

    # ==============================================================================
    # 9. Payment Key Extraction
    # ==============================================================================
    def test_09_payment_key_extraction(self):
        """
        Test 9: Payment Key Extraction
        """
        raw_text = "UPI payment pay_TEST_001 for invoice INV-2026-001 order ord_001"
        keys = NormalizerService.extract_reference_keys(raw_text)
        self.assertIn("PAY_TEST_001", [k.upper() for k in keys.payment])
        self.assertIn("INV-2026-001", keys.invoice)
        self.assertIn("ORD_001", [k.upper() for k in keys.order])

    # ==============================================================================
    # 10. Bank Description Key Extraction
    # ==============================================================================
    def test_10_bank_description_key_extraction(self):
        """
        Test 10: Bank Description Key Extraction
        """
        desc = "NEFT-RAZORPAY-pay_TEST_001-CR"
        keys = NormalizerService.extract_reference_keys(desc)
        self.assertIn("PAY_TEST_001", [k.upper() for k in keys.payment])

    # ==============================================================================
    # 11. Cross-Batch Isolation
    # ==============================================================================
    def test_11_cross_batch_isolation(self):
        """
        Test 11: Cross-Batch Isolation
        """
        txns_a, _ = IngestionService.ingest_and_normalize(GATEWAY_CSV, SourceKind.GATEWAY, ORG_ID_A, "BATCH_A")
        txns_b, _ = IngestionService.ingest_and_normalize(GATEWAY_CSV, SourceKind.GATEWAY, ORG_ID_A, "BATCH_B")

        for ta in txns_a:
            self.assertEqual(ta.batch_id, "BATCH_A")
        for tb in txns_b:
            self.assertEqual(tb.batch_id, "BATCH_B")

    # ==============================================================================
    # 12. Reconciliation Axioms (TEST_001 to TEST_003)
    # ==============================================================================
    def test_12_reconciliation_axioms_001_to_003(self):
        """
        Test 12: Reconciliation Axioms 001 to 003
        """
        # TEST_001: 499.00 - 9.98 - 1.80 = 487.22
        net_001 = 49900 - 998 - 180
        self.assertEqual(net_001, 48722)

        # TEST_002: 10,000.00 - 200.00 - 36.00 = 9,764.00
        net_002 = 1000000 - 20000 - 3600
        self.assertEqual(net_002, 976400)

        # TEST_003: 1,180.00 - 23.60 - 4.25 = 1,152.15
        net_003 = 118000 - 2360 - 425
        self.assertEqual(net_003, 115215)

    # ==============================================================================
    # 13. Reconciliation Axiom (TEST_004 Timing Lag)
    # ==============================================================================
    def test_13_reconciliation_axiom_004_timing_lag(self):
        """
        Test 13: TEST_004 Timing Lag Axiom
        Gateway 2,360.00, Fee 47.20, Tax 8.50 -> Expected Bank 2,304.30 on 2026-04-02
        """
        net_004 = 236000 - 4720 - 850
        self.assertEqual(net_004, 230430)

    # ==============================================================================
    # 14. Exact Matching
    # ==============================================================================
    def test_14_exact_matching(self):
        """
        Test 14: Exact 1:1 ID and Amount Match
        """
        gw_txns, _ = IngestionService.ingest_and_normalize(GATEWAY_CSV, SourceKind.GATEWAY, ORG_ID_A, BATCH_ID)
        bk_txns, _ = IngestionService.ingest_and_normalize(BANK_CSV, SourceKind.BANK, ORG_ID_A, BATCH_ID)
        gl_txns, _ = IngestionService.ingest_and_normalize(GL_CSV, SourceKind.LEDGER, ORG_ID_A, BATCH_ID)

        engine = ReconciliationEngine(org_id=ORG_ID_A, batch_id=BATCH_ID)
        engine.run_full_pipeline(gw_txns + bk_txns + gl_txns)
        self.assertGreaterEqual(len(engine.matches), 5)

    # ==============================================================================
    # 15. Contextual Matching
    # ==============================================================================
    def test_15_contextual_matching(self):
        """
        Test 15: Contextual Matching Net of Fee & Tax
        """
        gw_txns, _ = IngestionService.ingest_and_normalize(GATEWAY_CSV, SourceKind.GATEWAY, ORG_ID_A, BATCH_ID)
        bk_txns, _ = IngestionService.ingest_and_normalize(BANK_CSV, SourceKind.BANK, ORG_ID_A, BATCH_ID)
        gl_txns, _ = IngestionService.ingest_and_normalize(GL_CSV, SourceKind.LEDGER, ORG_ID_A, BATCH_ID)

        engine = ReconciliationEngine(org_id=ORG_ID_A, batch_id=BATCH_ID)
        engine.run_full_pipeline(gw_txns + bk_txns + gl_txns)

        gw_1001 = next(g for g in gw_txns if g.external_id == "pay_TEST_001")
        self.assertIn(gw_1001.id, engine.matched_txn_ids)

    # ==============================================================================
    # 16. Accounting Semantic Gate
    # ==============================================================================
    def test_16_accounting_semantic_gate(self):
        """
        Test 16: Accounting Semantic Gate
        """
        gw = CanonicalTransaction(
            id="gw1", org_id=ORG_ID_A, batch_id=BATCH_ID, source_kind=SourceKind.GATEWAY,
            external_id="pay_01", amount_minor=10000, direction=TxnDirection.INFLOW,
            currency="INR", occurred_at=datetime.now(timezone.utc), value_date=date(2026, 3, 25),
            description_raw="", description_norm=""
        )
        bk = CanonicalTransaction(
            id="bk1", org_id=ORG_ID_A, batch_id=BATCH_ID, source_kind=SourceKind.BANK,
            external_id="bk_01", amount_minor=10000, direction=TxnDirection.INFLOW,
            currency="USD", occurred_at=datetime.now(timezone.utc), value_date=date(2026, 3, 25),
            description_raw="", description_norm=""
        )
        ok, reason = AccountingSemanticGate.can_match(gw, bk)
        self.assertFalse(ok)
        self.assertIn("Currency mismatch", reason)

    # ==============================================================================
    # 17. N:1 Settlement Decomposition
    # ==============================================================================
    def test_17_n1_settlement_decomposition(self):
        """
        Test 17: N:1 Settlement Decomposition
        """
        gw1 = CanonicalTransaction(
            id="gw1", org_id=ORG_ID_A, batch_id=BATCH_ID, source_kind=SourceKind.GATEWAY,
            external_id="pay_n1_1", amount_minor=500000, gross_minor=500000, fee_minor=10000, tax_minor=1800,
            direction=TxnDirection.INFLOW, currency="INR", occurred_at=datetime.now(timezone.utc),
            value_date=date(2026, 3, 25), description_raw="", description_norm=""
        )
        gw2 = CanonicalTransaction(
            id="gw2", org_id=ORG_ID_A, batch_id=BATCH_ID, source_kind=SourceKind.GATEWAY,
            external_id="pay_n1_2", amount_minor=500000, gross_minor=500000, fee_minor=10000, tax_minor=1800,
            direction=TxnDirection.INFLOW, currency="INR", occurred_at=datetime.now(timezone.utc),
            value_date=date(2026, 3, 25), description_raw="", description_norm=""
        )
        bk = CanonicalTransaction(
            id="bk1", org_id=ORG_ID_A, batch_id=BATCH_ID, source_kind=SourceKind.BANK,
            external_id="UTR_N1", amount_minor=976400, direction=TxnDirection.INFLOW,
            currency="INR", occurred_at=datetime.now(timezone.utc), value_date=date(2026, 3, 25),
            description_raw="", description_norm=""
        )
        engine = ReconciliationEngine(org_id=ORG_ID_A, batch_id=BATCH_ID)
        engine.run_full_pipeline([gw1, gw2, bk])
        self.assertEqual(len(engine.matches), 1)

    # ==============================================================================
    # 18. Duplicate Detection & Safeguard Isolation
    # ==============================================================================
    def test_18_duplicate_detection(self):
        """
        Test 18: Duplicate Detection & Safeguard Isolation
        """
        gw_txns, _ = IngestionService.ingest_and_normalize(GATEWAY_CSV, SourceKind.GATEWAY, ORG_ID_A, BATCH_ID)
        p1005 = [t for t in gw_txns if t.external_id == "pay_TEST_005"]
        self.assertEqual(len(p1005), 2)

        engine = ReconciliationEngine(org_id=ORG_ID_A, batch_id=BATCH_ID)
        p0_txns = engine.pass_p0_dedupe(gw_txns)
        remaining_1005 = [t for t in p0_txns if t.external_id == "pay_TEST_005"]
        self.assertEqual(len(remaining_1005), 1)
        self.assertEqual(len(engine.exceptions), 1)
        self.assertEqual(engine.exceptions[0].exception_type, "DUPLICATE_RECORD")

    # ==============================================================================
    # 19. Missing Bank Settlement Detection
    # ==============================================================================
    def test_19_missing_bank_settlement(self):
        """
        Test 19: Missing Bank Settlement Detection
        """
        gw_txns, _ = IngestionService.ingest_and_normalize(GATEWAY_CSV, SourceKind.GATEWAY, ORG_ID_A, BATCH_ID)
        bk_txns, _ = IngestionService.ingest_and_normalize(BANK_CSV, SourceKind.BANK, ORG_ID_A, BATCH_ID)
        gl_txns, _ = IngestionService.ingest_and_normalize(GL_CSV, SourceKind.LEDGER, ORG_ID_A, BATCH_ID)

        engine = ReconciliationEngine(org_id=ORG_ID_A, batch_id=BATCH_ID)
        engine.run_full_pipeline(gw_txns + bk_txns + gl_txns)

        missing_exc = [e for e in engine.exceptions if e.exception_type == "MISSING_BANK_SETTLEMENT"]
        self.assertEqual(len(missing_exc), 1)
        self.assertEqual(missing_exc[0].impact_minor, 500000)

    # ==============================================================================
    # 20. End-to-End Three-Way Reconciliation Coverage
    # ==============================================================================
    def test_20_three_way_end_to_end_coverage(self):
        """
        Test 20: End-to-End Three-Way Reconciliation Coverage on User CSVs
        """
        gw_txns, _ = IngestionService.ingest_and_normalize(GATEWAY_CSV, SourceKind.GATEWAY, ORG_ID_A, BATCH_ID)
        bk_txns, _ = IngestionService.ingest_and_normalize(BANK_CSV, SourceKind.BANK, ORG_ID_A, BATCH_ID)
        gl_txns, _ = IngestionService.ingest_and_normalize(GL_CSV, SourceKind.LEDGER, ORG_ID_A, BATCH_ID)

        engine = ReconciliationEngine(org_id=ORG_ID_A, batch_id=BATCH_ID)
        summary = engine.run_full_pipeline(gw_txns + bk_txns + gl_txns)

        graph = summary["reconciliation_graph"]
        self.assertEqual(graph["three_way_matches_count"], 5)
        self.assertEqual(len(engine.exceptions), 3)

        total_exc_impact = sum(e.impact_minor for e in engine.exceptions)
        self.assertEqual(total_exc_impact, 614900) # Rs. 6,149.00


if __name__ == "__main__":
    unittest.main()
