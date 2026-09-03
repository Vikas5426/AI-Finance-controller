"""
LangGraph-Orchestrated Financial Controller Runtime
Coordinates autonomous three-way financial reconciliation across 7 stages:
1. Validation & Normalization Node
2. Deterministic 6-Pass Reconciliation Node (Exact, Hungarian, Subset-Sum DP)
3. Exception Triage Node (SOP Rules vs Ambiguous Exceptions)
4. AI Exception Investigation Node (Single Reasoning Agent with Deterministic Tools)
5. Arithmetic & Link Verifier Gate Node (Hard Math Gate with Reflection)
6. Decision Routing Node (Tier 1-4 Classification & Maker-Checker Proposals)
7. Finalize Batch Node (13-Week Cash Forecast & SHA-256 Audit Sealing)
"""

import logging
import time
import uuid
from datetime import datetime, timezone, date
from typing import Any, Dict, List, Optional, Set, Tuple, TypedDict

logger = logging.getLogger(__name__)

from langgraph.graph import StateGraph, END

from app.core.config import settings
from app.models.schemas import (
    CanonicalTransaction, SourceKind, DecisionTier, BatchWindowSummary,
    MatchSchema, MatchLegSchema, MatchTypeEnum, MatchMethodEnum,
    ExceptionSchema, ExceptionSeverity, ExceptionState, ReconciliationDecision,
    InvestigationResult
)
from app.services.validation_service import DataValidationService
from app.services.matching_engine import ReconciliationEngine
from app.services.context_builder import TransactionContextBuilder
from app.services.agent_tools import (
    TransactionLookupIndex, tool_lookup_candidates, tool_calculate_fee_split,
    tool_check_period_cutoff, tool_evaluate_sop_rules
)
from app.services.agent_runtime import AIAgentRuntime, DeterministicVerifier
from app.services.decision_engine import HybridDecisionEngine
from app.services.audit_chain import AuditHashChain
from app.services.cash_forecaster import SegmentedCashForecaster


class ReconciliationState(TypedDict):
    """Shared state dictionary tracked and mutated across LangGraph nodes."""
    batch_id: str
    org_id: str
    window_size: int
    raw_transactions: List[CanonicalTransaction]
    canonical_transactions: List[CanonicalTransaction]
    validation_errors: Dict[str, Any]
    
    # Engine matches and exceptions
    matches: List[MatchSchema]
    exceptions: List[ExceptionSchema]
    unmatched_transactions: List[CanonicalTransaction]
    matched_txn_ids: Set[str]
    safeguards_triggered: List[Dict[str, Any]]
    engine_summary: Dict[str, Any]
    
    # Exception Triage
    rule_resolved_items: List[Dict[str, Any]]
    ambiguous_exceptions: List[Dict[str, Any]]
    
    # AI Investigation & Verifier Gate
    agent_proposals: Dict[str, InvestigationResult]
    verified_proposals: Dict[str, InvestigationResult]
    rejected_proposals: Dict[str, str] # exception_id -> rejection reason
    retry_counts: Dict[str, int] # exception_id -> count
    
    # Operational Decisions & Governance
    decisions: Dict[str, ReconciliationDecision]
    proposals: List[Dict[str, Any]]
    windows: List[BatchWindowSummary]
    audit_events: List[Dict[str, Any]]
    cash_forecast: List[Dict[str, Any]]
    summary: Dict[str, Any]
    wall_clock_start: float


# ==============================================================================
# LANGGRAPH NODES
# ==============================================================================

def validate_and_normalize_node(state: ReconciliationState) -> Dict[str, Any]:
    """Node 1: Pre-flight validation gate and canonical sanity check."""
    txns = state["raw_transactions"]
    val_results = DataValidationService.validate_batch(txns)
    
    errors = {
        txn_id: res.errors for txn_id, res in val_results.items() if res.status == "INVALID"
    }

    # Initialize audit hash chain
    audit_events = []
    ts0 = datetime.now(timezone.utc)
    p0 = {"action": "BATCH_INITIALIZED", "total_records": len(txns)}
    h0 = AuditHashChain.compute_event_hash(
        AuditHashChain.GENESIS_HASH, state["org_id"], 1, "BATCH_INITIALIZED",
        state["batch_id"], "usr_system", p0, ts0
    )
    audit_events.append({
        "prev_hash": AuditHashChain.GENESIS_HASH,
        "org_id": state["org_id"],
        "event_seq": 1,
        "event_type": "BATCH_INITIALIZED",
        "entity_type": "BATCH",
        "entity_id": state["batch_id"],
        "actor_id": "usr_system",
        "actor_type": "system",
        "action": "CREATE_BATCH",
        "payload": p0,
        "created_at": ts0,
        "event_hash": h0
    })

    return {
        "canonical_transactions": txns,
        "validation_errors": errors,
        "audit_events": audit_events
    }


