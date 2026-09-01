import os
import sys
import unittest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.main import app
from app.core.security import create_access_token
from app.models.schemas import ExecutionMode

class TestLiveBatchApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        cls.org_id = "00000000-0000-0000-0000-000000000001"
        cls.token = create_access_token(
            subject="usr_test_controller",
            org_id=cls.org_id,
            role="approver"
        )
        cls.headers = {"Authorization": f"Bearer {cls.token}"}

    def test_internal_test_batch_execution(self):
        """Validates live POST /api/v1/batches/run with INTERNAL_TEST mode."""
        resp = self.client.post(
            "/api/v1/batches/run",
            json={"execution_mode": "INTERNAL_TEST", "window_size": 24},
            headers=self.headers
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "SUCCESS")
        self.assertIn("batch_id", data)
        self.assertIn("summary", data)
        summary = data["summary"]
        self.assertEqual(summary["total_records"], 36)
        self.assertIn("matched_records", summary)
        self.assertIn("match_rate", summary)
        self.assertIn("tier_breakdown", summary)
        self.assertIn("provenance", data)
        self.assertEqual(data["provenance"]["execution_mode"], "INTERNAL_TEST")
        self.assertIn("node_telemetry", data)
        tel = data["node_telemetry"]
        self.assertEqual(tel["node_1"]["normalized_records"], 36)
        self.assertGreater(tel["node_6"]["audit_blocks_sealed"], 0)

    def test_unauthenticated_approvals_rejected(self):
        """Validates that GET /api/v1/approvals/pending rejects requests with no token with 401."""
        resp = self.client.get("/api/v1/approvals/pending")
        self.assertEqual(resp.status_code, 401)

    def test_authenticated_approvals_succeeds(self):
        """Validates that GET /api/v1/approvals/pending succeeds with valid token."""
        resp = self.client.get("/api/v1/approvals/pending", headers=self.headers)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("items", data)

if __name__ == "__main__":
    unittest.main()
