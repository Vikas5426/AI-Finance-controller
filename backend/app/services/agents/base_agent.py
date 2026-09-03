import json
import logging
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from app.core.config import settings

logger = logging.getLogger(__name__)


class AICircuitBreaker:
    """
    Tracks AI provider rate limits (HTTP 429), quota exhaustion, and temporary outages.
    Enforces global batch/agent call budgets and avoids hammering exhausted APIs.
    """
    _cooldowns: Dict[str, float] = {}  # provider -> timestamp until available
    _batch_call_counts: Dict[str, int] = {}  # batch_id -> total LLM calls made
    _agent_call_counts: Dict[str, Dict[str, int]] = {}  # batch_id -> {agent_name: count}

    @classmethod
    def is_provider_available(cls, provider: str) -> Tuple[bool, float]:
        """Returns (is_available, remaining_cooldown_seconds)."""
        now = time.time()
        until = cls._cooldowns.get(provider.upper(), 0.0)
        if now < until:
            return False, round(until - now, 1)
        return True, 0.0

    @classmethod
    def record_429(cls, provider: str, retry_after_sec: Optional[float] = None):
        """Trips the circuit breaker for this provider upon receiving HTTP 429."""
        cooldown = retry_after_sec or getattr(settings, "AI_CIRCUIT_BREAKER_COOLDOWN_SEC", 60.0)
        cooldown = max(10.0, min(cooldown, 300.0))  # Bound between 10s and 5m
        cls._cooldowns[provider.upper()] = time.time() + cooldown
        logger.warning(
            "[AI_CIRCUIT_BREAKER] Provider '%s' rate limited (429). Cooldown for %.1fs.",
            provider.upper(), cooldown
        )

    @classmethod
    def record_success(cls, provider: str):
        """Clears cooldown upon a verified successful response."""
        cls._cooldowns.pop(provider.upper(), None)

    @classmethod
    def can_make_call(cls, batch_id: Optional[str], agent_name: str) -> Tuple[bool, str]:
        """Enforces global budget limits per batch and per agent."""
        if not batch_id:
            return True, "OK"

        max_batch = getattr(settings, "MAX_LLM_CALLS_PER_BATCH", 12)
        if "Agent 9" in agent_name:
            max_agent = getattr(settings, "MAX_LLM_CALLS_AGENT9", 5)
        else:
            max_agent = getattr(settings, "MAX_LLM_CALLS_PER_AGENT", 1)

        curr_batch = cls._batch_call_counts.get(batch_id, 0)
        if curr_batch >= max_batch:
            return False, f"BATCH_BUDGET_EXCEEDED (max={max_batch})"

        agent_counts = cls._agent_call_counts.setdefault(batch_id, {})
        curr_agent = agent_counts.get(agent_name, 0)
        if curr_agent >= max_agent:
            return False, f"AGENT_BUDGET_EXCEEDED (agent={agent_name}, max={max_agent})"

        return True, "OK"

    @classmethod
    def increment_call(cls, batch_id: Optional[str], agent_name: str):
        """Increments telemetry counter for batch and agent."""
        if not batch_id:
            return
        cls._batch_call_counts[batch_id] = cls._batch_call_counts.get(batch_id, 0) + 1
        agent_counts = cls._agent_call_counts.setdefault(batch_id, {})
        agent_counts[agent_name] = agent_counts.get(agent_name, 0) + 1

    @classmethod
    def reset_batch(cls, batch_id: str):
        """Resets call counters for a specific batch."""
        cls._batch_call_counts.pop(batch_id, None)
        cls._agent_call_counts.pop(batch_id, None)


