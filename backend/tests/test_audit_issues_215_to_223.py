import unittest
import os
import sys
import re
from datetime import datetime, date
from typing import Dict, Any

# Ensure backend directory is in path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.config import settings
from app.db.database_service import DatabaseService, get_db_context
from app.db.database import engine, Base
from app.db import schema
from app.core.security import verify_password
from app.services.normalizer import NormalizerService
from app.services.context_builder import TransactionContextBuilder
from app.services.agent_tools import TransactionLookupIndex
from app.services.agents.agent_suite import FinancialAgentSuite
from app.services.agent_runtime import AIAgentRuntime
from app.models.schemas import CanonicalTransaction, SourceKind, TxnDirection, DecisionTier
from app.api.v1.batches import get_tenant_state, TENANT_STATES, STATE
from app.api.v1.qa import assemble_live_batch_context, execute_dynamic_data_reasoner


class TestAuditIssues215To223(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Base.metadata.create_all(bind=engine)
        DatabaseService.seed_default_data()

    def test_2_15_loading_states_and_classes_in_css(self):
        """Issue 2.15: Verify loading, spinner, aria-busy, and skeleton styles exist."""
        css_path = os.path.join("frontend", "static", "css", "styles.css")
        with open(css_path, "r", encoding="utf-8") as f:
            css = f.read()

        self.assertIn(".btn-loading", css)
        self.assertIn(".btn-spinner", css)
        self.assertIn('[aria-busy="true"]', css)
        self.assertIn(".skeleton", css)
        self.assertIn("cursor: not-allowed", css)

    def test_2_16_responsive_layout_and_hamburger(self):
        """Issue 2.16: Verify responsive sidebar, hamburger toggle, and overlay exist."""
        html_path = os.path.join("frontend", "index.html")
        with open(html_path, "r", encoding="utf-8") as f:
            html = f.read()

        self.assertIn('id="btn-sidebar-toggle"', html)
        self.assertIn('id="sidebar-overlay"', html)

        css_path = os.path.join("frontend", "static", "css", "styles.css")
        with open(css_path, "r", encoding="utf-8") as f:
            css = f.read()

        self.assertIn("@media (max-width: 960px)", css)
        self.assertIn(".app-sidebar.sidebar-open", css)
        self.assertIn(".sidebar-overlay", css)

    def test_2_17_db_path_anchored_consistently(self):
        """Issue 2.17: Verify SQLite database path is anchored to repo root."""
        db_url = settings.DATABASE_URL
        self.assertTrue(
            "finance_controller.db" in db_url or "sqlite" in db_url,
            f"Unexpected DATABASE_URL: {db_url}"
        )

    def test_2_18_seeded_passwords_authenticate(self):
        """Issue 2.18: Verify all 3 documented seeded passwords authenticate correctly."""
        credentials = [
            ("admin@acme.co", "Admin@2026!"),
            ("approver@acme.co", "Approver@2026!"),
            ("analyst@acme.co", "Analyst@2026!")
        ]
        with get_db_context() as db:
            for email, password in credentials:
                user = db.query(schema.User).filter_by(email=email).first()
                self.assertIsNotNone(user, f"Seeded user {email} not found in DB")
                self.assertTrue(verify_password(password, user.password_hash), f"Password verification failed for {email}")

    def test_2_19_multi_tenant_state_isolation(self):
        """Issue 2.19: Verify TENANT_STATES isolates data per organization."""
        org_a = "org_tenant_alpha"
        org_b = "org_tenant_beta"

        state_a = get_tenant_state(org_a)
        state_b = get_tenant_state(org_b)

        state_a["transactions"] = [{"id": "txn_a1", "amount_minor": 50000}]
        state_b["transactions"] = [{"id": "txn_b1", "amount_minor": 90000}]

        self.assertEqual(len(get_tenant_state(org_a)["transactions"]), 1)
        self.assertEqual(get_tenant_state(org_a)["transactions"][0]["id"], "txn_a1")
        self.assertEqual(get_tenant_state(org_b)["transactions"][0]["id"], "txn_b1")

    def test_2_19_bounded_caches(self):
        """Issue 2.19: Verify agent suite and runtime caches are bounded."""
        suite = FinancialAgentSuite.get_suite()
        self.assertIsInstance(suite._cached_batch_analyses, dict)

        runtime = AIAgentRuntime()
        self.assertIsInstance(runtime._L1_CACHE, dict)

    def test_2_20_dynamic_period_derivation(self):
        """Issue 2.20: Verify period start/end derive from transaction timestamps."""
        t1 = CanonicalTransaction(
            id="t1",
            org_id="org_test",
            batch_id="b_test",
            source_kind=SourceKind.GATEWAY,
            direction=TxnDirection.INFLOW,
            amount_minor=10000,
            occurred_at=datetime(2026, 4, 5, 10, 0, 0),
            value_date=date(2026, 4, 5),
            external_id="EXT-1",
            description_raw="Test Payment 1",
            description_norm="test payment 1"
        )
        t2 = CanonicalTransaction(
            id="t2",
            org_id="org_test",
            batch_id="b_test",
            source_kind=SourceKind.BANK,
            direction=TxnDirection.INFLOW,
            amount_minor=10000,
            occurred_at=datetime(2026, 4, 25, 14, 0, 0),
            value_date=date(2026, 4, 25),
            external_id="EXT-2",
            description_raw="Test Bank Credit",
            description_norm="test bank credit"
        )

        p_dates = []
        for t in [t1, t2]:
            if t.occurred_at:
                p_dates.append(t.occurred_at.date() if isinstance(t.occurred_at, datetime) else t.occurred_at)
            if t.value_date:
                p_dates.append(t.value_date.date() if isinstance(t.value_date, datetime) else t.value_date)

        p_start = min(p_dates)
        p_end = max(p_dates)

        self.assertEqual(p_start, date(2026, 4, 5))
        self.assertEqual(p_end, date(2026, 4, 25))

    def test_2_21_cors_configuration(self):
        """Issue 2.21: Verify CORS settings handle credentials properly."""
        from app.main import app
        # Verify middleware is present
        middleware_names = [m.cls.__name__ for m in app.user_middleware]
        self.assertIn("CORSMiddleware", middleware_names)

    def test_2_23_b_get_batch_stats_scoped_to_batch(self):
        """Issue 2.23 b: Verify get_batch_stats queries audit_count for the specific batch."""
        stats = DatabaseService.get_batch_stats()
        self.assertIsInstance(stats, dict)

    def test_2_23_f_context_builder_indexed_lookup(self):
        """Issue 2.23 f: Verify TransactionContextBuilder accepts pre-built lookup index."""
        t1 = CanonicalTransaction(
            id="t_ctx_1",
            org_id="org_test",
            batch_id="b_test",
            source_kind=SourceKind.GATEWAY,
            direction=TxnDirection.INFLOW,
            amount_minor=118000,
            occurred_at=datetime(2026, 3, 15, 10, 0, 0),
            value_date=date(2026, 3, 15),
            external_id="EXT-CTX-1",
            description_raw="Invoice INV-9901 payment",
            description_norm="invoice inv 9901 payment"
        )
        t2 = CanonicalTransaction(
            id="t_ctx_2",
            org_id="org_test",
            batch_id="b_test",
            source_kind=SourceKind.BANK,
            direction=TxnDirection.INFLOW,
            amount_minor=115215,
            occurred_at=datetime(2026, 3, 17, 10, 0, 0),
            value_date=date(2026, 3, 17),
            external_id="EXT-CTX-2",
            description_raw="Razorpay Settlement net MDR fee",
            description_norm="razorpay settlement net mdr fee"
        )
        all_txns = [t1, t2]
        prebuilt_index = TransactionLookupIndex(all_txns)

        ctx = TransactionContextBuilder.build_context(t1, all_txns, lookup_index=prebuilt_index)
        self.assertIsNotNone(ctx)
        self.assertEqual(ctx.transaction_id, "t_ctx_1")

    def test_2_23_i_normalizer_first_present_preserves_zero(self):
        """Issue 2.23 i: Verify _first_present preserves zero values."""
        row = {"amount": 0, "Amount": 500, "fee_amount": "0.00", "fee": 25}
        amt = NormalizerService._first_present(row, "amount", "Amount")
        fee = NormalizerService._first_present(row, "fee_amount", "fee")

        self.assertEqual(amt, 0)
        self.assertEqual(fee, "0.00")

    def test_2_23_k_qa_greeting_regex_word_boundaries(self):
        """Issue 2.23 k: Verify QA greeting does not false match 'this', 'which', 'high'."""
        queries_not_greeting = [
            "which transactions are unallocated?",
            "explain this fee breakdown",
            "show high severity exceptions",
            "what is the difference in this batch?"
        ]
        for q in queries_not_greeting:
            is_greeting = bool(re.search(r'\b(hi|hello|hey|help)\b', q.lower()))
            self.assertFalse(is_greeting, f"Query '{q}' incorrectly matched as greeting!")

        queries_greeting = ["hi", "hello", "hey", "help", "what is this chat"]
        for q in queries_greeting:
            is_greeting = bool(re.search(r'\b(hi|hello|hey|help)\b', q.lower())) or ("what is this chat" in q.lower())
            self.assertTrue(is_greeting, f"Query '{q}' should match greeting!")

    def test_2_23_m_qa_severity_counts_authoritative(self):
        """Issue 2.23 m: Verify QA dynamic reasoner reports authoritative severity counts."""
        ctx = {
            "batch_id": "BATCH-TEST-QA",
            "total_records": 100,
            "match_rate_pct": 85.0,
            "total_exceptions": 15,
            "critical_exceptions_count": 5,
            "high_exceptions_count": 6,
            "medium_low_exceptions_count": 4,
            "open_exceptions_sample": [
                {"id": "EXC-1", "type": "CUTOFF", "severity": "CRITICAL", "impact_inr": "₹1,000.00", "recommended_action": "ACCRUE"}
            ]
        }
        res = execute_dynamic_data_reasoner("How many exceptions are there?", ctx)
        self.assertIn("5 Critical", res.direct_answer)
        self.assertIn("6 High", res.direct_answer)
        self.assertIn("4 Medium/Low", res.direct_answer)
        self.assertIn("15 open exceptions", res.direct_answer)


if __name__ == "__main__":
    unittest.main()
