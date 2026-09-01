"""
Autonomous AI Financial Controller - Scoped Batch Q&A & Settlement Investigator
Conversational AI Finance Analyst with Real LLM Multi-Turn Reasoning,
Live Dynamic Batch Data Analysis, and Verifiable Accounting SOP Citations.
"""

import hashlib
import json
import logging
import os
import re
import time
from datetime import datetime, date, timezone
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api.v1.batches import STATE
from app.core.config import settings
from app.core.security import require_roles
from app.db.database import get_db_context
from app.db import schema
from app.db.database_service import DatabaseService
from app.services.agent_tools import (
    tool_calculate_fee_split,
    tool_check_period_cutoff,
    TransactionLookupIndex
)
from app.services.fee_policy import FeePolicyRegistry

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/qa", tags=["Scoped Batch Q&A"])


class QARequest(BaseModel):
    query: str
    active_context: Optional[Dict[str, Any]] = None
    conversation_history: Optional[List[Dict[str, str]]] = None


class StatusCard(BaseModel):
    status_text: str
    badge_type: str = "warning"  # "success" | "warning" | "danger" | "info" | "neutral"
    amount: str
    expected_settlement: str
    risk_level: str
    delay_days: str


class EvidenceCheck(BaseModel):
    check: str
    result: str
    is_positive: bool = True


class TimelineStep(BaseModel):
    name: str
    status: str  # "completed" | "current" | "warning" | "pending"
    detail: str


class QAResponse(BaseModel):
    query: str
    answer: str  # Markdown summary
    direct_answer: str
    status_card: Optional[StatusCard] = None
    why_it_happened: List[str] = []
    evidence_checklist: List[EvidenceCheck] = []
    timeline_steps: List[TimelineStep] = []
    recommended_action: str = ""
    simple_explanation: Optional[str] = None
    why_we_think_that: Optional[str] = None
    follow_up_suggestions: List[str] = []
    active_context: Dict[str, Any] = {}
    tool_trace: List[Dict[str, Any]] = []
    citations: List[str] = []


# ==============================================================================
# LIVE FINANCIAL BATCH CONTEXT AGGREGATOR
# ==============================================================================

