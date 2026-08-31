"""
Specialized Reasoning Agents API Endpoints
Exposes Agents 9 to 13:
- Agent 9: Exception Investigation Agent
- Agent 10: Root Cause Analysis (RCA) Agent
- Agent 11: Financial Insight Agent
- Agent 12: Audit Explanation Agent
- Agent 13: Report Generation Agent
"""

from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Body
from pydantic import BaseModel

from app.api.v1.batches import STATE
from app.core.config import settings
from app.core.security import get_current_user, require_roles
from app.db.database import get_db_context
from app.db import schema
from app.services.agents import (
    FinancialAgentSuite,
    AgentTelemetryTracker,
    ExceptionInvestigationAgent,
    RootCauseAnalysisAgent,
    FinancialInsightAgent,
    AuditExplanationAgent,
    ReportGenerationAgent
)

router = APIRouter(prefix="/agents", tags=["Reasoning Agents (Agents 9-13)"])

# Every endpoint here can trigger a paid LLM call, so they are restricted to
# users who actually operate the reconciliation rather than left open.
require_agent_operator = require_roles(["analyst", "approver"])


class InvestigateRequest(BaseModel):
    exception_id: str
    exception_type: str = "AMOUNT_MISMATCH"
    impact_minor: int = 50000
    primary_txn: Optional[Dict[str, Any]] = None
    counterpart_txn: Optional[Dict[str, Any]] = None
    severity: str = "MEDIUM"


class BatchAgentRequest(BaseModel):
    batch_id: Optional[str] = None


def _derive_findings(e: "schema.ExceptionRecord") -> List[str]:
    """
    Builds human-readable findings for an exception from its persisted columns.

    The engine attaches ``findings`` to the in-memory ExceptionSchema, but the
    exceptions table has no such column, so anything read back from the database
    must reconstruct that context rather than assume the attribute exists.
    """
    amount = (e.impact_minor or 0) / 100
    findings = [
        f"{e.exception_type} classified {e.severity} with financial impact "
        f"{e.currency or 'INR'} {amount:,.2f}; current state {e.state}."
    ]
    if e.primary_txn_id and e.counterpart_txn_id:
        findings.append(
            f"Linked pair: primary txn {e.primary_txn_id} against counterpart {e.counterpart_txn_id}."
        )
    elif e.primary_txn_id:
        findings.append(f"Unpaired entry originating from txn {e.primary_txn_id}.")
    if e.assigned_to:
        findings.append(f"Assigned to {e.assigned_to}.")
    return findings


