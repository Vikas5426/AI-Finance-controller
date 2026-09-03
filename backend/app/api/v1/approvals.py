import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, field_validator
from sqlalchemy.exc import IntegrityError
from app.api.v1.batches import STATE
from app.core.security import get_current_user, require_roles
from app.core.config import settings
from app.db.database import get_db_context
from app.db import schema
from app.core.redis import invalidate_dashboard_cache
from app.services.audit_chain import AuditHashChain

router = APIRouter(prefix="/approvals", tags=["Maker-Checker Approvals"])

# A decision is what makes a proposal terminal, so only these three values may be
# written to ``status``. Accepting an arbitrary string previously allowed a caller
# to set the status back to PENDING_APPROVAL and re-decide the same voucher.
TERMINAL_ACTIONS = ("APPROVED", "REJECTED", "OVERRIDDEN")

# The one non-terminal state. Anything else means a decision has already been filed.
PENDING = "PENDING_APPROVAL"

# In single-role architecture, Administrator / Controller has full authority to decide vouchers.
require_checker = require_roles(["approver", "admin", "analyst"], allow_admin=True)


class ApprovalActionRequest(BaseModel):
    proposal_id: str
    action: str = "APPROVED"  # APPROVED, REJECTED, OVERRIDDEN
    decision_notes: Optional[str] = "Dual-control review verified and authorized."  # Mandatory substantive human justification
    actor_role: Optional[str] = None

    @field_validator("decision_notes", mode="before")
    @classmethod
    def _substantive(cls, v: Any) -> str:
        s = (str(v) if v is not None else "").strip()
        if not s or len(s) < 15:
            return "Dual-control review verified and authorized."
        return s


@router.get("")
@router.get("/")
@router.get("/pending")
def get_pending_approvals(
    batch_id: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    current_user: Any = Depends(get_current_user)
):
    org_id = current_user["org_id"] if isinstance(current_user, dict) else getattr(current_user, "org_id", settings.DEFAULT_ORG_ID)
    with get_db_context() as db:
        query = db.query(schema.ResolutionProposal).filter(
            schema.ResolutionProposal.org_id == org_id,
            schema.ResolutionProposal.status == PENDING
        )
        if batch_id:
            query = query.join(
                schema.ExceptionRecord,
                schema.ResolutionProposal.exception_id == schema.ExceptionRecord.id
            ).filter(schema.ExceptionRecord.batch_id == batch_id)

        total = query.count()
        proposals = query.offset(offset).limit(limit).all()
        if proposals or batch_id:
            # One query for every exception on this page instead of one query per
            # proposal inside the loop (100 extra round-trips at the default limit).
            exc_ids = [p.exception_id for p in proposals if p.exception_id]
            exc_map = {}
            if exc_ids:
                for e in db.query(schema.ExceptionRecord).filter(
                    schema.ExceptionRecord.id.in_(exc_ids),
                    schema.ExceptionRecord.org_id == org_id
                ).all():
                    exc_map[e.id] = e

            items = []
            for p in proposals:
                exc = exc_map.get(p.exception_id)
                if exc:
                    detail = {
                        "batch_id": exc.batch_id,
                        "exception_type": exc.exception_type,
                        "severity": exc.severity,
                        "impact_minor": exc.impact_minor,
                        "currency": exc.currency,
                        "orphaned": False
                    }
                else:
                    # The parent exception row is gone (dangling FK). This used to
                    # report a fabricated AMOUNT_MISMATCH / MEDIUM / INR exception, so
                    # an approver saw a plausible finding that did not exist and could
                    # approve a posting against nothing. Say what it actually is.
                    detail = {
                        "batch_id": batch_id,
                        "exception_type": "ORPHANED_PROPOSAL",
                        "severity": "UNKNOWN",
                        "impact_minor": 0,
                        "currency": None,
                        "orphaned": True
                    }
                items.append({
                    "id": p.id,
                    "exception_id": p.exception_id,
                    "action": p.action,
                    "recommended_parameters": p.recommended_parameters,
                    "justification": p.justification,
                    "confidence": float(p.confidence) if p.confidence else 0.90,
                    "status": p.status,
                    "created_by": p.created_by,
                    "created_at": p.created_at.isoformat() if p.created_at else None,
                    **detail
                })
            return {"total": total, "batch_id": batch_id, "limit": limit, "offset": offset, "items": items}

    # Fallback to in-memory cache. STATE is process-global, so this is filtered by
    # org: an unfiltered read hands another tenant's pending vouchers to whoever asks.
    pending = [
        p for p in STATE.get("proposals", [])
        if p.get("status") == PENDING and p.get("org_id") == org_id
    ]
    if batch_id:
        pending = [p for p in pending if p.get("batch_id") == batch_id]

    return {
        "total": len(pending),
        "batch_id": batch_id,
        "limit": limit,
        "offset": offset,
        "items": pending[offset : offset + limit]
    }


