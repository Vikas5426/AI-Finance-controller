import unittest
import os
import sys
from fastapi.testclient import TestClient

# Ensure backend directory is in path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.main import app
from app.core.config import settings
from app.core.security import create_access_token
from app.db.database_service import DatabaseService, get_db_context
from app.db.database import engine, Base
from app.db import schema
from app.api.v1.qa import (
    assemble_live_batch_context,
    execute_dynamic_data_reasoner
)


class TestQAResolutionConsistency(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Base.metadata.create_all(bind=engine)
        DatabaseService.seed_default_data()
        
        # Execute an INTERNAL_TEST batch run to seed real reconciliation transactions, matches, and exceptions
        client = TestClient(app)
        token = create_access_token("usr_test_controller", settings.DEFAULT_ORG_ID, "approver")
        resp = client.post(
            "/api/v1/batches/run",
            json={"execution_mode": "INTERNAL_TEST", "window_size": 24},
            headers={"Authorization": f"Bearer {token}"}
        )
        assert resp.status_code == 200, f"Failed to run test batch: {resp.text}"

    def test_resolved_transaction_context_and_reasoner(self):
        """Verify that a resolved transaction is recognized as settled cleanly and not hallucinated as pending."""
        org_id = settings.DEFAULT_ORG_ID

        # Dynamically locate a resolved transaction from the seeded batch
        base_ctx = assemble_live_batch_context("status", org_id)
        resolved_txn = next((t for t in base_ctx.get("transactions", []) if t.get("settled") or t.get("match_status") == "RESOLVED"), None)
        txn_ref = resolved_txn.get("external_id") if resolved_txn else "TXN001"

        # Test with direct query mentioning the external ID
        query = f"Why did invoice {txn_ref} not settle in this batch?"
        ctx = assemble_live_batch_context(query, org_id)

        target = ctx.get("target_transaction_referenced")
        self.assertIsNotNone(target, f"Should locate target transaction {txn_ref}")
        self.assertEqual(target.get("external_id"), txn_ref)
        self.assertTrue(target.get("settled"), f"Target transaction {txn_ref} should be marked as settled")
        self.assertEqual(target.get("match_status"), "RESOLVED")

        # Test reasoning output
        reasoning = execute_dynamic_data_reasoner(query, ctx)
        self.assertEqual(reasoning.status_card.badge_type, "success")
        self.assertEqual(reasoning.status_card.status_text, "Settled Cleanly")
        self.assertIn("actually settled and resolved cleanly", reasoning.direct_answer)
        self.assertNotIn("did NOT settle in this batch because it is held as an unresolved exception", reasoning.direct_answer)

    def test_inspection_query_with_active_context(self):
        """Verify that when the client sends the new inspect prompt and active_context, it resolves truthfully."""
        org_id = settings.DEFAULT_ORG_ID
        query = "Inspect transaction JE-004 and explain its settlement details in this batch."
        active_context = {
            "target_transaction": {
                "external_id": "JE-004",
                "match_status": "RESOLVED",
                "source_kind": "GENERAL_LEDGER"
            }
        }

        ctx = assemble_live_batch_context(query, org_id, active_context=active_context)
        target = ctx.get("target_transaction_referenced")
        self.assertIsNotNone(target)
        self.assertTrue(target.get("settled"))

        reasoning = execute_dynamic_data_reasoner(query, ctx)
        self.assertEqual(reasoning.status_card.badge_type, "success")
        self.assertEqual(reasoning.status_card.status_text, "Settled Cleanly")
        self.assertIn("JE-004", reasoning.direct_answer)

    def test_exception_transaction_properly_reported(self):
        """Verify that an actual exception transaction is correctly reported as an exception and not marked settled."""
        org_id = settings.DEFAULT_ORG_ID
        with get_db_context() as db:
            exc = db.query(schema.ExceptionRecord).first()
            self.assertIsNotNone(exc, "Exception record should exist in seeded test batch")
            exc_id = exc.id

        query = f"Why did exception {exc_id} occur in this batch?"
        ctx = assemble_live_batch_context(query, org_id)

        self.assertIsNotNone(ctx.get("target_transaction_exception"), "Should identify the associated exception record")
        reasoning = execute_dynamic_data_reasoner(query, ctx)
        self.assertIn(reasoning.status_card.badge_type, ["danger", "warning"])
    def test_gross_flow_volume_and_general_queries(self):
        """Verify that gross flow volume accurately reflects unique gateway flow and answers queries without ₹0.00."""
        org_id = settings.DEFAULT_ORG_ID
        query = "What is the gross flow volume for this batch?"
        ctx = assemble_live_batch_context(query, org_id)

        # Ensure gross_flow_volume is non-zero in the active batch
        self.assertIn("gross_flow_volume", ctx)
        gross_vol = ctx["gross_flow_volume"]
        self.assertNotEqual(gross_vol, "₹0.00", "Gross flow volume should not be ₹0.00 for seeded batch")
        self.assertEqual(gross_vol, f"₹{(ctx['gross_flow_minor'] / 100):,.2f}")

        # Test reasoning output for Gross Flow
        reasoning = execute_dynamic_data_reasoner(query, ctx)
        self.assertEqual(reasoning.status_card.status_text, "Gross Flow Volume")
        self.assertEqual(reasoning.status_card.badge_type, "success")
        self.assertEqual(reasoning.status_card.amount, gross_vol)
        self.assertIn(gross_vol, reasoning.direct_answer)
        self.assertNotIn("₹0.00", reasoning.direct_answer)

        # Test with client-supplied dashboard_metrics in active_context
        active_context = {
            "dashboard_metrics": {
                "gross_flow_volume": "₹20,038.00",
                "gross_flow_minor": 2003800,
                "match_rate": "20.31%",
                "total_records": 16,
                "total_exceptions": 4
            }
        }
        client = TestClient(app)
        token = create_access_token("usr_test_controller", settings.DEFAULT_ORG_ID, "approver")
        resp = client.post(
            "/api/v1/qa/ask",
            json={
                "query": "what is the gross flow volume",
                "active_context": active_context
            },
            headers={"Authorization": f"Bearer {token}"}
        )
        self.assertEqual(resp.status_code, 200)
        qa_data = resp.json()
        self.assertIn("20,038", qa_data.get("direct_answer", "") + str(qa_data.get("status_card", {})))
        self.assertNotEqual(qa_data.get("status_card", {}).get("amount"), "₹0.00")

    def test_match_rate_and_general_data_queries(self):
        """Verify that match rate and batch overview queries produce truthful metrics."""
        org_id = settings.DEFAULT_ORG_ID
        
        # Test match rate query
        query_mr = "What is the match rate?"
        ctx_mr = assemble_live_batch_context(query_mr, org_id)
        reasoning_mr = execute_dynamic_data_reasoner(query_mr, ctx_mr)
        self.assertIn("Matched", reasoning_mr.status_card.status_text)
        self.assertIn("%", reasoning_mr.status_card.amount)
        self.assertIn(str(ctx_mr["match_rate_pct"]), reasoning_mr.direct_answer)

        # Test general overview query
        query_ov = "Give me an overview of this batch data"
        ctx_ov = assemble_live_batch_context(query_ov, org_id)
        reasoning_ov = execute_dynamic_data_reasoner(query_ov, ctx_ov)
        self.assertIn(ctx_ov["gross_flow_volume"], reasoning_ov.direct_answer + "".join(reasoning_ov.why_it_happened))


if __name__ == "__main__":
    unittest.main()