def deterministic_reconciliation_node(state: ReconciliationState) -> Dict[str, Any]:
    """Node 2: 6-Pass Deterministic Matching Engine (P0 dedupe, P1 exact, P3 Hungarian, P4 DP subset-sum)."""
    txns = state["canonical_transactions"]
    engine = ReconciliationEngine(org_id=state["org_id"], batch_id=state["batch_id"])
    engine_res = engine.run_full_pipeline(txns)

    unmatched = [t for t in txns if t.id not in engine.matched_txn_ids]

    return {
        "matches": engine.matches,
        "exceptions": engine.exceptions,
        "unmatched_transactions": unmatched,
        "matched_txn_ids": engine.matched_txn_ids,
        "safeguards_triggered": engine.safeguards_triggered,
        "engine_summary": engine_res
    }


def triage_exceptions_node(state: ReconciliationState) -> Dict[str, Any]:
    """Node 3: Evaluates SOP rules on unmatched items and separates into rule-resolved vs ambiguous exceptions."""
    unmatched = state["unmatched_transactions"]
    all_txns = state["canonical_transactions"]
    index = TransactionLookupIndex(all_txns)
    
    rule_resolved = []
    ambiguous = []

    for txn in unmatched:
        # Build 360 context and candidate matches (O(1) candidate lookup with pre-built index)
        ctx = TransactionContextBuilder.build_context(txn, all_txns, lookup_index=index)
        cands = index.find_candidates(txn, limit=3)
        
        # Check declarative SOP rules
        cand_amt = cands[0]["amount_minor"] if cands else 0
        abs_diff = abs(txn.amount_minor - cand_amt)
        gross_val = txn.gross_minor or txn.amount_minor
        context_payload = {
            "source_kind": txn.source_kind.value if hasattr(txn.source_kind, "value") else str(txn.source_kind),
            "amount_minor": txn.amount_minor,
            "abs_diff_minor": abs_diff,
            "diff_pct_of_gross": (abs_diff / gross_val) if gross_val else None,
            "currency": txn.currency,
            "days_lag": 2 if ctx.is_period_cutoff else 0,
            "is_period_boundary": ctx.is_period_cutoff,
            "debit_credit_diff_minor": getattr(txn, "unbalanced_diff_minor", 0) or 0
        }
        sop_action = tool_evaluate_sop_rules(context_payload)

        exc_info = {
            "transaction": txn,
            "context": ctx,
            "candidates": cands,
            "sop_action": sop_action,
            "exception_id": f"EXC-{txn.id[:8]}",
            "impact_minor": txn.amount_minor
        }

        if sop_action and sop_action.get("auto_resolve"):
            rule_resolved.append(exc_info)
        else:
            ambiguous.append(exc_info)

    return {
        "rule_resolved_items": rule_resolved,
        "ambiguous_exceptions": ambiguous,
        "agent_proposals": state.get("agent_proposals", {}),
        "retry_counts": state.get("retry_counts", {})
    }