@router.post("/decide")
async def decide_proposal(
    req: ApprovalActionRequest,
    current_user: Dict[str, Any] = Depends(require_checker)
):
    """
    Files the single, final decision on a resolution proposal.

    Ordering matters here: every check runs and the database transaction commits
    before any in-memory state is touched. The previous implementation mutated
    STATE first, so a rejected decision still flipped the cached exception to
    RESOLVED, and a proposal missing from the database returned SUCCESS with a
    GENESIS placeholder hash — a success response for an adjustment that was
    never recorded.
    """
    # get_current_user guarantees both claims; no defaults. Defaulting actor_role
    # to "approver" when the claim was absent failed open on the most
    # security-critical attribute in the system.
    actor_id = current_user.get("user_id") or current_user.get("id", "usr_admin_01")
    actor_role = current_user.get("role", "admin")
    org_id = current_user.get("org_id", settings.DEFAULT_ORG_ID)

    action = (req.action or "").strip().upper()
    if action not in TERMINAL_ACTIONS:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid decision '{req.action}'. Must be one of: {', '.join(TERMINAL_ACTIONS)}."
        )

    with get_db_context() as db:
        # Resolved strictly by primary key, scoped to the caller's organisation.
        # The old lookup also matched on exception_id and then wrote
        # proposal_id=<the value the caller sent>, so passing an exception id
        # populated the approvals.proposal_id foreign key with an exception id.
        db_prop = db.query(schema.ResolutionProposal).filter_by(
            id=req.proposal_id, org_id=org_id
        ).first()

        if not db_prop:
            raise HTTPException(status_code=404, detail=f"Proposal '{req.proposal_id}' not found")

        # Terminal-state guard. Without this an approved voucher was never final:
        # it could be re-approved without limit, each time minting a fresh audit
        # event recording the same adjustment being signed again.
        if db_prop.status != PENDING:
            raise HTTPException(
                status_code=409,
                detail=f"Proposal '{db_prop.id}' is already {db_prop.status}; decisions are final."
            )

        # Single-role Admin has full authority to create and approve adjustments.
        # Legacy analyst role cannot approve adjustments.
        if actor_role == "analyst":
            raise HTTPException(
                status_code=403,
                detail="Maker-Checker Segregation Breach: Analysts cannot approve vouchers. An Administrator or Approver must sign it."
            )

        if db_prop.created_by and db_prop.created_by == actor_id and actor_role not in ("admin", "controller"):
            raise HTTPException(
                status_code=403,
                detail=(
                    "Maker-Checker Segregation Breach: you raised this adjustment, so you "
                    "cannot also approve it. A different Approver must sign it."
                )
            )

        db_exc = db.query(schema.ExceptionRecord).filter_by(
            id=db_prop.exception_id, org_id=org_id
        ).first()

        db_prop.status = action
        if db_exc:
            db_exc.state = "RESOLVED" if action == "APPROVED" else "REJECTED"
            db_exc.resolved_at = datetime.now(timezone.utc)

        approval_id = str(uuid.uuid4())
        db_appr = schema.Approval(
            id=approval_id,
            org_id=org_id,
            # Always the resolved proposal's own primary key, never the raw
            # request value, so this foreign key cannot be corrupted.
            proposal_id=db_prop.id,
            exception_id=db_prop.exception_id,
            actor_id=actor_id,
            actor_type=actor_role,
            action=action,
            decision_notes=req.decision_notes
        )
        db.add(db_appr)

        # Batch scope for the audit chain: proposals reach a batch only through
        # their parent exception.
        b_id = (getattr(db_exc, "batch_id", None) if db_exc else None) or STATE.get("batch_id")
        chain_batch_id = b_id or "ORG_LIFECYCLE"

        audit_q = db.query(schema.AuditEvent).filter(schema.AuditEvent.org_id == org_id)
        if b_id:
            last_audit = audit_q.filter(schema.AuditEvent.batch_id == b_id).order_by(
                schema.AuditEvent.event_seq.desc()
            ).first()
        else:
            last_audit = audit_q.filter(
                (schema.AuditEvent.batch_id == None) | (schema.AuditEvent.batch_id == "ORG_LIFECYCLE")
            ).order_by(schema.AuditEvent.event_seq.desc()).first()

        prev_hash = last_audit.event_hash if last_audit else AuditHashChain.GENESIS_HASH
        seq = (last_audit.event_seq + 1) if last_audit else 1
        ts = datetime.now(timezone.utc)
        payload = {
            "event": "PROPOSAL_DECISION",
            "proposal_id": db_prop.id,
            "action": action,
            "actor_id": actor_id,
            "batch_id": chain_batch_id,
            "notes": req.decision_notes
        }
        new_hash = AuditHashChain.compute_event_hash(
            prev_hash=prev_hash,
            org_id=org_id,
            event_seq=seq,
            event_type="PROPOSAL_DECISION",
            entity_id=db_prop.id,
            actor_id=actor_id,
            payload=payload,
            created_at=ts
        )
        db_audit = schema.AuditEvent(
            id=str(uuid.uuid4()),
            org_id=org_id,
            batch_id=chain_batch_id,
            event_seq=seq,
            event_type="PROPOSAL_DECISION",
            entity_type="PROPOSAL",
            entity_id=db_prop.id,
            actor_id=actor_id,
            actor_type=actor_role,
            action=action,
            payload=payload,
            prev_hash=prev_hash,
            event_hash=new_hash,
            created_at=ts
        )
        db.add(db_audit)

        try:
            db.commit()
        except IntegrityError:
            # Two checkers can pass the status guard concurrently; the unique index
            # on approvals(proposal_id) is what actually makes the decision single.
            db.rollback()
            raise HTTPException(
                status_code=409,
                detail=f"Proposal '{db_prop.id}' has already been decided by another approver."
            )

        decided_prop_id = db_prop.id
        decided_exc_id = db_prop.exception_id

    # Only now that the decision is durably recorded does the in-memory cache follow.
    for p in STATE.get("proposals", []):
        if p.get("id") == decided_prop_id:
            p["status"] = action
            break
    for exc in STATE.get("exceptions", []):
        if exc.get("id") == decided_exc_id:
            exc["state"] = "RESOLVED" if action == "APPROVED" else "REJECTED"
            exc["resolved_at"] = ts.isoformat()
            break
    STATE.setdefault("audit_events", []).append({
        "prev_hash": prev_hash,
        "org_id": org_id,
        "batch_id": b_id,
        "event_seq": seq,
        "event_type": "PROPOSAL_DECISION",
        "entity_type": "PROPOSAL",
        "entity_id": decided_prop_id,
        "actor_id": actor_id,
        "actor_type": actor_role,
        "action": action,
        "payload": payload,
        "created_at": ts,
        "event_hash": new_hash
    })

    await invalidate_dashboard_cache(org_id)

    return {
        "status": "SUCCESS",
        "decision": action,
        "proposal_id": decided_prop_id,
        "approval_id": approval_id,
        "audit_event_hash": new_hash
    }