class AgentTelemetryTracker:
    """Central in-memory store for LLM agent execution telemetry."""
    _logs: List[Dict[str, Any]] = []
    _stats: Dict[str, Any] = {
        "total_agent_calls": 0,
        "groq_calls": 0,
        "gemini_calls": 0,
        "deterministic_fallback_calls": 0,
        "total_tokens_est": 0,
        "avg_latency_ms": 0.0,
        "avg_llm_latency_ms": 0.0,
        "avg_deterministic_latency_ms": 0.0,
        "last_active_at": None
    }

    @classmethod
    def record_call(
        cls,
        agent_name: str,
        provider: str,
        model: str,
        latency_ms: float,
        tokens_est: int,
        status: str = "SUCCESS",
        metadata: Optional[Dict[str, Any]] = None
    ):
        cls._stats["total_agent_calls"] += 1
        is_llm = provider in ("GROQ", "GEMINI", "OPENAI")
        if provider == "GROQ":
            cls._stats["groq_calls"] += 1
        elif provider == "GEMINI":
            cls._stats["gemini_calls"] += 1
        else:
            cls._stats["deterministic_fallback_calls"] += 1

        cls._stats["total_tokens_est"] += tokens_est
        total = cls._stats["total_agent_calls"]
        curr_avg = cls._stats["avg_latency_ms"]
        cls._stats["avg_latency_ms"] = round(((curr_avg * (total - 1)) + latency_ms) / total, 2)

        if is_llm:
            llm_calls = cls._stats["groq_calls"] + cls._stats["gemini_calls"]
            curr_llm_avg = cls._stats.get("avg_llm_latency_ms", 0.0)
            cls._stats["avg_llm_latency_ms"] = round(((curr_llm_avg * (llm_calls - 1)) + latency_ms) / max(1, llm_calls), 2)
        else:
            det_calls = cls._stats["deterministic_fallback_calls"]
            curr_det_avg = cls._stats.get("avg_deterministic_latency_ms", 0.0)
            cls._stats["avg_deterministic_latency_ms"] = round(((curr_det_avg * (det_calls - 1)) + latency_ms) / max(1, det_calls), 2)

        cls._stats["last_active_at"] = datetime.now(timezone.utc).isoformat()

        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "agent_name": agent_name,
            "provider": provider,
            "model": model,
            "latency_ms": round(latency_ms, 2),
            "tokens_est": tokens_est,
            "status": status,
            "metadata": metadata or {}
        }
        cls._logs.append(entry)
        if len(cls._logs) > 200:
            cls._logs.pop(0)

    @classmethod
    def get_telemetry(cls) -> Dict[str, Any]:
        return {
            "stats": dict(cls._stats),
            "recent_executions": list(cls._logs[-25:])
        }


