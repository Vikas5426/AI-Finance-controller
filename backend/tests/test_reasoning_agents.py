"""
Reasoning Agents Test Suite (Agents 9-13)
Tests all 5 specialized financial reasoning agents with Groq (openai/gpt-oss-120b),
JSON schema adherence, arithmetic verifier gates, and telemetry tracking.
"""

import os
import sys
import unittest
import uuid
from typing import Any, Dict, List

# Ensure backend directory is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.config import settings
from app.services.agents import (
    ExceptionInvestigationAgent,
    RootCauseAnalysisAgent,
    FinancialInsightAgent,
    AuditExplanationAgent,
    ReportGenerationAgent,
    FinancialAgentSuite,
    AgentTelemetryTracker
)


class TestReasoningAgents(unittest.TestCase):

    def setUp(self):
        self.batch_id = f"BATCH-TEST-{uuid.uuid4().hex[:6]}"
        self.sample_summary = {
            "batch_id": self.batch_id,
            "total_records": 240,
            "matched_records": 228,
            "match_rate": 0.95,
            "exact_matches": 96,
            "contextual_matches": 18,
            "total_exceptions": 12,
            "needs_review_count": 10,
            "wall_clock_seconds": 0.08
        }
        self.sample_exceptions = [
            {
                "id": "EXC-001",
                "exception_type": "PERIOD_CUTOFF_TIMING",
                "severity": "MEDIUM",
                "impact_minor": 450000,
                "findings": ["T+2 period boundary cutoff clearing lag detected"]
            },
            {
                "id": "EXC-002",
                "exception_type": "FEE_VARIANCE",
                "severity": "LOW",
                "impact_minor": 3540,
                "findings": ["Gateway MDR fee deduction of 2.0% + 18% GST"]
            },
            {
                "id": "EXC-003",
                "exception_type": "UNALLOCATED_BANK_CREDIT",
                "severity": "HIGH",
                "impact_minor": 1500000,
                "findings": ["Unidentified direct wire credit in bank feed"]
            }
        ]
        self.sample_safeguards = [
            {
                "safeguard": "PERIOD_BOUNDARY_TIMING_SAFEGUARD",
                "reason": "Payment captured at period boundary cutoff with T+2 settlement lag."
            }
        ]
        self.sample_forecast = [
            {
                "week_index": 1,
                "week_label": "Week 1 (Aug 01 - Aug 07)",
                "total_projected_cash_minor": 5000000,
                "confirmed_inflow_minor": 4500000,
                "in_transit_inflow_minor": 500000
            },
            {
                "week_index": 2,
                "week_label": "Week 2 (Aug 08 - Aug 14)",
                "total_projected_cash_minor": 4200000,
                "confirmed_inflow_minor": 4000000,
                "in_transit_inflow_minor": 200000
            }
        ]
        self.sample_audit_events = [
            {
                "event_seq": 1,
                "event_type": "BATCH_INITIALIZED",
                "action": "CREATE_BATCH",
                "actor_id": "usr_system",
                "event_hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                "prev_hash": "0000000000000000000000000000000000000000000000000000000000000000"
            }
        ]
        self.sample_approvals = [
            {
                "id": "PROP-01",
                "exception_id": "EXC-001",
                "action": "ACCRUE_TO_CLEARING_1290",
                "created_by": "usr_analyst_01",
                "decided_by": "usr_approver_01",
                "status": "APPROVED",
                "justification": "Dual approved T+2 timing cutoff accrual"
            }
        ]

    def test_agent_9_investigation(self):
        """Test Agent 9: Exception Investigation Agent."""
        agent = ExceptionInvestigationAgent()
        primary = {
            "id": "txn_gw_99",
            "source_kind": "GATEWAY",
            "amount_minor": 118000,
            "occurred_at": "2026-08-15T10:00:00Z"
        }
        res = agent.investigate(
            exception_id="EXC-TEST-09",
            exception_type="FEE_AND_TAX_BOOKED_NET",
            impact_minor=2785,
            primary_txn=primary,
            counterpart_txn={"id": "txn_bk_99", "amount_minor": 115215},
            available_txns=[primary],
            severity="MEDIUM"
        )
        self.assertIsNotNone(res)
        self.assertEqual(res.exception_id, "EXC-TEST-09")
        self.assertTrue(0.0 <= res.confidence <= 1.0)
        self.assertIn(res.recommended_action, [
            "ADJUST_LEDGER_FEE_SPLIT", "ACCRUE_TO_CLEARING_1290", "MANUAL_JOURNAL_ENTRY",
            "AUTO_RESOLVE_TOLERANCE", "SPLIT_AND_POST_FEE"
        ])

    def test_agent_10_rca(self):
        """Test Agent 10: Root Cause Analysis Agent."""
        agent = RootCauseAnalysisAgent()
        res = agent.analyze_batch_exceptions(
            batch_id=self.batch_id,
            exceptions=self.sample_exceptions,
            safeguards=self.sample_safeguards,
            batch_summary=self.sample_summary
        )
        self.assertIsNotNone(res)
        self.assertIn("primary_bottleneck", res)
        self.assertIn("systemic_findings", res)
        self.assertIn("preventative_action_items", res)

    def test_agent_11_financial_insights(self):
        """Test Agent 11: Financial Insight Agent."""
        agent = FinancialInsightAgent()
        res = agent.generate_liquidity_insights(
            batch_id=self.batch_id,
            cash_forecast=self.sample_forecast,
            batch_summary=self.sample_summary
        )
        self.assertIsNotNone(res)
        self.assertIn("liquidity_health_score", res)
        self.assertIn("working_capital_recommendations", res)
        self.assertIn("cfo_executive_takeaway", res)

    def test_agent_12_audit_explanation(self):
        """Test Agent 12: Audit Explanation Agent."""
        agent = AuditExplanationAgent()
        res = agent.explain_audit_trail(
            batch_id=self.batch_id,
            audit_events=self.sample_audit_events,
            approvals=self.sample_approvals,
            batch_summary=self.sample_summary
        )
        self.assertIsNotNone(res)
        self.assertIn("audit_verdict", res)
        self.assertIn("sox_404_control_assertions", res)
        self.assertIn("maker_checker_governance_proof", res)

    def test_agent_13_report_generation(self):
        """Test Agent 13: Report Generation Agent."""
        agent = ReportGenerationAgent()
        res = agent.generate_controller_report(
            batch_id=self.batch_id,
            batch_summary=self.sample_summary
        )
        self.assertIsNotNone(res)
        self.assertIn("report_title", res)
        self.assertIn("full_markdown_report", res)
        self.assertIn("reconciliation_health_verdict", res)

    def test_financial_agent_suite_run_all(self):
        """Test FinancialAgentSuite coordinating all agents."""
        suite = FinancialAgentSuite.get_suite()
        all_res = suite.run_all_batch_agents(
            batch_id=self.batch_id,
            batch_summary=self.sample_summary,
            exceptions=self.sample_exceptions,
            safeguards=self.sample_safeguards,
            cash_forecast=self.sample_forecast,
            audit_events=self.sample_audit_events,
            approvals=self.sample_approvals
        )
        self.assertIsNotNone(all_res)
        self.assertIn("root_cause_analysis", all_res)
        self.assertIn("financial_insights", all_res)
        self.assertIn("audit_explanation", all_res)
        self.assertIn("controller_report", all_res)
        self.assertIn("telemetry_summary", all_res)


if __name__ == "__main__":
    unittest.main()
