"""
Agent 12: Audit Explanation Agent
Specialized LLM reasoning agent for plain-English regulatory compliance,
SOX-404 control narrative, cryptographic SHA-256 chain verification, and Maker-Checker segregation proofs.
"""

import json
from typing import Any, Dict, List, Optional
from app.services.agents.base_agent import BaseReasoningAgent
from app.services.audit_chain import AuditHashChain


class AuditExplanationAgent(BaseReasoningAgent):
    """Agent 12: Cryptographic audit narrative and compliance assurance agent."""

    def __init__(self, groq_api_key: Optional[str] = None, groq_model: Optional[str] = None):
        super().__init__(
            agent_name="AuditExplanationAgent",
            groq_api_key=groq_api_key,
            groq_model=groq_model
        )

    def explain_audit_trail(
        self,
        batch_id: str,
        audit_events: List[Dict[str, Any]],
        approvals: List[Dict[str, Any]],
        batch_summary: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Generates auditor-grade compliance explanation and cryptographic chain verification report."""
        total_blocks = len(audit_events)
        head_hash = audit_events[-1].get("event_hash") if audit_events else AuditHashChain.GENESIS_HASH
        prev_genesis = audit_events[0].get("prev_hash") if audit_events else AuditHashChain.GENESIS_HASH

        # Verify chain integrity deterministically first
        is_intact, broken_seq = AuditHashChain.verify_chain_integrity(audit_events)

        # Segregation of duties check: ensure maker != checker
        segregation_violations = []
        segregation_indeterminate = []
        for prop in approvals:
            if prop.get("status") != "APPROVED":
                continue
            maker = prop.get("created_by")
            checker = prop.get("decided_by") or prop.get("actor_id")
            if not maker or not checker:
                # Defaulting these to "usr_analyst_01" / "usr_approver_01" made an
                # approval with no recorded actors compare two different hardcoded
                # names, so the control silently passed on exactly the rows where it
                # could not be evaluated. Unknown identity is indeterminate, not clean.
                segregation_indeterminate.append(prop.get("id"))
            elif maker == checker:
                segregation_violations.append(prop.get("id"))

        context_envelope = {
            "batch_id": batch_id,
            "total_audit_blocks": total_blocks,
            "chain_integrity_verified": is_intact,
            "genesis_block_hash": prev_genesis,
            "head_block_hash": head_hash,
            "total_maker_checker_approvals": len(approvals),
            "maker_checker_segregation_breaches": len(segregation_violations),
            "maker_checker_unverifiable": len(segregation_indeterminate),
            "sample_audit_blocks": [
                {
                    "seq": e.get("event_seq"),
                    "type": e.get("event_type"),
                    "action": e.get("action"),
                    "actor": e.get("actor_id"),
                    "hash": e.get("event_hash")
                }
                for e in audit_events[:8]
            ]
        }

        system_prompt = (
            "You are the Senior Cryptographic Audit & Compliance Agent (Agent 12) in the AI Financial Controller system. "
            "Analyze the cryptographic hash chain and maker-checker governance records and output an auditor verification report in valid JSON matching:\n"
            "{\n"
            '  "batch_id": str,\n'
            '  "audit_verdict": str,\n'
            '  "cryptographic_integrity_summary": str,\n'
            '  "sox_404_control_assertions": [\n'
            '    {\n'
            '      "control_id": str,\n'
            '      "control_name": str,\n'
            '      "status": str,\n'
            '      "evidence_detail": str\n'
            '    }\n'
            '  ],\n'
            '  "maker_checker_governance_proof": str,\n'
            '  "auditor_signoff_notes": str\n'
            "}\n"
            "Rules:\n"
            "1. Output strictly valid JSON without markdown wrapping.\n"
            "2. Ground assertions directly in the SHA-256 block ledger facts and dual-control approvals.\n"
            "3. Structure output in professional SOX/ITGC compliance terminology."
        )

        user_prompt = json.dumps(context_envelope, indent=2, default=str)
        parsed_json, raw_text, telemetry = self.execute_prompt(system_prompt, user_prompt)

        if parsed_json:
            parsed_json["telemetry"] = telemetry
            # The chain check is deterministic, so report the computed result rather
            # than leaving the client to infer integrity from the model's prose. The
            # UI has no other honest source for its "Integrity Status" line.
            parsed_json["chain_intact"] = is_intact
            parsed_json["total_audit_blocks"] = total_blocks
            if not is_intact:
                parsed_json["chain_broken_at_sequence"] = broken_seq
            return parsed_json

        # Deterministic Fallback
        return self._deterministic_audit_fallback(
            batch_id=batch_id,
            total_blocks=total_blocks,
            head_hash=head_hash,
            is_intact=is_intact,
            approvals_count=len(approvals),
            segregation_breaches=len(segregation_violations),
            segregation_unverifiable=len(segregation_indeterminate),
            telemetry=telemetry
        )

    def _deterministic_audit_fallback(
        self,
        batch_id: str,
        total_blocks: int,
        head_hash: str,
        is_intact: bool,
        approvals_count: int,
        segregation_breaches: int,
        segregation_unverifiable: int,
        telemetry: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Deterministic audit explanation fallback."""
        return {
            "batch_id": batch_id,
            "audit_verdict": "CERTIFIED_TAMPER_PROOF" if is_intact else "INTEGRITY_COMPROMISED",
            "chain_intact": is_intact,
            "total_audit_blocks": total_blocks,
            # These strings used to assert "100% mathematical immutability verified"
            # and control status PASS unconditionally, so a broken chain still
            # produced a clean SOX assertion in the fallback path.
            "cryptographic_integrity_summary": (
                f"All {total_blocks} audit events are sequentially linked via SHA-256 hash chains "
                f"terminating at head hash {head_hash[:16]}... Chain integrity verified."
                if is_intact else
                f"Hash chain verification FAILED across {total_blocks} audit events for this batch. "
                f"The recomputed digest does not match the stored event hash, so the ledger cannot be "
                f"certified as tamper-evident. Investigate before relying on this batch's audit trail."
            ),
            "sox_404_control_assertions": [
                {
                    "control_id": "ITGC-AUD-01",
                    "control_name": "Immutable Cryptographic Audit Logging",
                    "status": "PASS" if is_intact else "FAIL",
                    "evidence_detail": (
                        f"Sequential SHA-256 hash block chaining verified across {total_blocks} ledger events."
                        if is_intact else
                        f"Hash chain verification failed across {total_blocks} ledger events."
                    )
                },
                {
                    # Derived from the actual maker/checker comparison rather than an
                    # unconditional PASS. "INDETERMINATE" is reported when approvals
                    # exist whose maker or checker identity was never recorded, since
                    # the control cannot be evidenced for those rows.
                    "control_id": "SOX-FIN-04",
                    "control_name": "Segregation of Duties & Dual Control",
                    "status": (
                        "FAIL" if segregation_breaches
                        else ("INDETERMINATE" if segregation_unverifiable else "PASS")
                    ),
                    "evidence_detail": (
                        f"{segregation_breaches} approval(s) where the maker also acted as checker."
                        if segregation_breaches else
                        (f"{segregation_unverifiable} approval(s) lack a recorded maker or checker identity, "
                         f"so segregation could not be evidenced."
                         if segregation_unverifiable else
                         f"{approvals_count} adjustments reviewed; maker and checker identities differ on every approval.")
                    )
                },
                {
                    # This agent receives only the audit ledger and approvals, so it
                    # has no arithmetic evidence to assert on. Reporting an
                    # unconditional PASS with "proven to 1-paise precision" claimed a
                    # control this agent never evaluated.
                    "control_id": "SOX-ACC-02",
                    "control_name": "Zero Hallucination Arithmetic Verifier",
                    "status": "NOT_EVALUATED",
                    "evidence_detail": (
                        "Arithmetic verification is performed by the reconciliation engine's balance "
                        "safeguards, not by this audit agent; no evidence was supplied to this control."
                    )
                }
            ],
            "maker_checker_governance_proof": (
                f"{approvals_count} proposal(s) examined: {segregation_breaches} segregation breach(es), "
                f"{segregation_unverifiable} with unverifiable actor identity."
            ),
            "auditor_signoff_notes": (
                "Deterministic fallback report: the hash chain and segregation checks above were computed "
                "directly from the ledger, but no LLM narrative was produced for this batch."
            ),
            "telemetry": telemetry
        }
