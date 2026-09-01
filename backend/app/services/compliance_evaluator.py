"""
Independent Compliance and Internal Controls Evaluation Engine.
Strictly separates:
1. HASH_CHAIN_INTEGRITY (Cryptographic SHA-256 ledger tamper-evidence)
2. MAKER_CHECKER_STATUS (Dual-control segregation of duties)
3. ACCESS_CONTROL_STATUS (Role enforcement and identity provenance)
4. CHANGE_CONTROL_STATUS (Audit log immutability verification)
5. OVERALL_COMPLIANCE_STATUS (Comprehensive SOX-404 posture)

A valid SHA-256 chain only proves internal ledger integrity; it does NOT prove
independent checker approvals or auditor sign-offs have occurred.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set
from app.services.audit_chain import AuditHashChain
from app.models.schemas import (
    HashChainIntegrityStatus,
    MakerCheckerStatus,
    AccessControlStatus,
    ChangeControlStatus,
    OverallComplianceStatus,
    ApprovalRecordSchema,
    AuditorSignOffState,
    ComplianceAssessment
)


class ComplianceEvaluator:
    """Evaluates the 5 independent compliance and internal control states for a batch."""

    @classmethod
    def evaluate_batch_compliance(
        cls,
        batch_id: str,
        audit_events: List[Dict[str, Any]],
        proposals: List[Dict[str, Any]],
        approvals: List[Dict[str, Any]],
        exceptions: Optional[List[Dict[str, Any]]] = None
    ) -> ComplianceAssessment:
        exceptions = exceptions or []
        total_excs = len(exceptions)

        # ---------------------------------------------------------
        # Control 1: Cryptographic Hash Chain Integrity
        # ---------------------------------------------------------
        if not audit_events:
            hash_status = HashChainIntegrityStatus.EMPTY
        else:
            sorted_events = sorted(audit_events, key=lambda x: x.get("event_seq", 1))
            is_valid, broken_seq = AuditHashChain.verify_chain_integrity(sorted_events)
            hash_status = HashChainIntegrityStatus.VALID if is_valid else HashChainIntegrityStatus.TAMPERED

        # ---------------------------------------------------------
        # Control 2: Maker-Checker Dual-Control Governance
        # ---------------------------------------------------------
        appr_records: List[ApprovalRecordSchema] = []
        pending_count = 0
        completed_approvals_count = 0
        segregation_violations_count = 0
        unverifiable_actors_count = 0

        # Build map of approvals by proposal_id / exception_id
        appr_by_prop: Dict[str, Dict[str, Any]] = {}
        for a in approvals:
            p_id = a.get("proposal_id")
            e_id = a.get("exception_id")
            if p_id:
                appr_by_prop[str(p_id)] = a
            elif e_id:
                appr_by_prop[str(e_id)] = a

        for p in proposals:
            p_id = str(p.get("id"))
            e_id = str(p.get("exception_id") or "")
            maker_id = p.get("created_by")
            maker_ts = str(p.get("created_at") or "")

            appr = appr_by_prop.get(p_id) or appr_by_prop.get(e_id)

            if not appr or p.get("status") == "PENDING_APPROVAL":
                pending_count += 1
                appr_records.append(ApprovalRecordSchema(
                    id=f"rec_{p_id}",
                    exception_id=e_id,
                    proposal_id=p_id,
                    maker_id=maker_id or "usr_maker_unrecorded",
                    checker_id=None,
                    maker_timestamp=maker_ts,
                    checker_timestamp=None,
                    approval_status="PENDING_CHECKER",
                    segregation_check=False,
                    decision_notes="Awaiting independent checker review."
                ))
            else:
                checker_id = appr.get("actor_id") or appr.get("decided_by")
                checker_ts = str(appr.get("created_at") or "")
                action = (appr.get("action") or "APPROVED").upper()

                if not maker_id or not checker_id:
                    unverifiable_actors_count += 1
                    appr_records.append(ApprovalRecordSchema(
                        id=str(appr.get("id") or f"rec_{p_id}"),
                        exception_id=e_id,
                        proposal_id=p_id,
                        maker_id=maker_id or "UNKNOWN",
                        checker_id=checker_id or "UNKNOWN",
                        maker_timestamp=maker_ts,
                        checker_timestamp=checker_ts,
                        approval_status="UNVERIFIABLE_IDENTITY",
                        segregation_check=False,
                        decision_notes="Maker or checker identity missing from record."
                    ))
                elif maker_id == checker_id:
                    segregation_violations_count += 1
                    appr_records.append(ApprovalRecordSchema(
                        id=str(appr.get("id") or f"rec_{p_id}"),
                        exception_id=e_id,
                        proposal_id=p_id,
                        maker_id=maker_id,
                        checker_id=checker_id,
                        maker_timestamp=maker_ts,
                        checker_timestamp=checker_ts,
                        approval_status="SEGREGATION_VIOLATION",
                        segregation_check=False,
                        decision_notes="Maker-Checker breach: maker and checker are the same user."
                    ))
                else:
                    if action == "APPROVED":
                        completed_approvals_count += 1
                    appr_records.append(ApprovalRecordSchema(
                        id=str(appr.get("id") or f"rec_{p_id}"),
                        exception_id=e_id,
                        proposal_id=p_id,
                        maker_id=maker_id,
                        checker_id=checker_id,
                        maker_timestamp=maker_ts,
                        checker_timestamp=checker_ts,
                        approval_status=action,
                        segregation_check=True,
                        decision_notes=appr.get("decision_notes") or "Reviewed and approved by independent checker."
                    ))

        # Maker-Checker Status Synthesis
        if segregation_violations_count > 0:
            mc_status = MakerCheckerStatus.SEGREGATION_VIOLATION
        elif len(proposals) == 0:
            mc_status = MakerCheckerStatus.NO_APPROVALS_REQUIRED
        elif completed_approvals_count == len(proposals) and completed_approvals_count > 0:
            mc_status = MakerCheckerStatus.FULLY_APPROVED
        elif completed_approvals_count > 0:
            mc_status = MakerCheckerStatus.PARTIALLY_APPROVED
        else:
            mc_status = MakerCheckerStatus.PENDING_REVIEW

        # ---------------------------------------------------------
        # Control 3: Access Control & Role Segregation
        # ---------------------------------------------------------
        if segregation_violations_count > 0:
            access_status = AccessControlStatus.VIOLATION_DETECTED
        elif unverifiable_actors_count > 0:
            access_status = AccessControlStatus.UNVERIFIABLE_ACTORS
        else:
            access_status = AccessControlStatus.SEGREGATION_COMPLIANT

        # ---------------------------------------------------------
        # Control 4: Change Control & Ledger Immutability
        # ---------------------------------------------------------
        if hash_status == HashChainIntegrityStatus.VALID:
            change_status = ChangeControlStatus.IMMUTABLE_LOG_VERIFIED
        elif hash_status == HashChainIntegrityStatus.TAMPERED:
            change_status = ChangeControlStatus.UNAUTHORIZED_MODIFICATION
        else:
            change_status = ChangeControlStatus.LOGS_UNVERIFIED

        # ---------------------------------------------------------
        # Auditor Sign-off State (Grounded in system events)
        # ---------------------------------------------------------
        signoff_event = next(
            (e for e in audit_events if e.get("event_type") == "AUDITOR_SIGNOFF" or (isinstance(e.get("payload"), dict) and e["payload"].get("event") == "AUDITOR_SIGNOFF")),
            None
        )
        if signoff_event:
            auditor_state = AuditorSignOffState(
                is_signed_off=True,
                signed_by_auditor_id=str(signoff_event.get("actor_id")),
                signed_at=str(signoff_event.get("created_at")),
                auditor_notes=signoff_event.get("payload", {}).get("notes", "Auditor certified"),
                system_event_id=str(signoff_event.get("id") or signoff_event.get("event_hash"))
            )
        else:
            auditor_state = AuditorSignOffState(
                is_signed_off=False,
                signed_by_auditor_id=None,
                signed_at=None,
                auditor_notes="No auditor sign-off recorded for this batch.",
                system_event_id=None
            )

        # ---------------------------------------------------------
        # Control 5: Overall Compliance Status Synthesis
        # ---------------------------------------------------------
        if hash_status == HashChainIntegrityStatus.TAMPERED or access_status == AccessControlStatus.VIOLATION_DETECTED:
            overall_status = OverallComplianceStatus.NON_COMPLIANT
        elif pending_count > 0 or mc_status == MakerCheckerStatus.PENDING_REVIEW:
            overall_status = OverallComplianceStatus.PENDING_ACTION
        elif hash_status == HashChainIntegrityStatus.VALID and (mc_status in (MakerCheckerStatus.FULLY_APPROVED, MakerCheckerStatus.NO_APPROVALS_REQUIRED)):
            overall_status = OverallComplianceStatus.AUDIT_READY
        else:
            overall_status = OverallComplianceStatus.COMPLIANT

        return ComplianceAssessment(
            batch_id=batch_id,
            hash_chain_integrity=hash_status,
            maker_checker_status=mc_status,
            access_control_status=access_status,
            change_control_status=change_status,
            overall_compliance_status=overall_status,
            total_exceptions=total_excs,
            pending_review_count=pending_count,
            completed_approvals_count=completed_approvals_count,
            segregation_violations_count=segregation_violations_count,
            approvals=appr_records,
            auditor_sign_off=auditor_state,
            controls_breakdown={
                "ITGC-AUD-01_immutable_logging": hash_status.value,
                "SOX-FIN-04_dual_control_segregation": mc_status.value,
                "SOX-SEC-02_access_control": access_status.value,
                "ITGC-CHG-01_change_control": change_status.value,
                "SOX-GOV-01_auditor_signoff": "COMPLETED" if auditor_state.is_signed_off else "PENDING_AUDITOR_ACTION"
            }
        )
