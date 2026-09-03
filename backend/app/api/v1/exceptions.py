from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from app.api.v1.batches import STATE
from app.core.config import settings
from app.core.security import get_current_user
from app.db.database import get_db_context
from app.db import schema
from app.services.agent_runtime import AIAgentRuntime

router = APIRouter(prefix="/exceptions", tags=["Exception Center"])

@router.get("/")
def get_exceptions(
    batch_id: Optional[str] = None,
    all_batches: bool = False,
    severity: Optional[str] = None,
    exception_type: Optional[str] = None,
    state: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    # Fail closed: get_current_user always supplies org_id, and defaulting to
    # DEFAULT_ORG_ID would silently serve org #1's exceptions on any future change
    # to the dependency.
    org_id = current_user["org_id"]
    with get_db_context() as db:
        # Without a batch scope this returned every exception the org had ever
        # produced (thousands across all historical runs) while the dashboard
        # cards showed only the current batch, so the queue and the KPIs
        # disagreed. Default to the most recent batch; all_batches=true opts into
        # the full history.
        target_batch = batch_id
        if not target_batch and not all_batches:
            latest = (
                db.query(schema.Batch.id)
                .filter(schema.Batch.org_id == org_id)
                .order_by(schema.Batch.created_at.desc())
                .first()
            )
            target_batch = latest[0] if latest else None

        query = db.query(schema.ExceptionRecord).filter(schema.ExceptionRecord.org_id == org_id)
        if target_batch:
            query = query.filter(schema.ExceptionRecord.batch_id == target_batch)
        if severity:
            query = query.filter(schema.ExceptionRecord.severity == severity)
        if exception_type:
            query = query.filter(schema.ExceptionRecord.exception_type == exception_type)
        if state:
            s_up = state.upper()
            if s_up in ("UNRESOLVED", "HELD", "OPEN", "PENDING"):
                query = query.filter(schema.ExceptionRecord.state.notin_(["RESOLVED", "APPROVED", "REJECTED"]))
            else:
                query = query.filter(schema.ExceptionRecord.state == state)

        total = query.count()
        db_items = query.order_by(schema.ExceptionRecord.detected_at.desc()).offset(offset).limit(limit).all()

        if db_items or target_batch is not None or all_batches:
            items = []
            exc_ids = [e.id for e in db_items]
            prop_map = {}
            if exc_ids:
                for p in db.query(schema.ResolutionProposal).filter(
                    schema.ResolutionProposal.exception_id.in_(exc_ids),
                    schema.ResolutionProposal.org_id == org_id
                ).all():
                    prop_map[p.exception_id] = p

            for e in db_items:
                prop = prop_map.get(e.id)
                items.append({
                    "id": e.id,
                    "batch_id": e.batch_id,
                    "proposal_id": prop.id if prop else None,
                    "proposal_action": prop.action if prop else None,
                    "proposal_status": prop.status if prop else None,
                    "primary_txn_id": e.primary_txn_id,
                    "counterpart_txn_id": e.counterpart_txn_id,
                    "exception_type": e.exception_type,
                    "severity": e.severity,
                    "state": e.state,
                    "impact_minor": e.impact_minor,
                    "currency": e.currency,
                    "detected_at": e.detected_at.isoformat() if e.detected_at else None,
                    "resolved_at": e.resolved_at.isoformat() if e.resolved_at else None
                })
            return {"total": total, "batch_id": target_batch or batch_id, "limit": limit, "offset": offset, "items": items}

    # Fallback to in-memory state. STATE is process-global and shared across
    # tenants, so it must be filtered to the caller's organisation.
    exceptions = [e for e in STATE.get("exceptions", []) if e.get("org_id") == org_id]
    proposals = [p for p in STATE.get("proposals", []) if p.get("org_id") == org_id]
    target_batch = batch_id
    if not target_batch and not all_batches:
        active_b = STATE.get("active_batch")
        if active_b and active_b.get("org_id") == org_id:
            target_batch = active_b.get("id")
    if target_batch:
        exceptions = [e for e in exceptions if e.get("batch_id") == target_batch]
        proposals = [p for p in proposals if p.get("batch_id") == target_batch]
    if severity:
        exceptions = [e for e in exceptions if e.get("severity") == severity]
    if exception_type:
        exceptions = [e for e in exceptions if e.get("exception_type") == exception_type]
    if state:
        s_up = state.upper()
        if s_up in ("UNRESOLVED", "HELD", "OPEN", "PENDING"):
            exceptions = [e for e in exceptions if e.get("state") not in ("RESOLVED", "APPROVED", "REJECTED")]
        else:
            exceptions = [e for e in exceptions if e.get("state") == state]

    enriched_items = []
    for e in exceptions[offset : offset + limit]:
        item_copy = dict(e)
        matching_prop = next((p for p in proposals if p.get("exception_id") == e.get("id")), None)
        if matching_prop:
            item_copy.setdefault("proposal_id", matching_prop.get("id"))
            item_copy.setdefault("proposal_action", matching_prop.get("action"))
            item_copy.setdefault("proposal_status", matching_prop.get("status"))
        enriched_items.append(item_copy)

    return {
        "total": len(exceptions),
        "batch_id": target_batch or batch_id,
        "limit": limit,
        "offset": offset,
        "items": enriched_items
    }

from app.core.redis import key_ai_investigation, get_cached_json, set_cached_json
import hashlib
import json

@router.get("/{exception_id}")
async def get_exception_detail(
    exception_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    org_id = current_user["org_id"]
    # Check in-memory first for dynamic proposals
    exceptions = [e for e in STATE.get("exceptions", []) if e.get("org_id") == org_id]
    target = next((e for e in exceptions if e.get("id") == exception_id), None)

    with get_db_context() as db:
        db_exc = db.query(schema.ExceptionRecord).filter_by(id=exception_id, org_id=org_id).first()
        if db_exc:
            target = {
                "id": db_exc.id,
                "batch_id": db_exc.batch_id,
                "primary_txn_id": db_exc.primary_txn_id,
                "counterpart_txn_id": db_exc.counterpart_txn_id,
                "exception_type": db_exc.exception_type,
                "severity": db_exc.severity,
                "state": db_exc.state,
                "impact_minor": db_exc.impact_minor,
                "currency": db_exc.currency
            }
            db_prop = db.query(schema.ResolutionProposal).filter_by(exception_id=exception_id, org_id=org_id).first()
            proposal = {
                "id": db_prop.id,
                "exception_id": db_prop.exception_id,
                "action": db_prop.action,
                "recommended_parameters": db_prop.recommended_parameters,
                "justification": db_prop.justification,
                "confidence": float(db_prop.confidence) if db_prop.confidence else 0.90,
                "status": db_prop.status
            } if db_prop else None

            # On-demand deep AI investigation with Redis caching
            txns = [t for t in STATE.get("transactions", []) if t.get("org_id") == org_id]
            txn_map = {t["id"]: t for t in txns if "id" in t}
            p_txn = txn_map.get(db_exc.primary_txn_id) if db_exc.primary_txn_id else None
            c_txn = txn_map.get(db_exc.counterpart_txn_id) if db_exc.counterpart_txn_id else None

            # Generate stable normalized hash for AI caching
            cache_payload = {
                "type": db_exc.exception_type,
                "impact": db_exc.impact_minor,
                "p_ext": p_txn.get("external_id") if p_txn else None,
                "p_amt": p_txn.get("amount_minor") if p_txn else None,
                "c_ext": c_txn.get("external_id") if c_txn else None,
                "c_amt": c_txn.get("amount_minor") if c_txn else None
            }
            payload_hash = hashlib.sha256(json.dumps(cache_payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:16]
            cache_key = key_ai_investigation(db_exc.exception_type, db_exc.impact_minor, payload_hash)

            # Check Redis AI Cache
            cached_inv = await get_cached_json(cache_key)
            if cached_inv:
                target["investigation"] = cached_inv
                target["investigation_source"] = "redis_cache"
            else:
                agent = AIAgentRuntime()
                deep_inv = agent.investigate_exception(
                    exception_id=exception_id,
                    exception_type=db_exc.exception_type,
                    impact_minor=db_exc.impact_minor,
                    primary_txn=p_txn,
                    counterpart_txn=c_txn,
                    available_txns=txns
                )
                inv_data = deep_inv.model_dump()
                target["investigation"] = inv_data
                target["investigation_source"] = "live_investigation"
                # Cache validated AI proposal for 24 hours (TTL: 86400s)
                await set_cached_json(cache_key, inv_data, ttl_sec=86400)

            return {
                "exception": target,
                "proposal": proposal
            }

    if target:
        proposals = [
            p for p in STATE.get("proposals", [])
            if p.get("exception_id") == exception_id and p.get("org_id") == org_id
        ]
        return {
            "exception": target,
            "proposal": proposals[0] if proposals else None
        }

    raise HTTPException(status_code=404, detail="Exception not found")