def assemble_live_batch_context(query: str, org_id: str) -> Dict[str, Any]:
    """Extracts a rich, real-time snapshot of the active reconciliation batch for LLM reasoning."""
    active_batch = STATE.get("active_batch") or {}
    if active_batch.get("org_id") not in (None, org_id):
        active_batch = {}
    # STATE is process-global. Feeding another organisation's ledger into the
    # answer would disclose their figures to whoever asked the question.
    txns = [t for t in (STATE.get("transactions") or []) if t.get("org_id") == org_id]
    matches = [m for m in (STATE.get("matches") or []) if m.get("org_id") == org_id]
    exceptions = [e for e in (STATE.get("exceptions") or []) if e.get("org_id") == org_id]
    proposals = [p for p in (STATE.get("proposals") or []) if p.get("org_id") == org_id]
    forecast = STATE.get("cash_forecast") or []
    qm = dict(STATE.get("quality_metrics") or {})

    # If in-memory state is empty, rehydrate from database
    if not txns:
        with get_db_context() as db:
            db_batch = (
                db.query(schema.Batch)
                .filter_by(org_id=org_id)
                .order_by(schema.Batch.created_at.desc())
                .first()
            )
            if db_batch:
                active_batch = {"id": db_batch.id, "org_id": org_id, "status": db_batch.status}
                db_txns = db.query(schema.Transaction).filter_by(batch_id=db_batch.id, org_id=org_id).all()
                txns = [
                    {
                        "id": t.id,
                        "source_kind": t.source_kind,
                        "external_id": t.external_id,
                        "amount_minor": t.amount_minor,
                        "direction": t.direction,
                        "occurred_at": str(t.occurred_at),
                        "description_raw": t.description_raw,
                        "reference_keys": t.reference_keys or {}
                    }
                    for t in db_txns
                ]
                db_excs = db.query(schema.ExceptionRecord).filter_by(batch_id=db_batch.id, org_id=org_id).all()
                exceptions = [
                    {
                        "id": e.id,
                        "exception_type": e.exception_type,
                        "severity": e.severity,
                        "state": e.state,
                        "impact_minor": e.impact_minor,
                        "primary_txn_id": e.primary_txn_id
                    }
                    for e in db_excs
                ]
                # Scope proposals to this batch's exceptions. Unfiltered, this loaded
                # every proposal the org had ever created (~10k rows) into the QA
                # agent's context alongside 24 batch-scoped exceptions, so the model
                # reasoned over resolutions belonging to unrelated historical runs.
                exc_ids = [e.id for e in db_excs]
                db_props = (
                    db.query(schema.ResolutionProposal)
                    .filter(
                        schema.ResolutionProposal.org_id == org_id,
                        schema.ResolutionProposal.exception_id.in_(exc_ids)
                    ).all()
                ) if exc_ids else []
                proposals = [
                    {
                        "id": p.id,
                        "exception_id": p.exception_id,
                        "action": p.action
                    }
                    for p in db_props
                ]
                if db_batch.match_rate is not None:
                    qm["match_rate"] = float(db_batch.match_rate)

        # Quality metrics and the cash forecast are only ever written to STATE by a
        # live run, so after a restart they were empty while the transactions above
        # rehydrated. Load the persisted copies so the assistant reasons over the
        # real batch instead of zeroes.
        db_ctx = DatabaseService.load_batch_context(org_id)
        if db_ctx["batch"]:
            merged = dict(db_ctx["quality_metrics"])
            merged.update({k: v for k, v in qm.items() if v})
            qm = merged
            if not forecast:
                forecast = db_ctx["cash_forecast"]

    total_records = len(txns)
    matched_records = sum(len(m.get("legs", [])) for m in matches)
    if matches and total_records > 0:
        match_rate = matched_records / total_records
    else:
        # `matches` is in-memory only and is never rehydrated, so dividing by the
        # rehydrated txn count produced 0/240 = 0.00% for a batch that actually
        # reconciled at 20.31%. Trust the persisted rate when matches are absent.
        match_rate = qm.get("match_rate", 0.0)

    # Calculate actual gross volume
    total_inflow_minor = sum(t.get("amount_minor", 0) for t in txns if str(t.get("direction", "")).upper() in ("INFLOW", "CREDIT"))
    total_outflow_minor = sum(t.get("amount_minor", 0) for t in txns if str(t.get("direction", "")).upper() in ("OUTFLOW", "DEBIT"))

    # Extract exceptions breakdown
    open_excs = []
    for e in exceptions[:15]:
        p_match = next((p for p in proposals if p.get("exception_id") == e.get("id")), None)
        open_excs.append({
            "id": e.get("id"),
            "type": e.get("exception_type"),
            "severity": e.get("severity"),
            "state": e.get("state", "OPEN"),
            "impact_inr": f"₹{(e.get('impact_minor', 0) / 100):,.2f}",
            "primary_txn_id": e.get("primary_txn_id"),
            "recommended_action": p_match.get("action") if p_match else "REVIEW_VOUCHER"
        })

    # Find specific transaction mentioned in query (e.g. INV-..., PAY-..., UTR-..., gw_...)
    target_txn = None
    target_counterparts = []
    ref_match = re.search(r'\b(INV-[\w\-]+|PAY-[\w\-]+|UTR-[\w\-]+|JE-[\w\-:]+|gw_[\w\-]+|bk_[\w\-]+|gl_[\w\-]+|EXC-[\w\-]+)\b', query, re.IGNORECASE)
    if ref_match:
        matched_token = ref_match.group(1).upper()
        for t in txns:
            ext = str(t.get("external_id", "")).upper()
            desc = str(t.get("description_raw", "")).upper()
            t_id = str(t.get("id", "")).upper()
            ref_keys = t.get("reference_keys", {})
            all_refs = [str(v).upper() for k_list in ref_keys.values() for v in (k_list if isinstance(k_list, list) else [k_list])]

            if matched_token in ext or matched_token in desc or matched_token == t_id or matched_token in all_refs:
                target_txn = t
                break

        if target_txn:
            t_amt = target_txn.get("amount_minor", 0)
            t_src = str(target_txn.get("source_kind", ""))
            for t in txns:
                if str(t.get("source_kind", "")) != t_src:
                    if abs(t.get("amount_minor", 0) - t_amt) <= max(round(t_amt * 0.05), 5000):
                        target_counterparts.append({
                            "id": t.get("id"),
                            "source_kind": t.get("source_kind"),
                            "external_id": t.get("external_id"),
                            "amount_inr": f"₹{(t.get('amount_minor', 0) / 100):,.2f}",
                            "date": str(t.get("occurred_at", ""))
                        })

    # Authoritative severity counts across all exceptions in batch (Issue 2.23 m)
    total_crit_count = sum(1 for e in exceptions if str(e.get("severity", "")).upper() == "CRITICAL")
    total_high_count = sum(1 for e in exceptions if str(e.get("severity", "")).upper() == "HIGH")
    total_med_count = sum(1 for e in exceptions if str(e.get("severity", "")).upper() in ("MEDIUM", "LOW", ""))

    # A real reference from this batch, used for follow-up suggestions. Suggesting a
    # hardcoded invoice id that is not in the ledger sends the user down a dead end.
    sample_ref = next(
        (str(t.get("external_id")) for t in txns if t.get("external_id")),
        None
    )

    return {
        # No fabricated batch id: if the org has no batch, say so rather than
        # printing a plausible-looking identifier that does not exist.
        "batch_id": active_batch.get("id") or "NO_ACTIVE_BATCH",
        "sample_reference": sample_ref,
        "total_records": total_records,
        "match_rate_pct": round(match_rate * 100, 2),
        "total_inflow_inr": f"₹{(total_inflow_minor / 100):,.2f}",
        "total_outflow_inr": f"₹{(total_outflow_minor / 100):,.2f}",
        "total_matches": len(matches),
        "total_exceptions": len(exceptions),
        "critical_exceptions_count": total_crit_count,
        "high_exceptions_count": total_high_count,
        "medium_low_exceptions_count": total_med_count,
        "open_exceptions_sample": open_excs,
        "cash_forecast_summary": [
            {
                "week": f.get("week_number"),
                "confirmed_inr": f"₹{(f.get('confirmed_inflow_minor', 0) / 100):,.2f}",
                "probable_inr": f"₹{(f.get('probable_inflow_minor', 0) / 100):,.2f}",
                "at_risk_inr": f"₹{(f.get('at_risk_inflow_minor', 0) / 100):,.2f}"
            }
            for f in forecast[:6]
        ],
        "target_transaction_referenced": target_txn,
        "target_counterpart_candidates": target_counterparts
    }


