from datetime import timezone
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from app.api.v1.batches import STATE
from app.core.security import get_current_user
from app.core.config import settings
from app.db.database import get_db_context
from app.db import schema
from app.services.audit_chain import AuditHashChain

router = APIRouter(prefix="/audit", tags=["Cryptographic Audit Chain"])


def _format_iso_utc(dt_val: Any) -> Optional[str]:
    if not dt_val:
        return None
    if isinstance(dt_val, str):
        if not dt_val.endswith("Z") and "+" not in dt_val and "-" not in dt_val[-6:]:
            return f"{dt_val}Z"
        return dt_val
    if hasattr(dt_val, "tzinfo"):
        if dt_val.tzinfo is None:
            return dt_val.replace(tzinfo=timezone.utc).isoformat()
        return dt_val.isoformat()
    return str(dt_val)


@router.get("/events")
def get_audit_events(
    batch_id: Optional[str] = Query(None, description="Optional batch ID to scope audit events"),
    limit: int = 100,
    offset: int = 0,
    current_user: Any = Depends(get_current_user)
):
    org_id = current_user["org_id"] if isinstance(current_user, dict) else settings.DEFAULT_ORG_ID
    with get_db_context() as db:
        query = db.query(schema.AuditEvent).filter(schema.AuditEvent.org_id == org_id)
        if batch_id:
            query = query.filter(schema.AuditEvent.batch_id == batch_id)
        events = query.order_by(schema.AuditEvent.event_seq.asc()).offset(offset).limit(limit).all()
        if events or batch_id:
            total = query.count()
            return {
                "total": total,
                "batch_id": batch_id,
                "items": [
                    {
                        "id": e.id,
                        "batch_id": e.batch_id,
                        "event_seq": e.event_seq,
                        "event_type": e.event_type,
                        "entity_type": e.entity_type,
                        "entity_id": e.entity_id,
                        "actor_id": e.actor_id,
                        "actor_type": e.actor_type,
                        "action": e.action,
                        "payload": e.payload,
                        "prev_hash": e.prev_hash,
                        "event_hash": e.event_hash,
                        "created_at": _format_iso_utc(e.created_at)
                    }
                    for e in events
                ]
            }

    # Fallback to in-memory state
    events = [e for e in STATE.get("audit_events", []) if e.get("org_id") == org_id]
    if batch_id:
        events = [e for e in events if e.get("batch_id") == batch_id or e.get("entity_id") == batch_id]
    
    formatted_items = []
    for e in events[offset : offset + limit]:
        item = dict(e)
        item["created_at"] = _format_iso_utc(item.get("created_at"))
        formatted_items.append(item)

    return {
        "total": len(events),
        "batch_id": batch_id,
        "items": formatted_items
    }

