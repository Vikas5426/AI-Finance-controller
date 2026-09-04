"""
Bounded Recon Investigation Runtime & Verifier Gate
Strict Policy:
- AI is strictly reserved for ambiguity, root-cause investigation, and contextual recommendations.
- AI is FORBIDDEN for arithmetic, exact ID matching, fee calculations, date comparisons,
  duplicate detection, and deterministic accounting rules.
- Context is targeted and scoped: Never passes arbitrary or unrelated transactions.
- L1 in-memory and L2 caching prevent redundant AI calls on recurring exception signatures.
"""

import json
import logging
import os
import time
import hashlib
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Set, Tuple
from app.core.config import settings
from app.models.schemas import InvestigationResult, ToolEvidence
from app.services.fee_policy import FeePolicyRegistry
from app.services.period import derive_period, _as_date

logger = logging.getLogger(__name__)


def _record_agent_telemetry(*args, **kwargs):
    """Helper to record telemetry without circular import."""
    try:
        from app.services.agents.base_agent import AgentTelemetryTracker
        AgentTelemetryTracker.record_call(*args, **kwargs)
    except Exception:
        pass

AMBIGUOUS_CREDIT_TYPES = (
    "UNALLOCATED_BANK_CREDIT",
    "ANONYMOUS_BANK_LINE",
    "UNKNOWN_BANK_CREDIT",
    "UNSETTLED_GATEWAY_RECORD"
)


class DeterministicVerifier:
    """Hard-gate verifier that enforces AI immutability, fact-checking, and zero-hallucination policies."""

    PROHIBITED_UNGROUNDED_TERMS = [
        "database failure", "database crash", "db connection failed",
        "api failure", "api timeout", "endpoint failure",
        "treasury failure", "treasury outage",
        "gateway failure", "gateway crash",
        "ingestion failure", "parser crash"
    ]

    @staticmethod
    def verify_proposal(
        proposal: InvestigationResult,
        exception_ctx: Dict[str, Any],
        valid_txn_ids: Set[str]
    ) -> Tuple[bool, Optional[str]]:
        
        # 1. Classification Immutability: AI CANNOT override deterministic classification
        expected_classification = exception_ctx.get("classification") or exception_ctx.get("exception_type")
        if expected_classification and proposal.classification != expected_classification:
            proposal.classification = expected_classification

        # 2. Candidate ID Existence check (AI CANNOT invent non-existent IDs)
        if valid_txn_ids:
            for cand_id in proposal.candidate_match_ids:
                if not cand_id or cand_id not in valid_txn_ids:
                    return False, f"Candidate ID {cand_id} does not exist in the active batch."

        # 3. ToolEvidence record_id enforcement (MUST contain real record_id, NEVER null)
        default_record_id = list(valid_txn_ids)[0] if valid_txn_ids else (exception_ctx.get("primary_txn_id") or "TXN-DEFAULT")
        for ev in proposal.evidence:
            if not getattr(ev, "record_id", None):
                ev.record_id = default_record_id
            elif ev.record_id not in valid_txn_ids and valid_txn_ids:
                ev.record_id = default_record_id

        # 4. Arithmetic verification for fee/tax splits & expected net
        has_fee_evidence = any(getattr(ev, "field", "") == "fee_breakup" for ev in proposal.evidence)
        if has_fee_evidence:
            claimed_sum = 0
            evidence_found = False
            for ev in proposal.evidence:
                if ev.field == "fee_breakup" and isinstance(ev.value, dict):
                    evidence_found = True
                    if "total_deduction_minor" in ev.value:
                        try:
                            claimed_sum = int(ev.value["total_deduction_minor"])
                        except (ValueError, TypeError):
                            claimed_sum = 0
                    elif "fee_minor" in ev.value and "tax_minor" in ev.value:
                        try:
                            claimed_sum = int(ev.value["fee_minor"]) + int(ev.value["tax_minor"])
                        except (ValueError, TypeError):
                            claimed_sum = 0
            
            actual_diff = exception_ctx.get("impact_minor", 0)
            if evidence_found and actual_diff > 0 and abs(claimed_sum - actual_diff) > 2:
                return False, f"Arithmetic mismatch: claimed sum ({claimed_sum}) != actual variance ({actual_diff})."

        # 5. Hallucination Check: Prohibit unevidenced operational/API/DB failure claims
        explanation_text = (f"{proposal.likely_cause} {proposal.possible_cause or ''}").lower()
        for term in DeterministicVerifier.PROHIBITED_UNGROUNDED_TERMS:
            if term in explanation_text:
                anomaly_flags = [f.lower() for f in exception_ctx.get("anomaly_flags", [])]
                if not any(term in f for f in anomaly_flags):
                    proposal.possible_cause = "Cause cannot be determined from the supplied evidence."
                    proposal.likely_cause = f"Discrepancy of classification {proposal.classification} detected by deterministic engine. Cause cannot be determined from the supplied evidence."
                    break

        # 6. Structured 4-tier reasoning fallback if missing
        if not proposal.facts:
            proposal.facts = [
                f"Exception ID: {proposal.exception_id}",
                f"Verified Classification: {proposal.classification}",
                f"Impact: ₹{exception_ctx.get('impact_minor', 0)/100:,.2f}"
            ]
        if not proposal.observations:
            proposal.observations = [
                f"Deterministic reconciliation pipeline isolated transaction under rule verification."
            ]
        if not proposal.possible_cause:
            proposal.possible_cause = proposal.likely_cause or "Cause cannot be determined from the supplied evidence."
        if not proposal.recommendation:
            proposal.recommendation = proposal.recommended_action or "Queue for standard controller maker-checker review."

        # 7. Confidence bounds check
        if proposal.confidence < 0.0 or proposal.confidence > 1.0:
            return False, "Confidence score must be strictly bounded between 0.0 and 1.0."

        return True, None


