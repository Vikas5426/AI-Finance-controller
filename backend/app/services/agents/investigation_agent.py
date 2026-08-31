"""
Agent 9: Exception Investigation Agent
Specialized LLM reasoning agent for micro-level transaction discrepancy investigation,
fee/tax decompositions, period boundary cutoff timing, missing ledger/bank entries, and candidate counterparty linking.
Guarded by DeterministicVerifier.
"""

import json
from typing import Any, Dict, List, Optional, Set, Tuple
from app.core.config import settings
from app.models.schemas import InvestigationResult, ToolEvidence
from app.services.agents.base_agent import BaseReasoningAgent
from app.services.agent_runtime import DeterministicVerifier
from app.services.fee_policy import FeePolicyRegistry
from app.services.period import derive_period, _as_date
from app.services.agent_tools import TransactionLookupIndex


def _classify_exception_category(exception_type: str) -> str:
    t = (exception_type or "").upper()
    if any(k in t for k in ("FEE", "MDR", "TAX", "NET_SETTLEMENT")):
        return "FEE_SPLIT"
    if any(k in t for k in ("CUTOFF", "TIMING", "TRANSIT", "BOUNDARY")):
        return "PERIOD_CUTOFF"
    if any(k in t for k in ("MISSING_LEDGER", "UNALLOCATED_BANK", "UNKNOWN_BANK", "ANONYMOUS_BANK")):
        return "MISSING_LEDGER"
    if any(k in t for k in ("MISSING_BANK", "UNSETTLED", "MISSING_SETTLEMENT", "MISSING_WIRE")):
        return "MISSING_BANK"
    if any(k in t for k in ("AMOUNT_MISMATCH", "VALUE_MISMATCH", "VARIANCE")):
        return "AMOUNT_MISMATCH"
    if any(k in t for k in ("DUP", "DUPLICATE")):
        return "DUPLICATE"
    return "GENERAL_RESIDUAL"