class BaseReasoningAgent:
    """Base class for all specialized financial reasoning agents."""

    def __init__(
        self,
        agent_name: str,
        groq_api_key: Optional[str] = None,
        groq_api_key_secondary: Optional[str] = None,
        groq_model: Optional[str] = None
    ):
        self.agent_name = agent_name
        self.groq_api_key = groq_api_key or settings.GROQ_API_KEY
        self.groq_api_key_secondary = groq_api_key_secondary or getattr(settings, "GROQ_API_KEY_SECONDARY", None)
        self.groq_model = groq_model or getattr(settings, "GROQ_MODEL", "openai/gpt-oss-120b")

        self._groq_client = None
        if self.groq_api_key:
            try:
                from groq import Groq
                self._groq_client = Groq(api_key=self.groq_api_key, timeout=12.0)
            except Exception as e:
                logger.warning(f"[{self.agent_name}] Failed to initialize Groq client: {e}")

        self._groq_client_secondary = None
        if self.groq_api_key_secondary:
            try:
                from groq import Groq
                self._groq_client_secondary = Groq(api_key=self.groq_api_key_secondary, timeout=12.0)
            except Exception as e:
                logger.warning(f"[{self.agent_name}] Failed to initialize secondary Groq client: {e}")

        self._gemini_client = None
        if settings.GEMINI_API_KEY:
            try:
                from google import genai
                self._gemini_client = genai.Client(api_key=settings.GEMINI_API_KEY)
            except Exception:
                pass

    @staticmethod
    def extract_json(raw_text: str) -> Optional[Dict[str, Any]]:
        """Extracts JSON object cleanly from raw LLM output, handling markdown fences."""
        if not raw_text:
            return None
        text = raw_text.strip()
        if text.startswith("```json"):
            text = text[7:]
        elif text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

        start = text.find("{")
        end = text.rfind("}") + 1
        if start != -1 and end != -1:
            try:
                return json.loads(text[start:end])
            except json.JSONDecodeError:
                pass
        return None

    def execute_prompt(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 1.0,
        max_tokens: int = 2048,
        reasoning_effort: str = "medium",
        batch_id: Optional[str] = None,
        purpose: str = "financial_reasoning"
    ) -> Tuple[Optional[Dict[str, Any]], str, Dict[str, Any]]:
        """
        Executes reasoning prompt with:
        1. Global budget gate
        2. Circuit breaker check
        3. Structured trace logging ([AI_CALL], [AI_CALL_COMPLETE])
        4. Bounded fallback: Groq -> Gemini -> Deterministic logic
        Returns: (parsed_json, raw_text, telemetry_dict)
        """
        start_t = time.time()
        request_id = uuid.uuid4().hex[:8]

        # 0. Check Global Batch Budget
        allowed, budget_reason = AICircuitBreaker.can_make_call(batch_id, self.agent_name)
        if not allowed:
            logger.info(
                "[AI_CALL_SKIPPED] agent=%s request_id=%s batch_id=%s reason=%s -> routing to deterministic fallback",
                self.agent_name, request_id, batch_id or "N/A", budget_reason
            )
            lat = round((time.time() - start_t) * 1000, 2)
            telemetry = {
                "provider": "DETERMINISTIC_REASONER",
                "model": "rule_engine_v1",
                "latency_ms": lat,
                "tokens_est": 0,
                "status": "BUDGET_FALLBACK"
            }
            AgentTelemetryTracker.record_call(
                agent_name=self.agent_name,
                provider="DETERMINISTIC_REASONER",
                model="rule_engine_v1",
                latency_ms=lat,
                tokens_est=0,
                status="BUDGET_FALLBACK",
                metadata={"request_id": request_id, "reason": budget_reason}
            )
            return None, "", telemetry

        # 1. Attempt Groq clients (Primary and Secondary failover)
        groq_candidates = []
        if self._groq_client:
            groq_candidates.append(("GROQ_PRIMARY", self._groq_client))
        if self._groq_client_secondary:
            groq_candidates.append(("GROQ_SECONDARY", self._groq_client_secondary))

        for prov_label, client in groq_candidates:
            groq_avail, groq_cooldown = AICircuitBreaker.is_provider_available(prov_label)
            if not groq_avail:
                continue

            g_model = self.groq_model
            logger.info(
                "[AI_CALL] agent=%s provider=%s model=%s request_id=%s batch_id=%s purpose=%s",
                self.agent_name, prov_label, g_model, request_id, batch_id or "N/A", purpose
            )

            try:
                kwargs: Dict[str, Any] = {
                    "model": g_model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    "temperature": temperature,
                    "top_p": 1,
                    "max_completion_tokens": max_tokens,
                    "timeout": 12.0
                }
                if "openai" in g_model:
                    try:
                        kwargs["reasoning_effort"] = reasoning_effort
                        completion = client.chat.completions.create(**kwargs)
                    except Exception:
                        kwargs.pop("reasoning_effort", None)
                        completion = client.chat.completions.create(**kwargs)
                else:
                    completion = client.chat.completions.create(**kwargs)

                raw_text = completion.choices[0].message.content or ""
                if not raw_text.strip():
                    kwargs_stream = dict(kwargs)
                    kwargs_stream["stream"] = True
                    stream_comp = client.chat.completions.create(**kwargs_stream)
                    stream_chunks = []
                    for chunk in stream_comp:
                        if chunk.choices and chunk.choices[0].delta:
                            stream_chunks.append(chunk.choices[0].delta.content or "")
                    raw_text = "".join(stream_chunks)

                latency_ms = round((time.time() - start_t) * 1000, 2)
                tokens_est = max(50, len(raw_text) // 4)
                parsed_json = self.extract_json(raw_text)

                if parsed_json:
                    AICircuitBreaker.record_success(prov_label)
                    AICircuitBreaker.record_success("GROQ")
                    AICircuitBreaker.increment_call(batch_id, self.agent_name)

                    logger.info(
                        "[AI_CALL_COMPLETE] request_id=%s tokens_est=%d duration_ms=%.1f status=SUCCESS provider=%s",
                        request_id, tokens_est, latency_ms, prov_label
                    )

                    telemetry = {
                        "provider": prov_label,
                        "model": g_model,
                        "latency_ms": latency_ms,
                        "tokens_est": tokens_est,
                        "status": "SUCCESS"
                    }
                    AgentTelemetryTracker.record_call(
                        agent_name=self.agent_name,
                        provider=prov_label,
                        model=g_model,
                        latency_ms=latency_ms,
                        tokens_est=tokens_est,
                        status="SUCCESS",
                        metadata={"request_id": request_id}
                    )
                    return parsed_json, raw_text, telemetry

            except Exception as e:
                err_str = str(e)
                if "429" in err_str or "rate_limit" in err_str.lower() or "quota" in err_str.lower():
                    retry_match = re.search(r"retry\s+in\s+([\d\.]+)", err_str, re.IGNORECASE)
                    retry_sec = float(retry_match.group(1)) if retry_match else 60.0
                    AICircuitBreaker.record_429(prov_label, retry_sec)
                    logger.warning(
                        "[AI_PROVIDER_UNAVAILABLE] provider=%s reason=rate_limit retry_after=%.1fs",
                        prov_label, retry_sec
                    )
                else:
                    logger.warning(f"[{self.agent_name}] {prov_label} execution error: {e}")

        # 2. Attempt Gemini Fallback if available and not on 429 cooldown
        gemini_avail, gemini_cooldown = AICircuitBreaker.is_provider_available("GEMINI")
        if self._gemini_client and gemini_avail:
            gemini_model = getattr(settings, "AGENT_GEMINI_MODEL", "gemini-3.6-flash")
            logger.info(
                "[AI_CALL] agent=%s provider=GEMINI model=%s request_id=%s batch_id=%s purpose=%s (fallback tier)",
                self.agent_name, gemini_model, request_id, batch_id or "N/A", purpose
            )
            try:
                combined_prompt = f"{system_prompt}\n\nUser Context:\n{user_prompt}"
                response = self._gemini_client.models.generate_content(
                    model=gemini_model,
                    contents=combined_prompt
                )
                raw_text = response.text or ""
                latency_ms = round((time.time() - start_t) * 1000, 2)
                tokens_est = max(50, len(raw_text) // 4)
                parsed_json = self.extract_json(raw_text)

                if parsed_json:
                    AICircuitBreaker.record_success("GEMINI")
                    AICircuitBreaker.increment_call(batch_id, self.agent_name)

                    logger.info(
                        "[AI_CALL_COMPLETE] request_id=%s tokens_est=%d duration_ms=%.1f status=SUCCESS provider=GEMINI",
                        request_id, tokens_est, latency_ms
                    )

                    telemetry = {
                        "provider": "GEMINI",
                        "model": gemini_model,
                        "latency_ms": latency_ms,
                        "tokens_est": tokens_est,
                        "status": "SUCCESS"
                    }
                    AgentTelemetryTracker.record_call(
                        agent_name=self.agent_name,
                        provider="GEMINI",
                        model=gemini_model,
                        latency_ms=latency_ms,
                        tokens_est=tokens_est,
                        status="SUCCESS",
                        metadata={"request_id": request_id}
                    )
                    return parsed_json, raw_text, telemetry

            except Exception as e:
                err_str = str(e)
                if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
                    retry_match = re.search(r"retryDelay':\s*'([\d]+)", err_str)
                    retry_sec = float(retry_match.group(1)) if retry_match else 60.0
                    AICircuitBreaker.record_429("GEMINI", retry_sec)
                    logger.warning(
                        "[AI_PROVIDER_UNAVAILABLE] provider=gemini reason=rate_limit retry_after=%.1fs",
                        retry_sec
                    )
                else:
                    logger.warning(f"[{self.agent_name}] Gemini fallback failed: {e}")

        # 3. Controlled Deterministic Fallback
        latency_ms = round((time.time() - start_t) * 1000, 2)
        logger.info(
            "[AI_CALL_COMPLETE] request_id=%s tokens_est=0 duration_ms=%.1f status=DETERMINISTIC_FALLBACK",
            request_id, latency_ms
        )

        telemetry = {
            "provider": "DETERMINISTIC_REASONER",
            "model": "rule_engine_v1",
            "latency_ms": latency_ms,
            "tokens_est": 0,
            "status": "FALLBACK"
        }
        AgentTelemetryTracker.record_call(
            agent_name=self.agent_name,
            provider="DETERMINISTIC_REASONER",
            model="rule_engine_v1",
            latency_ms=latency_ms,
            tokens_est=0,
            status="FALLBACK",
            metadata={"request_id": request_id}
        )
        return None, "", telemetry

