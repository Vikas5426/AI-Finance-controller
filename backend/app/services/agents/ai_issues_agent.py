"""
Agent 14: AI Issues Center Reasoning Agent
Directly analyzes all multi-stream reconciliation exceptions, missing records,
settlement delays, and discrepancies to produce a structured, prioritized report
sorted from Critical to Low risk.
"""

import json
from typing import Any, Dict, List, Optional
from app.services.agents.base_agent import BaseReasoningAgent


class AIIssuesReasoningAgent(BaseReasoningAgent):
    """Reasoning agent specialized in structuring and synthesizing financial issues."""

    def __init__(self, groq_api_key: Optional[str] = None, groq_model: Optional[str] = None):
        super().__init__(
            agent_name="AIIssuesReasoningAgent",
            groq_api_key=groq_api_key,
            groq_model=groq_model
        )

    def analyze_issues(
        self,
        batch_id: str,
        exceptions: List[Dict[str, Any]],
        batch_summary: Dict[str, Any],
        audit_integrity: str = "PASS"
    ) -> Optional[Dict[str, Any]]:
        """
        Submits reconciliation discrepancies directly to the LLM for structured analysis
        sorted by critical sections.
        """
        if not exceptions:
            return None

        # Build clean, condensed context envelope (compact to stay well within Groq TPM limits)
        exc_summaries = []
        for e in exceptions[:8]:
            p_txn = e.get("primary_txn") or {}
            c_txn = e.get("counterpart_txn") or {}
            exc_summaries.append({
                "type": e.get("exception_type"),
                "severity": e.get("severity"),
                "impact_inr": f"₹{(e.get('impact_minor', 0) / 100):,.2f}",
                "primary_ref": p_txn.get("external_id"),
                "counterpart_ref": c_txn.get("external_id"),
                "description": (p_txn.get("description_raw") or c_txn.get("description_raw") or "")[:60]
            })

        system_prompt = (
            "You are an expert AI Financial Controller.\n"
            "Your task is to analyze verified deterministic reconciliation discrepancies and structure them into a simple, clear, and easy-to-understand executive summary.\n"
            "STRICT FINANCIAL SAFETY RULES:\n"
            "1. NEVER invent, fabricate, or hallucinate transaction IDs, amounts, invoice numbers, bank deposits, or references (e.g. never invent B001, B002, B003, ₹31,250, ₹45,000).\n"
            "2. NEVER recalculate or alter any financial figures. Use only the exact numbers provided in the verified discrepancy envelope.\n"
            "3. Clearly distinguish VERIFIED FACT from LIKELY CAUSE.\n"
            "4. If bank data is incomplete, explicitly state that settlement arrival cannot be verified rather than assuming funds are missing.\n"
            "5. Write in simple, clear, plain English so that any manager or auditor can understand immediately.\n"
            "6. Return strictly valid JSON adhering to the specified schema."
        )

        user_prompt = f"""
Batch Discrepancy Envelope:
{json.dumps({
    "batch_id": batch_id,
    "batch_summary": batch_summary,
    "audit_integrity": audit_integrity,
    "exceptions_count": len(exceptions),
    "exceptions_sample": exc_summaries
}, indent=2)}

Please analyze these issues and return a structured JSON response with this exact structure:
{{
  "summary": "<Concise 1-2 sentence overview in plain English>",
  "overall_health": "CRITICAL_RISK" | "ACTION_REQUIRED" | "HEALTHY",
  "issues": [
    {{
      "issue_id": "ISSUE-01",
      "title": "<Simple Issue Title>",
      "severity": "CRITICAL" | "HIGH" | "MEDIUM" | "LOW",
      "affected_records": 1,
      "financial_impact_inr": 150.00,
      "what_happened": "<Simple plain English description of what happened>",
      "why_it_matters": "<Why this matters to the business>",
      "likely_cause": "<Simple explanation of why it happened>",
      "evidence": ["<Fact 1>", "<Fact 2>"],
      "recommended_action": "<Clear action step to fix it>",
      "owner": "<Responsible Team (e.g. Accounting Team)>",
      "next_step": "<Immediate next action>",
      "citations": ["SOP-01", "GAAP ASC 606"]
    }}
  ],
  "systemic_patterns": [
    {{
      "pattern_id": "PAT-01",
      "pattern_name": "<Pattern Title>",
      "affected_count": 1,
      "impact_inr": 150.00,
      "likely_systemic_cause": "<Simple root cause>",
      "recommended_remediation": "<Simple remediation action>",
      "remediation_owner": "<Team>",
      "root_cause_status": "IDENTIFIED"
    }}
  ],
  "controller_takeaway": "<Simple 2-3 sentence summary explaining what needs to be done next>"
}}
"""

        parsed_json, _, _ = self.execute_prompt(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=2048,
            batch_id=batch_id,
            purpose="ai_issues_report"
        )
        if parsed_json and isinstance(parsed_json.get("issues"), list):
            return parsed_json

        return None
