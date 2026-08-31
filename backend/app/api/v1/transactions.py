from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from app.api.v1.batches import STATE
from app.core.config import settings
from app.core.security import get_current_user
from app.db.database import get_db_context
from app.db import schema

router = APIRouter(prefix="/transactions", tags=["Transactions & Matches"])


def _org_txns(org_id: str) -> List[Dict[str, Any]]:
    """
    In-memory transactions belonging to one organisation.

    STATE is a single process-global dict shared by every tenant, so reading it
    unfiltered would return another organisation's ledger.
    """
    return [t for t in STATE.get("transactions", []) if t.get("org_id") == org_id]


@router.get("/")
def get_transactions(
    batch_id: Optional[str] = None,
    all_batches: bool = False,
    source_kind: Optional[str] = None,
    match_status: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    current_user: Any = Depends(get_current_user)
):
    # Fail closed: get_current_user always supplies org_id, so defaulting to
    # DEFAULT_ORG_ID only serves to leak org #1's ledger if the dependency changes.
    org_id = current_user["org_id"]
    with get_db_context() as db:
        # Like /exceptions/, this returned the org's entire transaction history
        # (989 rows across every historical run) while the dashboard cards
        # described the current batch only, so the results table and the KPIs
        # disagreed. Default to the latest batch; all_batches=true opts into all.
        target_batch = batch_id
        if not target_batch and not all_batches:
            latest = (
                db.query(schema.Batch.id)
                .filter(schema.Batch.org_id == org_id)
                .order_by(schema.Batch.created_at.desc())
                .first()
            )
            target_batch = latest[0] if latest else None

        query = db.query(schema.Transaction).filter(schema.Transaction.org_id == org_id)
        if target_batch:
            query = query.filter(schema.Transaction.batch_id == target_batch)
        if source_kind:
            query = query.filter(schema.Transaction.source_kind == source_kind)
        if match_status:
            query = query.filter(schema.Transaction.match_status == match_status)
        if search:
            search_clean = f"%{search}%"
            query = query.filter(
                (schema.Transaction.external_id.ilike(search_clean)) |
                (schema.Transaction.description_raw.ilike(search_clean))
            )

        total = query.count()
        db_items = query.order_by(schema.Transaction.occurred_at.desc()).offset(offset).limit(limit).all()

        if db_items:
            items = []
            for t in db_items:
                items.append({
                    "id": t.id,
                    "batch_id": t.batch_id,
                    "source_kind": t.source_kind,
                    "external_id": t.external_id,
                    "txn_type": t.txn_type,
                    "direction": t.direction,
                    "amount_minor": t.amount_minor,
                    "gross_minor": t.gross_minor,
                    "fee_minor": t.fee_minor,
                    "tax_minor": t.tax_minor,
                    "currency": t.currency,
                    "occurred_at": t.occurred_at.isoformat() if t.occurred_at else None,
                    "value_date": t.value_date.isoformat() if t.value_date else None,
                    "counterparty_raw": t.counterparty_raw,
                    "counterparty_norm": t.counterparty_norm,
                    "description_raw": t.description_raw,
                    "description_norm": t.description_norm,
                    "reference_keys": t.reference_keys or {},
                    "account_code": t.account_code,
                    "match_status": t.match_status
                })
            return {"total": total, "batch_id": batch_id, "limit": limit, "offset": offset, "items": items}

    # Fallback to in-memory state
    txns = _org_txns(org_id)
    if batch_id:
        txns = [t for t in txns if t.get("batch_id") == batch_id]
    if source_kind:
        txns = [t for t in txns if t.get("source_kind") == source_kind]
    if match_status:
        txns = [t for t in txns if t.get("match_status") == match_status]
    if search:
        s_lower = search.lower()
        txns = [t for t in txns if s_lower in str(t.get("external_id", "")).lower() or s_lower in str(t.get("description_raw", "")).lower()]

    return {
        "total": len(txns),
        "batch_id": batch_id,
        "limit": limit,
        "offset": offset,
        "items": txns[offset : offset + limit]
    }

