"""
Agent 10: Root Cause Analysis (RCA) Agent
Specialized LLM reasoning agent for batch-wide systemic root-cause diagnostics,
discovering macro discrepancy patterns, feed anomalies, vendor delays, and IT/Treasury remediation steps.
"""

import json
from typing import Any, Dict, List, Optional
from app.services.agents.base_agent import BaseReasoningAgent


class RootCauseAnalysisAgent(BaseReasoningAgent):
    """Agent 10: Macro-level batch root cause analysis and systemic diagnostic agent."""

    def __init__(self, groq_api_key: Optional[str] = None, groq_model: Optional[str] = None):
        super().__init__(
            agent_name="RootCauseAnalysisAgent",
            groq_api_key=groq_api_key,
            groq_model=groq_model
        )

    def analyze_batch_exceptions(
        self,
        batch_id: str,
        exceptions: List[Dict[str, Any]],
        safeguards: List[Dict[str, Any]],
        batch_summary: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Runs systemic RCA across the entire exception set of a financial batch."""
        total_excs = len(exceptions)
        
        # Aggregate exception statistics
        exc_type_counts: Dict[str, int] = {}
        severity_counts: Dict[str, int] = {}
        total_held_minor = 0

        for exc in exceptions:
            e_type = exc.get("exception_type") or "UNKNOWN_RESIDUAL"
            sev = exc.get("severity") or "MEDIUM"
            imp = int(exc.get("impact_minor") or 0)
            exc_type_counts[e_type] = exc_type_counts.get(e_type, 0) + 1
            severity_counts[sev] = severity_counts.get(sev, 0) + 1
            total_held_minor += imp

        # Prepare structured context payload
        context_envelope = {
            "batch_id": batch_id,
            "total_records": batch_summary.get("total_records", 0),
            "match_rate": batch_summary.get("match_rate", 0.0),
            "total_exceptions_count": total_excs,
            "total_held_amount_inr": f"₹{total_held_minor / 100:.2f}",
            "exception_type_breakdown": exc_type_counts,
            "severity_breakdown": severity_counts,
            "safeguards_triggered": safeguards[:8],
            "sample_exceptions": [
                {
                    "id": e.get("id"),
                    "type": e.get("exception_type"),
                    "severity": e.get("severity"),
                    "impact_inr": f"₹{(int(e.get('impact_minor') or 0)) / 100:.2f}",
                    "findings": e.get("findings", [])
                }
                for e in exceptions[:10]
            ]
        }

        system_prompt = (
            "You are the Senior Root Cause Analysis Agent (Agent 10) in the AI Financial Controller system. "
            "Analyze the batch-wide exception dataset and provide systemic diagnostic findings in valid JSON matching:\n"
            "{\n"
            '  "batch_id": str,\n'
            '  "primary_bottleneck": str,\n'
            '  "systemic_risk_score": float,\n'
            '  "systemic_findings": [\n'
            '    {\n'
            '      "pattern_name": str,\n'
            '      "affected_count": int,\n'
            '      "impact_inr": str,\n'
            '      "root_cause_explanation": str,\n'
            '      "recommended_remediation": str,\n'
            '      "remediation_owner": str\n'
            '    }\n'
            '  ],\n'
            '  "operational_summary": str,\n'
            '  "preventative_action_items": list[str]\n'
            "}\n"
            "Rules:\n"
            "1. Output strictly valid JSON without markdown wrapping.\n"
            "2. Ground all numbers directly in the provided exception distribution.\n"
            "3. Identify clear ownership: IT/Engineering, Treasury Operations, Gateway Aggregator, or Accounting."
        )

        user_prompt = json.dumps(context_envelope, indent=2, default=str)
        parsed_json, raw_text, telemetry = self.execute_prompt(system_prompt, user_prompt)

        if parsed_json:
            parsed_json["telemetry"] = telemetry
            return parsed_json

        # Deterministic Fallback
        return self._deterministic_rca_fallback(
            batch_id=batch_id,
            total_excs=total_excs,
            total_held_minor=total_held_minor,
            exc_type_counts=exc_type_counts,
            telemetry=telemetry
        )

    def _deterministic_rca_fallback(
        self,
        batch_id: str,
        total_excs: int,
        total_held_minor: int,
        exc_type_counts: Dict[str, int],
        telemetry: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Deterministic root cause analysis fallback."""
        findings = []
        for exc_type, count in exc_type_counts.items():
            if "CUTOFF" in exc_type or "TIMING" in exc_type:
                findings.append({
                    "pattern_name": "Month-End Period Boundary Timing Difference (T+2 Clearing)",
                    "affected_count": count,
                    "impact_inr": f"₹{total_held_minor / 100:.2f}",
                    "root_cause_explanation": "Payments captured near month-end boundary settle across banking value dates.",
                    "recommended_remediation": "Apply automatic monthly accrual entry to GL Account 1290 (In-Transit Clearing).",
                    "remediation_owner": "Treasury Operations"
                })
            elif "FEE" in exc_type or "MDR" in exc_type:
                findings.append({
                    "pattern_name": "Gateway MDR Processing Deductions Booked Net",
                    "affected_count": count,
                    "impact_inr": f"₹{total_held_minor / 100:.2f}",
                    "root_cause_explanation": "Gateway settlement files deduct 2.0% MDR + 18% GST before bank credit.",
                    "recommended_remediation": "Configure automated fee splitting rule to post gross revenue and debit MDR expense Account 5010.",
                    "remediation_owner": "Accounting Operations"
                })
            else:
                findings.append({
                    "pattern_name": f"Unmatched Residuals: {exc_type}",
                    "affected_count": count,
                    "impact_inr": f"₹{total_held_minor / 100:.2f}",
                    "root_cause_explanation": "Unallocated direct deposits or missing counterpart records.",
                    "recommended_remediation": "Submit Maker-Checker resolution vouchers for manual journal booking.",
                    "remediation_owner": "Controller Review Team"
                })

        return {
            "batch_id": batch_id,
            "primary_bottleneck": "Period Cutoff Lag & Fee Netting Variances",
            "systemic_risk_score": round(min(1.0, total_excs / 50.0), 2),
            "systemic_findings": findings or [{
                "pattern_name": "Standard Variance Distribution",
                "affected_count": total_excs,
                "impact_inr": f"₹{total_held_minor / 100:.2f}",
                "root_cause_explanation": "Routine multi-stream variances within configured tolerance thresholds.",
                "recommended_remediation": "Proceed with standard maker-checker review queue.",
                "remediation_owner": "Accounting Team"
            }],
            "operational_summary": f"Systemic analysis of batch {batch_id} covering {total_excs} held exceptions totaling ₹{total_held_minor/100:.2f}.",
            "preventative_action_items": [
                "Deploy automated T+2 clearing accrual schedules at month-end.",
                "Update merchant aggregator MDR fee policy in FeePolicyRegistry.",
                "Enforce mandatory UTR transmission on direct wire deposits."
            ],
            "telemetry": telemetry
        }