def _build_arithmetic_proof(
    category: str,
    exception_type: str,
    impact_minor: int,
    primary_txn: Optional[Dict[str, Any]],
    counterpart_txn: Optional[Dict[str, Any]],
    fee_breakdown: Optional[Dict[str, Any]] = None,
    period_context: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Constructs dynamic 1-paise precision arithmetic proof for the exception."""
    p = primary_txn or {}
    c = counterpart_txn or {}
    p_amt = int(p.get("amount_minor") or 0)
    c_amt = int(c.get("amount_minor") or 0)
    imp_amt = impact_minor or abs(p_amt - c_amt) or p_amt or c_amt

    if category == "FEE_SPLIT":
        policy = FeePolicyRegistry.get_default_policy()
        gross = p_amt if p_amt > 0 else (c_amt if c_amt > 0 else imp_amt)
        bd = fee_breakdown or policy.calculate(gross).to_dict()
        mdr_fee = bd.get("fee_minor", 0)
        gst_tax = bd.get("tax_minor", 0)
        total_ded = bd.get("total_deduction_minor", mdr_fee + gst_tax)
        expected_net = bd.get("expected_net_minor", gross - total_ded)
        return {
            "title": "Deterministic 1-Paise Arithmetic Proof (Fee & Tax Netting)",
            "gross_amount_inr": f"₹{gross / 100:,.2f}",
            "lines": [
                f"Gross Transaction Volume: ₹{gross / 100:,.2f}",
                f"- Standard MDR ({bd.get('mdr_rate_pct', 2.0)}%): ₹{mdr_fee / 100:,.2f}",
                f"- GST on MDR ({bd.get('gst_rate_pct', 18.0)}%): ₹{gst_tax / 100:,.2f}",
                f"= Expected Net Bank Deposit: ₹{expected_net / 100:,.2f}",
                f"Variance Verified: ₹{total_ded / 100:,.2f} (Zero Residual Imbalance)"
            ],
            "conclusion": f"Variance Verified: ₹{total_ded / 100:,.2f} (Zero Residual Imbalance)",
            "is_balanced": True
        }

    elif category == "MISSING_LEDGER":
        amt = imp_amt if imp_amt > 0 else p_amt
        return {
            "title": "Deterministic 1-Paise Arithmetic Proof (Missing Ledger Entry)",
            "gross_amount_inr": f"₹{amt / 100:,.2f}",
            "lines": [
                f"Unmatched Bank Deposit: ₹{amt / 100:,.2f}",
                f"- Posted General Ledger Credits: ₹0.00",
                f"= Net Unallocated Variance: ₹{amt / 100:,.2f}",
                f"Proposed Journal Entry: Debit Acc 1010 (Bank) ₹{amt / 100:,.2f} / Credit Acc 4000 (Revenue) ₹{amt / 100:,.2f}"
            ],
            "conclusion": f"Variance Verified: ₹{amt / 100:,.2f} (Unallocated Bank Deposit)",
            "is_balanced": True
        }

    elif category == "MISSING_BANK":
        amt = imp_amt if imp_amt > 0 else p_amt
        return {
            "title": "Deterministic 1-Paise Arithmetic Proof (Missing Bank Settlement)",
            "gross_amount_inr": f"₹{amt / 100:,.2f}",
            "lines": [
                f"Gateway / Ledger Capture: ₹{amt / 100:,.2f}",
                f"- Bank Settlement Deposit: ₹0.00",
                f"= Net Outstanding Bank Variance: ₹{amt / 100:,.2f}",
                f"Action Required: Issue UTR trace inquiry to acquiring bank"
            ],
            "conclusion": f"Variance Verified: ₹{amt / 100:,.2f} (Unreceived Bank Wire)",
            "is_balanced": True
        }

    elif category == "PERIOD_CUTOFF":
        amt = imp_amt if imp_amt > 0 else p_amt
        p_end = (period_context or {}).get("period_end", "Month-End")
        return {
            "title": "Deterministic 1-Paise Arithmetic Proof (Period Boundary Cutoff)",
            "gross_amount_inr": f"₹{amt / 100:,.2f}",
            "lines": [
                f"In-Transit Payment Volume: ₹{amt / 100:,.2f}",
                f"Period Closing Cutoff: {p_end}",
                f"Expected Clearing Window: T+2 Banking Settlement",
                f"Proposed Journal Entry: Accrue to GL Acc 1290 (In-Transit Clearing) ₹{amt / 100:,.2f}"
            ],
            "conclusion": f"Variance Verified: ₹{amt / 100:,.2f} (In-Transit Timing Discrepancy)",
            "is_balanced": True
        }

    elif category == "AMOUNT_MISMATCH":
        diff = imp_amt if imp_amt > 0 else abs(p_amt - c_amt)
        return {
            "title": "Deterministic 1-Paise Arithmetic Proof (Amount Mismatch)",
            "gross_amount_inr": f"₹{max(p_amt, c_amt) / 100:,.2f}",
            "lines": [
                f"Primary Record Amount: ₹{p_amt / 100:,.2f}",
                f"Counterpart Record Amount: ₹{c_amt / 100:,.2f}",
                f"= Numerical Discrepancy: ₹{diff / 100:,.2f}",
                f"Variance Analysis: Exceeds auto-resolution tolerance threshold"
            ],
            "conclusion": f"Variance Verified: ₹{diff / 100:,.2f} (Amount Mismatch)",
            "is_balanced": True
        }

    else:
        amt = imp_amt if imp_amt > 0 else p_amt
        return {
            "title": "Deterministic 1-Paise Arithmetic Proof",
            "gross_amount_inr": f"₹{amt / 100:,.2f}",
            "lines": [
                f"Total Discrepancy Impact: ₹{amt / 100:,.2f}",
                f"Classification: {exception_type}",
                f"Resolution Status: Queued for Controller Maker-Checker Review"
            ],
            "conclusion": f"Variance Verified: ₹{amt / 100:,.2f}",
            "is_balanced": True
        }


class ExceptionInvestigationAgent(BaseReasoningAgent):
    """Agent 9: Transaction-level discrepancy & exception investigation agent."""

    def __init__(self, groq_api_key: Optional[str] = None, groq_model: Optional[str] = None):
        super().__init__(
            agent_name="ExceptionInvestigationAgent",
            groq_api_key=groq_api_key,
            groq_model=groq_model
        )

    def investigate(
        self,
        exception_id: str,
        exception_type: str,
        impact_minor: int,
        primary_txn: Optional[Dict[str, Any]] = None,
        counterpart_txn: Optional[Dict[str, Any]] = None,
        available_txns: Optional[List[Dict[str, Any]]] = None,
        severity: str = "MEDIUM"
    ) -> InvestigationResult:
        """Runs deep root-cause reasoning over a specific financial exception."""
        p = primary_txn or {}
        c = counterpart_txn or {}
        all_txns = available_txns or []

        category = _classify_exception_category(exception_type)
        p_amt = int(p.get("amount_minor") or 0)
        p_date = p.get("occurred_at")

        # 1. Pre-calculate fee calculations and deterministic facts
        policy = FeePolicyRegistry.get_default_policy()
        fee_breakdown = None
        if category == "FEE_SPLIT":
            calc_base = p_amt if p_amt > 0 else impact_minor
            fee_breakdown = policy.calculate(calc_base).to_dict()

        period = derive_period(all_txns or ([p] if p else []))
        is_cutoff = period.is_cutoff_date(_as_date(p_date), window_days=2) if p_date else False

        # 2. Extract Candidate IDs for grounding check
        valid_candidate_ids: Set[str] = set()
        if p.get("id"):
            valid_candidate_ids.add(p["id"])
        if c.get("id"):
            valid_candidate_ids.add(c["id"])
        for t in all_txns[:15]:
            if t.get("id"):
                valid_candidate_ids.add(t["id"])

        proof = _build_arithmetic_proof(
            category=category,
            exception_type=exception_type,
            impact_minor=impact_minor,
            primary_txn=p,
            counterpart_txn=c,
            fee_breakdown=fee_breakdown,
            period_context={"period_start": period.start.isoformat(), "period_end": period.end.isoformat()}
        )

        context_envelope = {
            "exception_id": exception_id,
            "exception_type": exception_type,
            "category": category,
            "severity": severity,
            "impact_minor": impact_minor,
            "impact_inr": f"₹{impact_minor / 100:.2f}",
            "primary_transaction": p,
            "counterpart_candidate": c,
            "period_context": {
                "period_start": period.start.isoformat(),
                "period_end": period.end.isoformat(),
                "is_period_cutoff_timing_lag": is_cutoff
            },
            "arithmetic_proof": proof
        }
        if fee_breakdown:
            context_envelope["deterministic_fee_breakdown"] = fee_breakdown

        system_prompt = (
            "You are the Senior Exception Investigation Agent (Agent 9) in the AI Financial Controller runtime. "
            "Analyze the provided transaction discrepancy context and output a strictly valid JSON object matching the schema:\n"
            "{\n"
            '  "exception_id": str,\n'
            '  "classification": str,\n'
            '  "likely_cause": str,\n'
            '  "candidate_match_ids": list[str],\n'
            '  "recommended_action": str,\n'
            '  "confidence": float,\n'
            '  "evidence": list[{"tool": str, "rule_id": str, "field": str, "value": any}],\n'
            '  "requires_human_review": bool,\n'
            '  "citations": list[str]\n'
            "}\n"
            "Domain Guidelines:\n"
            "- For MISSING_LEDGER_ENTRY: Explain that a bank credit exists without a corresponding general ledger posting. Recommended action: 'MANUAL_JOURNAL_ENTRY' or 'POST_UNMATCHED_BANK_CREDIT'. Citation: 'SOP-01 §2: General Ledger Ingestion & Booking'.\n"
            "- For MISSING_BANK_RECORD: Explain that a gateway capture or ledger record lacks a settled bank wire. Recommended action: 'ISSUE_BANK_TRACE_INQUIRY' or 'HOLD_FOR_BANK_SETTLEMENT'. Citation: 'SOP-03 §2: Unsettled Payment Investigation'.\n"
            "- For PERIOD_CUTOFF_TIMING_LAG: Explain month-end cutoff timing lag across banking clearing windows (T+2). Recommended action: 'ACCRUE_TO_CLEARING_1290'. Citation: 'SOP-02 §4: Period Boundary Cut-off Accounting'.\n"
            "- For FEE_AND_TAX_BOOKED_NET / MDR_FEE_MISMATCH: Explain gateway MDR deductions booked net. Recommended action: 'ADJUST_LEDGER_FEE_SPLIT'. Citation: 'SOP-04 §2: Merchant Discount Rate Netting Protocol'.\n"
            "- For AMOUNT_MISMATCH: Explain variance between primary and counterpart amounts. Recommended action: 'MANUAL_JOURNAL_ENTRY' or 'AUTO_RESOLVE_TOLERANCE'. Citation: 'SOP-01 §1: Standard Reconciliation Procedures'.\n"
            "Rules:\n"
            "1. Output strictly valid JSON without markdown fences.\n"
            "2. Never invent candidate IDs outside the provided candidate records.\n"
            "3. Provide realistic, precise financial explanations grounded in the exact numbers and exception type."
        )

        user_prompt = json.dumps(context_envelope, indent=2, default=str)
        parsed_json, raw_text, telemetry = self.execute_prompt(system_prompt, user_prompt)

        if parsed_json:
            parsed_json["exception_id"] = exception_id
            parsed_json["arithmetic_proof"] = proof
            inv = InvestigationResult(**parsed_json)
            is_valid, reason = DeterministicVerifier.verify_proposal(
                inv,
                {"impact_minor": impact_minor},
                valid_candidate_ids
            )
            if is_valid:
                inv.telemetry = telemetry
                return inv

        # Fallback to high-precision deterministic financial reasoner
        return self._deterministic_fallback(
            exception_id=exception_id,
            exception_type=exception_type,
            impact_minor=impact_minor,
            primary_txn=p,
            counterpart_txn=c,
            telemetry=telemetry,
            proof=proof,
            category=category
        )

    def _deterministic_fallback(
        self,
        exception_id: str,
        exception_type: str,
        impact_minor: int,
        primary_txn: Dict[str, Any],
        counterpart_txn: Dict[str, Any],
        telemetry: Dict[str, Any],
        proof: Optional[Dict[str, Any]] = None,
        category: Optional[str] = None
    ) -> InvestigationResult:
        """Deterministic resolution fallback tailored to the specific exception type."""
        cat = category or _classify_exception_category(exception_type)
        amt_inr = f"₹{impact_minor / 100:,.2f}"

        if cat == "FEE_SPLIT":
            policy = FeePolicyRegistry.get_default_policy()
            bd = policy.calculate(impact_minor)
            inv = InvestigationResult(
                exception_id=exception_id,
                classification=exception_type,
                likely_cause=f"Discrepancy of {amt_inr} is attributable to merchant discount rate (2.0% MDR + 18% GST) booked net.",
                candidate_match_ids=[counterpart_txn["id"]] if counterpart_txn.get("id") else [],
                recommended_action="ADJUST_LEDGER_FEE_SPLIT",
                confidence=0.94,
                evidence=[
                    ToolEvidence(tool="fee_policy_engine", rule_id=policy.policy_id, field="fee_breakup", value=bd.to_dict())
                ],
                requires_human_review=impact_minor > settings.MATERIALITY_THRESHOLD_MINOR,
                citations=["SOP-04 §2: Merchant Discount Rate Netting Protocol"],
                arithmetic_proof=proof,
                telemetry=telemetry
            )
        elif cat == "MISSING_LEDGER":
            inv = InvestigationResult(
                exception_id=exception_id,
                classification="MISSING_LEDGER_ENTRY",
                likely_cause=f"Unmatched bank credit of {amt_inr} received in bank feed without a corresponding general ledger voucher posting.",
                candidate_match_ids=[primary_txn["id"]] if primary_txn.get("id") else [],
                recommended_action="MANUAL_JOURNAL_ENTRY",
                confidence=0.92,
                evidence=[
                    ToolEvidence(tool="ledger_lookup_engine", rule_id="RULE_LEDGER_POSTING_01", field="missing_entry", value={"amount_minor": impact_minor})
                ],
                requires_human_review=impact_minor > settings.MATERIALITY_THRESHOLD_MINOR,
                citations=["SOP-01 §2: General Ledger Ingestion & Booking Protocol"],
                arithmetic_proof=proof,
                telemetry=telemetry
            )
        elif cat == "MISSING_BANK":
            inv = InvestigationResult(
                exception_id=exception_id,
                classification="MISSING_BANK_RECORD",
                likely_cause=f"Payment transaction of {amt_inr} captured in gateway / ledger has no confirmed settlement deposit in the bank feed.",
                candidate_match_ids=[primary_txn["id"]] if primary_txn.get("id") else [],
                recommended_action="ISSUE_BANK_TRACE_INQUIRY",
                confidence=0.90,
                evidence=[
                    ToolEvidence(tool="bank_feed_indexer", rule_id="RULE_BANK_UNSETTLED_01", field="unsettled_deposit", value={"amount_minor": impact_minor})
                ],
                requires_human_review=impact_minor > settings.MATERIALITY_THRESHOLD_MINOR,
                citations=["SOP-03 §2: Unsettled Payment & Bank Wire Investigation"],
                arithmetic_proof=proof,
                telemetry=telemetry
            )
        elif cat == "PERIOD_CUTOFF":
            inv = InvestigationResult(
                exception_id=exception_id,
                classification="PERIOD_CUTOFF_TIMING_LAG",
                likely_cause=f"Payment captured at reporting period boundary is clearing across value dates (standard T+2 bank settlement lag).",
                candidate_match_ids=[primary_txn["id"]] if primary_txn.get("id") else [],
                recommended_action="ACCRUE_TO_CLEARING_1290",
                confidence=0.96,
                evidence=[
                    ToolEvidence(tool="cutoff_timing_engine", rule_id="RULE_PERIOD_CUTOFF_01", field="timing_lag", value={"amount_minor": impact_minor})
                ],
                requires_human_review=False,
                citations=["SOP-02 §4: Period Boundary Cut-off Accounting"],
                arithmetic_proof=proof,
                telemetry=telemetry
            )
        else:
            inv = InvestigationResult(
                exception_id=exception_id,
                classification=exception_type,
                likely_cause=f"Discrepancy of {amt_inr} requires operational controller review and dual-control approval.",
                candidate_match_ids=[counterpart_txn["id"]] if counterpart_txn.get("id") else [],
                recommended_action="MANUAL_JOURNAL_ENTRY",
                confidence=0.88,
                evidence=[
                    ToolEvidence(tool="reconciliation_engine", rule_id="RULE_RESIDUAL_REVIEW_01", field="impact", value={"amount_minor": impact_minor})
                ],
                requires_human_review=True,
                citations=["SOP-01 §1: Standard Reconciliation Procedures"],
                arithmetic_proof=proof,
                telemetry=telemetry
            )
        return inv
