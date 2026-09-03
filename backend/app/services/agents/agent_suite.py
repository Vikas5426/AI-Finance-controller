"""
Financial Agent Suite Registry & Orchestrator
Coordinates Agents 9 to 13:
- Exception Investigation Agent (Agent 9)
- Root Cause Analysis Agent (Agent 10)
- Financial Insight Agent (Agent 11)
- Audit Explanation Agent (Agent 12)
- Report Generation Agent (Agent 13)
"""

from typing import Any, Dict, List, Optional
from app.services.agents.investigation_agent import ExceptionInvestigationAgent
from app.services.agents.rca_agent import RootCauseAnalysisAgent
from app.services.agents.insights_agent import FinancialInsightAgent
from app.services.agents.audit_agent import AuditExplanationAgent
from app.services.agents.report_agent import ReportGenerationAgent
from app.services.agents.base_agent import AgentTelemetryTracker


class FinancialAgentSuite:
    """Singleton Suite coordinating all 5 reasoning agents."""

    _instance: Optional["FinancialAgentSuite"] = None
    _cached_batch_analyses: Dict[str, Dict[str, Any]] = {}

    def __init__(
        self,
        groq_api_key: Optional[str] = None,
        groq_api_key_secondary: Optional[str] = None
    ):
        from app.core.config import settings
        primary_k = groq_api_key or settings.GROQ_API_KEY
        secondary_k = groq_api_key_secondary or getattr(settings, "GROQ_API_KEY_SECONDARY", None)

        # Distribute keys across agents to split rate limits and concurrent load:
        # Core reconciliation investigation & RCA use Primary key (Secondary as failover)
        self.investigation_agent = ExceptionInvestigationAgent(
            groq_api_key=primary_k,
            groq_api_key_secondary=secondary_k
        )
        self.rca_agent = RootCauseAnalysisAgent(
            groq_api_key=primary_k,
            groq_api_key_secondary=secondary_k
        )
        # Macro advisory, audit narratives, and reporting use Secondary key (Primary as failover)
        self.insights_agent = FinancialInsightAgent(
            groq_api_key=secondary_k or primary_k,
            groq_api_key_secondary=primary_k if secondary_k else None
        )
        self.audit_agent = AuditExplanationAgent(
            groq_api_key=secondary_k or primary_k,
            groq_api_key_secondary=primary_k if secondary_k else None
        )
        self.report_agent = ReportGenerationAgent(
            groq_api_key=secondary_k or primary_k,
            groq_api_key_secondary=primary_k if secondary_k else None
        )

    @classmethod
    def get_suite(
        cls,
        groq_api_key: Optional[str] = None,
        groq_api_key_secondary: Optional[str] = None
    ) -> "FinancialAgentSuite":
        if cls._instance is None:
            cls._instance = FinancialAgentSuite(
                groq_api_key=groq_api_key,
                groq_api_key_secondary=groq_api_key_secondary
            )
        return cls._instance

    def run_all_batch_agents(
        self,
        batch_id: str,
        batch_summary: Dict[str, Any],
        exceptions: List[Dict[str, Any]],
        safeguards: List[Dict[str, Any]],
        cash_forecast: List[Dict[str, Any]],
        audit_events: List[Dict[str, Any]],
        approvals: List[Dict[str, Any]],
        force_refresh: bool = False
    ) -> Dict[str, Any]:
        """Runs RCA, Financial Insights, Audit Explanation, and Report Generation agents in sequence with caching."""
        if not force_refresh and batch_id and batch_id in self._cached_batch_analyses:
            return self._cached_batch_analyses[batch_id]

        # 1. Run RCA Agent (Agent 10)
        rca_res = self.rca_agent.analyze_batch_exceptions(
            batch_id=batch_id,
            exceptions=exceptions,
            safeguards=safeguards,
            batch_summary=batch_summary
        )

        # 2. Run Financial Insight Agent (Agent 11)
        insights_res = self.insights_agent.generate_liquidity_insights(
            batch_id=batch_id,
            cash_forecast=cash_forecast,
            batch_summary=batch_summary
        )

        # 3. Run Audit Explanation Agent (Agent 12)
        audit_res = self.audit_agent.explain_audit_trail(
            batch_id=batch_id,
            audit_events=audit_events,
            approvals=approvals,
            batch_summary=batch_summary
        )

        # 4. Run Report Generation Agent (Agent 13)
        report_res = self.report_agent.generate_controller_report(
            contract_or_batch_id=batch_id,
            batch_summary=batch_summary,
            rca_results=rca_res,
            insights_results=insights_res,
            audit_results=audit_res
        )

        full_analysis = {
            "batch_id": batch_id,
            "root_cause_analysis": rca_res,
            "financial_insights": insights_res,
            "audit_explanation": audit_res,
            "controller_report": report_res,
            "telemetry_summary": AgentTelemetryTracker.get_telemetry()
        }

        self._cached_batch_analyses[batch_id] = full_analysis
        if len(self._cached_batch_analyses) > 50:
            oldest_k = next(iter(self._cached_batch_analyses))
            self._cached_batch_analyses.pop(oldest_k, None)
        return full_analysis

    @classmethod
    def get_cached_analysis(cls, batch_id: str) -> Optional[Dict[str, Any]]:
        return cls._cached_batch_analyses.get(batch_id)