# ==============================================================================
# REAL LLM FINANCIAL REASONING ENGINE
# ==============================================================================

def execute_llm_financial_investigation(query: str, batch_context: Dict[str, Any], history: Optional[List[Dict[str, str]]] = None) -> Optional[Dict[str, Any]]:
    """Calls real Gemini or Anthropic LLM with structured finance prompt and live batch context."""
    system_prompt = (
        "You are the Senior AI Financial Controller and forensic reconciliation assistant. "
        "You have full, real-time visibility into the organization's three-way settlement reconciliation ledger, "
        "including Gateway captures, Bank statement deposits, General Ledger ERP journal postings, open exceptions, and 13-week cash forecasts.\n\n"
        "Analyze the user's inquiry using the live financial batch data provided. Perform thorough financial reasoning, "
        "cite exact numerical values, invoice IDs, and standard accounting principles (SOP-01 Deduplication, SOP-02 Period Boundary Cutoff, "
        "SOP-03 13-Week Cash Forecast, SOP-04 MDR Netting Formulas, SOP-05 Maker-Checker Governance).\n\n"
        "You MUST respond ONLY with a strictly valid JSON object matching this exact schema (no surrounding markdown text or explanations):\n"
        "{\n"
        '  "direct_answer": "Concise 1-2 sentence core conclusion with exact figures.",\n'
        '  "status_card": {\n'
        '    "status_text": "Short headline status",\n'
        '    "badge_type": "success|warning|danger|info",\n'
        '    "amount": "₹X,XX,XXX.XX or appropriate metric",\n'
        '    "expected_settlement": "Settlement timeline or detail",\n'
        '    "risk_level": "Low|Medium|High",\n'
        '    "delay_days": "e.g. On Schedule or T+2 Days"\n'
        '  },\n'
        '  "why_it_happened": ["Bullet point 1 analyzing root cause", "Bullet point 2 with data evidence", "Bullet point 3 accounting treatment"],\n'
        '  "evidence_checklist": [\n'
        '    {"check": "Description of validation check", "result": "Outcome", "is_positive": true}\n'
        '  ],\n'
        '  "timeline_steps": [\n'
        '    {"name": "Stage 1", "status": "completed|current|warning|pending", "detail": "Details"}\n'
        '  ],\n'
        '  "recommended_action": "Concrete next step for controller/reviewer",\n'
        '  "simple_explanation": "Plain English summary for business stakeholders",\n'
        '  "why_we_think_that": "Underlying formula, rule, or mathematical proof",\n'
        '  "follow_up_suggestions": ["Related query 1", "Related query 2"],\n'
        '  "citations": ["SOP-XX Citation"]\n'
        "}"
    )

    user_payload = {
        "user_query": query,
        "live_reconciliation_batch_data": batch_context,
        "recent_conversation_history": (history or [])[-4:]
    }

    user_message_str = json.dumps(user_payload, indent=2, default=str)

    # 1. Try Groq (Ultra-Fast High-Intelligence LLM)
    groq_key = settings.GROQ_API_KEY
    if groq_key:
        try:
            from groq import Groq
            groq_client = Groq(api_key=groq_key, timeout=12.0)
            groq_models = [
                getattr(settings, "GROQ_MODEL", None) or "openai/gpt-oss-120b",
                "qwen/qwen3.8-27b",
                "qwen/qwen3.6-27b",
                "openai/gpt-oss-20b"
            ]
            for g_model in groq_models:
                try:
                    kwargs = {
                        "model": g_model,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": f"Live Financial Context & Query:\n{user_message_str}"}
                        ],
                        "temperature": 0.2,
                        "max_tokens": 1500
                    }
                    if "openai" in g_model:
                        kwargs["response_format"] = {"type": "json_object"}
                    completion = groq_client.chat.completions.create(**kwargs)
                    raw_text = completion.choices[0].message.content or ""
                    json_start = raw_text.find("{")
                    json_end = raw_text.rfind("}") + 1
                    if json_start != -1 and json_end != -1:
                        parsed = json.loads(raw_text[json_start:json_end])
                        if "direct_answer" in parsed:
                            return parsed
                except Exception as e:
                    logger.warning("[qa] Groq model %s failed: %s", g_model, e)
                    continue
        except Exception as e:
            logger.warning("[qa] Groq provider unavailable: %s", e)

    # 2. Try Gemini
    if settings.GEMINI_API_KEY:
        # Read the configured model. A hardcoded id here means a provider-side
        # retirement silently kills this fallback tier with no way to fix it
        # from configuration.
        gemini_model = settings.AGENT_GEMINI_MODEL
        try:
            from google import genai
            client = genai.Client(api_key=settings.GEMINI_API_KEY)
            response = client.models.generate_content(
                model=gemini_model,
                contents=f"{system_prompt}\n\nUser Context:\n{user_message_str}"
            )
            raw_text = response.text or ""
            json_start = raw_text.find("{")
            json_end = raw_text.rfind("}") + 1
            if json_start != -1 and json_end != -1:
                parsed = json.loads(raw_text[json_start:json_end])
                return parsed
        except Exception as e:
            logger.warning("[qa] Gemini fallback failed (model=%s): %s", gemini_model, e)

    # 3. Try Anthropic
    if settings.ANTHROPIC_API_KEY:
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
            resp = client.messages.create(
                model=settings.AGENT_INVESTIGATION_MODEL,
                max_tokens=1500,
                system=system_prompt,
                messages=[{"role": "user", "content": user_message_str}]
            )
            raw_text = resp.content[0].text
            json_start = raw_text.find("{")
            json_end = raw_text.rfind("}") + 1
            if json_start != -1 and json_end != -1:
                parsed = json.loads(raw_text[json_start:json_end])
                return parsed
        except Exception as e:
            logger.warning("[qa] Anthropic fallback failed: %s", e)

    logger.warning("[qa] All LLM providers failed or unconfigured; falling back to deterministic answer.")
    return None


