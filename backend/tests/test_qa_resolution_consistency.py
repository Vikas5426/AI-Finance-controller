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
        """Verify that a resolved transaction (e.g. JE-004) is recognized as settled cleanly and not hallucinated as pending."""
        org_id = settings.DEFAULT_ORG_ID

        # Test with direct query mentioning the external ID
        query = "Why did invoice JE-004 not settle in this batch?"
        ctx = assemble_live_batch_context(query, org_id)

        target = ctx.get("target_transaction_referenced")
        self.assertIsNotNone(target, "Should locate target transaction JE-004")
        self.assertEqual(target.get("external_id"), "JE-004")
        self.assertTrue(target.get("settled"), "Target transaction JE-004 should be marked as settled")
        self.assertEqual(target.get("match_status"), "RESOLVED")

        # Test reasoning output
        reasoning = execute_dynamic_data_reasoner(query, ctx)
        self.assertEqual(reasoning.status_card.badge_type, "success")
        self.assertEqual(reasoning.status_card.status_text, "Settled Cleanly")
        self.assertIn("actually settled and resolved cleanly", reasoning.direct_answer)
        self.assertIn("pay_TEST_004", reasoning.direct_answer)
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
        self.assertNotEqual(reasoning.status_card.status_text, "Settled Cleanly")


if __name__ == "__main__":
    unittest.main()
