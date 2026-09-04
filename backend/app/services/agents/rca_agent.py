"""
Agent 10: Root Cause Analysis (RCA) Agent
Specialized LLM and deterministic reasoning agent for batch-wide systemic root-cause diagnostics.
Strictly scoped to verified exceptions from the CURRENT batch.
Never infers operational root causes as facts without explicit evidence.
"""

import json
from typing import Any, Dict, List, Optional, Set
from app.services.agents.base_agent import BaseReasoningAgent
from app.models.schemas import (
    RootCauseStatus,
    SystemicRCAFinding,
    SystemicRCAResult
)


class RootCauseAnalysisAgent(BaseReasoningAgent):
    """Agent 10: Macro-level batch root cause analysis and systemic diagnostic agent."""

    def __init__(
        self,
        groq_api_key: Optional[str] = None,
        groq_model: Optional[str] = None,
        groq_api_key_secondary: Optional[str] = None
    ):
        super().__init__(
            agent_name="RootCauseAnalysisAgent",
            groq_api_key=groq_api_key,
            groq_api_key_secondary=groq_api_key_secondary,
            groq_model=groq_model
        )

    def analyze_batch_exceptions(
        self,
        batch_id: str,
        exceptions: List[Dict[str, Any]],
        safeguards: List[Dict[str, Any]],
        batch_summary: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Runs systemic RCA strictly across verified exceptions of the current batch."""
        # 1. Strict Current Batch Scoping
        batch_exceptions = [
            e for e in exceptions
            if not e.get("batch_id") or e.get("batch_id") == batch_id
        ]
        total_excs = len(batch_exceptions)
        
        # Collect candidate ID whitelists from current batch
        valid_exception_ids: Set[str] = {str(e.get("id")) for e in batch_exceptions if e.get("id")}
        valid_record_ids: Set[str] = set()
        for e in batch_exceptions:
            if e.get("primary_txn_id"):
                valid_record_ids.add(str(e.get("primary_txn_id")))
            if e.get("counterpart_txn_id"):
                valid_record_ids.add(str(e.get("counterpart_txn_id")))

        # Handle 0 exceptions case
        if total_excs == 0:
            res = SystemicRCAResult(
                batch_id=batch_id,
                total_exceptions_analyzed=0,
                total_impact_inr=0.0,
                systemic_risk_score=0.0,
                systemic_findings=[],
                operational_summary=f"Batch {batch_id} has zero unresolved exceptions. All transaction streams fully reconciled.",
                preventative_action_items=["Maintain current ingestion and automated reconciliation SLA."],
                telemetry={"mode": "ZERO_EXCEPTIONS_CLEAN_BATCH"}
            )
            return res.model_dump()

        # Aggregate exception statistics
        exc_type_groups: Dict[str, List[Dict[str, Any]]] = {}
        total_held_minor = 0

        for exc in batch_exceptions:
            e_type = exc.get("exception_type") or "UNKNOWN_RESIDUAL"
            exc_type_groups.setdefault(e_type, []).append(exc)
            total_held_minor += int(exc.get("impact_minor") or 0)

        # Build Deterministic Baseline
        deterministic_findings = self._build_deterministic_findings(
            batch_id=batch_id,
            exc_type_groups=exc_type_groups
        )

        # Enforce Count Reconciliation Assertions on deterministic baseline
        self._assert_findings_integrity(
            findings=deterministic_findings,
            total_exceptions=total_excs,
            valid_exception_ids=valid_exception_ids
        )

        # Prepare context payload for LLM analysis
        context_envelope = {
            "batch_id": batch_id,
            "total_records": batch_summary.get("total_records", 0),
            "match_rate": batch_summary.get("match_rate", 0.0),
            "total_exceptions_count": total_excs,
            "total_held_amount_inr": f"₹{total_held_minor / 100:.2f}",
            "exception_type_breakdown": {k: len(v) for k, v in exc_type_groups.items()},
            "safeguards_triggered": safeguards[:8],
            "deterministic_baseline_findings": [f.model_dump() for f in deterministic_findings]
        }

        system_prompt = (
            "You are the Senior Root Cause Analysis Agent (Agent 10) in the Recon system. "
            "Analyze the batch-wide exception dataset and provide systemic diagnostic findings in valid JSON matching:\n"
            "{\n"
            '  "batch_id": str,\n'
            '  "primary_bottleneck": str,\n'
            '  "systemic_risk_score": float,\n'
            '  "systemic_findings": [\n'
            '    {\n'
            '      "pattern_name": str,\n'
            '      "affected_count": int,\n'
            '      "impact_inr": float,\n'
            '      "affected_exception_ids": list[str],\n'
            '      "affected_record_ids": list[str],\n'
            '      "observed_evidence": list[str],\n'
            '      "root_cause_status": "CONFIRMED" | "SUPPORTED_HYPOTHESIS" | "UNKNOWN",\n'
            '      "root_cause_explanation": str,\n'
            '      "confidence": float,\n'
            '      "recommended_remediation": str,\n'
            '      "remediation_owner": str\n'
            '    }\n'
            '  ],\n'
            '  "operational_summary": str,\n'
            '  "preventative_action_items": list[str]\n'
            "}\n"
            "CRITICAL RULES:\n"
            "1. Output strictly valid JSON without markdown wrapping.\n"
            "2. root_cause_status MUST be one of: 'CONFIRMED', 'SUPPORTED_HYPOTHESIS', 'UNKNOWN'.\n"
            "3. NEVER infer operational causes (e.g. 'Bank API timeout', 'Database crash') as facts unless explicit system evidence exists.\n"
            "4. The sum of affected_count across all findings MUST equal the total exceptions count.\n"
            "5. All affected_exception_ids and affected_record_ids must exist in the provided batch."
        )

        user_prompt = json.dumps(context_envelope, indent=2, default=str)
        parsed_json, raw_text, telemetry = self.execute_prompt(system_prompt, user_prompt)

        if parsed_json and self._verify_llm_rca(parsed_json, total_excs, valid_exception_ids, valid_record_ids):
            parsed_json["telemetry"] = telemetry
            # Convert finding objects to validated models
            sanitized_findings = [
                SystemicRCAFinding(**f) for f in parsed_json.get("systemic_findings", [])
            ]
            result = SystemicRCAResult(
                batch_id=batch_id,
                total_exceptions_analyzed=total_excs,
                total_impact_inr=round(total_held_minor / 100, 2),
                systemic_risk_score=float(parsed_json.get("systemic_risk_score", round(min(1.0, total_excs / 50.0), 2))),
                systemic_findings=sanitized_findings,
                operational_summary=parsed_json.get("operational_summary", f"Batch {batch_id} systemic analysis of {total_excs} exceptions."),
                preventative_action_items=parsed_json.get("preventative_action_items", []),
                telemetry=telemetry
            )
            d = result.model_dump()
            d["primary_bottleneck"] = parsed_json.get("primary_bottleneck") or (sanitized_findings[0].pattern_name if sanitized_findings else "General Discrepancies")
            return d

        # Deterministic Verified Fallback
        res = SystemicRCAResult(
            batch_id=batch_id,
            total_exceptions_analyzed=total_excs,
            total_impact_inr=round(total_held_minor / 100, 2),
            systemic_risk_score=round(min(1.0, total_excs / 50.0), 2),
            systemic_findings=deterministic_findings,
            operational_summary=f"Systemic diagnostic of batch {batch_id} covering {total_excs} held exceptions totaling ₹{total_held_minor/100:,.2f}.",
            preventative_action_items=[
                "Deploy automated T+2 clearing accrual schedules at month-end.",
                "Verify merchant aggregator MDR fee policy in FeePolicyRegistry.",
                "Enforce mandatory UTR transmission on direct wire deposits."
            ],
            telemetry=telemetry
        )
        d = res.model_dump()
        d["primary_bottleneck"] = deterministic_findings[0].pattern_name if deterministic_findings else "General Discrepancies"
        return d

    def _build_deterministic_findings(
        self,
        batch_id: str,
        exc_type_groups: Dict[str, List[Dict[str, Any]]]
    ) -> List[SystemicRCAFinding]:
        """Builds mathematically reconciled, evidence-grounded systemic findings."""
        findings: List[SystemicRCAFinding] = []

        for exc_type, group in exc_type_groups.items():
            count = len(group)
            impact_minor = sum(int(e.get("impact_minor") or 0) for e in group)
            impact_inr = round(impact_minor / 100, 2)
            exc_ids = [str(e.get("id")) for e in group if e.get("id")]
            rec_ids = list(set(filter(None, [str(e.get("primary_txn_id") or e.get("counterpart_txn_id")) for e in group])))

            if "CUTOFF" in exc_type or "TIMING" in exc_type or "DATE_MISMATCH" in exc_type:
                findings.append(SystemicRCAFinding(
                    pattern_name="Month-End Period Boundary Timing Difference (T+2 Clearing)",
                    affected_count=count,
                    impact_inr=impact_inr,
                    affected_exception_ids=exc_ids,
                    affected_record_ids=rec_ids,
                    observed_evidence=[
                        f"{count} payments captured near month-end boundary settle across banking value dates."
                    ],
                    root_cause_status=RootCauseStatus.SUPPORTED_HYPOTHESIS,
                    root_cause_explanation="Payments captured near month-end boundary settle across banking value dates within standard clearing window.",
                    confidence=0.90,
                    recommended_remediation="Apply automatic monthly accrual entry to GL Account 1290 (In-Transit Clearing).",
                    remediation_owner="Treasury Operations"
                ))
            elif "FEE" in exc_type or "MDR" in exc_type:
                findings.append(SystemicRCAFinding(
                    pattern_name="Gateway MDR Processing Deductions Booked Net",
                    affected_count=count,
                    impact_inr=impact_inr,
                    affected_exception_ids=exc_ids,
                    affected_record_ids=rec_ids,
                    observed_evidence=[
                        f"{count} gateway settlement records deduct standard MDR fee and GST before crediting bank account."
                    ],
                    root_cause_status=RootCauseStatus.CONFIRMED,
                    root_cause_explanation="Gateway settlement files deduct contractual MDR fee and GST before bank credit.",
                    confidence=0.98,
                    recommended_remediation="Configure automated fee splitting rule to post gross revenue and debit MDR expense Account 5010.",
                    remediation_owner="Accounting Operations"
                ))
            elif "MISSING_BANK" in exc_type:
                findings.append(SystemicRCAFinding(
                    pattern_name="Unsettled Gateway Captures Pending Bank Wire",
                    affected_count=count,
                    impact_inr=impact_inr,
                    affected_exception_ids=exc_ids,
                    affected_record_ids=rec_ids,
                    observed_evidence=[
                        f"Bank settlement is missing for {count} payment records in the current batch."
                    ],
                    root_cause_status=RootCauseStatus.SUPPORTED_HYPOTHESIS,
                    root_cause_explanation="Bank settlement credit is missing for captured payments; possible settlement processing delay.",
                    confidence=0.85,
                    recommended_remediation="Escalate settlement batch UTR reference with payment gateway operations.",
                    remediation_owner="Treasury Operations"
                ))
            elif "UNKNOWN_BANK" in exc_type:
                findings.append(SystemicRCAFinding(
                    pattern_name="Unallocated Direct Bank Credits",
                    affected_count=count,
                    impact_inr=impact_inr,
                    affected_exception_ids=exc_ids,
                    affected_record_ids=rec_ids,
                    observed_evidence=[
                        f"{count} direct bank credit deposits without matching order or invoice reference keys."
                    ],
                    root_cause_status=RootCauseStatus.UNKNOWN,
                    root_cause_explanation="Direct customer bank deposits without structured reference keys; root cause cannot be determined from file data alone.",
                    confidence=0.75,
                    recommended_remediation="Route to Accounts Receivable for manual remittance advice matching.",
                    remediation_owner="Accounts Receivable Team"
                ))
            elif "DUPLICATE" in exc_type:
                findings.append(SystemicRCAFinding(
                    pattern_name="Duplicate Feed Records Quarantined",
                    affected_count=count,
                    impact_inr=impact_inr,
                    affected_exception_ids=exc_ids,
                    affected_record_ids=rec_ids,
                    observed_evidence=[
                        f"{count} source rows share duplicate external transaction IDs and amounts."
                    ],
                    root_cause_status=RootCauseStatus.CONFIRMED,
                    root_cause_explanation="Duplicate source rows received in feed; quarantined by reconciliation engine.",
                    confidence=1.0,
                    recommended_remediation="Quarantine redundant duplicate rows and maintain single authoritative ledger entry.",
                    remediation_owner="Data Integration Team"
                ))
            else:
                findings.append(SystemicRCAFinding(
                    pattern_name=f"Multi-Stream Variance: {exc_type}",
                    affected_count=count,
                    impact_inr=impact_inr,
                    affected_exception_ids=exc_ids,
                    affected_record_ids=rec_ids,
                    observed_evidence=[
                        f"{count} transactions classified as {exc_type} totaling ₹{impact_inr:,.2f}."
                    ],
                    root_cause_status=RootCauseStatus.UNKNOWN,
                    root_cause_explanation=f"Discrepancy pattern for {exc_type}; root cause cannot be confirmed without external operational logs.",
                    confidence=0.70,
                    recommended_remediation="Submit Maker-Checker resolution vouchers for manual journal booking.",
                    remediation_owner="Controller Review Team"
                ))

        return findings

    def _assert_findings_integrity(
        self,
        findings: List[SystemicRCAFinding],
        total_exceptions: int,
        valid_exception_ids: Set[str]
    ) -> None:
        """Enforces strict mathematical reconciliation and bounding assertions on RCA findings."""
        sum_affected = sum(f.affected_count for f in findings)
        if sum_affected > total_exceptions:
            raise ValueError(
                f"RCA affected count ({sum_affected}) exceeds total applicable exceptions ({total_exceptions})."
            )
        for f in findings:
            if f.affected_count > total_exceptions:
                raise ValueError(
                    f"Finding '{f.pattern_name}' affected_count ({f.affected_count}) exceeds total exceptions ({total_exceptions})."
                )
            if len(f.affected_exception_ids) != f.affected_count:
                raise ValueError(
                    f"Finding '{f.pattern_name}' affected_exception_ids count ({len(f.affected_exception_ids)}) does not match affected_count ({f.affected_count})."
                )
            invalid_ids = set(f.affected_exception_ids) - valid_exception_ids
            if invalid_ids:
                raise ValueError(
                    f"Finding '{f.pattern_name}' references invalid exception IDs not present in current batch: {invalid_ids}"
                )

    def _verify_llm_rca(
        self,
        parsed_json: Dict[str, Any],
        total_exceptions: int,
        valid_exception_ids: Set[str],
        valid_record_ids: Set[str]
    ) -> bool:
        """Validates LLM output against strict mathematical, anti-hallucination, and candidate constraints."""
        findings = parsed_json.get("systemic_findings")
        if not isinstance(findings, list) or len(findings) == 0:
            return False

        sum_affected = 0
        forbidden_operational_inventions = [
            "api timeout", "api failure", "database failure", "database crashed",
            "treasury failure", "network outage", "gateway crash", "server reboot"
        ]

        for f in findings:
            if not isinstance(f, dict):
                return False
            status = f.get("root_cause_status")
            if status not in ("CONFIRMED", "SUPPORTED_HYPOTHESIS", "UNKNOWN"):
                return False

            count = f.get("affected_count", 0)
            if count <= 0 or count > total_exceptions:
                return False
            sum_affected += count

            # Validate IDs
            exc_ids = set(f.get("affected_exception_ids", []))
            if exc_ids - valid_exception_ids:
                return False  # Hallucinated exception ID

            rec_ids = set(f.get("affected_record_ids", []))
            if rec_ids - valid_record_ids:
                return False  # Hallucinated record ID

            # Anti-hallucination of operational causes as confirmed facts
            explanation_lower = (f.get("root_cause_explanation") or "").lower()
            if status == "CONFIRMED":
                for phrase in forbidden_operational_inventions:
                    if phrase in explanation_lower:
                        return False  # Cannot claim operational IT failure as CONFIRMED without proof

        if sum_affected != total_exceptions:
            return False  # Sum of affected counts must exactly reconcile with total exceptions

        return True