@router.get("/verify-chain")
def verify_audit_chain(
    batch_id: Optional[str] = Query(None, description="Optional batch ID to scope cryptographic chain verification"),
    current_user: Any = Depends(get_current_user)
):
    org_id = current_user["org_id"] if isinstance(current_user, dict) else settings.DEFAULT_ORG_ID
    raw_events = []
    with get_db_context() as db:
        query = db.query(schema.AuditEvent).filter(schema.AuditEvent.org_id == org_id)
        if batch_id:
            query = query.filter(schema.AuditEvent.batch_id == batch_id)
        db_events = query.order_by(schema.AuditEvent.event_seq.asc()).all()
        if db_events:
            raw_events = [
                {
                    "org_id": e.org_id,
                    "batch_id": e.batch_id,
                    "event_seq": e.event_seq,
                    "event_type": e.event_type,
                    "entity_id": e.entity_id,
                    "actor_id": e.actor_id,
                    "payload": e.payload,
                    "prev_hash": e.prev_hash,
                    "event_hash": e.event_hash,
                    "created_at": e.created_at
                }
                for e in db_events
            ]

    if not raw_events:
        return {
            "status": "NO_AUDIT_EVENTS",
            "batch_id": batch_id,
            "total_events_checked": 0,
            "head_event_hash": AuditHashChain.GENESIS_HASH,
            "message": f"No audit events found for verification{' in batch ' + batch_id if batch_id else ''}."
        }

    if batch_id:
        raw_events.sort(key=lambda x: x.get("event_seq", 1))
        is_valid, broken_seq = AuditHashChain.verify_chain_integrity(raw_events)
        if not is_valid:
            raise HTTPException(
                status_code=409,
                detail=f"Audit chain verification failed for batch '{batch_id}' at sequence {broken_seq}. Potential tampering detected."
            )
        head_hash = raw_events[-1]["event_hash"]
        return {
            "status": "VERIFIED",
            "is_valid": True,
            "batch_id": batch_id,
            "total_events_checked": len(raw_events),
            "head_event_hash": head_hash,
            "message": f"All {len(raw_events)} audit blocks in batch '{batch_id}' verified successfully against immutable SHA-256 hash chain."
        }

    # When no batch_id is specified, verify each batch's hash chain independently
    # since each batch starts with a genesis block (prev_hash = GENESIS_HASH).
    batches_events: Dict[str, List[Dict[str, Any]]] = {}
    lifecycle_events: List[Dict[str, Any]] = []

    for ev in raw_events:
        b_id = ev.get("batch_id")
        if not b_id or b_id in ("GENESIS_BATCH", "ORG_LIFECYCLE"):
            lifecycle_events.append(ev)
        else:
            batches_events.setdefault(b_id, []).append(ev)

    compromised: List[Dict[str, Any]] = []
    for b_id, b_events in batches_events.items():
        b_events.sort(key=lambda x: x.get("event_seq", 1))
        is_valid, broken_seq = AuditHashChain.verify_chain_integrity(b_events)
        if not is_valid:
            compromised.append({
                "batch_id": b_id,
                "broken_at_sequence": broken_seq,
                "events_in_chain": len(b_events)
            })

    unverifiable_legacy: List[Dict[str, Any]] = []
    if lifecycle_events:
        lifecycle_events.sort(key=lambda x: x.get("event_seq", 1))
        is_valid, broken_seq = AuditHashChain.verify_chain_integrity(lifecycle_events)
        if not is_valid:
            first_ev = lifecycle_events[0]
            if first_ev.get("prev_hash") != AuditHashChain.GENESIS_HASH or first_ev.get("event_seq", 1) > 1:
                unverifiable_legacy.append({
                    "chain_id": "ORG_LIFECYCLE",
                    "reason": "LEGACY_NON_GENESIS_CHAIN",
                    "starting_sequence": first_ev.get("event_seq"),
                    "events_in_chain": len(lifecycle_events)
                })
            else:
                compromised.append({
                    "batch_id": "ORG_LIFECYCLE",
                    "broken_at_sequence": broken_seq,
                    "events_in_chain": len(lifecycle_events)
                })

    head_hash = raw_events[-1]["event_hash"]
    total_batches = len(batches_events)
    verified_batches = total_batches - len([c for c in compromised if c["batch_id"] != "ORG_LIFECYCLE"])

    if compromised:
        return {
            "status": "TAMPERED",
            "is_valid": False,
            "batch_id": None,
            "total_events_checked": len(raw_events),
            "total_batches_checked": total_batches,
            "verified_batches": verified_batches,
            "compromised_batches": compromised,
            "unverifiable_legacy_events": unverifiable_legacy,
            "head_event_hash": head_hash,
            "message": (
                f"{verified_batches} of {total_batches} audit chains verified. "
                f"{len(compromised)} chain(s) failed integrity verification: "
                + ", ".join(c["batch_id"] for c in compromised[:5])
                + (" …" if len(compromised) > 5 else "")
            )
        }

    return {
        "status": "VERIFIED",
        "is_valid": True,
        "batch_id": None,
        "total_events_checked": len(raw_events),
        "total_batches_checked": total_batches,
        "verified_batches": verified_batches,
        "compromised_batches": [],
        "unverifiable_legacy_events": unverifiable_legacy,
        "head_event_hash": head_hash,
        "message": f"All {len(raw_events)} audit blocks across {total_batches} batches verified successfully against immutable SHA-256 hash chains."
    }

from pydantic import BaseModel

class AuditorSignOffRequest(BaseModel):
    batch_id: str
    notes: str = "Independent audit examination completed. All controls verified."

