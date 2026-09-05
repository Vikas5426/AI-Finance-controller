from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends
from sqlalchemy import func
from app.api.v1.batches import STATE
from app.core.config import settings
from app.core.redis import key_dashboard_summary, get_cached_json, set_cached_json
from app.core.security import get_current_user
from app.db.database import get_db_context
from app.db import schema
from app.db.database_service import DatabaseService

router = APIRouter(prefix="/reports", tags=["Reports & Analytics"])

@router.get("/summary")
async def get_executive_summary(
    batch_id: Optional[str] = None,
    current_user: Any = Depends(get_current_user)
):
    # The organisation comes from the verified token, never from a query
    # parameter: ?org_id=<other-tenant> previously returned that tenant's
    # dashboard (and its Redis-cached copy) to anyone who asked.
    if isinstance(current_user, dict) and "org_id" in current_user:
        target_org = current_user["org_id"]
    elif isinstance(batch_id, str) and ("-" in batch_id or len(batch_id) >= 10) and not batch_id.startswith("BATCH"):
        target_org = batch_id
        batch_id = None
    else:
        target_org = getattr(current_user, "org_id", settings.DEFAULT_ORG_ID)

    cache_key = key_dashboard_summary(f"{target_org}:{batch_id}") if batch_id else key_dashboard_summary(target_org)

    # 1. Check Redis Cache
    cached_summary = await get_cached_json(cache_key)
    if cached_summary:
        return cached_summary

    # 2. Rebuild from the database. This used to be computed from the in-memory
    #    STATE dict, so every figure on the executive dashboard reset to zero /
    #    null after a restart even though the batch was fully persisted, and the
    #    QA agent then reported a 0.00% match rate for a completed run.
    ctx = DatabaseService.load_batch_context(target_org, batch_id=batch_id)
    if not ctx["batch"]:
        return {
            "batch": {}, "quality_metrics": {}, "windows": [], "cash_forecast": [],
            "exception_breakdown": {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0},
            "mode": "REAL_USER_DATA",
            "operational_metrics": {
                "is_synthetic_benchmark": False, "total_records": 0, "matched_records": 0,
                "unmatched_records": 0, "matched_pairs": 0, "exceptions_count": 0,
                "manual_review_required": 0, "processing_time_seconds": 0.0,
                "false_positive_safeguards_triggered": 0,
                "confidence_breakdown": {
                    "high_confidence_matches": 0, "medium_confidence_matches": 0,
                    "low_confidence_matches": 0
                },
                "ai_investigations_performed": 0,
            },
        }

    qm = ctx["quality_metrics"]
    total_txns = ctx["stats"]["total_records"]
    matched_count = ctx["batch"]["matched_records"]

    # STATE still holds the only copy of a few in-flight, non-persisted details
    # (per-match confidence, live AI investigations). Use it when it belongs to
    # this organisation and describes this same batch; never otherwise.
    state_active = STATE.get("active_batch") or {}
    state_is_ours = (
        state_active.get("org_id") == target_org
        and state_active.get("id") == ctx["batch_id"]
    )
    matches = [m for m in STATE.get("matches", [])] if state_is_ours else []
    exceptions = [e for e in STATE.get("exceptions", [])] if state_is_ours else []

    def _conf(m: Any) -> float:
        return m.get("confidence", 0) if isinstance(m, dict) else getattr(m, "confidence", 0)

    forecast_segments = ctx["cash_forecast"] or []
    has_future_inflow = any(s.get("confirmed_future_inflows_minor", 0) > 0 for s in forecast_segments)
    has_clearing = any(s.get("probable_inflows_minor", 0) > 0 or s.get("probable_inflow_minor", 0) > 0 for s in forecast_segments)
    obs_cash = sum(s.get("observed_cash_minor", 0) or s.get("confirmed_inflow_minor", 0) for s in forecast_segments[:1])

    if not forecast_segments or (obs_cash == 0 and not has_future_inflow and not has_clearing):
        fc_status = "INSUFFICIENT_DATA"
        fc_missing = "No financial transactions found in the batch to generate liquidity projections."
    elif not has_future_inflow:
        fc_status = "INSUFFICIENT_DATA"
        fc_missing = "Insufficient forward horizon data for weeks 3–13: The uploaded reconciliation batch contains settled transaction records for the current clearing cycle (W1–W2), but contains zero future-dated invoice receivables, scheduled payouts, or explicit recurring revenue assumptions."
    else:
        fc_status = "COMPLETE"
        fc_missing = None

    summary_dict = ctx.get("summary") or {}
    gross_flow_minor = summary_dict.get("gross_flow_minor", ctx["batch"].get("gross_flow_minor", 0))
    total_gross_inr = summary_dict.get("total_gross_inr", round(gross_flow_minor / 100.0, 2))
    gross_flow_vol = summary_dict.get("gross_flow_volume", f"₹{total_gross_inr:,.2f}")
    net_vol = summary_dict.get("net_volume", f"₹{summary_dict.get('net_volume_inr', total_gross_inr):,.2f}")

    resp_payload: Dict[str, Any] = {
        "batch": ctx["batch"],
        "summary": {
            **summary_dict,
            "gross_flow_minor": gross_flow_minor,
            "gross_flow_volume": gross_flow_vol,
            "total_gross_inr": total_gross_inr,
            "net_volume": net_vol,
            "match_rate": ctx["batch"].get("match_rate", 0.0),
        },
        "gross_flow_volume": gross_flow_vol,
        "gross_flow_minor": gross_flow_minor,
        "total_gross_inr": total_gross_inr,
        "net_volume": net_vol,
        "quality_metrics": qm,
        "windows": ctx["windows"],
        "cash_forecast": forecast_segments,
        "forecast_status": fc_status,
        "missing_fields_explanation": fc_missing,
        "liquidity_forecast": {
            "forecast_status": fc_status,
            "missing_fields_explanation": fc_missing,
            "total_observed_cash_minor": obs_cash,
            "total_projected_inflow_minor": sum(s.get("probable_inflows_minor", 0) or s.get("probable_inflow_minor", 0) for s in forecast_segments),
            "segments": forecast_segments
        },
        "exception_breakdown": ctx["exception_breakdown"],
        "mode": "REAL_USER_DATA",
        "operational_metrics": {
            "is_synthetic_benchmark": False,
            "total_records": total_txns,
            "matched_records": matched_count,
            "unmatched_records": max(0, total_txns - matched_count),
            "matched_pairs": qm["exact_matches"] + qm["contextual_matches"],
            "exceptions_count": ctx["stats"]["total_exceptions"],
            "manual_review_required": ctx["stats"]["pending_approvals"],
            "processing_time_seconds": ctx["batch"]["execution_time_sec"],
            "gross_flow_volume": gross_flow_vol,
            "gross_flow_minor": gross_flow_minor,
            "total_gross_inr": total_gross_inr,
            "net_volume": net_vol,
            "false_positive_safeguards_triggered": qm["safeguards_triggered_count"],
            "confidence_breakdown": {
                "high_confidence_matches": len([m for m in matches if _conf(m) >= 0.95]),
                "medium_confidence_matches": len([m for m in matches if 0.80 <= _conf(m) < 0.95]),
                "low_confidence_matches": len([m for m in matches if _conf(m) < 0.80]),
            },
            "ai_investigations_performed": len([
                e for e in exceptions
                if (e.get("investigation") if isinstance(e, dict) else getattr(e, "investigation", None))
            ]) or qm.get("ai_investigated", 0) or ctx["stats"].get("ai_investigations_performed", 0),
        },
    }

    # Cache in Redis for 60 seconds (TTL: 60s)
    await set_cached_json(cache_key, resp_payload, ttl_sec=60)
    return resp_payload