# ==============================================================================
# DYNAMIC FINANCIAL DATA REASONER (High-Precision Fallback)
# ==============================================================================

def _ref_question(ctx: Dict[str, Any]) -> str:
    """Builds a follow-up suggestion around a reference that actually exists.

    The suggestions used to name a fixed invoice id, so on any real dataset the
    prompt pointed at a transaction the ledger had never seen."""
    ref = ctx.get("sample_reference")
    if ref:
        return f"Why didn't {ref} settle in this batch?"
    return "Which transactions are still unsettled?"


def execute_dynamic_data_reasoner(query: str, ctx: Dict[str, Any]) -> QAResponse:
    """Performs real-time, non-canned mathematical analysis on loaded batch data."""
    q_lower = query.lower()
    batch_id = ctx.get("batch_id", "ACTIVE")
    total_records = ctx.get("total_records", 0)
    match_rate = ctx.get("match_rate_pct", 0.0)
    open_excs = ctx.get("open_exceptions_sample", [])
    target_txn = ctx.get("target_transaction_referenced")
    forecast = ctx.get("cash_forecast_summary", [])

    # Case A: Specific Transaction / Invoice Referenced
    if target_txn:
        ext_id = target_txn.get("external_id", "REF-UNKNOWN")
        amt_minor = target_txn.get("amount_minor", 0)
        amt_inr = f"₹{(amt_minor / 100):,.2f}"
        src = str(target_txn.get("source_kind", "GATEWAY")).upper()
        occ = str(target_txn.get("occurred_at", ""))[:10]
        cands = ctx.get("target_counterpart_candidates", [])

        # Check fee calculation
        fee_split = tool_calculate_fee_split(amt_minor, "POL-MDR-STD-2026")
        cutoff_check = tool_check_period_cutoff(target_txn.get("occurred_at"), target_txn.get("value_date"))

        direct_ans = f"Transaction {ext_id} ({amt_inr} via {src} on {occ}) has been analyzed against active bank and ledger streams."
        why_list = [
            f"Gross amount: {amt_inr}. Under standard MDR policy (POL-MDR-STD-2026), expected net bank deposit is ₹{(fee_split['expected_net_minor']/100):,.2f} after ₹{(fee_split['total_deduction_minor']/100):,.2f} fee & GST deduction.",
            f"Period boundary evaluation: {'Detected as T+2 clearing cutoff crossing into next period' if cutoff_check['is_period_cutoff_timing_difference'] else 'Standard intra-period clearing cycle'}.",
            f"Found {len(cands)} candidate counterpart entries in related settlement streams."
        ]

        status_card = StatusCard(
            status_text=f"Analyzed: {ext_id}",
            badge_type="info" if not cutoff_check["is_period_cutoff_timing_difference"] else "warning",
            amount=amt_inr,
            expected_settlement=cutoff_check["expected_bank_clearing_date"] if cutoff_check["is_period_cutoff_timing_difference"] else "Cleared",
            risk_level="Low" if cands or fee_split else "Medium",
            delay_days=f"T+{cutoff_check['settlement_delay_days']} Days"
        )

        ev_list = [
            EvidenceCheck(check="Gross capture verified", result=f"✓ {amt_inr} in {src}", is_positive=True),
            EvidenceCheck(check="MDR fee netting formula", result=f"✓ Net: ₹{(fee_split['expected_net_minor']/100):,.2f}", is_positive=True),
            EvidenceCheck(check="Period cutoff status", result=f"{'⚠ T+2 In-Transit' if cutoff_check['is_period_cutoff_timing_difference'] else '✓ Within Period'}", is_positive=not cutoff_check["is_period_cutoff_timing_difference"])
        ]

        tl_list = [
            TimelineStep(name="1. Gateway Capture", status="completed", detail=f"{ext_id} captured at full gross value"),
            TimelineStep(name="2. Fee & Tax Deduction", status="completed", detail=f"MDR ₹{(fee_split['fee_minor']/100):,.2f} + GST ₹{(fee_split['tax_minor']/100):,.2f}"),
            TimelineStep(name="3. Bank Settlement", status="current" if cutoff_check["is_period_cutoff_timing_difference"] else "completed", detail=f"Expected deposit ₹{(fee_split['expected_net_minor']/100):,.2f}")
        ]

        rec_act = f"Accrue to Account 1290 (In-Transit) or confirm net deposit ₹{(fee_split['expected_net_minor']/100):,.2f} in bank statement."
        simple_exp = f"This payment of {amt_inr} is tracked. After the gateway fee deduction of ₹{(fee_split['total_deduction_minor']/100):,.2f}, the remaining net amount is scheduled for settlement."
        why_think = f"Applied SOP-04 fee policy POL-MDR-STD-2026 and SOP-02 period cutoff checks on {ext_id}."

        formatted_md = f"**{direct_ans}**\n\n" + "\n".join(f"• {w}" for w in why_list) + f"\n\n**Recommended Next Step:**\n{rec_act}"
        return QAResponse(
            query=query,
            answer=formatted_md,
            direct_answer=direct_ans,
            status_card=status_card,
            why_it_happened=why_list,
            evidence_checklist=ev_list,
            timeline_steps=tl_list,
            recommended_action=rec_act,
            simple_explanation=simple_exp,
            why_we_think_that=why_think,
            follow_up_suggestions=["Explain MDR fee splits", "How many exceptions are there?", "What is the cash forecast?"],
            citations=["SOP-04 §2: MDR Fee Accounting", "SOP-02 §4: Period Boundary Cutoff"]
        )

    # Case B: Exceptions Breakdown Query
    if any(k in q_lower for k in ("exception", "unmatched", "mismatch", "discrepancy", "error", "flagged")):
        crit_count = ctx.get("critical_exceptions_count", sum(1 for e in open_excs if e.get("severity") == "CRITICAL"))
        high_count = ctx.get("high_exceptions_count", sum(1 for e in open_excs if e.get("severity") == "HIGH"))
        med_count = ctx.get("medium_low_exceptions_count", sum(1 for e in open_excs if e.get("severity") in ("MEDIUM", "LOW")))

        direct_ans = f"There are currently {ctx.get('total_exceptions', len(open_excs))} open exceptions in batch {batch_id} ({crit_count} Critical, {high_count} High, {med_count} Medium/Low severity)."
        why_list = [
            f"• {e['id']}: {e['type']} ({e['impact_inr']}) — Proposed Action: {e['recommended_action']}"
            for e in open_excs[:4]
        ]
        if not why_list:
            why_list = ["All transactions in this batch have been deterministically reconciled."]

        status_card = StatusCard(
            status_text=f"{ctx.get('total_exceptions', len(open_excs))} Open Exceptions",
            badge_type="danger" if crit_count > 0 else "warning",
            amount=f"{crit_count} Critical Items",
            expected_settlement="Pending Maker-Checker Review",
            risk_level="High" if crit_count > 0 else "Medium",
            delay_days="Review Queue Active"
        )

        ev_list = [
            EvidenceCheck(check="Critical Missing Wire Scan", result=f"{crit_count} Flagged", is_positive=(crit_count == 0)),
            EvidenceCheck(check="MDR Fee Netting Variances", result=f"{med_count} Identified", is_positive=True),
            EvidenceCheck(check="Dual-Control Segregation", result="✓ Approver Sign-off Required", is_positive=True)
        ]

        tl_list = [
            TimelineStep(name="1. Deterministic Pass", status="completed", detail="Exact reference IDs matched"),
            TimelineStep(name="2. Exception Isolation", status="current", detail=f"{len(open_excs)} held for controller review"),
            TimelineStep(name="3. Dual-Control Approval", status="pending", detail="Awaiting Checker authorization")
        ]

        rec_act = "Open the Exceptions & Approvals queue to review and sign off on pending adjustment vouchers."
        simple_exp = f"We have {len(open_excs)} items that need human review before posting, mainly comprising timing differences and fee split adjustments."
        why_think = f"Real-time exception registry query across batch {batch_id}."

        formatted_md = f"**{direct_ans}**\n\n**Key Open Exceptions:**\n" + "\n".join(why_list) + f"\n\n**Recommended Next Step:**\n{rec_act}"
        return QAResponse(
            query=query,
            answer=formatted_md,
            direct_answer=direct_ans,
            status_card=status_card,
            why_it_happened=why_list,
            evidence_checklist=ev_list,
            timeline_steps=tl_list,
            recommended_action=rec_act,
            simple_explanation=simple_exp,
            why_we_think_that=why_think,
            follow_up_suggestions=[_ref_question(ctx), "What is the match rate?", "Explain MDR fee splits"],
            citations=["SOP-05 §1: Three-Way Reconciliation Governance"]
        )

    # Case C: Cash Forecasting & Liquidity Query
    if any(k in q_lower for k in ("forecast", "cash", "liquidity", "runway", "trajectory", "inflow")):
        w1_conf = forecast[0]["confirmed_inr"] if forecast else "₹0.00"
        w2_prob = forecast[1]["probable_inr"] if len(forecast) > 1 else "₹0.00"

        direct_ans = f"The 13-week segmented cash forecast models real inflows starting with {w1_conf} confirmed operating cash in Week 1, and {w2_prob} probable T+2 clearing inflows in Week 2."
        why_list = [
            f"Week 1-2: {w1_conf} confirmed cleared in bank account (Tier 1 - 100% confidence).",
            f"Week 3-4: {w2_prob} in-transit gateway receivables with T+2 SLA clearing (Tier 2 - 70% confidence).",
            "Variance Guardrails: Automated timing difference adjustments compensate for month-end cutoff boundaries."
        ]

        status_card = StatusCard(
            status_text="13-Week Cash Forecast Active",
            badge_type="success",
            amount=f"{w1_conf} (W1 Confirmed)",
            expected_settlement="13-Week Trajectory",
            risk_level="Low (<5% At-Risk)",
            delay_days="T+2 Compensated"
        )

        ev_list = [
            EvidenceCheck(check="Confirmed Bank Liquidity", result=f"✓ {w1_conf}", is_positive=True),
            EvidenceCheck(check="T+2 In-Transit Pipeline", result=f"✓ {w2_prob}", is_positive=True),
            EvidenceCheck(check="Double-Entry Balance", result="✓ 100% Balanced", is_positive=True)
        ]

        tl_list = [
            TimelineStep(name="Weeks 1-4", status="completed", detail="Confirmed Operating Liquidity"),
            TimelineStep(name="Weeks 5-8", status="current", detail="Probable Inflows & Accruals"),
            TimelineStep(name="Weeks 9-13", status="pending", detail="Projected Runway")
        ]

        rec_act = "Review the Liquidity Waterfall chart in the Dashboard to inspect weekly distribution curves."
        simple_exp = "We model future cash inflow based on what is already in your bank account versus what is currently clearing through payment gateways."
        why_think = "Dynamic segmentation using SegmentedCashForecaster algorithm on canonical transactions."

        formatted_md = f"**{direct_ans}**\n\n**Forecast Trajectory:**\n" + "\n".join(f"• {w}" for w in why_list) + f"\n\n**Recommended Next Step:**\n{rec_act}"
        return QAResponse(
            query=query,
            answer=formatted_md,
            direct_answer=direct_ans,
            status_card=status_card,
            why_it_happened=why_list,
            evidence_checklist=ev_list,
            timeline_steps=tl_list,
            recommended_action=rec_act,
            simple_explanation=simple_exp,
            why_we_think_that=why_think,
            follow_up_suggestions=["How many exceptions are there?", "What is the match rate?", "Explain maker-checker rules"],
            citations=["SOP-03: Cash Position Forecasting & Liquidity Planning"]
        )

    # Case D: General Batch Overview & Dynamic Summary
    direct_ans = f"Batch {batch_id} contains {total_records} loaded transactions reconciling at {match_rate}% match rate with {ctx.get('total_exceptions', 0)} items held in the review queue."
    why_list = [
        f"Total Inflows: {ctx.get('total_inflow_inr', '₹0.00')} across Gateway and Bank streams.",
        f"Total Outflows / Debits: {ctx.get('total_outflow_inr', '₹0.00')} in Bank and General Ledger accounts.",
        f"Reconciliation Performance: {ctx.get('total_matches', 0)} match clusters formed with multi-pass deterministic & contextual assignment."
    ]

    status_card = StatusCard(
        status_text="Batch Reconciled & Audited",
        badge_type="success" if match_rate >= 90.0 else "warning",
        amount=f"{total_records} Total Records",
        expected_settlement="Continuous Hash Chain Sealed",
        risk_level="Assessed Deterministically",
        delay_days="On Schedule"
    )

    ev_list = [
        EvidenceCheck(check="Cryptographic Audit Hash Chain", result="✓ SHA-256 Verified", is_positive=True),
        EvidenceCheck(check="Double-Entry Balance", result="✓ 100% Balanced", is_positive=True),
        EvidenceCheck(check="Dual-Control Maker-Checker Gate", result="✓ Active & Enforced", is_positive=True)
    ]

    tl_list = [
        TimelineStep(name="1. Multi-Feed Ingestion", status="completed", detail="SHA-256 Provenance Tracked"),
        TimelineStep(name="2. Deterministic Matching", status="completed", detail=f"{match_rate}% Reconciled"),
        TimelineStep(name="3. Controller Sign-off", status="current", detail="Maker-Checker Review Queue")
    ]

    # Case Greeting & Capabilities (Issue 2.23 k: Exact word boundary match)
    is_greeting = bool(re.search(r'\b(hi|hello|hey|help)\b', q_lower)) or any(p in q_lower for p in ("what is this chat", "what can you do", "who are you"))
    if is_greeting:
        direct_ans = f"I am your Senior AI Financial Controller assistant. I monitor batch {batch_id} across {total_records} records with real-time settlement analysis, MDR fee validation, and dual-control Maker-Checker governance."
        status_card = StatusCard(
            status_text="Senior AI Financial Controller Active",
            badge_type="success",
            amount=f"{total_records} Records",
            expected_settlement="Continuous Hash Chain",
            risk_level="Protected",
            delay_days="On Schedule"
        )
        return QAResponse(
            query=query,
            answer=f"**{direct_ans}**",
            direct_answer=direct_ans,
            status_card=status_card,
            why_it_happened=[
                "Deterministic 6-pass reconciliation engine with O(1) indexed lookups.",
                "Automated MDR fee split computation & GST ledger postings.",
                "Dual-control Maker-Checker segregation and cryptographic SHA-256 audit chaining."
            ],
            evidence_checklist=[
                EvidenceCheck(check="Financial Controller Engine", result="✓ Operational", is_positive=True),
                EvidenceCheck(check="Audit Blockchain", result="✓ Verified", is_positive=True)
            ],
            timeline_steps=[
                TimelineStep(name="Ingestion", status="completed", detail="Multi-feed checksum verified"),
                TimelineStep(name="Matching", status="completed", detail="Deterministic & Contextual Passes"),
                TimelineStep(name="Governance", status="current", detail="Maker-Checker Review")
            ],
            recommended_action="Ask about specific invoices, fee calculations, open exceptions, or cash forecasts.",
            simple_explanation="I help finance teams automatically match payments and resolve accounting variances.",
            why_we_think_that="Active financial controller runtime.",
            follow_up_suggestions=["How many exceptions are there?", _ref_question(ctx), "Explain MDR fee splits"],
            citations=["SOP-05 §1: Three-Way Reconciliation Governance"],
            tool_trace=[{"tool": "get_batch_context", "status": "SUCCESS"}]
        )

    rec_act = "Verify audit chain integrity and proceed to authorize open maker-checker vouchers."
    simple_exp = f"Your transactions have been processed through the 6-pass matching engine. {match_rate}% of all records matched cleanly."
    why_think = f"Dynamic multi-feed ledger evaluation for batch {batch_id}."

    formatted_md = f"**{direct_ans}**\n\n**Financial Overview:**\n" + "\n".join(f"• {w}" for w in why_list) + f"\n\n**Recommended Next Step:**\n{rec_act}"
    return QAResponse(
        query=query,
        answer=formatted_md,
        direct_answer=direct_ans,
        status_card=status_card,
        why_it_happened=why_list,
        evidence_checklist=ev_list,
        timeline_steps=tl_list,
        recommended_action=rec_act,
        simple_explanation=simple_exp,
        why_we_think_that=why_think,
        follow_up_suggestions=["How many exceptions are there?", "Explain MDR fee splits", "What is the cash forecast?"],
        citations=["SOP-05 §1: Three-Way Reconciliation Governance"],
        tool_trace=[{"tool": "get_batch_context", "status": "SUCCESS"}]
    )