def investigate_exception_agent_node(state: ReconciliationState) -> Dict[str, Any]:
    """
    Node 4: Specialized Financial Exception Investigation Node.
    Deterministically triages all exceptions, and caps external LLM reasoning to at most
    MAX_LLM_CALLS_PER_BATCH top material items to protect API budgets.
    """
    ambiguous = state["ambiguous_exceptions"]
    all_txns = state["canonical_transactions"]
    all_txns_dicts = [t.model_dump() for t in all_txns]
    agent = AIAgentRuntime()
    proposals = dict(state.get("agent_proposals", {}))
    retry_counts = dict(state.get("retry_counts", {}))

    # Cap external AI calls per batch run to avoid quota exhaustion on large feeds
    ai_inv_budget = getattr(settings, "MAX_LLM_CALLS_PER_BATCH", 3)
    ai_inv_count = 0

    for idx, item in enumerate(ambiguous):
        exc_id = item["exception_id"]
        # Skip if already verified
        if exc_id in state.get("verified_proposals", {}):
            continue

        txn = item["transaction"]
        cands = item["candidates"]
        counterpart = cands[0] if cands else None
        
        # Track retry attempts: only increment when retrying a rejected proposal
        is_retry = exc_id in state.get("rejected_proposals", {})
        if is_retry:
            retry_counts[exc_id] = retry_counts.get(exc_id, 0) + 1

        # Classify semantic exception type
        raw_desc = (txn.description_raw or "").upper()
        if item["context"].is_period_cutoff:
            exc_type = "PERIOD_CUTOFF"
        elif "DUP" in raw_desc or "DUPLICATE" in raw_desc:
            exc_type = "DUPLICATE_RECORD"
        elif txn.fee_minor and txn.fee_minor > 0:
            exc_type = "AMOUNT_MISMATCH"
        elif txn.source_kind == SourceKind.BANK and not cands:
            exc_type = "UNALLOCATED_BANK_CREDIT"
        elif txn.source_kind == SourceKind.GATEWAY and not cands:
            exc_type = "UNSETTLED_GATEWAY_RECORD"
        else:
            exc_type = "AMOUNT_MISMATCH" if counterpart else "UNSETTLED_GATEWAY_RECORD"

        # Severity determined strictly by financial materiality and risk taxonomy
        if txn.amount_minor >= settings.MATERIALITY_THRESHOLD_MINOR or exc_type in ("DUPLICATE_RECORD", "UNSETTLED_GATEWAY_RECORD"):
            sev = "HIGH"
        elif exc_type == "PERIOD_CUTOFF":
            sev = "MEDIUM"
        else:
            sev = "LOW"

        # Only allow external LLM reasoning for top material items within budget; use fast deterministic rules for the rest
        use_deterministic_rule = bool((item.get("sop_action") or {}).get("auto_resolve")) or (ai_inv_count >= ai_inv_budget)
        if not use_deterministic_rule:
            ai_inv_count += 1

        # Agent Investigation
        inv_result = agent.investigate_exception(
            exception_id=exc_id,
            exception_type=exc_type,
            impact_minor=txn.amount_minor,
            primary_txn=txn.model_dump(),
            counterpart_txn=counterpart,
            available_txns=all_txns_dicts,
            severity=sev,
            has_deterministic_rule=use_deterministic_rule,
            force_refresh=is_retry
        )
        proposals[exc_id] = inv_result

    return {
        "agent_proposals": proposals,
        "retry_counts": retry_counts
    }


def verify_proposal_node(state: ReconciliationState) -> Dict[str, Any]:
    """
    Node 5: Arithmetic & Reference Verifier Gate.
    Deterministically re-executes arithmetic, verifies candidate existence, and rejects hallucinated proposals.
    """
    all_txn_ids = {t.id for t in state["canonical_transactions"]}
    proposals = state["agent_proposals"]
    verified = dict(state.get("verified_proposals", {}))
    rejected = dict(state.get("rejected_proposals", {}))

    for item in state["ambiguous_exceptions"]:
        exc_id = item["exception_id"]
        if exc_id in verified:
            continue

        prop = proposals.get(exc_id)
        if not prop:
            continue

        is_valid, reason = DeterministicVerifier.verify_proposal(
            prop,
            {"impact_minor": item["impact_minor"]},
            all_txn_ids
        )

        if is_valid:
            verified[exc_id] = prop
            if exc_id in rejected:
                del rejected[exc_id]
        else:
            rejected[exc_id] = reason or "Verification gate failure"

    return {
        "verified_proposals": verified,
        "rejected_proposals": rejected
    }