def _get_batch_context_data(batch_id: Optional[str], org_id: str) -> Dict[str, Any]:
    """Helper to retrieve batch context from database or memory, scoped to one org."""
    active_b = STATE.get("active_batch") or {}
    active_is_ours = active_b.get("org_id") == org_id
    # No "BATCH-ACTIVE" sentinel: it was never a real batch id, so the lookup below
    # always missed and only worked by accident via the latest-report fallback. Ask
    # the database for this org's most recent batch instead.
    target_b_id = batch_id or (active_b.get("id") if active_is_ours else None)
    if not target_b_id:
        with get_db_context() as db:
            latest_b = (
                db.query(schema.Batch.id)
                .filter(schema.Batch.org_id == org_id)
                .order_by(schema.Batch.created_at.desc())
                .first()
            )
            target_b_id = latest_b[0] if latest_b else None

    # STATE is process-global; only feed the agents this organisation's records.
    state_exceptions = [e for e in STATE.get("exceptions", []) if e.get("org_id") == org_id]
    state_audit_events = [e for e in STATE.get("audit_events", []) if e.get("org_id") == org_id]
    state_txns = [t for t in STATE.get("transactions", []) if t.get("org_id") == org_id]
    state_matches = [m for m in STATE.get("matches", []) if m.get("org_id") == org_id]

    with get_db_context() as db:
        db_report = db.query(schema.BatchReport).filter_by(batch_id=target_b_id, org_id=org_id).first()
        if not db_report:
            db_report = (
                db.query(schema.BatchReport)
                .filter_by(org_id=org_id)
                .order_by(schema.BatchReport.created_at.desc())
                .first()
            )
            if db_report:
                target_b_id = db_report.batch_id

        report_json = db_report.report_json if db_report and db_report.report_json else {}
        db_exceptions = db.query(schema.ExceptionRecord).filter_by(batch_id=target_b_id, org_id=org_id).all()
        db_events = (
            db.query(schema.AuditEvent)
            .filter_by(batch_id=target_b_id, org_id=org_id)
            .order_by(schema.AuditEvent.event_seq.asc())
            .all()
        )
        # resolution_proposals has no batch_id column; it reaches a batch only
        # through its parent exception. Joining is the sole correct path here.
        db_props = (
            db.query(schema.ResolutionProposal)
            .join(
                schema.ExceptionRecord,
                schema.ResolutionProposal.exception_id == schema.ExceptionRecord.id,
            )
            .filter(
                schema.ExceptionRecord.batch_id == target_b_id,
                schema.ExceptionRecord.org_id == org_id,
            )
            .all()
        )

        exceptions = [
            {
                "id": e.id,
                "exception_type": e.exception_type,
                "severity": e.severity,
                "impact_minor": e.impact_minor,
                "state": e.state,
                # ExceptionSchema.findings is an in-flight engine field and is not
                # persisted on the exceptions table. Reconstruct equivalent context
                # from the stored columns so downstream agents still receive signal.
                "findings": _derive_findings(e),
            }
            for e in db_exceptions
        ] or state_exceptions

        audit_events = [
            {
                # The full hash preimage must be present or verify_chain_integrity
                # recomputes a different digest and always reports tampering. This
                # dict used to omit org_id, entity_id, payload and created_at, so the
                # SOX compliance agent reported an integrity FAIL on every healthy
                # batch. Field set and ordering now mirror /audit/verify-chain.
                "org_id": e.org_id,
                "batch_id": e.batch_id,
                "event_seq": e.event_seq,
                "event_type": e.event_type,
                "action": e.action,
                "entity_id": e.entity_id,
                "actor_id": e.actor_id,
                "payload": e.payload,
                "created_at": e.created_at,
                "event_hash": e.event_hash,
                "prev_hash": e.prev_hash
            }
            for e in db_events
        ] or state_audit_events

        approvals = [
            {
                "id": p.id,
                "exception_id": p.exception_id,
                "action": p.action,
                "status": p.status,
                "justification": p.justification
            }
            for p in db_props
        ] or [p for p in STATE.get("proposals", []) if p.get("org_id") == org_id]

        summary = report_json.get("summary") or STATE.get("quality_metrics")
        if not summary:
            matched_rec_count = sum(len(m.get("legs", [])) if isinstance(m, dict) else len(getattr(m, "legs", [])) for m in state_matches)
            summary = {
                "total_records": len(state_txns),
                "matched_records": matched_rec_count,
                "match_rate": (matched_rec_count / max(1, len(state_txns))) if len(state_txns) > 0 else 0.0,
                "total_exceptions": len(exceptions),
                "exact_matches": len([m for m in state_matches if (m.get("decision_tier") if isinstance(m, dict) else getattr(m, "decision_tier", "")) == "Tier 1: Exact Match"]),
                "contextual_matches": len([m for m in state_matches if (m.get("decision_tier") if isinstance(m, dict) else getattr(m, "decision_tier", "")) != "Tier 1: Exact Match"])
            }

        cash_forecast = report_json.get("cash_forecast", STATE.get("cash_forecast", []))

        return {
            "batch_id": target_b_id,
            "summary": summary,
            "exceptions": exceptions,
            "safeguards": summary.get("safeguards_breakdown", STATE.get("safeguards_triggered", [])),
            "cash_forecast": cash_forecast,
            "audit_events": audit_events,
            "approvals": approvals
        }


@router.get("/telemetry")
def get_agents_telemetry(current_user: Dict[str, Any] = Depends(get_current_user)):
    """Returns real-time execution telemetry, model providers, and token estimates across all agents."""
    return AgentTelemetryTracker.get_telemetry()


@router.post("/investigate")
def run_exception_investigation(
    req: InvestigateRequest,
    current_user: Dict[str, Any] = Depends(require_agent_operator)
):
    """Agent 9: Deep-dive transaction discrepancy investigation."""
    org_id = current_user["org_id"]
    primary_txn = req.primary_txn
    counterpart_txn = req.counterpart_txn
    exception_type = req.exception_type
    impact_minor = req.impact_minor
    severity = req.severity

    with get_db_context() as db:
        db_exc = db.query(schema.ExceptionRecord).filter_by(id=req.exception_id, org_id=org_id).first()
        if db_exc:
            if not primary_txn and db_exc.primary_txn_id:
                p_db = db.query(schema.Transaction).filter_by(id=db_exc.primary_txn_id, org_id=org_id).first()
                if p_db:
                    primary_txn = {
                        "id": p_db.id,
                        "external_id": p_db.external_id,
                        "amount_minor": p_db.amount_minor,
                        "currency": p_db.currency,
                        "source_kind": str(p_db.source_kind),
                        "account_code": p_db.account_code,
                        "description_raw": p_db.description_raw,
                        "occurred_at": p_db.occurred_at.isoformat() if p_db.occurred_at else None
                    }
            if not counterpart_txn and db_exc.counterpart_txn_id:
                c_db = db.query(schema.Transaction).filter_by(id=db_exc.counterpart_txn_id, org_id=org_id).first()
                if c_db:
                    counterpart_txn = {
                        "id": c_db.id,
                        "external_id": c_db.external_id,
                        "amount_minor": c_db.amount_minor,
                        "currency": c_db.currency,
                        "source_kind": str(c_db.source_kind),
                        "account_code": c_db.account_code,
                        "description_raw": c_db.description_raw,
                        "occurred_at": c_db.occurred_at.isoformat() if c_db.occurred_at else None
                    }
            if db_exc.impact_minor is not None:
                impact_minor = db_exc.impact_minor
            if db_exc.exception_type:
                exception_type = db_exc.exception_type
            if db_exc.severity:
                severity = db_exc.severity

    agent = ExceptionInvestigationAgent()
    res = agent.investigate(
        exception_id=req.exception_id,
        exception_type=exception_type,
        impact_minor=impact_minor,
        primary_txn=primary_txn,
        counterpart_txn=counterpart_txn,
        available_txns=[t for t in STATE.get("transactions", []) if t.get("org_id") == org_id],
        severity=severity
    )
    return res.model_dump()