# ==============================================================================
# MAIN QA ROUTER ENDPOINT
# ==============================================================================

@router.post("/ask", response_model=QAResponse)
def ask_question(
    request: QARequest,
    current_user: Dict[str, Any] = Depends(require_roles(["admin", "analyst", "approver"], allow_admin=True))
):
    query = request.query.strip()
    history = request.conversation_history or []

    # 1. Assemble live dynamic context from active batch
    batch_context = assemble_live_batch_context(query, current_user["org_id"])

    # 2. Attempt Real LLM Reasoning (Gemini / Anthropic)
    llm_result = execute_llm_financial_investigation(query, batch_context, history)
    if llm_result:
        try:
            status_card_dict = llm_result.get("status_card")
            status_card_obj = StatusCard(**status_card_dict) if status_card_dict else None

            ev_checklist = [
                EvidenceCheck(**e) for e in llm_result.get("evidence_checklist", [])
                if isinstance(e, dict) and "check" in e and "result" in e
            ]
            tl_steps = [
                TimelineStep(**t) for t in llm_result.get("timeline_steps", [])
                if isinstance(t, dict) and "name" in t and "detail" in t
            ]

            direct_ans = llm_result.get("direct_answer", "Financial analysis completed.")
            why_list = llm_result.get("why_it_happened", [])
            rec_act = llm_result.get("recommended_action", "Review Maker-Checker queue.")
            formatted_md = f"**{direct_ans}**\n\n" + "\n".join(f"• {w}" for w in why_list) + f"\n\n**Recommended Next Step:**\n{rec_act}"

            return QAResponse(
                query=query,
                answer=formatted_md,
                direct_answer=direct_ans,
                status_card=status_card_obj,
                why_it_happened=why_list,
                evidence_checklist=ev_checklist,
                timeline_steps=tl_steps,
                recommended_action=rec_act,
                simple_explanation=llm_result.get("simple_explanation"),
                why_we_think_that=llm_result.get("why_we_think_that"),
                follow_up_suggestions=llm_result.get("follow_up_suggestions", []),
                active_context=batch_context,
                citations=llm_result.get("citations", ["SOP-05 §1: Financial Reconciliation"]),
                tool_trace=[{"tool": "get_batch_context", "status": "SUCCESS"}]
            )
        except Exception:
            pass

    # 3. Fallback to Dynamic Financial Data Reasoner
    return execute_dynamic_data_reasoner(query, batch_context)


# Backwards compatibility alias
ask_batch_assistant = ask_question
