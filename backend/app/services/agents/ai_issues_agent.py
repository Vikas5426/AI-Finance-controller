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

        # Build clean, condensed context envelope
        exc_summaries = []
        for e in exceptions[:30]:  # Cap at 30 to stay within prompt token budget
            p_txn = e.get("primary_txn") or {}
            c_txn = e.get("counterpart_txn") or {}
            exc_summaries.append({
                "exception_id": e.get("id"),
                "type": e.get("exception_type"),
                "severity": e.get("severity"),
                "impact_minor": e.get("impact_minor", 0),
                "impact_inr": f"₹{(e.get('impact_minor', 0) / 100):,.2f}",
                "state": e.get("state"),
                "primary_txn": {
                    "id": p_txn.get("external_id") or p_txn.get("id"),
                    "amount_inr": f"₹{(p_txn.get('amount_minor', 0) / 100):,.2f}" if p_txn.get("amount_minor") is not None else None,
                    "source": p_txn.get("source_kind"),
                    "date": p_txn.get("occurred_at"),
                    "desc": p_txn.get("description_raw")
                } if p_txn else None,
                "counterpart_txn": {
                    "id": c_txn.get("external_id") or c_txn.get("id"),
                    "amount_inr": f"₹{(c_txn.get('amount_minor', 0) / 100):,.2f}" if c_txn.get("amount_minor") is not None else None,
                    "source": c_txn.get("source_kind"),
                    "date": c_txn.get("occurred_at"),
                    "desc": c_txn.get("description_raw")
                } if c_txn else None
            })

        system_prompt = (
            "You are the Senior AI Financial Controller and Chartered Accountant.\n"
            "Your task is to analyze all reconciliation discrepancies in the financial batch and structure them "
            "into a clean, prioritized report sorted strictly from CRITICAL to LOW severity.\n\n"
            "Severity Ranking Rules:\n"
            "1. CRITICAL: Missing GL journal entries, unreconciled unrecorded cash, direct financial exposure.\n"
            "2. HIGH: Missing bank settlement wires, unreceived acquirer deposits, major timing variances.\n"
            "3. MEDIUM: Period cutoff timing lags, gateway fee deviations.\n"
            "4. LOW: Duplicate records, minor rounding adjustments.\n\n"
            "Requirements for Output:\n"
            "- Return strictly valid JSON adhering to the specified schema.\n"
            "- Explain what happened, why it matters, likely root cause, evidence points, recommended action, responsible owner, and immediate next step.\n"
            "- Provide systemic patterns across feeds and an executive controller takeaway."
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
  "summary": "<Concise overview of situation>",
  "overall_health": "CRITICAL_RISK" | "ACTION_REQUIRED" | "HEALTHY",
  "issues": [
    {{
      "issue_id": "ISSUE-01",
      "title": "<Crisp Issue Title>",
      "severity": "CRITICAL" | "HIGH" | "MEDIUM" | "LOW",
      "affected_records": 1,
      "financial_impact_inr": 150.00,
      "what_happened": "<Clear description of the discrepancy>",
      "why_it_matters": "<Accounting, balance sheet, or audit impact>",
      "likely_cause": "<Operational root cause>",
      "evidence": ["<Fact 1>", "<Fact 2>"],
      "recommended_action": "<Concrete resolution advice>",
      "owner": "<Responsible Team (e.g. Treasury & GL Operations)>",
      "next_step": "<Immediate action>",
      "citations": ["SOP-01 §3", "GAAP ASC 606"]
    }}
  ],
  "systemic_patterns": [
    {{
      "pattern_id": "PAT-01",
      "pattern_name": "<Pattern Title>",
      "affected_count": 1,
      "impact_inr": 150.00,
      "likely_systemic_cause": "<Root cause>",
      "recommended_remediation": "<Remediation action>",
      "remediation_owner": "<Team>",
      "root_cause_status": "IDENTIFIED"
    }}
  ],
  "controller_takeaway": "<Executive CFO conclusion paragraph>"
}}
"""

        if self._groq_client:
            try:
                completion = self._groq_client.chat.completions.create(
                    model=self.groq_model or "openai/gpt-oss-120b",
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    temperature=0.1,
                    max_completion_tokens=2048,
                    timeout=3.5
                )
                raw_text = completion.choices[0].message.content or ""
                parsed_json = self.extract_json(raw_text)
                if parsed_json and isinstance(parsed_json.get("issues"), list):
                    return parsed_json
            except Exception:
                pass

        if self._gemini_client:
            try:
                gemini_model = "gemini-2.5-flash"
                combined_prompt = f"{system_prompt}\n\nUser Context:\n{user_prompt}"
                response = self._gemini_client.models.generate_content(
                    model=gemini_model,
                    contents=combined_prompt
                )
                raw_text = response.text or ""
                parsed_json = self.extract_json(raw_text)
                if parsed_json and isinstance(parsed_json.get("issues"), list):
                    return parsed_json
            except Exception:
                pass

        return None