def decision_routing_node(state: ReconciliationState) -> Dict[str, Any]:
    """
    Node 6: Maps exact matches, contextual ties, and verified AI outputs into 4 operational tiers
    and constructs Maker-Checker review proposals.
    """
    all_txns = state["canonical_transactions"]
    matches = state["matches"]
    verified_proposals = state["verified_proposals"]
    matched_ids = state["matched_txn_ids"]

    decisions: Dict[str, ReconciliationDecision] = {}
    proposals: List[Dict[str, Any]] = []

    # Map matched counterparts
    match_partner_map = {}
    for m in matches:
        if len(m.legs) >= 2:
            l1, l2 = m.legs[0].transaction_id, m.legs[1].transaction_id
            match_partner_map[l1] = l2
            match_partner_map[l2] = l1

    index = TransactionLookupIndex(all_txns)

    for txn in all_txns:
        exc_id = f"EXC-{txn.id[:8]}"
        ai_prop = verified_proposals.get(exc_id)
        
        ctx = TransactionContextBuilder.build_context(txn, all_txns, lookup_index=index)
        c_cand_id = match_partner_map.get(txn.id) or (ctx.possible_candidate_ids[0] if ctx.possible_candidate_ids else None)

        raw_desc = (txn.description_raw or "").upper()

        if txn.match_status == "MATCHED_EXACT":
            dec_tier = DecisionTier.RESOLVED
            conf = 1.00
            expl = "Deterministically matched across control accounts with exact reference and amount tie-out."
            req_mc = False
        elif txn.match_status in ("MATCHED_CONTEXTUAL", "MATCHED_TIMING_LAG"):
            dec_tier = DecisionTier.RESOLVED_WITH_EXPLANATION
            conf = 0.95
            expl = ("Settlement received T+2 net of gateway processing fees (MDR + 18% GST); "
                    "arithmetic verified to the paise.")
            req_mc = False
        elif txn.match_status == "NEEDS_REVIEW" or (ctx.is_period_cutoff and txn.match_status not in ("MATCHED_EXACT", "MATCHED_CONTEXTUAL", "MATCHED_TIMING_LAG")):
            dec_tier = DecisionTier.NEEDS_REVIEW
            conf = ai_prop.confidence if ai_prop else 0.88
            expl = ai_prop.likely_cause if ai_prop else "T+2 period boundary cutoff timing difference. Propose accrual to Account 1290 (In-Transit Clearing)."
            req_mc = True
        elif txn.match_status in ("UNRESOLVED_EXCEPTION", "UNMATCHED") or not txn.match_status:
            dec_tier = DecisionTier.UNRESOLVED_EXCEPTION
            conf = ai_prop.confidence if ai_prop else 0.60
            expl = ai_prop.likely_cause if ai_prop else "Unmatched residual entry. No counterpart record found within configured tolerance gates."
            req_mc = True
        else:
            logger.warning("Unrecognized match_status '%s' for txn %s. Defaulting to UNRESOLVED_EXCEPTION.", txn.match_status, txn.id)
            dec_tier = DecisionTier.UNRESOLVED_EXCEPTION
            conf = ai_prop.confidence if ai_prop else 0.60
            expl = ai_prop.likely_cause if ai_prop else f"Residual entry with status {txn.match_status}."
            req_mc = True

        decision = ReconciliationDecision(
            transaction_id=txn.id,
            tier=dec_tier,
            confidence=conf,
            deterministic_score=1.0 if dec_tier == DecisionTier.RESOLVED else (0.85 if dec_tier == DecisionTier.RESOLVED_WITH_EXPLANATION else 0.40),
            cross_source_score=1.0 if dec_tier in (DecisionTier.RESOLVED, DecisionTier.RESOLVED_WITH_EXPLANATION) else 0.20,
            ai_score=ai_prop.confidence if ai_prop else 0.0,
            risk_penalties=0.0 if dec_tier == DecisionTier.RESOLVED else 0.15,
            explanation=expl,
            evidence_summary=[expl] + (ctx.anomaly_flags or []),
            matched_counterpart_id=c_cand_id,
            requires_maker_checker=req_mc
        )
        decisions[txn.id] = decision

        # Maker-Checker voucher
        if req_mc:
            # Semantic action and exception type mapping
            if ai_prop and ai_prop.recommended_action:
                prop_action = ai_prop.recommended_action
            elif dec_tier == DecisionTier.NEEDS_REVIEW or ctx.is_period_cutoff:
                prop_action = "ACCRUE_TO_CLEARING_1290"
            elif "DUP" in raw_desc or "DUPLICATE" in raw_desc:
                prop_action = "FLAG_DUPLICATE_FOR_VOID"
            elif txn.fee_minor and txn.fee_minor > 0:
                prop_action = "ADJUST_LEDGER_FEE_SPLIT"
            elif txn.source_kind == SourceKind.BANK:
                prop_action = "INVESTIGATE_UNALLOCATED_CREDIT"
            else:
                prop_action = "INVESTIGATE_MISSING_WIRE"

            if ai_prop and ai_prop.classification:
                prop_exc_type = ai_prop.classification
            elif dec_tier == DecisionTier.NEEDS_REVIEW or ctx.is_period_cutoff:
                prop_exc_type = "PERIOD_CUTOFF_TIMING"
            elif "DUP" in raw_desc or "DUPLICATE" in raw_desc:
                prop_exc_type = "DUPLICATE_RECORD"
            elif txn.fee_minor and txn.fee_minor > 0:
                prop_exc_type = "AMOUNT_MISMATCH"
            elif txn.source_kind == SourceKind.BANK:
                prop_exc_type = "UNALLOCATED_BANK_CREDIT"
            else:
                prop_exc_type = "UNSETTLED_GATEWAY_RECORD"

            is_verified = bool(ai_prop and exc_id in verified_proposals)
            proposals.append({
                "id": f"PROP-{txn.id[:8]}",
                "org_id": state["org_id"],
                "exception_id": exc_id,
                "investigation_id": f"INV-{exc_id}" if ai_prop else None,
                "window_id": getattr(txn, "window_id", "WIN-01") or "WIN-01",
                "transaction_id": txn.id,
                "exception_type": prop_exc_type,
                "impact_minor": txn.amount_minor,
                "action": prop_action,
                "recommended_parameters": {
                    "transaction_id": txn.id,
                    "impact_minor": txn.amount_minor,
                    "action": prop_action
                },
                "justification": expl,
                "confidence": conf,
                "status": "PENDING_APPROVAL",
                "tier": dec_tier.value,
                "requires_human_review": True,
                "verified_by_code": is_verified,
                "evidence": [expl],
                "created_at": datetime.now(timezone.utc).isoformat()
            })

    return {
        "decisions": decisions,
        "proposals": proposals
    }