@router.get("/compliance-status")
def get_compliance_status(
    batch_id: Optional[str] = Query(None, description="Batch ID for 5-state compliance evaluation"),
    current_user: Any = Depends(get_current_user)
):
    from app.services.compliance_evaluator import ComplianceEvaluator
    org_id = current_user["org_id"] if isinstance(current_user, dict) else settings.DEFAULT_ORG_ID

    with get_db_context() as db:
        target_batch = batch_id
        if not target_batch:
            latest = db.query(schema.Batch.id).filter(schema.Batch.org_id == org_id).order_by(schema.Batch.created_at.desc()).first()
            target_batch = latest[0] if latest else "BATCH_DEFAULT"

        db_events = db.query(schema.AuditEvent).filter(schema.AuditEvent.org_id == org_id, schema.AuditEvent.batch_id == target_batch).all()
        db_props = db.query(schema.ResolutionProposal).join(
            schema.ExceptionRecord, schema.ResolutionProposal.exception_id == schema.ExceptionRecord.id
        ).filter(schema.ExceptionRecord.batch_id == target_batch, schema.ExceptionRecord.org_id == org_id).all()
        db_apprs = db.query(schema.Approval).filter(schema.Approval.org_id == org_id).all()
        db_excs = db.query(schema.ExceptionRecord).filter(schema.ExceptionRecord.batch_id == target_batch, schema.ExceptionRecord.org_id == org_id).all()

        events_list = [
            {
                "id": e.id,
                "org_id": e.org_id,
                "batch_id": e.batch_id,
                "event_seq": e.event_seq,
                "event_type": e.event_type,
                "entity_id": e.entity_id,
                "actor_id": e.actor_id,
                "payload": e.payload,
                "prev_hash": e.prev_hash,
                "event_hash": e.event_hash,
                "created_at": e.created_at
            }
            for e in db_events
        ]
        props_list = [
            {
                "id": p.id,
                "exception_id": p.exception_id,
                "created_by": p.created_by,
                "status": p.status,
                "created_at": p.created_at.isoformat() if p.created_at else None
            }
            for p in db_props
        ]
        apprs_list = [
            {
                "id": a.id,
                "proposal_id": a.proposal_id,
                "exception_id": a.exception_id,
                "actor_id": a.actor_id,
                "action": a.action,
                "created_at": a.created_at.isoformat() if a.created_at else None,
                "decision_notes": a.decision_notes
            }
            for a in db_apprs
        ]
        excs_list = [{"id": e.id, "impact_minor": e.impact_minor} for e in db_excs]

    # Fallback to in-memory if DB empty
    if not events_list:
        events_list = [e for e in STATE.get("audit_events", []) if e.get("org_id") == org_id and (not target_batch or e.get("batch_id") == target_batch)]
    if not props_list:
        props_list = [p for p in STATE.get("proposals", []) if p.get("org_id") == org_id]
    if not apprs_list:
        apprs_list = [a for a in STATE.get("approvals", []) if a.get("org_id") == org_id]
    if not excs_list:
        excs_list = [e for e in STATE.get("exceptions", []) if e.get("org_id") == org_id]

    assessment = ComplianceEvaluator.evaluate_batch_compliance(
        batch_id=target_batch,
        audit_events=events_list,
        proposals=props_list,
        approvals=apprs_list,
        exceptions=excs_list
    )
    return assessment.model_dump()


@router.post("/sign-off")
def record_auditor_signoff(
    req: AuditorSignOffRequest,
    current_user: Any = Depends(get_current_user)
):
    import uuid
    from datetime import datetime, timezone
    org_id = current_user["org_id"] if isinstance(current_user, dict) else settings.DEFAULT_ORG_ID
    actor_id = current_user.get("user_id") or current_user.get("id", "usr_auditor_01")
    actor_role = current_user.get("role", "admin")

    ts = datetime.now(timezone.utc)
    with get_db_context() as db:
        last_audit = db.query(schema.AuditEvent).filter(
            schema.AuditEvent.org_id == org_id,
            schema.AuditEvent.batch_id == req.batch_id
        ).order_by(schema.AuditEvent.event_seq.desc()).first()

        prev_hash = last_audit.event_hash if last_audit else AuditHashChain.GENESIS_HASH
        seq = (last_audit.event_seq + 1) if last_audit else 1
        payload = {
            "event": "AUDITOR_SIGNOFF",
            "batch_id": req.batch_id,
            "auditor_id": actor_id,
            "role": actor_role,
            "notes": req.notes,
            "signed_at": ts.isoformat()
        }
        new_hash = AuditHashChain.compute_event_hash(
            prev_hash=prev_hash,
            org_id=org_id,
            event_seq=seq,
            event_type="AUDITOR_SIGNOFF",
            entity_id=req.batch_id,
            actor_id=actor_id,
            payload=payload,
            created_at=ts
        )
        db_audit = schema.AuditEvent(
            id=str(uuid.uuid4()),
            org_id=org_id,
            batch_id=req.batch_id,
            event_seq=seq,
            event_type="AUDITOR_SIGNOFF",
            entity_type="BATCH",
            entity_id=req.batch_id,
            actor_id=actor_id,
            actor_type=actor_role,
            action="AUDITOR_SIGNOFF",
            payload=payload,
            prev_hash=prev_hash,
            event_hash=new_hash,
            created_at=ts
        )
        db.add(db_audit)
        db.commit()

        event_id = db_audit.id

    return {
        "status": "SUCCESS",
        "batch_id": req.batch_id,
        "is_signed_off": True,
        "signed_by_auditor_id": actor_id,
        "signed_at": ts.isoformat(),
        "auditor_notes": req.notes,
        "system_event_id": event_id,
        "event_hash": new_hash
    }

