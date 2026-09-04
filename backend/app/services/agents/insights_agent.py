"""
Agent 11: Financial Insight Agent
Specialized LLM reasoning agent for working capital optimization,
treasury runway insights, settlement analysis, and financial variance commentary.
"""

import json
from typing import Any, Dict, List, Optional
from app.services.agents.base_agent import BaseReasoningAgent


class FinancialInsightAgent(BaseReasoningAgent):
    """Agent 11: Strategic financial intelligence and liquidity advisory agent."""

    def __init__(
        self,
        groq_api_key: Optional[str] = None,
        groq_model: Optional[str] = None,
        groq_api_key_secondary: Optional[str] = None
    ):
        super().__init__(
            agent_name="FinancialInsightAgent",
            groq_api_key=groq_api_key,
            groq_api_key_secondary=groq_api_key_secondary,
            groq_model=groq_model
        )

    def generate_liquidity_insights(
        self,
        batch_id: str,
        cash_forecast: List[Dict[str, Any]],
        batch_summary: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Generates strategic liquidity commentary and working capital optimization recommendations."""
        total_records = batch_summary.get("total_records", 0)
        match_rate = batch_summary.get("match_rate", 0.0)

        # Aggregate forecast numbers.
        # CashForecastSegment exposes confirmed/probable/at_risk/unknown inflows; it has
        # no "total_projected_cash_minor" or "in_transit_inflow_minor" key. Reading those
        # names made both sums silently fall back to 0, so the agent was told the 13-week
        # projection was Rs.0.00 while the waterfall it was shown held real weekly
        # inflows -- the model then reported a "critical data integrity failure".
        def _w(win: Dict[str, Any], *keys: str) -> int:
            return sum(int(win.get(k) or 0) for k in keys)

        total_confirmed_inflows_minor = sum(_w(w, "confirmed_inflow_minor") for w in cash_forecast)
        # Anything not yet confirmed is cash the controller cannot bank on this week.
        total_in_transit_minor = sum(
            _w(w, "probable_inflow_minor", "at_risk_inflow_minor", "unknown_inflow_minor")
            for w in cash_forecast
        )
        total_projected_cash_minor = total_confirmed_inflows_minor + total_in_transit_minor

        context_envelope = {
            "batch_id": batch_id,
            "reconciliation_match_rate": f"{match_rate * 100:.1f}%",
            "total_records_processed": total_records,
            "13_week_total_projected_inr": f"₹{total_projected_cash_minor / 100:,.2f}",
            "confirmed_cash_inr": f"₹{total_confirmed_inflows_minor / 100:,.2f}",
            # Renamed from "in_transit_held_cash_inr": this figure is every inflow not
            # yet confirmed (probable + at risk + unknown), not just settlement float.
            "unconfirmed_cash_inr": f"₹{total_in_transit_minor / 100:,.2f}",
            "weekly_waterfall_sample": cash_forecast[:6]
        }

        system_prompt = (
            "You are the Senior Financial Insight & Treasury Advisory Agent (Agent 11) in the AI Financial Controller system. "
            "Analyze the 13-week cash liquidity forecast and output strategic commentary in valid JSON matching:\n"
            "{\n"
            '  "batch_id": str,\n'
            '  "liquidity_health_score": float,  // MUST be 0.0-1.0, e.g. 0.85 for healthy. Never a 0-100 percentage.\n'
            '  "liquidity_status": str,\n'
            '  "cash_runway_assessment": str,\n'
            '  "peak_inflow_week": str,\n'
            '  "liquidity_stress_points": list[str],\n'
            '  "working_capital_recommendations": [\n'
            '    {\n'
            '      "action": str,\n'
            '      "expected_impact_inr": str,\n'
            '      "timeframe": str,\n'
            '      "rationale": str\n'
            '    }\n'
            '  ],\n'
            '  "cfo_executive_takeaway": str\n'
            "}\n"
            "Rules:\n"
            "1. Output strictly valid JSON without markdown wrapping.\n"
            "2. Ground all insights directly in the provided cash waterfall figures.\n"
            "3. Provide realistic financial controller / treasury advice."
        )

        user_prompt = json.dumps(context_envelope, indent=2, default=str)
        parsed_json, raw_text, telemetry = self.execute_prompt(system_prompt, user_prompt)

        if parsed_json:
            parsed_json["telemetry"] = telemetry
            return parsed_json

        # Deterministic Fallback
        return self._deterministic_insights_fallback(
            batch_id=batch_id,
            total_projected_minor=total_projected_cash_minor,
            confirmed_minor=total_confirmed_inflows_minor,
            in_transit_minor=total_in_transit_minor,
            telemetry=telemetry
        )

    def _deterministic_insights_fallback(
        self,
        batch_id: str,
        total_projected_minor: int,
        confirmed_minor: int,
        in_transit_minor: int,
        telemetry: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Deterministic financial insight fallback."""
        in_transit_pct = (in_transit_minor / total_projected_minor * 100) if total_projected_minor > 0 else 0
        # The score used to be a hardcoded 0.94 with status STRONG_LIQUIDITY_BUFFER,
        # so a batch with every rupee stuck in transit still reported strong liquidity.
        # Derive it from the share of projected cash that is actually confirmed.
        confirmed_share = (confirmed_minor / total_projected_minor) if total_projected_minor > 0 else 0.0
        score = round(max(0.0, min(1.0, confirmed_share)), 2)
        if total_projected_minor <= 0:
            status = "NO_FORECAST_DATA"
        elif score >= 0.85:
            status = "STRONG_LIQUIDITY_BUFFER"
        elif score >= 0.60:
            status = "ADEQUATE_LIQUIDITY"
        else:
            status = "LIQUIDITY_AT_RISK"

        recommendations = []
        if in_transit_minor > 0:
            recommendations.append({
                "action": "Accelerate Gateway T+1 Settlement Sweep",
                "expected_impact_inr": f"₹{in_transit_minor/100:,.2f}",
                "timeframe": "Next 7 Days",
                "rationale": "Reduces bank settlement clearing lag from T+2 to T+1, unlocking faster operating liquidity."
            })
        if not recommendations:
            recommendations.append({
                "action": "No deterministic recommendation available",
                "expected_impact_inr": "Not quantified",
                "timeframe": "n/a",
                "rationale": "No in-transit balance or forecast variance was present to act on in this batch."
            })

        return {
            "batch_id": batch_id,
            "liquidity_health_score": score,
            "liquidity_status": status,
            "cash_runway_assessment": (
                f"13-week projected liquidity stands at ₹{total_projected_minor/100:,.2f}, of which "
                f"₹{confirmed_minor/100:,.2f} ({score*100:.1f}%) is confirmed and "
                f"₹{in_transit_minor/100:,.2f} is not yet confirmed."
                if total_projected_minor > 0 else
                "No cash forecast windows were produced for this batch, so no runway can be assessed."
            ),
            # Peak week is only knowable from the waterfall, which this fallback is
            # not given; claiming "Week 1 to Week 3" was an invention.
            "peak_inflow_week": "Not determined (no LLM narrative for this batch)",
            "liquidity_stress_points": (
                [f"₹{in_transit_minor/100:,.2f} ({in_transit_pct:.1f}%) of projected inflow is probable, at risk, or unknown rather than confirmed."]
                if in_transit_minor > 0 else
                ["Every projected inflow in this batch is confirmed."]
            ),
            "working_capital_recommendations": recommendations,
            "cfo_executive_takeaway": (
                f"Deterministic assessment: {score*100:.1f}% of projected 13-week cash is confirmed "
                f"({in_transit_pct:.1f}% in transit). No LLM narrative was produced for this batch."
            ),
            "telemetry": telemetry
        }