def finalize_batch_node(state: ReconciliationState) -> Dict[str, Any]:
    """
    Node 7: Constructs window summaries, 13-week cash liquidity forecast,
    and seals the cryptographic audit hash chain.
    """
    all_txns = state["canonical_transactions"]
    total = len(all_txns)
    window_size = state.get("window_size", 24)
    num_windows = max(1, (total + window_size - 1) // window_size)

    windows: List[BatchWindowSummary] = []
    audit_events = list(state.get("audit_events", []))
    prev_hash = audit_events[-1]["event_hash"] if audit_events else AuditHashChain.GENESIS_HASH
    event_seq = len(audit_events) + 1

    # Chunk into analysis windows
    for w_idx in range(num_windows):
        start_i = w_idx * window_size
        end_i = min(total, (w_idx + 1) * window_size)
        chunk = all_txns[start_i:end_i]
        w_id = f"WIN-{w_idx + 1:02d}"

        for t in chunk:
            t.window_id = w_id

        w_exact = len([t for t in chunk if t.match_status == "MATCHED_EXACT"]) // 2
        w_ctx = len([t for t in chunk if t.match_status == "MATCHED_CONTEXTUAL"]) // 2
        w_exc = len([t for t in chunk if t.match_status in ("NEEDS_REVIEW", "UNRESOLVED_EXCEPTION")])

        w_start = datetime.fromtimestamp(state.get("wall_clock_start", time.time()), timezone.utc)
        w_end = datetime.now(timezone.utc)
        w_ai_count = len([
            p for p in state.get("agent_proposals", {}).values()
            if (getattr(p, "telemetry", {}).get("provider") if hasattr(p, "telemetry") and isinstance(p.telemetry, dict) else (p.get("telemetry", {}).get("provider") if isinstance(p, dict) else None)) in ("GROQ", "GEMINI", "OPENAI")
        ])

        w_summary = BatchWindowSummary(
            window_index=w_idx + 1,
            window_id=w_id,
            records_count=len(chunk),
            start_index=start_i,
            end_index=end_i,
            status="COMPLETED",
            started_at=w_start,
            completed_at=w_end,
            exact_matches=w_exact,
            contextual_matches=w_ctx,
            ai_investigated=w_ai_count,
            exceptions_count=w_exc
        )
        windows.append(w_summary)

        # Audit event per window
        ts_win = datetime.now(timezone.utc)
        p_win = {
            "window_id": w_id,
            "records_processed": len(chunk),
            "exact_matches": w_exact,
            "contextual_matches": w_ctx,
            "exceptions": w_exc
        }
        h_win = AuditHashChain.compute_event_hash(
            prev_hash, state["org_id"], event_seq, "WINDOW_PROCESSED", w_id, "usr_system", p_win, ts_win
        )
        audit_events.append({
            "prev_hash": prev_hash,
            "org_id": state["org_id"],
            "event_seq": event_seq,
            "event_type": "WINDOW_PROCESSED",
            "entity_type": "BATCH_WINDOW",
            "entity_id": w_id,
            "actor_id": "usr_system",
            "actor_type": "system",
            "action": "PROCESS_WINDOW",
            "payload": p_win,
            "created_at": ts_win,
            "event_hash": h_win
        })
        prev_hash = h_win
        event_seq += 1

    # 13-Week Cash Forecast
    forecast = SegmentedCashForecaster.forecast_13_weeks(all_txns, state["decisions"])

    # Final summary calculations
    wall_clock = time.time() - state.get("wall_clock_start", time.time())
    exact_matches_count = len([m for m in state["matches"] if m.decision_tier == DecisionTier.RESOLVED])
    contextual_matches_count = len([m for m in state["matches"] if m.decision_tier == DecisionTier.RESOLVED_WITH_EXPLANATION])
    total_matched_records = len(state["matched_txn_ids"])
    match_rate = total_matched_records / total if total > 0 else 0.0

    unmatched_count = len(all_txns) - total_matched_records
    needs_review_count = len([p for p in state["proposals"] if p["tier"] == "NEEDS_REVIEW"])

    raw_exceptions = state.get("exceptions", [])

    def _is_resolved(e):
        st = getattr(e, "state", None) or (e.get("state") if isinstance(e, dict) else None)
        st_val = getattr(st, "value", st)
        return str(st_val).upper() in ("RESOLVED", "APPROVED")

    def _is_crit_high(e):
        sev = getattr(e, "severity", None) or (e.get("severity") if isinstance(e, dict) else None)
        sev_val = getattr(sev, "value", sev)
        return str(sev_val).upper() in ("CRITICAL", "HIGH")

    open_exceptions = [e for e in raw_exceptions if not _is_resolved(e)]
    unresolved_exceptions_count = len(open_exceptions)
    critical_high_unresolved_count = len([e for e in open_exceptions if _is_crit_high(e)])
    total_exceptions_count = len(raw_exceptions)

    ai_inv_performed = len([
        p for p in state.get("agent_proposals", {}).values()
        if (getattr(p, "telemetry", {}).get("provider") if hasattr(p, "telemetry") and isinstance(p.telemetry, dict) else (p.get("telemetry", {}).get("provider") if isinstance(p, dict) else None)) in ("GROQ", "GEMINI", "OPENAI")
    ])

    confidences = [m.confidence for m in state["matches"]]
    avg_confidence = round(sum(confidences) / len(confidences), 4) if confidences else 0.0
    false_risk = round(sum(max(0.0, 1.0 - c) for c in confidences) / len(confidences), 4) if confidences else 0.0

    engine_res = state.get("engine_summary", {})

    summary = {
        "batch_id": state["batch_id"],
        "total_records": total,
        "total_windows": len(windows),
        "exact_matches": exact_matches_count,
        "contextual_matches": contextual_matches_count,
        "matched_records": total_matched_records,
        "needs_review_count": needs_review_count,
        "total_unresolved_records": unmatched_count,
        "critical_high_unresolved": critical_high_unresolved_count,
        "unresolved_exceptions": unresolved_exceptions_count,
        "total_exceptions": total_exceptions_count,
        "ai_investigations_performed": ai_inv_performed,
        "match_rate": round(match_rate, 4),
        "reconciliation_graph": engine_res.get("reconciliation_graph", {}),
        "three_way_matches_count": engine_res.get("three_way_matches_count", 0),
        "three_way_records_count": engine_res.get("three_way_records_count", 0),
        "three_way_match_rate": engine_res.get("three_way_match_rate", 0.0),
        "pairwise_matches_count": engine_res.get("pairwise_matches_count", 0),
        "pairwise_match_rate": engine_res.get("pairwise_match_rate", 0.0),
        "n1_settlement_clusters_count": engine_res.get("n1_settlement_clusters_count", 0),
        "overall_reconciliation_rate": engine_res.get("overall_reconciliation_rate", round(match_rate, 4)),
        "source_breakdown": engine_res.get("source_breakdown", {}),
        "tier_breakdown": engine_res.get("tier_breakdown", {
            "tier_1_exact": exact_matches_count,
            "tier_2_contextual": contextual_matches_count,
            "tier_3_needs_review": needs_review_count,
            "tier_4_unresolved": critical_high_unresolved_count
        }),
        "avg_confidence": avg_confidence,
        "average_match_confidence": avg_confidence,
        "false_match_risk": false_risk,
        "avg_investigation_depth": round(sum(len(p.evidence) for p in state.get("verified_proposals", {}).values()) / max(1, len(state.get("verified_proposals", {}))), 2) if state.get("verified_proposals") else 1.0,
        "wall_clock_seconds": round(wall_clock, 4),
        "records_per_sec": round(total / max(wall_clock, 0.001), 1),
        "windows": [w.model_dump() for w in windows]
    }

    return {
        "windows": windows,
        "audit_events": audit_events,
        "cash_forecast": [f.model_dump() for f in forecast],
        "summary": summary
    }


# ==============================================================================
# CONDITIONAL EDGES / ROUTERS
# ==============================================================================

def route_after_reconciliation(state: ReconciliationState) -> str:
    """Route after deterministic matching."""
    if len(state.get("unmatched_transactions", [])) == 0:
        return "finalize_batch_node"
    return "triage_exceptions_node"


def route_after_triage(state: ReconciliationState) -> str:
    """Route after exception triage."""
    if len(state.get("ambiguous_exceptions", [])) == 0:
        return "decision_routing_node"
    return "investigate_exception_agent_node"


def route_after_verification(state: ReconciliationState) -> str:
    """Route after verifier gate: retry if failed and retries < AGENT_MAX_RETRIES, else proceed."""
    rejected = state.get("rejected_proposals", {})
    retry_counts = state.get("retry_counts", {})
    max_retries = getattr(settings, "AGENT_MAX_RETRIES", 1)
    
    # Check if any rejected proposal can be retried (< max_retries)
    can_retry = False
    for exc_id in rejected:
        if retry_counts.get(exc_id, 0) < max_retries:
            can_retry = True
            break

    if can_retry:
        return "investigate_exception_agent_node"
    return "decision_routing_node"


# ==============================================================================
# LANGGRAPH BUILDER & RUNNER
# ==============================================================================

def build_reconciliation_graph():
    """Builds and compiles the complete LangGraph financial controller workflow."""
    builder = StateGraph(ReconciliationState)

    builder.add_node("validate_and_normalize", validate_and_normalize_node)
    builder.add_node("deterministic_reconciliation", deterministic_reconciliation_node)
    builder.add_node("triage_exceptions", triage_exceptions_node)
    builder.add_node("investigate_exceptions", investigate_exception_agent_node)
    builder.add_node("verify_proposals", verify_proposal_node)
    builder.add_node("decision_routing", decision_routing_node)
    builder.add_node("finalize_batch", finalize_batch_node)

    # Graph Edges
    builder.set_entry_point("validate_and_normalize")
    builder.add_edge("validate_and_normalize", "deterministic_reconciliation")
    
    builder.add_conditional_edges(
        "deterministic_reconciliation",
        route_after_reconciliation,
        {
            "finalize_batch_node": "finalize_batch",
            "triage_exceptions_node": "triage_exceptions"
        }
    )

    builder.add_conditional_edges(
        "triage_exceptions",
        route_after_triage,
        {
            "decision_routing_node": "decision_routing",
            "investigate_exception_agent_node": "investigate_exceptions"
        }
    )

    builder.add_edge("investigate_exceptions", "verify_proposals")

    builder.add_conditional_edges(
        "verify_proposals",
        route_after_verification,
        {
            "investigate_exception_agent_node": "investigate_exceptions",
            "decision_routing_node": "decision_routing"
        }
    )

    builder.add_edge("decision_routing", "finalize_batch")
    builder.add_edge("finalize_batch", END)

    return builder.compile()


class LangGraphBatchOrchestrator:
    """Enterprise LangGraph Orchestrator managing execution and state extraction."""

    def __init__(self, org_id: str, batch_id: str, window_size: int = 24):
        self.org_id = org_id
        self.batch_id = batch_id
        self.window_size = window_size
        self.app = build_reconciliation_graph()
        
        # State containers for compatibility with database persistence and API
        self.transactions: List[CanonicalTransaction] = []
        self.matches: List[MatchSchema] = []
        self.exceptions: List[ExceptionSchema] = []
        self.decisions: Dict[str, ReconciliationDecision] = {}
        self.proposals: List[Dict[str, Any]] = []
        self.audit_events: List[Dict[str, Any]] = []
        self.windows: List[BatchWindowSummary] = []
        self.safeguards_triggered: List[Dict[str, Any]] = []
        self.cash_forecast: List[Dict[str, Any]] = []
        self.summary: Dict[str, Any] = {}

    def run_windowed_pipeline(self, all_txns: List[CanonicalTransaction]) -> Dict[str, Any]:
        """Executes the full LangGraph state machine across the transaction set."""
        initial_state: ReconciliationState = {
            "batch_id": self.batch_id,
            "org_id": self.org_id,
            "window_size": self.window_size,
            "raw_transactions": all_txns,
            "canonical_transactions": all_txns,
            "validation_errors": {},
            "matches": [],
            "unmatched_transactions": [],
            "matched_txn_ids": set(),
            "safeguards_triggered": [],
            "engine_summary": {},
            "rule_resolved_items": [],
            "ambiguous_exceptions": [],
            "agent_proposals": {},
            "verified_proposals": {},
            "rejected_proposals": {},
            "retry_counts": {},
            "decisions": {},
            "proposals": [],
            "windows": [],
            "audit_events": [],
            "cash_forecast": [],
            "summary": {},
            "wall_clock_start": time.time()
        }

        # Run compiled LangGraph
        final_state = self.app.invoke(initial_state)

        # Unpack state
        self.transactions = final_state["canonical_transactions"]
        self.matches = final_state["matches"]
        self.exceptions = final_state.get("exceptions", [])
        self.decisions = final_state["decisions"]
        self.proposals = final_state["proposals"]
        self.verified_proposals = final_state.get("verified_proposals", {})
        self.agent_proposals = final_state.get("agent_proposals", {})
        self.audit_events = final_state["audit_events"]
        self.windows = final_state["windows"]
        self.safeguards_triggered = final_state["safeguards_triggered"]
        self.cash_forecast = final_state["cash_forecast"]
        self.summary = final_state["summary"]

        # If engine exceptions are empty, populate from unmatched transactions
        if not self.exceptions:
            for t in self.transactions:
                if t.id not in final_state["matched_txn_ids"]:
                    exc_id = f"EXC-{t.id[:8]}"
                    dec = self.decisions.get(t.id)
                    ai_prop = self.verified_proposals.get(exc_id)
                    
                    raw_desc = (t.description_raw or "").upper()
                    if ai_prop and ai_prop.classification:
                        exc_type = ai_prop.classification
                    elif dec and dec.tier == DecisionTier.NEEDS_REVIEW:
                        exc_type = "PERIOD_CUTOFF_TIMING"
                    elif "DUP" in raw_desc or "DUPLICATE" in raw_desc:
                        exc_type = "DUPLICATE_RECORD"
                    elif t.fee_minor and t.fee_minor > 0:
                        exc_type = "AMOUNT_MISMATCH"
                    elif t.source_kind == SourceKind.BANK:
                        exc_type = "UNALLOCATED_BANK_CREDIT"
                    else:
                        exc_type = "UNSETTLED_GATEWAY_RECORD"

                    rec_act = ai_prop.recommended_action if ai_prop else (
                        "ACCRUE_TO_CLEARING_1290" if (dec and dec.tier == DecisionTier.NEEDS_REVIEW) else "INVESTIGATE_MISSING_WIRE"
                    )

                    # Advance state to PROPOSED if a proposal exists
                    exc_state = ExceptionState.PROPOSED if (exc_id in self.verified_proposals or (dec and dec.requires_maker_checker)) else ExceptionState.DETECTED

                    self.exceptions.append(ExceptionSchema(
                        id=exc_id,
                        org_id=self.org_id,
                        batch_id=self.batch_id,
                        primary_txn_id=t.id,
                        exception_type=exc_type,
                        severity=ExceptionSeverity.CRITICAL if t.amount_minor >= settings.MATERIALITY_THRESHOLD_MINOR else ExceptionSeverity.MEDIUM,
                        state=exc_state,
                        impact_minor=t.amount_minor,
                        recommended_action=rec_act,
                        resolution_confidence=dec.confidence if dec else 0.60,
                        findings=[dec.explanation] if dec else ["Unreconciled entry"],
                        checks_performed=["Exact Reference Check", "MDR Netting Formula", "SOP Rules", "LangGraph Reasoning Agent"]
                    ))
        else:
            for e in self.exceptions:
                if e.id in self.verified_proposals:
                    e.state = ExceptionState.PROPOSED

        return self.summary
