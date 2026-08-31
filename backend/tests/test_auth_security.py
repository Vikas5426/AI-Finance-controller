import os
import sys
import unittest
from fastapi import HTTPException

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.security import create_access_token, get_current_user, get_password_hash, verify_password
from app.api.v1.approvals import get_pending_approvals

class TestAuthSecurity(unittest.TestCase):
    def setUp(self):
        self.org_id = "00000000-0000-0000-0000-000000000001"

    def test_unauthenticated_request_rejected_with_401(self):
        """Validates that missing token raises HTTP 401 rather than defaulting to approver."""
        with self.assertRaises(HTTPException) as cm:
            get_current_user(token=None)
        self.assertEqual(cm.exception.status_code, 401)
        self.assertIn("Authentication required", cm.exception.detail)

    def test_invalid_token_rejected_with_401(self):
        """Validates that tampered or garbage token raises HTTP 401."""
        with self.assertRaises(HTTPException) as cm:
            get_current_user(token="invalid.garbage.jwt_token")
        self.assertEqual(cm.exception.status_code, 401)

    def test_valid_token_authenticated_correctly(self):
        """Validates that a legitimate JWT token decodes to the exact user identity and role."""
        token = create_access_token(
            subject="usr_approver_01",
            org_id=self.org_id,
            role="approver"
        )
        user = get_current_user(token=token)
        self.assertEqual(user["user_id"], "usr_approver_01")
        self.assertEqual(user["role"], "approver")
        self.assertEqual(user["org_id"], self.org_id)

    def test_analyst_token_authenticated_as_analyst(self):
        """Validates analyst token is correctly identified as analyst and cannot act as approver."""
        token = create_access_token(
            subject="usr_analyst_01",
            org_id=self.org_id,
            role="analyst"
        )
        user = get_current_user(token=token)
        self.assertEqual(user["user_id"], "usr_analyst_01")
        self.assertEqual(user["role"], "analyst")

if __name__ == "__main__":
    unittest.main()