@router.post("/rca")
def run_root_cause_analysis(
    req: Optional[BatchAgentRequest] = None,
    current_user: Dict[str, Any] = Depends(require_agent_operator)
):
    """Agent 10: Batch-wide systemic Root Cause Analysis."""
    b_id = req.batch_id if req else None
    data = _get_batch_context_data(b_id, current_user["org_id"])
    agent = RootCauseAnalysisAgent()
    return agent.analyze_batch_exceptions(
        batch_id=data["batch_id"],
        exceptions=data["exceptions"],
        safeguards=data["safeguards"],
        batch_summary=data["summary"]
    )


@router.post("/insights")
def run_financial_insights(
    req: Optional[BatchAgentRequest] = None,
    current_user: Dict[str, Any] = Depends(require_agent_operator)
):
    """Agent 11: 13-Week Cash Liquidity Forecasting & Treasury Advisory."""
    b_id = req.batch_id if req else None
    data = _get_batch_context_data(b_id, current_user["org_id"])
    agent = FinancialInsightAgent()
    return agent.generate_liquidity_insights(
        batch_id=data["batch_id"],
        cash_forecast=data["cash_forecast"],
        batch_summary=data["summary"]
    )


@router.post("/audit-explain")
def run_audit_explanation(
    req: Optional[BatchAgentRequest] = None,
    current_user: Dict[str, Any] = Depends(require_agent_operator)
):
    """Agent 12: SOX-404 Compliance & Cryptographic Audit Trail Explanation."""
    b_id = req.batch_id if req else None
    data = _get_batch_context_data(b_id, current_user["org_id"])
    agent = AuditExplanationAgent()
    return agent.explain_audit_trail(
        batch_id=data["batch_id"],
        audit_events=data["audit_events"],
        approvals=data["approvals"],
        batch_summary=data["summary"]
    )


@router.post("/generate-report")
def run_report_generation(
    req: Optional[BatchAgentRequest] = None,
    current_user: Dict[str, Any] = Depends(require_agent_operator)
):
    """Agent 13: Executive Controller Brief & Board Reconciliation Package Generator."""
    b_id = req.batch_id if req else None
    data = _get_batch_context_data(b_id, current_user["org_id"])
    suite = FinancialAgentSuite.get_suite()
    cached = suite.get_cached_analysis(data["batch_id"])

    rca_res = cached.get("root_cause_analysis") if cached else None
    insights_res = cached.get("financial_insights") if cached else None
    audit_res = cached.get("audit_explanation") if cached else None

    agent = ReportGenerationAgent()
    return agent.generate_controller_report(
        batch_id=data["batch_id"],
        batch_summary=data["summary"],
        rca_results=rca_res,
        insights_results=insights_res,
        audit_results=audit_res
    )


@router.post("/run-all")
def run_all_agents(
    req: Optional[BatchAgentRequest] = None,
    current_user: Dict[str, Any] = Depends(require_agent_operator)
):
    """Runs all macro reasoning agents (Agents 10 to 13) sequentially on the batch."""
    b_id = req.batch_id if req else None
    data = _get_batch_context_data(b_id, current_user["org_id"])
    suite = FinancialAgentSuite.get_suite()
    return suite.run_all_batch_agents(
        batch_id=data["batch_id"],
        batch_summary=data["summary"],
        exceptions=data["exceptions"],
        safeguards=data["safeguards"],
        cash_forecast=data["cash_forecast"],
        audit_events=data["audit_events"],
        approvals=data["approvals"]
    )


@router.get("/analysis/{batch_id}")
def get_batch_analysis(
    batch_id: str,
    current_user: Dict[str, Any] = Depends(require_agent_operator)
):
    """Retrieves cached multi-agent analysis for a specific batch."""
    org_id = current_user["org_id"]

    # A cached analysis is keyed by batch id alone, so ownership has to be
    # checked before it is handed back.
    with get_db_context() as db:
        owned = db.query(schema.Batch.id).filter_by(id=batch_id, org_id=org_id).first()
    active = STATE.get("active_batch") or {}
    if not owned and not (active.get("id") == batch_id and active.get("org_id") == org_id):
        raise HTTPException(status_code=404, detail=f"Batch '{batch_id}' not found")

    suite = FinancialAgentSuite.get_suite()
    res = suite.get_cached_analysis(batch_id)
    if not res:
        # Generate on the fly
        data = _get_batch_context_data(batch_id, org_id)
        return suite.run_all_batch_agents(
            batch_id=data["batch_id"],
            batch_summary=data["summary"],
            exceptions=data["exceptions"],
            safeguards=data["safeguards"],
            cash_forecast=data["cash_forecast"],
            audit_events=data["audit_events"],
            approvals=data["approvals"]
        )
    return res
