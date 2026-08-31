"""
Quality-First 13-Week Segmented Forward Cash Forecast Engine
Partitions weekly inflows into Confirmed, Probable, At-Risk, and Unknown cash buckets
with controller risk narrative explanations.
"""

from datetime import datetime, timedelta, date
from typing import Any, Dict, List
from app.models.schemas import CashForecastSegment, DecisionTier, CanonicalTransaction, ReconciliationDecision

class SegmentedCashForecaster:
    """Computes 13-week forward cash runway with risk-segmented liquidity buckets."""

    @staticmethod
    def forecast_13_weeks(
        transactions: List[CanonicalTransaction],
        decisions: Dict[str, ReconciliationDecision]
    ) -> List[CashForecastSegment]:
        base_date = date(2026, 3, 31)
        forecast_weeks: List[CashForecastSegment] = []

        # Baseline recurring revenue profile
        weekly_baseline_inflow = 55000000 # ₹550,000.00 base run-rate

        # Categorize batch transactions into risk buckets
        confirmed_batch = 0
        probable_batch = 0
        at_risk_batch = 0
        unknown_batch = 0

        for t in transactions:
            dec = decisions.get(t.id)
            amt = t.amount_minor
            if not dec:
                probable_batch += amt
            elif dec.tier == DecisionTier.RESOLVED:
                confirmed_batch += amt
            elif dec.tier == DecisionTier.RESOLVED_WITH_EXPLANATION:
                confirmed_batch += int(amt * 0.98) # Net of fee
            elif dec.tier == DecisionTier.NEEDS_REVIEW:
                probable_batch += amt # Timing difference settling in W1
            elif dec.tier == DecisionTier.UNRESOLVED_EXCEPTION:
                exp_upper = dec.explanation.upper()
                if "MISSING" in exp_upper or "DISPUTED" in exp_upper or "EXCEPTION" in exp_upper:
                    at_risk_batch += amt
                else:
                    unknown_batch += amt

        for w in range(1, 14):
            w_start = base_date + timedelta(days=(w - 1) * 7 + 1)
            w_end = base_date + timedelta(days=w * 7)

            if w == 1:
                confirmed = confirmed_batch + int(weekly_baseline_inflow * 0.85)
                probable = probable_batch + int(weekly_baseline_inflow * 0.15)
                at_risk = at_risk_batch
                unknown = unknown_batch
                narrative = f"Week 1 includes ₹{at_risk/100000:.2f}K at-risk cash due to {at_risk_batch//500000} missing bank settlement credits pending gateway escalation."
            elif w == 2:
                confirmed = int(weekly_baseline_inflow * 0.90)
                probable = int(weekly_baseline_inflow * 0.10)
                at_risk = int(at_risk_batch * 0.50) # Residual risk
                unknown = 0
                narrative = "Week 2 reflects normal T+2 billing cycle with 90% confirmed receivables."
            else:
                growth_factor = 1.0 + (w * 0.015)
                confirmed = int(weekly_baseline_inflow * 0.92 * growth_factor)
                probable = int(weekly_baseline_inflow * 0.08 * growth_factor)
                at_risk = int(weekly_baseline_inflow * 0.02)
                unknown = 0
                narrative = f"Week {w} steady-state SaaS subscription runway projection."

            forecast_weeks.append(CashForecastSegment(
                week_number=w,
                period_start=w_start.isoformat(),
                period_end=w_end.isoformat(),
                confirmed_inflow_minor=confirmed,
                probable_inflow_minor=probable,
                at_risk_inflow_minor=at_risk,
                unknown_inflow_minor=unknown,
                risk_narrative=narrative
            ))

        return forecast_weeks
