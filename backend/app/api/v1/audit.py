from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from app.api.v1.batches import STATE
from app.core.security import get_current_user
from app.core.config import settings
from app.db.database import get_db_context
from app.db import schema
from app.services.audit_chain import AuditHashChain

router = APIRouter(prefix="/audit", tags=["Cryptographic Audit Chain"])

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
                        "created_at": e.created_at.isoformat() if e.created_at else None
                    }
                    for e in events
                ]
            }

    # Fallback to in-memory state
    events = [e for e in STATE.get("audit_events", []) if e.get("org_id") == org_id]
    if batch_id:
        events = [e for e in events if e.get("batch_id") == batch_id or e.get("entity_id") == batch_id]
    return {
        "total": len(events),
        "batch_id": batch_id,
        "items": events[offset : offset + limit]
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
    for ev in raw_events:
        b_id = ev.get("batch_id") or "GENESIS_BATCH"
        batches_events.setdefault(b_id, []).append(ev)

    # Report every failing chain instead of raising on the first one. A single
    # legacy batch whose hash was written by an older formula used to 409 the whole
    # endpoint, so the SOX compliance agent reported "FAIL" for organisations whose
    # current batches were all intact and gave no way to tell which batch was at
    # fault. Callers asking about one specific batch still get a hard 409 above.
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

    head_hash = raw_events[-1]["event_hash"]
    verified_batches = len(batches_events) - len(compromised)
    if compromised:
        return {
            "status": "TAMPERED",
            "is_valid": False,
            "batch_id": None,
            "total_events_checked": len(raw_events),
            "total_batches_checked": len(batches_events),
            "verified_batches": verified_batches,
            "compromised_batches": compromised,
            "head_event_hash": head_hash,
            "message": (
                f"{verified_batches} of {len(batches_events)} audit chains verified. "
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
        "total_batches_checked": len(batches_events),
        "verified_batches": verified_batches,
        "compromised_batches": [],
        "head_event_hash": head_hash,
        "message": f"All {len(raw_events)} audit blocks across {len(batches_events)} batches verified successfully against immutable SHA-256 hash chains."
    }