@router.get("/matches")
def get_matches(
    batch_id: Optional[str] = None,
    all_batches: bool = False,
    limit: int = 50,
    offset: int = 0,
    current_user: Any = Depends(get_current_user)
):
    org_id = current_user["org_id"]
    with get_db_context() as db:
        # Same batch scoping as /transactions/ and /exceptions/ so the match list
        # describes the run the rest of the dashboard is showing.
        target_batch = batch_id
        if not target_batch and not all_batches:
            latest = (
                db.query(schema.Batch.id)
                .filter(schema.Batch.org_id == org_id)
                .order_by(schema.Batch.created_at.desc())
                .first()
            )
            target_batch = latest[0] if latest else None

        org_matches = db.query(schema.Match).filter(schema.Match.org_id == org_id)
        if target_batch:
            org_matches = org_matches.filter(schema.Match.batch_id == target_batch)
        matches = org_matches.offset(offset).limit(limit).all()
        if matches:
            items = []
            for m in matches:
                legs = db.query(schema.MatchLeg).filter_by(match_id=m.id).all()
                items.append({
                    "id": m.id,
                    "batch_id": m.batch_id,
                    "match_type": m.match_type,
                    "method": m.method,
                    "score": float(m.score) if m.score else 1.0,
                    "confidence": float(m.confidence) if m.confidence else 1.0,
                    "status": m.status,
                    "legs": [
                        {
                            "id": leg.id,
                            "transaction_id": leg.transaction_id,
                            "role": leg.role,
                            "signed_amount_minor": leg.signed_amount_minor
                        }
                        for leg in legs
                    ]
                })
            return {"total": org_matches.count(), "limit": limit, "offset": offset, "items": items}

    matches = [m for m in STATE.get("matches", []) if m.get("org_id") == org_id]
    return {
        "total": len(matches),
        "limit": limit,
        "offset": offset,
        "items": matches[offset : offset + limit]
    }

@router.get("/{transaction_id}/context")
def get_transaction_context(
    transaction_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    org_id = current_user["org_id"]
    txns = _org_txns(org_id)
    # 1. Exact ID match
    target = next((t for t in txns if t.get("id") == transaction_id), None)
    
    # 2. Prefix ID match
    if not target and len(transaction_id) >= 4:
        target = next((t for t in txns if t.get("id", "").startswith(transaction_id)), None)
        
    # 3. Exception ID resolution (e.g. EXC-1234abcd)
    if not target and transaction_id.startswith("EXC-"):
        exc_sub = transaction_id[4:]
        excs = [e for e in STATE.get("exceptions", []) if e.get("org_id") == org_id]
        matched_exc = next((e for e in excs if e.get("id") == transaction_id or e.get("id", "").endswith(exc_sub)), None)
        if matched_exc and matched_exc.get("primary_txn_id"):
            target = next((t for t in txns if t.get("id") == matched_exc["primary_txn_id"]), None)
        if not target:
            target = next((t for t in txns if t.get("id", "").startswith(exc_sub)), None)

    # 4. External ID match
    if not target:
        target = next((t for t in txns if t.get("external_id") == transaction_id or t.get("external_id", "").upper() == transaction_id.upper()), None)

    # 5. Database lookup fallback
    if not target:
        with get_db_context() as db:
            db_t = db.query(schema.Transaction).filter(
                schema.Transaction.org_id == org_id,
                (schema.Transaction.id == transaction_id) |
                (schema.Transaction.external_id == transaction_id)
            ).first()
            if db_t:
                target = {
                    "id": db_t.id,
                    # org_id is required by CanonicalTransaction below; omitting
                    # it made this fallback path raise a validation error.
                    "org_id": db_t.org_id,
                    "batch_id": db_t.batch_id,
                    "source_kind": db_t.source_kind,
                    "external_id": db_t.external_id,
                    "txn_type": db_t.txn_type,
                    "direction": db_t.direction,
                    "amount_minor": db_t.amount_minor,
                    "gross_minor": db_t.gross_minor,
                    "fee_minor": db_t.fee_minor,
                    "tax_minor": db_t.tax_minor,
                    "currency": db_t.currency,
                    "occurred_at": db_t.occurred_at.isoformat() if db_t.occurred_at else None,
                    "value_date": db_t.value_date.isoformat() if db_t.value_date else None,
                    "counterparty_raw": db_t.counterparty_raw,
                    "counterparty_norm": db_t.counterparty_norm,
                    "description_raw": db_t.description_raw,
                    "description_norm": db_t.description_norm,
                    "reference_keys": db_t.reference_keys or {},
                    "account_code": db_t.account_code,
                    "match_status": db_t.match_status
                }

    if not target:
        raise HTTPException(status_code=404, detail=f"Transaction {transaction_id} not found")

    from app.models.schemas import CanonicalTransaction
    from app.services.context_builder import TransactionContextBuilder

    target_obj = CanonicalTransaction(**target)
    all_objs = [CanonicalTransaction(**t) for t in txns] if txns else [target_obj]
    ctx = TransactionContextBuilder.build_context(target_obj, all_objs)
    actual_txn_id = target.get("id")
    decision = STATE.get("decisions", {}).get(actual_txn_id)

    # If linked to an exception, attach the exception details
    exc_obj = next(
        (
            e for e in STATE.get("exceptions", [])
            if e.get("org_id") == org_id
            and (e.get("primary_txn_id") == actual_txn_id or e.get("id") == f"EXC-{actual_txn_id[:8]}")
        ),
        None
    )

    return {
        "transaction": target,
        "context": ctx.model_dump(),
        "decision": decision,
        "exception": exc_obj
    }