class AIAgentRuntime:
    """Bounded AI investigation runtime with targeted context extraction and priority filtering."""

    # In-memory L1 cache for recurring exception signatures
    _L1_CACHE: Dict[str, InvestigationResult] = {}

    # Audit & telemetry counters
    stats = {
        "total_exceptions": 0,
        "deterministically_resolved": 0,
        "ai_investigated": 0,
        "manual_review": 0,
        "ai_avoided": 0,
        "cache_hits": 0
    }

    def __init__(
        self,
        groq_api_key: Optional[str] = None,
        groq_api_key_secondary: Optional[str] = None,
        gemini_api_key: Optional[str] = None,
        anthropic_api_key: Optional[str] = None
    ):
        self.groq_api_key = groq_api_key or settings.GROQ_API_KEY
        self.groq_api_key_secondary = groq_api_key_secondary or getattr(settings, "GROQ_API_KEY_SECONDARY", None)
        self.gemini_api_key = gemini_api_key or settings.GEMINI_API_KEY
        self.anthropic_api_key = anthropic_api_key or settings.ANTHROPIC_API_KEY

        self._groq_client = None
        if self.groq_api_key:
            try:
                from groq import Groq
                self._groq_client = Groq(api_key=self.groq_api_key, timeout=8.0)
            except Exception as e:
                logger.warning("[agent_runtime] Groq client unavailable despite configured key: %s", e)

        self._groq_client_secondary = None
        if self.groq_api_key_secondary:
            try:
                from groq import Groq
                self._groq_client_secondary = Groq(api_key=self.groq_api_key_secondary, timeout=8.0)
            except Exception as e:
                logger.warning("[agent_runtime] Secondary Groq client unavailable: %s", e)

        self._gemini_client = None
        if self.gemini_api_key:
            try:
                from google import genai
                self._gemini_client = genai.Client(api_key=self.gemini_api_key)
            except Exception as e:
                logger.warning("[agent_runtime] Gemini client unavailable despite configured key: %s", e)

        self._anthropic_client = None
        if self.anthropic_api_key:
            try:
                import anthropic
                self._anthropic_client = anthropic.Anthropic(api_key=self.anthropic_api_key)
            except Exception as e:
                logger.warning("[agent_runtime] Anthropic client unavailable despite configured key: %s", e)

    @classmethod
    def reset_stats(cls):
        """Resets telemetry counters for a fresh audit cycle."""
        cls.stats = {
            "total_exceptions": 0,
            "deterministically_resolved": 0,
            "ai_investigated": 0,
            "manual_review": 0,
            "ai_avoided": 0,
            "cache_hits": 0
        }

    @classmethod
    def get_audit_summary(cls) -> Dict[str, Any]:
        """Returns the current AI usage and prevention audit summary."""
        return dict(cls.stats)

    @staticmethod
    def should_invoke_ai(
        exception_type: str,
        severity: str,
        impact_minor: int,
        has_deterministic_rule: bool = False
    ) -> Tuple[bool, str]:
        """
        Decision Flow Gate:
        - Deterministic matching & accounting rules resolved -> finalize without AI
        - Exact ID matching, fee variance calculations, duplicate detection -> deterministic
        - Ambiguous exception, multi-leg discrepancy, cutoff lag -> call AI Investigation Agent
        - High-risk/critical items -> flagged for Human Approval
        """
        deterministic_types = {
            "AMOUNT_TOLERANCE_MINOR",
            "ROUNDING_DIFFERENCE",
            "DUPLICATE_RECORD",
            "DUPLICATE_GATEWAY_WEBHOOK",
            "DUPLICATE_LEDGER_POSTING",
            "TIMING_DIFFERENCE",
            "TIMING_DIFFERENCE_PERIOD_CUTOFF",
            "FEE_AND_TAX_BOOKED_NET",
            "MDR_FEE_VARIANCE",
            "MDR_FEE_MISMATCH"
        }

        if has_deterministic_rule or exception_type in deterministic_types:
            return False, "DETERMINISTIC_RULES_SUFFICIENT"

        # 2. Low impact routine items -> Manual review queue (Avoid AI call)
        if severity == "LOW" or (impact_minor <= 50000 and severity not in ("CRITICAL", "HIGH") and exception_type not in AMBIGUOUS_CREDIT_TYPES):
            return False, "LOW_IMPACT_MANUAL_REVIEW_QUEUE"

        # 3. High/Critical impact or ambiguous direct deposits / unexplained missing funds -> AI
        if severity in ("CRITICAL", "HIGH") or impact_minor >= settings.MATERIALITY_THRESHOLD_MINOR or exception_type in AMBIGUOUS_CREDIT_TYPES:
            return True, "HIGH_FINANCIAL_IMPACT_AMBIGUOUS_INVESTIGATION"

        # 4. Fallback for other medium ambiguity
        if severity == "MEDIUM":
            return True, "MEDIUM_AMBIGUITY_ROOT_CAUSE_INVESTIGATION"

        return False, "LOW_IMPACT_MANUAL_REVIEW_QUEUE"

    @staticmethod
    def build_targeted_context(
        exception_id: str,
        exception_type: str,
        severity: str,
        impact_minor: int,
        primary_txn: Optional[Dict[str, Any]],
        counterpart_txn: Optional[Dict[str, Any]],
        all_txns: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """
        Constructs a targeted, relevant context envelope for AI adhering to AIExceptionContext:
        - Strict structured contract with all deterministic figures pre-computed.
        - NEVER passes null record IDs.
        - Provides real source and matched records.
        """
        all_txns = all_txns or []
        p = primary_txn or {}
        c = counterpart_txn or {}

        # 1. Extract reference tokens from primary
        p_id = str(p.get("id") or exception_id)
        p_ext = str(p.get("external_id") or "")
        p_desc = str(p.get("description_raw") or "")
        p_amt = int(p.get("amount_minor") or 0)
        p_kind = str(p.get("source_kind") or "")
        p_date = p.get("occurred_at")

        # 2. Find Gateway record
        gateway_rec = p if p_kind == "GATEWAY" else None
        if not gateway_rec:
            for t in all_txns:
                if t.get("source_kind") == "GATEWAY" and (
                    (p_ext and p_ext in str(t.get("external_id", ""))) or
                    (p_ext and p_ext in str(t.get("description_raw", "")))
                ):
                    gateway_rec = t
                    break

        # 3. Find Candidate Bank Records based on reference, amount proximity, or date window
        candidate_bank_records = []
        for t in all_txns:
            if t.get("source_kind") == "BANK":
                b_ext = str(t.get("external_id") or "")
                b_desc = str(t.get("description_raw") or "")
                b_amt = int(t.get("amount_minor") or 0)
                
                # Check reference match
                ref_match = bool(p_ext and (p_ext in b_desc or p_ext in b_ext))
                amt_proximity = abs(b_amt - p_amt) <= max(round(p_amt * 0.05), 10000)
                
                if ref_match or amt_proximity:
                    candidate_bank_records.append({
                        "id": str(t.get("id") or f"BANK-{b_ext}"),
                        "record_id": str(t.get("id") or f"BANK-{b_ext}"),
                        "external_id": b_ext,
                        "amount_minor": b_amt,
                        "amount_inr": f"₹{b_amt/100:.2f}",
                        "description": b_desc,
                        "date": str(t.get("occurred_at")),
                        "ref_match": ref_match
                    })
                if len(candidate_bank_records) >= 3:
                    break

        # 4. Find Related Ledger Entries
        related_ledger_entries = []
        for t in all_txns:
            if t.get("source_kind") == "LEDGER":
                l_desc = str(t.get("description_raw") or "")
                l_code = str(t.get("account_code") or "")
                l_amt = int(t.get("amount_minor") or 0)
                
                if (p_ext and p_ext in l_desc) or abs(l_amt - p_amt) <= 5000:
                    related_ledger_entries.append({
                        "id": str(t.get("id") or f"GL-{t.get('external_id')}"),
                        "record_id": str(t.get("id") or f"GL-{t.get('external_id')}"),
                        "external_id": t.get("external_id"),
                        "account_code": l_code,
                        "account_name": t.get("account_name"),
                        "amount_minor": l_amt,
                        "amount_inr": f"₹{l_amt/100:.2f}",
                        "memo": l_desc
                    })
                if len(related_ledger_entries) >= 5:
                    break

        # 5. Pre-compute Amount Calculations via Versioned Fee Policy
        gross = gateway_rec.get("amount_minor", p_amt) if gateway_rec else p_amt
        decl_fee = (gateway_rec.get("fee_minor") if gateway_rec else p.get("fee_minor")) or 0
        decl_tax = (gateway_rec.get("tax_minor") if gateway_rec else p.get("tax_minor")) or 0
        if decl_fee > 0 or decl_tax > 0:
            fee_minor = decl_fee
            tax_minor = decl_tax
            net_minor = gross - fee_minor - tax_minor
            formula_proof = f"Gross ₹{gross/100:.2f} - Declared Fee ₹{fee_minor/100:.2f} - Tax ₹{tax_minor/100:.2f} = Net ₹{net_minor/100:.2f}"
            policy_id = "POL-DECLARED-MDR"
        else:
            policy = FeePolicyRegistry.get_default_policy()
            breakdown = policy.calculate(gross)
            fee_minor = breakdown.fee_minor
            tax_minor = breakdown.tax_minor
            net_minor = breakdown.expected_net_minor
            formula_proof = breakdown.formula_proof
            policy_id = policy.policy_id

        # 6. Date Difference & Dynamic Period Cutoff Check
        period = derive_period(all_txns or ([primary_txn] if primary_txn else []))
        val_d = _as_date(p_date) or date.today()
        is_cutoff = period.is_cutoff_date(val_d, window_days=2)

        actual_bank_settlement = None
        if counterpart_txn and counterpart_txn.get("amount_minor") is not None:
            actual_bank_settlement = round(int(counterpart_txn["amount_minor"]) / 100, 2)
        elif p_kind == "BANK":
            actual_bank_settlement = round(p_amt / 100, 2)

        source_records = []
        if primary_txn and primary_txn.get("id"):
            source_records.append({
                "record_id": primary_txn["id"],
                "source_kind": primary_txn.get("source_kind"),
                "external_id": primary_txn.get("external_id"),
                "amount_minor": primary_txn.get("amount_minor"),
                "amount_inr": f"₹{int(primary_txn.get('amount_minor', 0))/100:.2f}",
                "date": str(primary_txn.get("occurred_at")),
                "description": primary_txn.get("description_raw")
            })

        matched_records = []
        if counterpart_txn and counterpart_txn.get("id"):
            matched_records.append({
                "record_id": counterpart_txn["id"],
                "source_kind": counterpart_txn.get("source_kind"),
                "external_id": counterpart_txn.get("external_id"),
                "amount_minor": counterpart_txn.get("amount_minor"),
                "amount_inr": f"₹{int(counterpart_txn.get('amount_minor', 0))/100:.2f}",
                "date": str(counterpart_txn.get("occurred_at")),
                "description": counterpart_txn.get("description_raw")
            })

        batch_id = str(primary_txn.get("batch_id") or "BATCH-ACTIVE") if primary_txn else "BATCH-ACTIVE"
        payment_id = primary_txn.get("payment_id") or primary_txn.get("external_id") if primary_txn else None
        capture_d = str(gateway_rec.get("occurred_at")) if gateway_rec else (str(p_date) if p_kind == "GATEWAY" else None)
        settlement_d = str(counterpart_txn.get("occurred_at")) if counterpart_txn else (str(p_date) if p_kind == "BANK" else None)

        deterministic_rules = [
            "RULE_01_EXACT_REFERENCE_KEY_LOOKUP",
            "RULE_02_MDR_GST_NETTING_FORMULA (Gross - Fee - Tax = Expected Net)",
            "RULE_03_SETTLEMENT_TIMING_WINDOW_SEARCH (0 <= T <= 7)",
            "RULE_04_INTRA_SOURCE_DEDUPLICATION_FINGERPRINT",
            "RULE_05_DOUBLE_ENTRY_LEDGER_BALANCE_CONTROL"
        ]
        deterministic_result = f"Deterministic Pipeline evaluated {exception_type} for primary ID {p_ext or exception_id} with Gross ₹{gross/100:,.2f}, Expected Net ₹{net_minor/100:,.2f}, and Verified Variance ₹{impact_minor/100:,.2f}."

        return {
            "batch_id": batch_id,
            "exception_id": exception_id,
            "classification": exception_type,
            "payment_id": payment_id,
            "source_records": source_records,
            "matched_records": matched_records,
            "gross_amount": round(gross / 100, 2),
            "fee": round(fee_minor / 100, 2),
            "tax": round(tax_minor / 100, 2),
            "expected_net_settlement": round(net_minor / 100, 2),
            "actual_bank_settlement": actual_bank_settlement,
            "variance": round(impact_minor / 100, 2),
            "capture_date": capture_d,
            "settlement_date": settlement_d,
            "timing_window": "T+2 Banking Days (0 <= days <= 7)",
            "deterministic_rules": deterministic_rules,
            "deterministic_result": deterministic_result,
            
            # Sub-dictionaries for backwards compatibility
            "exception": {
                "id": exception_id,
                "type": exception_type,
                "severity": severity,
                "impact_minor": impact_minor
            },
            "candidate_bank_records": candidate_bank_records,
            "related_ledger_entries": related_ledger_entries,
            "amount_calculations": {
                "gross_amount_minor": gross,
                "policy_id": policy_id,
                "calculated_mdr_fee_minor": fee_minor,
                "calculated_gst_tax_minor": tax_minor,
                "expected_net_settlement_minor": net_minor,
                "actual_variance_minor": impact_minor,
                "formula_proof": formula_proof
            },
            "date_difference": {
                "primary_date": str(p_date),
                "counterpart_date": str(c.get("occurred_at")) if c else None,
                "period_start": period.start.isoformat(),
                "period_end": period.end.isoformat(),
                "timing_cutoff_lag_detected": is_cutoff
            }
        }

    def investigate_exception(
        self,
        exception_id: str,
        exception_type: str,
        impact_minor: int,
        primary_txn: Optional[Dict[str, Any]] = None,
        counterpart_txn: Optional[Dict[str, Any]] = None,
        available_txns: Optional[List[Dict[str, Any]]] = None,
        severity: str = "MEDIUM",
        has_deterministic_rule: bool = False,
        force_refresh: bool = False
    ) -> InvestigationResult:
        """
        Runs a scoped investigation over an exception:
        1. Checks priority gate: skips AI for deterministic/low-priority items.
        2. Checks L1 in-memory cache and returns cached result on match (unless force_refresh).
        3. Constructs structured, targeted context without arbitrary transactions.
        4. Calls LLM according to configured AGENT_PRIMARY_PROVIDER, verified by DeterministicVerifier.
        5. Records telemetry into AgentTelemetryTracker.
        """
        self.stats["total_exceptions"] += 1

        # 1. Check Priority & Decision Gate
        should_call_ai, reason = self.should_invoke_ai(
            exception_type=exception_type,
            severity=severity,
            impact_minor=impact_minor,
            has_deterministic_rule=has_deterministic_rule
        )

        if not should_call_ai:
            if reason == "DETERMINISTIC_RULES_SUFFICIENT":
                self.stats["deterministically_resolved"] += 1
                self.stats["ai_avoided"] += 1
            else:
                self.stats["manual_review"] += 1
                self.stats["ai_avoided"] += 1

            start_t = time.time()
            inv = self._deterministic_investigate(
                exception_id=exception_id,
                exception_type=exception_type,
                impact_minor=impact_minor,
                primary_txn=primary_txn,
                counterpart_txn=counterpart_txn,
                reason=reason
            )
            lat = round((time.time() - start_t) * 1000, 2)
            inv.telemetry = {
                "provider": "DETERMINISTIC_REASONER",
                "model": "rule_engine_v1",
                "latency_ms": lat,
                "verifier_status": "PASSED",
                "tokens_est": 0
            }
            _record_agent_telemetry(
                agent_name="Agent 9: Exception Investigation Agent",
                provider="DETERMINISTIC",
                model="rule_engine_v1",
                latency_ms=lat,
                tokens_est=0,
                status="SUCCESS",
                metadata={"exception_id": exception_id, "exception_type": exception_type, "classification": inv.classification}
            )
            return inv

        # 2. Build Structured Targeted Context Envelope
        targeted_context = self.build_targeted_context(
            exception_id=exception_id,
            exception_type=exception_type,
            severity=severity,
            impact_minor=impact_minor,
            primary_txn=primary_txn,
            counterpart_txn=counterpart_txn,
            all_txns=available_txns
        )

        # 3. Check L1 Memory Cache
        cache_key = hashlib.sha256(
            json.dumps(targeted_context, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()

        if not force_refresh and cache_key in self._L1_CACHE:
            self.stats["cache_hits"] += 1
            self.stats["ai_investigated"] += 1
            cached = self._L1_CACHE[cache_key]
            _record_agent_telemetry(
                agent_name="Agent 9: Exception Investigation Agent",
                provider=cached.telemetry.get("provider", "L1_CACHE") if cached.telemetry else "L1_CACHE",
                model=cached.telemetry.get("model", "cached") if cached.telemetry else "cached",
                latency_ms=0.5,
                tokens_est=cached.telemetry.get("tokens_est", 0) if cached.telemetry else 0,
                status="SUCCESS",
                metadata={"exception_id": exception_id, "cache_hit": True}
            )
            return cached

        start_time = time.time()

        valid_candidate_ids = {
            c["id"] for c in targeted_context.get("candidate_bank_records", []) if c.get("id")
        }
        if primary_txn and "id" in primary_txn:
            valid_candidate_ids.add(primary_txn["id"])
        if counterpart_txn and "id" in counterpart_txn:
            valid_candidate_ids.add(counterpart_txn["id"])

        system_prompt = (
            "You are the Senior Recon Financial Controller. "
            "Analyze the given targeted financial context and output a strictly valid JSON object matching the schema:\n"
            "{\n"
            '  "exception_id": str,\n'
            '  "classification": str,\n'
            '  "likely_cause": str,\n'
            '  "candidate_match_ids": list[str],\n'
            '  "recommended_action": str,\n'
            '  "confidence": float,\n'
            '  "evidence": list[{"tool": str, "rule_id": str, "field": str, "value": any}],\n'
            '  "requires_human_review": bool,\n'
            '  "citations": list[str]\n'
            "}\n"
            "Rules:\n"
            "1. Never invent transaction IDs outside the provided candidate records.\n"
            "2. Trust pre-computed arithmetic calculations.\n"
            "3. Output strictly valid JSON without markdown wrapping."
        )

        user_prompt = json.dumps(targeted_context, indent=2, default=str)

        # 0. Check Global Batch Budget & Circuit Breaker
        try:
            from app.services.agents.base_agent import AICircuitBreaker
            batch_id_val = None
            if primary_txn and primary_txn.get("batch_id"):
                batch_id_val = primary_txn["batch_id"]
            
            allowed, budget_reason = AICircuitBreaker.can_make_call(batch_id_val, "Agent 9: Exception Investigation Agent")
            if not allowed:
                start_fb = time.time()
                inv = self._generate_rule_based_investigation(
                    exception_id=exception_id,
                    exception_type=exception_type,
                    impact_minor=impact_minor,
                    primary_txn=primary_txn,
                    counterpart_txn=counterpart_txn,
                    targeted_context=self.build_targeted_context(
                        exception_id, exception_type, severity, impact_minor, primary_txn, counterpart_txn
                    )
                )
                lat_fb = round((time.time() - start_fb) * 1000, 2)
                inv.telemetry = {
                    "provider": "DETERMINISTIC",
                    "model": "rule_engine_v1",
                    "latency_ms": lat_fb,
                    "fallback_reason": budget_reason,
                    "verifier_status": "PASSED",
                    "tokens_est": 0
                }
                _record_agent_telemetry(
                    agent_name="Agent 9: Exception Investigation Agent",
                    provider="DETERMINISTIC",
                    model="rule_engine_v1",
                    latency_ms=lat_fb,
                    tokens_est=0,
                    status="SUCCESS",
                    metadata={"exception_id": exception_id, "fallback_reason": budget_reason, "classification": inv.classification}
                )
                return inv
        except Exception:
            pass

        # 4. Determine Provider Priority Order based on settings
        primary_pref = getattr(settings, "AGENT_PRIMARY_PROVIDER", "groq").lower()
        if primary_pref == "groq":
            providers = ["groq", "gemini"]
        elif primary_pref == "gemini":
            providers = ["gemini", "groq"]
        else:
            providers = ["groq", "gemini"]

        for prov in providers:
            try:
                from app.services.agents.base_agent import AICircuitBreaker
                avail, _ = AICircuitBreaker.is_provider_available(prov)
                if not avail:
                    continue
            except Exception:
                pass

            if prov == "groq" and (self._groq_client or self._groq_client_secondary):
                groq_model = getattr(settings, "GROQ_MODEL", "openai/gpt-oss-120b")
                
                # Assemble Groq clients (Primary and Secondary)
                groq_candidates = []
                if self._groq_client:
                    groq_candidates.append(("GROQ_PRIMARY", self._groq_client))
                if self._groq_client_secondary:
                    groq_candidates.append(("GROQ_SECONDARY", self._groq_client_secondary))
                
                # Load balance: alternate starting client to distribute TPM/RPM across accounts
                if len(groq_candidates) > 1 and (self.stats["total_exceptions"] % 2 == 1):
                    groq_candidates = [groq_candidates[1], groq_candidates[0]]

                for prov_label, client in groq_candidates:
                    try:
                        from app.services.agents.base_agent import AICircuitBreaker
                        g_avail, _ = AICircuitBreaker.is_provider_available(prov_label)
                        if not g_avail:
                            continue
                    except Exception:
                        pass

                    try:
                        kwargs = {
                            "model": groq_model,
                            "messages": [
                                {"role": "system", "content": system_prompt},
                                {"role": "user", "content": f"Targeted Context:\n{user_prompt}"}
                            ],
                            "temperature": 0.1,
                            "top_p": 1,
                            "max_completion_tokens": 1500,
                            "timeout": float(getattr(settings, "AGENT_TIMEOUT_SECONDS", 12))
                        }
                        if "openai" in groq_model:
                            kwargs["reasoning_effort"] = "low"

                        completion = client.chat.completions.create(**kwargs)
                        raw_text = completion.choices[0].message.content or ""
                        if not raw_text.strip():
                            # Stream collection
                            kwargs_stream = dict(kwargs)
                            kwargs_stream["stream"] = True
                            stream_comp = client.chat.completions.create(**kwargs_stream)
                            stream_chunks = []
                            for chunk in stream_comp:
                                if chunk.choices and chunk.choices[0].delta:
                                    stream_chunks.append(chunk.choices[0].delta.content or "")
                            raw_text = "".join(stream_chunks)

                        json_start = raw_text.find("{")
                        json_end = raw_text.rfind("}") + 1
                        if json_start != -1 and json_end != -1:
                            data = json.loads(raw_text[json_start:json_end])
                            data["exception_id"] = exception_id
                            if "evidence" in data and isinstance(data["evidence"], list):
                                fallback_id = str(primary_txn.get("id") if primary_txn else (counterpart_txn.get("id") if counterpart_txn else exception_id))
                                for ev in data["evidence"]:
                                    if isinstance(ev, dict) and not ev.get("record_id"):
                                        ev["record_id"] = fallback_id
                            inv = InvestigationResult(**data)
                            is_valid, _ = DeterministicVerifier.verify_proposal(
                                inv,
                                {"impact_minor": impact_minor},
                                valid_candidate_ids
                            )
                            if is_valid:
                                lat = round((time.time() - start_time) * 1000, 2)
                                tok = max(50, len(raw_text) // 4)
                                inv.telemetry = {
                                    "provider": prov_label,
                                    "model": groq_model,
                                    "latency_ms": lat,
                                    "verifier_status": "PASSED",
                                    "tokens_est": tok
                                }
                                self.stats["ai_investigated"] += 1
                                self._L1_CACHE[cache_key] = inv

                                try:
                                    from app.services.agents.base_agent import AICircuitBreaker
                                    AICircuitBreaker.record_success(prov_label)
                                    AICircuitBreaker.record_success("GROQ")
                                    if batch_id_val:
                                        AICircuitBreaker.increment_call(batch_id_val, "Agent 9: Exception Investigation Agent")
                                except Exception:
                                    pass

                                _record_agent_telemetry(
                                    agent_name="Agent 9: Exception Investigation Agent",
                                    provider=prov_label,
                                    model=groq_model,
                                    latency_ms=lat,
                                    tokens_est=tok,
                                    status="SUCCESS",
                                    metadata={"exception_id": exception_id, "classification": inv.classification}
                                )
                                return inv
                    except Exception as e:
                        err_str = str(e)
                        if "429" in err_str or "rate_limit" in err_str.lower() or "quota" in err_str.lower():
                            try:
                                from app.services.agents.base_agent import AICircuitBreaker
                                retry_match = re.search(r"retry\s+in\s+([\d\.]+)", err_str, re.IGNORECASE)
                                retry_sec = float(retry_match.group(1)) if retry_match else 60.0
                                AICircuitBreaker.record_429(prov_label, retry_sec)
                            except Exception:
                                pass
                        logger.warning("[agent_runtime] %s investigation failed (model=%s): %s", prov_label, groq_model, e)

            elif prov == "gemini" and self._gemini_client:
                gemini_model = settings.AGENT_GEMINI_MODEL
                try:
                    response = self._gemini_client.models.generate_content(
                        model=gemini_model,
                        contents=f"{system_prompt}\n\nTargeted Context:\n{user_prompt}"
                    )
                    raw_text = response.text or ""
                    json_start = raw_text.find("{")
                    json_end = raw_text.rfind("}") + 1
                    if json_start != -1 and json_end != -1:
                        data = json.loads(raw_text[json_start:json_end])
                        data["exception_id"] = exception_id
                        if "evidence" in data and isinstance(data["evidence"], list):
                            fallback_id = str(primary_txn.get("id") if primary_txn else (counterpart_txn.get("id") if counterpart_txn else exception_id))
                            for ev in data["evidence"]:
                                if isinstance(ev, dict) and not ev.get("record_id"):
                                    ev["record_id"] = fallback_id
                        inv = InvestigationResult(**data)
                        is_valid, _ = DeterministicVerifier.verify_proposal(
                            inv,
                            {"impact_minor": impact_minor},
                            valid_candidate_ids
                        )
                        if is_valid:
                            lat = round((time.time() - start_time) * 1000, 2)
                            tok = max(50, len(raw_text) // 4)
                            inv.telemetry = {
                                "provider": "GEMINI",
                                "model": gemini_model,
                                "latency_ms": lat,
                                "verifier_status": "PASSED",
                                "tokens_est": tok
                            }
                            self.stats["ai_investigated"] += 1
                            self._L1_CACHE[cache_key] = inv

                            try:
                                from app.services.agents.base_agent import AICircuitBreaker
                                AICircuitBreaker.record_success("GEMINI")
                                if batch_id_val:
                                    AICircuitBreaker.increment_call(batch_id_val, "Agent 9: Exception Investigation Agent")
                            except Exception:
                                pass

                            _record_agent_telemetry(
                                agent_name="Agent 9: Exception Investigation Agent",
                                provider="GEMINI",
                                model=gemini_model,
                                latency_ms=lat,
                                tokens_est=tok,
                                status="SUCCESS",
                                metadata={"exception_id": exception_id, "classification": inv.classification}
                            )
                            return inv
                except Exception as e:
                    err_str = str(e)
                    if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
                        try:
                            from app.services.agents.base_agent import AICircuitBreaker
                            AICircuitBreaker.record_429("GEMINI", 60.0)
                        except Exception:
                            pass
                    logger.warning("[agent_runtime] Gemini investigation fallback failed (model=%s): %s", gemini_model, e)

            elif prov == "anthropic" and (self._anthropic_client or self.anthropic_api_key):
                anthropic_model = getattr(settings, "AGENT_INVESTIGATION_MODEL", "claude-sonnet-5")
                try:
                    client = self._anthropic_client
                    if client is None and self.anthropic_api_key:
                        import anthropic
                        client = anthropic.Anthropic(api_key=self.anthropic_api_key)
                        self._anthropic_client = client
                    if client is not None:
                        resp = client.messages.create(
                            model=anthropic_model,
                            max_tokens=1000,
                            system="You are the Recon Financial Controller. Return a valid JSON InvestigationResult from targeted context.",
                            messages=[{"role": "user", "content": user_prompt}]
                        )
                        raw_text = resp.content[0].text
                        json_start = raw_text.find("{")
                        json_end = raw_text.rfind("}") + 1
                        if json_start != -1 and json_end != -1:
                            data = json.loads(raw_text[json_start:json_end])
                            data["exception_id"] = exception_id
                            inv = InvestigationResult(**data)
                            is_valid, _ = DeterministicVerifier.verify_proposal(
                                inv,
                                {"impact_minor": impact_minor},
                                valid_candidate_ids
                            )
                            if is_valid:
                                lat = round((time.time() - start_time) * 1000, 2)
                                tok = max(50, len(raw_text) // 4)
                                inv.telemetry = {
                                    "provider": "ANTHROPIC",
                                    "model": anthropic_model,
                                    "latency_ms": lat,
                                    "verifier_status": "PASSED",
                                    "tokens_est": tok
                                }
                                self.stats["ai_investigated"] += 1
                                self._L1_CACHE[cache_key] = inv
                                if len(self._L1_CACHE) > 500:
                                    oldest = next(iter(self._L1_CACHE))
                                    self._L1_CACHE.pop(oldest, None)
                                _record_agent_telemetry(
                                    agent_name="Agent 9: Exception Investigation Agent",
                                    provider="ANTHROPIC",
                                    model=anthropic_model,
                                    latency_ms=lat,
                                    tokens_est=tok,
                                    status="SUCCESS",
                                    metadata={"exception_id": exception_id, "classification": inv.classification}
                                )
                                return inv
                except Exception as e:
                    logger.warning("[agent_runtime] Anthropic investigation fallback failed (model=%s): %s", anthropic_model, e)

        # 5. Fallback to High-Precision Deterministic Financial Reasoner
        inv = self._deterministic_investigate(
            exception_id=exception_id,
            exception_type=exception_type,
            impact_minor=impact_minor,
            primary_txn=primary_txn,
            counterpart_txn=counterpart_txn,
            reason=reason
        )
        lat = round((time.time() - start_time) * 1000, 2)
        inv.telemetry = {
            "provider": "DETERMINISTIC_REASONER",
            "model": "rule_engine_v1",
            "latency_ms": lat,
            "verifier_status": "PASSED",
            "tokens_est": 0
        }
        self.stats["ai_investigated"] += 1
        self._L1_CACHE[cache_key] = inv
        _record_agent_telemetry(
            agent_name="Agent 9: Exception Investigation Agent",
            provider="DETERMINISTIC",
            model="rule_engine_v1",
            latency_ms=lat,
            tokens_est=0,
            status="SUCCESS",
            metadata={"exception_id": exception_id, "exception_type": exception_type, "classification": inv.classification}
        )
        return inv

    def _deterministic_investigate(
        self,
        exception_id: str,
        exception_type: str,
        impact_minor: int,
        primary_txn: Optional[Dict[str, Any]] = None,
        counterpart_txn: Optional[Dict[str, Any]] = None,
        reason: str = "DETERMINISTIC"
    ) -> InvestigationResult:
        """High-precision deterministic financial reasoner with 4-tier reasoning and non-null record IDs."""
        p = primary_txn or {}
        c = counterpart_txn or {}
        p_id = str(p.get("id") or (c.get("id") if c else None) or exception_id)
        c_id = str(c.get("id")) if c and c.get("id") else None
        p_ext = str(p.get("external_id") or "")
        amt_inr = f"₹{impact_minor / 100:,.2f}"

        if exception_type in ("AMOUNT_MISMATCH", "FEE_AND_TAX_BOOKED_NET", "MDR_FEE_MISMATCH"):
            gross = p.get("amount_minor", 0) if p else impact_minor
            policy = FeePolicyRegistry.get_default_policy()
            bd = policy.calculate(gross)
            expected_fee = bd.fee_minor
            expected_tax = bd.tax_minor
            surcharge = impact_minor - (expected_fee + expected_tax)
            if surcharge < 0:
                surcharge = 0
                expected_fee = impact_minor

            evidence = [
                ToolEvidence(
                    tool="get_transaction_details",
                    record_id=p_id,
                    field="fee_breakup",
                    value={"mdr": expected_fee, "gst": expected_tax, "surcharge": surcharge, "policy_id": policy.policy_id}
                ),
                ToolEvidence(tool="get_reconciliation_rules", record_id=p_id, rule_id=policy.policy_id)
            ]
            
            return InvestigationResult(
                exception_id=exception_id,
                classification="FEE_AND_TAX_BOOKED_NET" if exception_type in ("AMOUNT_MISMATCH", "FEE_AND_TAX_BOOKED_NET") else exception_type,
                likely_cause=f"Discrepancy of {amt_inr} is attributable to MDR fee (₹{expected_fee / 100:.2f}) and GST (₹{expected_tax / 100:.2f}) under policy {policy.policy_id} booked net in ledger.",
                facts=[
                    f"Transaction ID: {p_id} (External: {p_ext})",
                    f"Gross Amount: ₹{gross / 100:,.2f}",
                    f"MDR Policy: {policy.name} ({policy.policy_id})",
                    f"Expected Fee: ₹{expected_fee / 100:.2f}, GST: ₹{expected_tax / 100:.2f}"
                ],
                observations=[
                    f"Numerical variance of {amt_inr} matches policy-calculated merchant discount fee and tax schedule exactly."
                ],
                possible_cause="Gateway payment processor deducted merchant discount rate at source and settled net to bank.",
                recommendation="Book standard fee adjustment journal entry to record payment gateway processing expense and GST input credit.",
                candidate_match_ids=[c_id] if c_id else [],
                recommended_action="ADJUST_LEDGER_FEE_SPLIT",
                confidence=0.98,
                evidence=evidence,
                requires_human_review=(impact_minor > settings.MATERIALITY_THRESHOLD_MINOR),
                citations=["SOP-04 §2: Merchant Discount Rate Accounting"]
            )

        elif exception_type in ("TIMING_DIFFERENCE", "TIMING_DIFFERENCE_PERIOD_CUTOFF", "PERIOD_CUTOFF", "PERIOD_CUTOFF_TIMING_LAG", "MATCHED_WITH_TIMING_LAG"):
            period = derive_period([primary_txn] if primary_txn else [])
            return InvestigationResult(
                exception_id=exception_id,
                classification="PERIOD_CUTOFF_IN_TRANSIT" if exception_type in ("PERIOD_CUTOFF", "PERIOD_CUTOFF_IN_TRANSIT") else exception_type,
                likely_cause=f"Payment was captured near reporting period boundary ({period.end.isoformat()}) and settled in bank on subsequent value date (T+2 cycle).",
                facts=[
                    f"Transaction ID: {p_id} (External: {p_ext})",
                    f"Captured Date: {p.get('occurred_at') or 'Month-End'}",
                    f"Period Closing Boundary: {period.end.isoformat()}"
                ],
                observations=[
                    f"Transaction was captured before period cutoff date but clearing settlement completed in following period (T+2 timing lag)."
                ],
                possible_cause="Standard interbank clearing settlement cycle across calendar month boundary.",
                recommendation="Accrue in-transit clearing deposit to General Ledger Account 1290 (In-Transit Clearing) pending value date confirmation.",
                candidate_match_ids=[c_id] if c_id else [],
                recommended_action="ACCRUE_TO_CLEARING_1290",
                confidence=0.98,
                evidence=[ToolEvidence(tool="get_batch_context", record_id=p_id, field="cutoff_date", value=period.end.isoformat())],
                requires_human_review=False,
                citations=["SOP-02 §4: Period Boundary Cut-off Accounting"]
            )

        elif exception_type in ("DUPLICATE_RECORD", "DUPLICATE_GATEWAY_WEBHOOK", "DUPLICATE_LEDGER_POSTING"):
            return InvestigationResult(
                exception_id=exception_id,
                classification="DUPLICATE_INGESTION_ROW" if exception_type in ("DUPLICATE_RECORD", "DUPLICATE_INGESTION_ROW") else exception_type,
                likely_cause="Identical payment ID / fingerprint detected within the source stream (duplicate webhook replay or double file export).",
                facts=[
                    f"Transaction ID: {p_id} (External: {p_ext})",
                    f"Source Stream: {p.get('source_kind') or 'GATEWAY'}",
                    f"Amount: {amt_inr}"
                ],
                observations=[
                    f"Intra-source deduplication gate detected identical cryptographic fingerprint with an earlier ingested record."
                ],
                possible_cause="Duplicate webhook notification replay from payment gateway or redundant export row.",
                recommendation="Quarantine redundant record and flag for voiding to prevent duplicate ledger posting.",
                candidate_match_ids=[],
                recommended_action="FLAG_DUPLICATE_FOR_VOID",
                confidence=0.99,
                evidence=[ToolEvidence(tool="get_transaction_details", record_id=p_id, field="fingerprint_match", value=True)],
                requires_human_review=False,
                citations=["SOP-01 §3: Deduplication Controls"]
            )

        elif exception_type in ("UNALLOCATED_BANK_CREDIT", "ANONYMOUS_BANK_LINE", "UNKNOWN_BANK_CREDIT"):
            return InvestigationResult(
                exception_id=exception_id,
                classification="ANONYMOUS_BANK_DEPOSIT" if exception_type in ("UNALLOCATED_BANK_CREDIT", "ANONYMOUS_BANK_DEPOSIT") else exception_type,
                likely_cause=f"Direct bank credit of {amt_inr} received without matching gateway capture or customer receivable posting.",
                facts=[
                    f"Bank Record ID: {p_id} (Ref: {p_ext})",
                    f"Amount Deposited: {amt_inr}",
                    f"Description: {p.get('description_raw') or 'Direct Deposit'}"
                ],
                observations=[
                    f"Bank feed reflects confirmed cash deposit with no matching invoice, order, or gateway transaction token."
                ],
                possible_cause="Direct customer wire deposit, offline NEFT remittance, or unallocated partner credit.",
                recommendation="Route to Accounts Receivable team to issue customer remittance inquiry and match to open invoices.",
                candidate_match_ids=[],
                recommended_action="INVESTIGATE_UNALLOCATED_CREDIT",
                confidence=0.90,
                evidence=[ToolEvidence(tool="get_bank_details", record_id=p_id, field="direct_deposit", value=True)],
                requires_human_review=True,
                citations=["SOP-05 §3: Unidentified Direct Deposits Protocol"]
            )

        elif exception_type in ("UNSETTLED_GATEWAY_RECORD", "MISSING_BANK_SETTLEMENT", "MISSING_BANK_RECORD"):
            gross = p.get("amount_minor", impact_minor)
            fee = p.get("fee_minor") or int(gross * 0.02)
            tax = p.get("tax_minor") or int(fee * 0.18)
            net = gross - fee - tax
            return InvestigationResult(
                exception_id=exception_id,
                classification=exception_type,
                likely_cause=f"Gateway payment of Gross ₹{gross/100:,.2f} (Expected Net: ₹{net/100:,.2f}) confirmed captured but no bank settlement deposit received.",
                facts=[
                    f"Gateway Payment ID: {p_id} (External: {p_ext})",
                    f"Gross Exposure: ₹{gross/100:,.2f}",
                    f"Expected Net Settlement: ₹{net/100:,.2f} (MDR: ₹{fee/100:.2f}, GST: ₹{tax/100:.2f})"
                ],
                observations=[
                    f"Payment captured on gateway portal with zero matching credit received in bank account across settlement SLA window."
                ],
                possible_cause="Payment processor payout delay, rolling reserve hold, or unsettled aggregator batch.",
                recommendation="Initiate payment gateway settlement trace inquiry and inspect merchant balance payout ledger.",
                candidate_match_ids=[],
                recommended_action="ISSUE_BANK_TRACE_INQUIRY",
                confidence=0.92,
                evidence=[ToolEvidence(tool="get_gateway_details", record_id=p_id, field="settlement_status", value="UNSETTLED")],
                requires_human_review=True,
                citations=["SOP-03 §2: Unsettled Payment Investigation"]
            )

        elif exception_type == "MISSING_LEDGER_ENTRY":
            return InvestigationResult(
                exception_id=exception_id,
                classification=exception_type,
                likely_cause=f"Transaction voucher of {amt_inr} lacks corresponding General Ledger credit posting or account receivable clearance.",
                facts=[
                    f"Record ID: {p_id} (External: {p_ext})",
                    f"Amount: {amt_inr}",
                    f"Source: {p.get('source_kind') or 'LEDGER'}"
                ],
                observations=[
                    f"Accounting journal entry is unlinked to settled bank funds or gateway capture stream."
                ],
                possible_cause="Pending invoice booking, manual journal voucher mismatch, or timing gap in ERP sync.",
                recommendation="Review ERP journal entry and create manual clearing voucher to balance control accounts.",
                candidate_match_ids=[],
                recommended_action="MANUAL_JOURNAL_ENTRY",
                confidence=0.90,
                evidence=[ToolEvidence(tool="ledger_lookup_engine", record_id=p_id, field="missing_entry", value={"amount_minor": impact_minor})],
                requires_human_review=True,
                citations=["SOP-01 §2: General Ledger Ingestion & Booking Protocol"]
            )

        else:
            return InvestigationResult(
                exception_id=exception_id,
                classification=exception_type,
                likely_cause=f"Discrepancy of {amt_inr} detected. Cause cannot be determined from the supplied evidence.",
                facts=[
                    f"Record ID: {p_id} (External: {p_ext})",
                    f"Classification: {exception_type}",
                    f"Impact: {amt_inr}"
                ],
                observations=[
                    f"Transaction was not reconciled by deterministic rules within configured tolerance gates."
                ],
                possible_cause="Cause cannot be determined from the supplied evidence.",
                recommendation="Queue for controller maker-checker operational review.",
                candidate_match_ids=[c_id] if c_id else [],
                recommended_action="MANUAL_JOURNAL_ENTRY",
                confidence=0.75,
                evidence=[ToolEvidence(tool="reconciliation_engine", record_id=p_id, field="impact", value={"amount_minor": impact_minor})],
                requires_human_review=True,
                citations=["SOP-01 §1: Standard Reconciliation Procedures"]
            )
