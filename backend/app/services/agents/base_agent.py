"""
Base Reasoning Agent Infrastructure for AI Financial Controller.
Provides unified Groq LLM integration, telemetry logging, structured JSON extraction,
and deterministic fallback gates.
"""

import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from app.core.config import settings

logger = logging.getLogger(__name__)


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
        groq_model: Optional[str] = None
    ):
        self.agent_name = agent_name
        self.groq_api_key = groq_api_key or settings.GROQ_API_KEY
        self.groq_model = groq_model or getattr(settings, "GROQ_MODEL", "openai/gpt-oss-120b")

        self._groq_client = None
        if self.groq_api_key:
            try:
                from groq import Groq
                self._groq_client = Groq(api_key=self.groq_api_key, timeout=12.0)
            except Exception as e:
                logger.warning(f"[{self.agent_name}] Failed to initialize Groq client: {e}")

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
        # Strip markdown fences if present
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
        temperature: float = 0.1,
        max_tokens: int = 2048,
        reasoning_effort: str = "medium"
    ) -> Tuple[Optional[Dict[str, Any]], str, Dict[str, Any]]:
        """
        Executes reasoning prompt on Groq with fallback to Gemini or deterministic logic.
        Returns: (parsed_json, raw_text, telemetry_dict)
        """
        start_t = time.time()

        # 1. Attempt Groq
        if self._groq_client:
            candidate_models = [self.groq_model]
            for m in ["qwen/qwen3.8-27b", "qwen/qwen3.6-27b", "openai/gpt-oss-20b"]:
                if m not in candidate_models:
                    candidate_models.append(m)

            for g_model in candidate_models:
                try:
                    kwargs: Dict[str, Any] = {
                        "model": g_model,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt}
                        ],
                        "temperature": temperature,
                        "max_completion_tokens": max_tokens,
                        "timeout": 12.0
                    }
                    
                    # Some models support reasoning_effort
                    if "openai" in g_model:
                        try:
                            kwargs["reasoning_effort"] = reasoning_effort
                            completion = self._groq_client.chat.completions.create(**kwargs)
                        except Exception:
                            kwargs.pop("reasoning_effort", None)
                            completion = self._groq_client.chat.completions.create(**kwargs)
                    else:
                        completion = self._groq_client.chat.completions.create(**kwargs)

                    raw_text = completion.choices[0].message.content or ""
                    latency_ms = (time.time() - start_t) * 1000
                    tokens_est = max(50, len(raw_text) // 4)
                    parsed_json = self.extract_json(raw_text)

                    if parsed_json:
                        telemetry = {
                            "provider": "GROQ",
                            "model": g_model,
                            "latency_ms": round(latency_ms, 2),
                            "tokens_est": tokens_est,
                            "status": "SUCCESS"
                        }

                        AgentTelemetryTracker.record_call(
                            agent_name=self.agent_name,
                            provider="GROQ",
                            model=g_model,
                            latency_ms=latency_ms,
                            tokens_est=tokens_est,
                            status="SUCCESS"
                        )

                        return parsed_json, raw_text, telemetry
                except Exception as e:
                    logger.warning(f"[{self.agent_name}] Groq execution on {g_model} failed: {e}. Trying next model...")
                    continue

        # 2. Attempt Gemini Fallback
        if self._gemini_client:
            try:
                # The setting is AGENT_GEMINI_MODEL; reading a non-existent
                # GEMINI_MODEL silently pinned every fallback to a retired model
                # id, so the fallback tier 404'd instead of answering.
                gemini_model = settings.AGENT_GEMINI_MODEL
                combined_prompt = f"{system_prompt}\n\nUser Context:\n{user_prompt}"
                response = self._gemini_client.models.generate_content(
                    model=gemini_model,
                    contents=combined_prompt
                )
                raw_text = response.text or ""
                latency_ms = (time.time() - start_t) * 1000
                tokens_est = max(50, len(raw_text) // 4)
                parsed_json = self.extract_json(raw_text)

                telemetry = {
                    "provider": "GEMINI",
                    "model": gemini_model,
                    "latency_ms": round(latency_ms, 2),
                    "tokens_est": tokens_est,
                    "status": "SUCCESS"
                }

                AgentTelemetryTracker.record_call(
                    agent_name=self.agent_name,
                    provider="GEMINI",
                    model=gemini_model,
                    latency_ms=latency_ms,
                    tokens_est=tokens_est,
                    status="SUCCESS"
                )

                return parsed_json, raw_text, telemetry

            except Exception as e:
                logger.warning(f"[{self.agent_name}] Gemini fallback failed: {e}")

        # 3. Fallback to Empty Telemetry
        latency_ms = (time.time() - start_t) * 1000
        telemetry = {
            "provider": "DETERMINISTIC_REASONER",
            "model": "rule_engine_v1",
            "latency_ms": round(latency_ms, 2),
            "tokens_est": 0,
            "status": "FALLBACK"
        }
        AgentTelemetryTracker.record_call(
            agent_name=self.agent_name,
            provider="DETERMINISTIC_REASONER",
            model="rule_engine_v1",
            latency_ms=latency_ms,
            tokens_est=0,
            status="FALLBACK"
        )
        return None, "", telemetry
