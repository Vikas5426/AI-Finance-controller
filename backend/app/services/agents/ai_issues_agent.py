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

    def __init__(
        self,
        groq_api_key: Optional[str] = None,
        groq_model: Optional[str] = None,
        groq_api_key_secondary: Optional[str] = None
    ):
        super().__init__(
            agent_name="AIIssuesReasoningAgent",
            groq_api_key=groq_api_key,
            groq_api_key_secondary=groq_api_key_secondary,
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

        # 1. Aggregate exceptions by exception_type to give the LLM structured, non-truncated financial clarity
        categorized_exceptions: Dict[str, Dict[str, Any]] = {}
        for e in exceptions:
            exc_type = e.get("exception_type") or "GENERAL_RESIDUAL"
            p_txn = e.get("primary_txn") or {}
            c_txn = e.get("counterpart_txn") or {}
            impact = round((e.get("impact_minor") or 0) / 100.0, 2)
            sev = (e.get("severity") or "MEDIUM").upper()

            if exc_type not in categorized_exceptions:
                categorized_exceptions[exc_type] = {
                    "exception_type": exc_type,
                    "severity": sev,
                    "record_count": 0,
                    "total_impact_inr": 0.0,
                    "sample_records": []
                }
            cat = categorized_exceptions[exc_type]
            cat["record_count"] += 1
            cat["total_impact_inr"] = round(cat["total_impact_inr"] + impact, 2)

            if len(cat["sample_records"]) < 3:
                ref_id = p_txn.get("external_id") or c_txn.get("external_id") or e.get("id") or "N/A"
                source = p_txn.get("source_kind") or c_txn.get("source_kind") or "UNKNOWN"
                desc = (p_txn.get("description_raw") or c_txn.get("description_raw") or "")[:80]
                cat["sample_records"].append({
                    "reference": ref_id,
                    "source": source,
                    "amount_inr": f"₹{impact:,.2f}",
                    "description": desc
                })

        # Convert to list for concise prompt injection
        categories_list = []
        for cat in categorized_exceptions.values():
            categories_list.append({
                "exception_type": cat["exception_type"],
                "severity": cat["severity"],
                "count": cat["record_count"],
                "total_impact": f"₹{cat['total_impact_inr']:,.2f}",
                "samples": cat["sample_records"]
            })

        system_prompt = (
            "You are an expert Recon Financial Controller.\n"
            "Your task is to analyze verified deterministic reconciliation discrepancies and structure them into a simple, clear, minimal, and executive-ready summary.\n"
            "STRICT FINANCIAL SAFETY RULES:\n"
            "1. NEVER invent, fabricate, or hallucinate transaction IDs, amounts, invoice numbers, bank deposits, or references.\n"
            "2. NEVER alter any financial figures. Use only the exact figures provided in the verified envelope.\n"
            "3. Clearly distinguish VERIFIED FACT from LIKELY CAUSE.\n"
            "4. If bank data is incomplete, explicitly state that settlement arrival cannot be verified rather than assuming funds are missing.\n"
            "5. Write in clear, crisp, minimal, and plain English so any controller or executive understands immediately.\n"
            "6. Return strictly valid JSON adhering to the specified schema."
        )

        user_prompt = f"""
Batch Discrepancy Envelope:
{json.dumps({
    "batch_id": batch_id,
    "batch_summary": batch_summary,
    "audit_integrity": audit_integrity,
    "total_exceptions_count": len(exceptions),
    "discrepancy_categories": categories_list
}, indent=2)}

Please analyze these issues and return a structured JSON response with this exact structure:
{{
  "summary": "<Concise 1-2 sentence executive overview in plain English stating batch health, total exposure, and core root cause>",
  "overall_health": "CRITICAL_RISK" | "ACTION_REQUIRED" | "HEALTHY",
  "issues": [
    {{
      "exception_type": "<Exact matching exception_type string from categories>",
      "title": "<Concise, professional issue title, e.g. 'Duplicate Gateway Captured Records'>",
      "severity": "CRITICAL" | "HIGH" | "MEDIUM" | "LOW",
      "what_happened": "<Simple, plain English 1-2 sentence description of what occurred>",
      "why_it_matters": "<Why this matters to financial reporting and ledger integrity>",
      "likely_cause": "<Precise operational root cause>",
      "evidence": ["<Fact 1 with exact reference or source>", "<Fact 2>"],
      "recommended_action": "<Clear operational action step for resolution>",
      "owner": "<Responsible Team (e.g. Accounting Team, Treasury Operations)>",
      "next_step": "<Immediate next action>",
      "citations": ["SOP-01"]
    }}
  ],
  "systemic_patterns": [
    {{
      "pattern_name": "<Sleek operational pattern title>",
      "likely_systemic_cause": "<Clear systemic root cause>",
      "recommended_remediation": "<Actionable process fix>",
      "remediation_owner": "<Team>",
      "root_cause_status": "IDENTIFIED"
    }}
  ],
  "controller_takeaway": "<Concise 2-3 sentence executive recommendation explaining what needs to be done next>"
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
