"""
Quality-First 13-Week Segmented Forward Cash Forecast Engine
Partitions weekly inflows into:
1. OBSERVED CASH (Observed / Calculated)
2. CONFIRMED FUTURE INFLOWS (Forecast)
3. PROBABLE INFLOWS (Calculated)
4. AT-RISK INFLOWS (Calculated)
5. UNKNOWN INFLOWS (Observed)
6. ASSUMPTIONS (Assumption)

Strictly derived from actual uploaded batch data with full record ID provenance.
Zero hardcoded synthetic baseline amounts.
"""

from datetime import datetime, timedelta, date
from typing import Any, Dict, List, Optional, Tuple
from app.models.schemas import (
    CashForecastSegment,
    ForecastEntry,
    ForecastClassification,
    DataNature,
    ForecastStatus,
    LiquidityForecastEnvelope,
    DecisionTier,
    CanonicalTransaction,
    ReconciliationDecision
)

class SegmentedCashForecaster:
    """Computes 13-week forward cash runway derived purely from actual batch transactions."""

    @classmethod
    def generate_liquidity_envelope(
        cls,
        transactions: List[CanonicalTransaction],
        decisions: Dict[str, ReconciliationDecision]
    ) -> LiquidityForecastEnvelope:
        """Generates the full audited LiquidityForecastEnvelope with provenance and data nature."""
        if not transactions:
            base_date = date.today()
            empty_segments = [
                CashForecastSegment(
                    week_number=w,
                    period_start=(base_date + timedelta(days=(w - 1) * 7 + 1)).isoformat(),
                    period_end=(base_date + timedelta(days=w * 7)).isoformat(),
                    observed_cash_minor=0,
                    confirmed_future_inflows_minor=0,
                    probable_inflows_minor=0,
                    at_risk_inflows_minor=0,
                    unknown_inflows_minor=0,
                    assumptions_minor=0,
                    confirmed_inflow_minor=0,
                    probable_inflow_minor=0,
                    at_risk_inflow_minor=0,
                    unknown_inflow_minor=0,
                    entries=[],
                    risk_narrative=f"Week {w}: No active transactions present."
                )
                for w in range(1, 14)
            ]
            return LiquidityForecastEnvelope(
                forecast_status=ForecastStatus.INSUFFICIENT_DATA,
                missing_fields_explanation="No financial transactions found in the uploaded batch. Upload bank statements, gateway exports, or general ledger vouchers to generate verified liquidity projections.",
                as_of_date=base_date.isoformat(),
                total_observed_cash_minor=0,
                total_projected_inflow_minor=0,
                segments=empty_segments,
                provenance_summary={
                    "total_source_records": 0,
                    "observed_cash_records": 0,
                    "probable_clearing_records": 0,
                    "at_risk_records": 0,
                    "assumptions_used": []
                }
            )

        # Dynamic anchor date: cut-off date of settled batch records
        p_dates = []
        for t in transactions:
            if getattr(t, "occurred_at", None):
                p_dates.append(t.occurred_at.date() if isinstance(t.occurred_at, datetime) else t.occurred_at)
            if getattr(t, "value_date", None):
                p_dates.append(t.value_date.date() if isinstance(t.value_date, datetime) else t.value_date)

        # Anchor is the earliest/settled baseline date in the batch
        base_date = min(p_dates) if p_dates else date.today()

        # Group transaction inflows by category
        observed_txns: List[CanonicalTransaction] = []
        future_confirmed_txns: List[CanonicalTransaction] = []
        probable_txns: List[CanonicalTransaction] = []
        at_risk_txns: List[CanonicalTransaction] = []
        unknown_txns: List[CanonicalTransaction] = []

        for t in transactions:
            direction_str = t.direction.value if hasattr(t.direction, "value") else str(t.direction)
            if direction_str not in ("INFLOW", "DEPOSIT", "CREDIT"):
                continue

            dec = decisions.get(t.id)
            if not dec:
                probable_txns.append(t)
            elif dec.tier in (DecisionTier.RESOLVED, DecisionTier.RESOLVED_WITH_EXPLANATION):
                t_date = t.value_date if isinstance(t.value_date, date) else (t.occurred_at.date() if isinstance(t.occurred_at, datetime) else base_date)
                if t_date > base_date:
                    future_confirmed_txns.append(t)
                else:
                    observed_txns.append(t)
            elif dec.tier == DecisionTier.NEEDS_REVIEW:
                probable_txns.append(t)
            elif dec.tier == DecisionTier.UNRESOLVED_EXCEPTION:
                exp_upper = (dec.explanation or "").upper()
                if "MISSING" in exp_upper or "DISPUTED" in exp_upper or "EXCEPTION" in exp_upper:
                    at_risk_txns.append(t)
                else:
                    unknown_txns.append(t)

        # Sum amounts
        observed_cash_minor = sum(t.amount_minor for t in observed_txns)
        future_confirmed_minor = sum(t.amount_minor for t in future_confirmed_txns)
        probable_minor = sum(t.amount_minor for t in probable_txns)
        at_risk_minor = sum(t.amount_minor for t in at_risk_txns)
        unknown_minor = sum(t.amount_minor for t in unknown_txns)

        # Build week segments
        segments: List[CashForecastSegment] = []
        for w in range(1, 14):
            w_start = base_date + timedelta(days=(w - 1) * 7 + 1)
            w_end = base_date + timedelta(days=w * 7)
            entries: List[ForecastEntry] = []

            w_obs = 0
            w_fut = 0
            w_prob = 0
            w_risk = 0
            w_unk = 0

            if w == 1:
                w_obs = observed_cash_minor
                w_risk = at_risk_minor
                w_unk = unknown_minor

                if w_obs > 0:
                    entries.append(ForecastEntry(
                        week_number=1,
                        amount_minor=w_obs,
                        amount_inr=round(w_obs / 100, 2),
                        classification=ForecastClassification.OBSERVED_CASH,
                        data_nature=DataNature.OBSERVED,
                        source_record_ids=[t.id for t in observed_txns],
                        calculation_method="SUM_SETTLED_MATCHED_CREDITS",
                        assumption_ids=[],
                        narrative=f"Confirmed settled funds across {len(observed_txns)} matched transaction records."
                    ))
                if w_risk > 0:
                    entries.append(ForecastEntry(
                        week_number=1,
                        amount_minor=w_risk,
                        amount_inr=round(w_risk / 100, 2),
                        classification=ForecastClassification.AT_RISK_INFLOWS,
                        data_nature=DataNature.CALCULATED,
                        source_record_ids=[t.id for t in at_risk_txns],
                        calculation_method="SUM_UNRESOLVED_EXCEPTIONS",
                        assumption_ids=[],
                        narrative=f"Unreconciled gateway captures ({len(at_risk_txns)} records) with unconfirmed bank settlement."
                    ))
                if w_unk > 0:
                    entries.append(ForecastEntry(
                        week_number=1,
                        amount_minor=w_unk,
                        amount_inr=round(w_unk / 100, 2),
                        classification=ForecastClassification.UNKNOWN_INFLOWS,
                        data_nature=DataNature.OBSERVED,
                        source_record_ids=[t.id for t in unknown_txns],
                        calculation_method="SUM_UNALLOCATED_BANK_CREDITS",
                        assumption_ids=[],
                        narrative=f"Unidentified direct bank deposits ({len(unknown_txns)} records) pending counterparty allocation."
                    ))

                narrative = f"Week 1: ₹{w_obs/100:,.2f} verified cash on hand. ₹{w_risk/100:,.2f} at-risk exceptions."
            elif w == 2:
                w_prob = probable_minor
                if w_prob > 0:
                    entries.append(ForecastEntry(
                        week_number=2,
                        amount_minor=w_prob,
                        amount_inr=round(w_prob / 100, 2),
                        classification=ForecastClassification.PROBABLE_INFLOWS,
                        data_nature=DataNature.FORECAST,
                        source_record_ids=[t.id for t in probable_txns],
                        calculation_method="SUM_T2_CLEARING_LAG",
                        assumption_ids=[],
                        narrative=f"In-transit receivables ({len(probable_txns)} records) clearing within standard T+2 bank clearing SLA."
                    ))
                    narrative = f"Week 2: ₹{w_prob/100:,.2f} probable inflows clearing across value dates."
                else:
                    narrative = "Week 2: Zero pending clearing inflows."
            else:
                # Weeks 3-13: Only populate if future dated transactions exist in batch
                matching_fut = [t for t in future_confirmed_txns if w_start <= (t.value_date if isinstance(t.value_date, date) else t.occurred_at.date()) <= w_end]
                if matching_fut:
                    w_fut = sum(t.amount_minor for t in matching_fut)
                    entries.append(ForecastEntry(
                        week_number=w,
                        amount_minor=w_fut,
                        amount_inr=round(w_fut / 100, 2),
                        classification=ForecastClassification.CONFIRMED_FUTURE_INFLOWS,
                        data_nature=DataNature.FORECAST,
                        source_record_ids=[t.id for t in matching_fut],
                        calculation_method="SUM_SCHEDULED_FUTURE_INVOICES",
                        assumption_ids=[],
                        narrative=f"Scheduled future receivables ({len(matching_fut)} records)."
                    ))
                    narrative = f"Week {w}: ₹{w_fut/100:,.2f} confirmed scheduled inflows."
                else:
                    narrative = f"Week {w}: No future-dated receivables provided in batch data."

            segments.append(CashForecastSegment(
                week_number=w,
                period_start=w_start.isoformat(),
                period_end=w_end.isoformat(),
                observed_cash_minor=w_obs,
                confirmed_future_inflows_minor=w_fut,
                probable_inflows_minor=w_prob,
                at_risk_inflows_minor=w_risk,
                unknown_inflows_minor=w_unk,
                assumptions_minor=0,
                confirmed_inflow_minor=w_obs + w_fut,
                probable_inflow_minor=w_prob,
                at_risk_inflow_minor=w_risk,
                unknown_inflow_minor=w_unk,
                entries=entries,
                risk_narrative=narrative
            ))

        # Determine forecast completeness status
        has_future_inflows = (future_confirmed_minor > 0)
        has_clearing = (probable_minor > 0)
        
        if not has_future_inflows and not has_clearing and observed_cash_minor == 0:
            status = ForecastStatus.INSUFFICIENT_DATA
            missing_reason = "No valid inflow transactions found in the batch to construct cash projections."
        elif not has_future_inflows:
            status = ForecastStatus.INSUFFICIENT_DATA
            missing_reason = (
                "Insufficient forward horizon data for weeks 3–13: The uploaded reconciliation batch contains "
                "settled transaction records for the current clearing cycle (W1–W2), but contains zero future-dated "
                "invoice receivables, scheduled payouts, or explicit recurring revenue assumptions."
            )
        else:
            status = ForecastStatus.COMPLETE
            missing_reason = None

        return LiquidityForecastEnvelope(
            forecast_status=status,
            missing_fields_explanation=missing_reason,
            as_of_date=base_date.isoformat(),
            total_observed_cash_minor=observed_cash_minor,
            total_projected_inflow_minor=future_confirmed_minor + probable_minor,
            segments=segments,
            provenance_summary={
                "total_source_records": len(transactions),
                "observed_cash_records": len(observed_txns),
                "probable_clearing_records": len(probable_txns),
                "at_risk_records": len(at_risk_txns),
                "unknown_records": len(unknown_txns),
                "future_confirmed_records": len(future_confirmed_txns),
                "assumptions_used": []
            }
        )

    @classmethod
    def forecast_13_weeks(
        cls,
        transactions: List[CanonicalTransaction],
        decisions: Dict[str, ReconciliationDecision]
    ) -> List[CashForecastSegment]:
        """Convenience method returning segment list for backwards compatibility."""
        envelope = cls.generate_liquidity_envelope(transactions, decisions)
        return envelope.segments

