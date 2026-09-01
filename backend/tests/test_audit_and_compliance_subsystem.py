"""
Audit and Compliance Subsystem Verification Suite.
Verifies separate evaluation of:
1. HASH_CHAIN_INTEGRITY
2. MAKER_CHECKER_STATUS
3. ACCESS_CONTROL_STATUS
4. CHANGE_CONTROL_STATUS
5. OVERALL_COMPLIANCE_STATUS

Tests for:
- pending approval
- maker approval
- checker approval
- same maker/checker (segregation violation)
- missing checker
- invalid approval
- tampered hash
- valid hash (separated from approval/SOX states)
- auditor sign-off event
"""

import unittest
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List

from app.models.schemas import (
    HashChainIntegrityStatus,
    MakerCheckerStatus,
    AccessControlStatus,
    ChangeControlStatus,
    OverallComplianceStatus
)
from app.services.audit_chain import AuditHashChain
from app.services.compliance_evaluator import ComplianceEvaluator


class TestAuditAndComplianceSubsystem(unittest.TestCase):

    def setUp(self):
        self.batch_id = f"BATCH-COMP-{uuid.uuid4().hex[:6]}"
        self.org_id = f"ORG-{uuid.uuid4().hex[:6]}"

    def _create_audit_chain(self, num_events: int = 3) -> List[Dict[str, Any]]:
        events = []
        prev_hash = AuditHashChain.GENESIS_HASH
        for i in range(1, num_events + 1):
            ts = datetime(2026, 3, 10, 12, i, 0, tzinfo=timezone.utc)
            payload = {"action": f"STEP_{i}", "data": f"record_{i}"}
            h = AuditHashChain.compute_event_hash(
                prev_hash=prev_hash,
                org_id=self.org_id,
                event_seq=i,
                event_type="BATCH_EVENT",
                entity_id=f"ent_{i}",
                actor_id="usr_system",
                payload=payload,
                created_at=ts
            )
            events.append({
                "id": f"evt_{i}",
                "org_id": self.org_id,
                "batch_id": self.batch_id,
                "event_seq": i,
                "event_type": "BATCH_EVENT",
                "entity_id": f"ent_{i}",
                "actor_id": "usr_system",
                "payload": payload,
                "prev_hash": prev_hash,
                "event_hash": h,
                "created_at": ts.isoformat()
            })
            prev_hash = h
        return events

    def test_01_pending_approval(self):
        """1. When exceptions exist and proposals are pending, report PENDING_REVIEW, not APPROVED."""
        audit_events = self._create_audit_chain(2)
        proposals = [
            {
                "id": "prop_101",
                "exception_id": "exc_101",
                "created_by": "usr_maker_1",
                "status": "PENDING_APPROVAL",
                "created_at": "2026-03-10T12:00:00Z"
            }
        ]
        exceptions = [{"id": "exc_101", "impact_minor": 50000}]

        comp = ComplianceEvaluator.evaluate_batch_compliance(
            batch_id=self.batch_id,
            audit_events=audit_events,
            proposals=proposals,
            approvals=[],
            exceptions=exceptions
        )

        self.assertEqual(comp.maker_checker_status, MakerCheckerStatus.PENDING_REVIEW)
        self.assertEqual(comp.pending_review_count, 1)
        self.assertEqual(comp.completed_approvals_count, 0)
        self.assertEqual(comp.overall_compliance_status, OverallComplianceStatus.PENDING_ACTION)
        self.assertFalse(comp.auditor_sign_off.is_signed_off)

    def test_02_maker_approval(self):
        """2. Maker raises proposal, pending checker review -> approval_status is PENDING_CHECKER."""
        audit_events = self._create_audit_chain(2)
        proposals = [
            {
                "id": "prop_201",
                "exception_id": "exc_201",
                "created_by": "usr_analyst_raj",
                "status": "PENDING_APPROVAL",
                "created_at": "2026-03-10T12:00:00Z"
            }
        ]

        comp = ComplianceEvaluator.evaluate_batch_compliance(
            batch_id=self.batch_id,
            audit_events=audit_events,
            proposals=proposals,
            approvals=[]
        )

        self.assertEqual(len(comp.approvals), 1)
        appr = comp.approvals[0]
        self.assertEqual(appr.maker_id, "usr_analyst_raj")
        self.assertIsNone(appr.checker_id)
        self.assertEqual(appr.approval_status, "PENDING_CHECKER")
        self.assertFalse(appr.segregation_check)

    def test_03_checker_approval(self):
        """3. Independent checker approves -> valid APPROVED state with segregation_check True."""
        audit_events = self._create_audit_chain(3)
        proposals = [
            {
                "id": "prop_301",
                "exception_id": "exc_301",
                "created_by": "usr_maker_raj",
                "status": "APPROVED",
                "created_at": "2026-03-10T12:00:00Z"
            }
        ]
        approvals = [
            {
                "id": "appr_301",
                "proposal_id": "prop_301",
                "exception_id": "exc_301",
                "actor_id": "usr_checker_priya",
                "action": "APPROVED",
                "created_at": "2026-03-10T12:30:00Z",
                "decision_notes": "Reviewed and confirmed."
            }
        ]

        comp = ComplianceEvaluator.evaluate_batch_compliance(
            batch_id=self.batch_id,
            audit_events=audit_events,
            proposals=proposals,
            approvals=approvals
        )

        self.assertEqual(comp.maker_checker_status, MakerCheckerStatus.FULLY_APPROVED)
        self.assertEqual(comp.completed_approvals_count, 1)
        self.assertEqual(comp.pending_review_count, 0)
        self.assertEqual(comp.segregation_violations_count, 0)

        appr = comp.approvals[0]
        self.assertEqual(appr.maker_id, "usr_maker_raj")
        self.assertEqual(appr.checker_id, "usr_checker_priya")
        self.assertTrue(appr.segregation_check)
        self.assertEqual(appr.approval_status, "APPROVED")

    def test_04_same_maker_checker(self):
        """4. Same maker and checker -> SEGREGATION_VIOLATION detected and compliance marked NON_COMPLIANT."""
        audit_events = self._create_audit_chain(3)
        proposals = [
            {
                "id": "prop_401",
                "exception_id": "exc_401",
                "created_by": "usr_admin_vikas",
                "status": "APPROVED",
                "created_at": "2026-03-10T12:00:00Z"
            }
        ]
        approvals = [
            {
                "id": "appr_401",
                "proposal_id": "prop_401",
                "exception_id": "exc_401",
                "actor_id": "usr_admin_vikas",  # SAME AS MAKER!
                "action": "APPROVED",
                "created_at": "2026-03-10T12:30:00Z",
                "decision_notes": "Self approved."
            }
        ]

        comp = ComplianceEvaluator.evaluate_batch_compliance(
            batch_id=self.batch_id,
            audit_events=audit_events,
            proposals=proposals,
            approvals=approvals
        )

        self.assertEqual(comp.maker_checker_status, MakerCheckerStatus.SEGREGATION_VIOLATION)
        self.assertEqual(comp.access_control_status, AccessControlStatus.VIOLATION_DETECTED)
        self.assertEqual(comp.overall_compliance_status, OverallComplianceStatus.NON_COMPLIANT)
        self.assertEqual(comp.segregation_violations_count, 1)
        self.assertEqual(comp.completed_approvals_count, 0)
        self.assertFalse(comp.approvals[0].segregation_check)
        self.assertEqual(comp.approvals[0].approval_status, "SEGREGATION_VIOLATION")

    def test_05_missing_checker(self):
        """5. Missing checker identity cannot be counted as completed approval."""
        audit_events = self._create_audit_chain(2)
        proposals = [
            {
                "id": "prop_501",
                "exception_id": "exc_501",
                "created_by": "usr_maker_1",
                "status": "APPROVED",
                "created_at": "2026-03-10T12:00:00Z"
            }
        ]
        approvals = [
            {
                "id": "appr_501",
                "proposal_id": "prop_501",
                "exception_id": "exc_501",
                "actor_id": None,  # MISSING CHECKER!
                "action": "APPROVED",
                "created_at": "2026-03-10T12:30:00Z"
            }
        ]

        comp = ComplianceEvaluator.evaluate_batch_compliance(
            batch_id=self.batch_id,
            audit_events=audit_events,
            proposals=proposals,
            approvals=approvals
        )

        self.assertEqual(comp.completed_approvals_count, 0)
        self.assertEqual(comp.access_control_status, AccessControlStatus.UNVERIFIABLE_ACTORS)
        self.assertFalse(comp.approvals[0].segregation_check)

    def test_06_tampered_hash(self):
        """6. Tampered block in audit chain triggers TAMPERED status and NON_COMPLIANT."""
        events = self._create_audit_chain(3)
        # Tamper with event sequence 2 payload
        events[1]["payload"]["action"] = "MUTATED_ACTION"

        comp = ComplianceEvaluator.evaluate_batch_compliance(
            batch_id=self.batch_id,
            audit_events=events,
            proposals=[],
            approvals=[]
        )

        self.assertEqual(comp.hash_chain_integrity, HashChainIntegrityStatus.TAMPERED)
        self.assertEqual(comp.change_control_status, ChangeControlStatus.UNAUTHORIZED_MODIFICATION)
        self.assertEqual(comp.overall_compliance_status, OverallComplianceStatus.NON_COMPLIANT)

    def test_07_valid_hash_separate_from_maker_checker_and_sox(self):
        """7. Valid SHA-256 chain does NOT imply maker-checker approval or auditor sign-off."""
        events = self._create_audit_chain(4)
        # Chain is valid, but 2 proposals are pending
        proposals = [
            {"id": "p1", "exception_id": "e1", "created_by": "maker1", "status": "PENDING_APPROVAL"},
            {"id": "p2", "exception_id": "e2", "created_by": "maker2", "status": "PENDING_APPROVAL"}
        ]

        comp = ComplianceEvaluator.evaluate_batch_compliance(
            batch_id=self.batch_id,
            audit_events=events,
            proposals=proposals,
            approvals=[]
        )

        # Cryptographic chain is VALID
        self.assertEqual(comp.hash_chain_integrity, HashChainIntegrityStatus.VALID)
        self.assertEqual(comp.change_control_status, ChangeControlStatus.IMMUTABLE_LOG_VERIFIED)

        # But Maker-Checker is PENDING and NOT approved!
        self.assertEqual(comp.maker_checker_status, MakerCheckerStatus.PENDING_REVIEW)
        self.assertEqual(comp.pending_review_count, 2)
        self.assertEqual(comp.completed_approvals_count, 0)

        # And Auditor sign-off is NOT present!
        self.assertFalse(comp.auditor_sign_off.is_signed_off)
        self.assertEqual(comp.overall_compliance_status, OverallComplianceStatus.PENDING_ACTION)

    def test_08_auditor_signoff_event_grounding(self):
        """8. Auditor sign-off only set when real AUDITOR_SIGNOFF event exists in audit chain."""
        events = self._create_audit_chain(2)
        # Add real auditor sign-off event
        signoff_ts = datetime(2026, 3, 10, 14, 0, 0, tzinfo=timezone.utc)
        prev_h = events[-1]["event_hash"]
        signoff_payload = {"event": "AUDITOR_SIGNOFF", "notes": "SOX-404 annual review clean"}
        signoff_h = AuditHashChain.compute_event_hash(
            prev_hash=prev_h,
            org_id=self.org_id,
            event_seq=3,
            event_type="AUDITOR_SIGNOFF",
            entity_id=self.batch_id,
            actor_id="usr_lead_auditor_kpmg",
            payload=signoff_payload,
            created_at=signoff_ts
        )
        events.append({
            "id": "evt_signoff_3",
            "org_id": self.org_id,
            "batch_id": self.batch_id,
            "event_seq": 3,
            "event_type": "AUDITOR_SIGNOFF",
            "entity_id": self.batch_id,
            "actor_id": "usr_lead_auditor_kpmg",
            "payload": signoff_payload,
            "prev_hash": prev_h,
            "event_hash": signoff_h,
            "created_at": signoff_ts.isoformat()
        })

        comp = ComplianceEvaluator.evaluate_batch_compliance(
            batch_id=self.batch_id,
            audit_events=events,
            proposals=[],
            approvals=[]
        )

        self.assertTrue(comp.auditor_sign_off.is_signed_off)
        self.assertEqual(comp.auditor_sign_off.signed_by_auditor_id, "usr_lead_auditor_kpmg")
        self.assertEqual(comp.auditor_sign_off.auditor_notes, "SOX-404 annual review clean")
        self.assertEqual(comp.overall_compliance_status, OverallComplianceStatus.AUDIT_READY)


if __name__ == "__main__":
    unittest.main()
