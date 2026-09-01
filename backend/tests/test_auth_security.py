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
        """Validates analyst token is correctly identified as analyst."""
        token = create_access_token(
            subject="usr_analyst_01",
            org_id=self.org_id,
            role="analyst"
        )
        user = get_current_user(token=token)
        self.assertEqual(user["user_id"], "usr_analyst_01")
        self.assertEqual(user["role"], "analyst")

    def test_admin_token_authenticated_with_full_access(self):
        """Validates admin token decodes correctly and passes RBAC guards."""
        from app.core.security import require_roles
        token = create_access_token(
            subject="usr_admin_01",
            org_id=self.org_id,
            role="admin"
        )
        user = get_current_user(token=token)
        self.assertEqual(user["user_id"], "usr_admin_01")
        self.assertEqual(user["role"], "admin")

        # Verify admin passes require_roles
        checker = require_roles(["approver"], allow_admin=True)
        res = checker(current_user=user)
        self.assertEqual(res["role"], "admin")

    def test_admin_can_approve_proposals(self):
        """Validates admin can decide proposals in single-role full access architecture."""
        import asyncio
        import uuid
        from app.api.v1.approvals import decide_proposal, ApprovalActionRequest
        from app.db.database import get_db_context
        from app.db import schema

        prop_id = f"prop_{uuid.uuid4().hex[:8]}"
        exc_id = f"exc_{uuid.uuid4().hex[:8]}"

        with get_db_context() as db:
            exc = schema.ExceptionRecord(
                id=exc_id, org_id=self.org_id, batch_id="BATCH-TEST-01",
                exception_type="AMOUNT_MISMATCH", severity="LOW",
                impact_minor=1000, state="OPEN"
            )
            prop = schema.ResolutionProposal(
                id=prop_id, org_id=self.org_id, exception_id=exc_id,
                action="WRITE_OFF_IMMATERIAL", recommended_parameters={"account": "write_off_clearing"},
                justification="Minor variance",
                confidence=0.99, status="PENDING_APPROVAL",
                created_by="usr_admin_01"  # Created by admin
            )
            db.add_all([exc, prop])
            db.commit()

        # Admin approving their own raised proposal in single-role setup
        admin_user = {
            "user_id": "usr_admin_01",
            "org_id": self.org_id,
            "role": "admin"
        }
        req = ApprovalActionRequest(
            proposal_id=prop_id,
            action="APPROVED",
            decision_notes="Approved by Admin"
        )
        res = asyncio.run(decide_proposal(req, current_user=admin_user))
        self.assertEqual(res["status"], "SUCCESS")
        self.assertEqual(res["decision"], "APPROVED")

if __name__ == "__main__":
    unittest.main()
