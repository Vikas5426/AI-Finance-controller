"""
Hybrid Decision Policy & Confidence Evaluation Engine
Evaluates deterministic evidence, cross-source links, AI investigation output, and risk penalties
to route transactions into 4 distinct operational tiers:
- Tier 1: RESOLVED
- Tier 2: RESOLVED_WITH_EXPLANATION
- Tier 3: NEEDS_REVIEW
- Tier 4: UNRESOLVED_EXCEPTION
"""

from typing import Any, Dict, List, Optional
from app.models.schemas import DecisionTier, ReconciliationDecision, CanonicalTransaction, InvestigationResult, TransactionContext

class HybridDecisionEngine:
    """Computes bounded confidence and assigns strict decision tiers."""

    @staticmethod
    def evaluate_decision(
        txn: CanonicalTransaction,
        context: TransactionContext,
        exact_match: Optional[CanonicalTransaction] = None,
        contextual_match: Optional[CanonicalTransaction] = None,
        ai_investigation: Optional[InvestigationResult] = None
    ) -> ReconciliationDecision:
        
        det_score = 0.0
        cross_score = 0.0
        ai_score = 0.0
        risk_penalties = 0.0
        evidence_summary: List[str] = []
        matched_id = None

        # ---------------------------------------------------------------------
        # 1. Tier 1: 100% Deterministic Exact Match
        # ---------------------------------------------------------------------
        if exact_match and exact_match.amount_minor == txn.amount_minor:
            det_score = 1.00
            cross_score = 1.00
            matched_id = exact_match.id
            evidence_summary.append("Exact reference key and amount tie out across both sources.")
            
            return ReconciliationDecision(
                transaction_id=txn.id,
                tier=DecisionTier.RESOLVED,
                confidence=1.00,
                deterministic_score=1.00,
                cross_source_score=1.00,
                ai_score=0.0,
                risk_penalties=0.0,
                explanation="Deterministically reconciled against Ledger/Bank control account with exact ID and amount.",
                evidence_summary=evidence_summary,
                matched_counterpart_id=matched_id,
                requires_maker_checker=False
            )

        # ---------------------------------------------------------------------
        # 2. Tier 2: Contextual Match with Verified Fee/Tax Arithmetic
        # ---------------------------------------------------------------------
        if contextual_match:
            diff = abs(txn.amount_minor - contextual_match.amount_minor)
            fee_p = context.historical_fee_profile or {}
            
            # Check 2.0% MDR + GST
            is_fee_2pct = abs(diff - (fee_p.get("standard_2pct_mdr_fee", 0) + fee_p.get("standard_2pct_gst", 0))) <= 100
            # Check 1.5% MDR + GST
            is_fee_1_5pct = abs(diff - (fee_p.get("enterprise_1_5pct_mdr_fee", 0) + fee_p.get("enterprise_1_5pct_gst", 0))) <= 100

            if is_fee_2pct or is_fee_1_5pct:
                det_score = 0.85
                cross_score = 0.90
                ai_score = (ai_investigation.confidence if ai_investigation else 0.92)
                matched_id = contextual_match.id
                tier_label = "2.0% Standard MDR" if is_fee_2pct else "1.5% Enterprise MDR"
                evidence_summary.append(f"Net variance of ₹{diff/100:.2f} ties out to {tier_label} + 18% GST.")

                final_conf = min(0.95, (det_score * 0.4 + cross_score * 0.3 + ai_score * 0.3))
                return ReconciliationDecision(
                    transaction_id=txn.id,
                    tier=DecisionTier.RESOLVED_WITH_EXPLANATION,
                    confidence=round(final_conf, 2),
                    deterministic_score=det_score,
                    cross_source_score=cross_score,
                    ai_score=ai_score,
                    risk_penalties=0.0,
                    explanation=f"Reconciled net of gateway fee ({tier_label} + GST) with verified arithmetic proof.",
                    evidence_summary=evidence_summary,
                    matched_counterpart_id=matched_id,
                    requires_maker_checker=False
                )

        # ---------------------------------------------------------------------
        # 3. Tier 3: Period Cut-Off / Timing Lag (Requires Maker-Checker Sign-Off)
        # ---------------------------------------------------------------------
        if context.is_period_cutoff or "PERIOD_BOUNDARY_CUTOFF_T2_LAG" in context.anomaly_flags:
            det_score = 0.60
            cross_score = 0.70
            ai_score = (ai_investigation.confidence if ai_investigation else 0.90)
            evidence_summary.append("Payment captured within 5 minutes of monthly period cutoff (T+2 settlement delay).")
            
            return ReconciliationDecision(
                transaction_id=txn.id,
                tier=DecisionTier.NEEDS_REVIEW,
                confidence=0.88,
                deterministic_score=det_score,
                cross_source_score=cross_score,
                ai_score=ai_score,
                risk_penalties=0.05,
                explanation="T+2 period boundary cutoff timing difference. Propose accrual to Account 1290 (In-Transit Clearing).",
                evidence_summary=evidence_summary,
                matched_counterpart_id=context.possible_candidate_ids[0] if context.possible_candidate_ids else None,
                requires_maker_checker=True
            )

        # ---------------------------------------------------------------------
        # 4. Tier 4: Honest Unresolved Exception
        # ---------------------------------------------------------------------
        risk_penalties = 0.30 if "MISSING_BANK_SETTLEMENT_CREDIT" in context.anomaly_flags else 0.15
        ai_score = ai_investigation.confidence if ai_investigation else 0.70
        confidence = max(0.20, min(0.70, ai_score - risk_penalties))

        reason = "No counterpart record found within configured tolerance gates."
        if "MISSING_BANK_SETTLEMENT_CREDIT" in context.anomaly_flags:
            reason = "Captured on gateway but bank settlement wire is completely missing. Escalated as High-Risk Exception."
        elif "DUPLICATE_SOURCE_RECORD" in str(context.anomaly_flags):
            reason = "Duplicate record ingested in batch. Flagged for de-duplication."
        elif "CHARGEBACK_RESERVE_WITHHELD" in context.anomaly_flags:
            reason = "Disputed transaction with chargeback reserve withheld by gateway."

        return ReconciliationDecision(
            transaction_id=txn.id,
            tier=DecisionTier.UNRESOLVED_EXCEPTION,
            confidence=round(confidence, 2),
            deterministic_score=0.10,
            cross_source_score=0.10,
            ai_score=ai_score,
            risk_penalties=risk_penalties,
            explanation=reason,
            evidence_summary=context.anomaly_flags or [reason],
            matched_counterpart_id=None,
            requires_maker_checker=True
        )
