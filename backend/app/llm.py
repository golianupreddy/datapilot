from __future__ import annotations

import json
import logging
import random
import re
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

import httpx
from google import genai
from google.genai import errors, types

from .config import get_settings

log = logging.getLogger("datapilot.llm")

RETRYABLE_CODES = {429, 500, 502, 503, 504}
CAPABILITY_HINTS = (
    "json mode is not enabled",
    "developer instruction is not enabled",
    "system instruction",
    "response_mime_type",
    "response mime type",
)


class LLMError(RuntimeError):
    pass


class _EmptyResponse(Exception):
    pass


@dataclass
class LLMResult:
    text: str
    prompt_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    model: str = ""


@dataclass
class _ModelState:
    cooldown_until: float = 0.0
    last_error: str = ""
    last_ok: float = 0.0
    ok_calls: int = 0
    failed_calls: int = 0


def _parse_json(text: str) -> dict[str, Any]:
    t = re.sub(r"^`(?:json)?\s*|\s*`$", "", text.strip(), flags=re.I)
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", t, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
    raise LLMError("Model did not return valid JSON.")


class LLMClient:
    """Gemini/Gemma wrapper with a model fallback chain, per-model cooldowns (circuit breaker),
    fail-fast retries, per-call deadlines, token accounting and cached query embeddings."""

    def __init__(self) -> None:
        self.s = get_settings()
        self.client = genai.Client(
            api_key=self.s.gemini_api_key,
            http_options=types.HttpOptions(timeout=int(self.s.llm_request_timeout_s * 1000)),
        )
        chain = [m.strip() for m in self.s.llm_models.split(",") if m.strip()]
        self.chain: list[str] = chain or [self.s.llm_model]
        self.state: dict[str, _ModelState] = {m: _ModelState() for m in self.chain}
        self._plain: set[str] = set()
        self._lock = threading.Lock()
        self._last_call = 0.0
        self._embed_cache: dict[str, list[float]] = {}

    def _throttle(self) -> None:
        gap = getattr(self.s, "llm_min_interval_seconds", 0.0)
        if gap <= 0:
            return
        with self._lock:
            wait = self._last_call + gap - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self._last_call = time.monotonic()

    def _order(self, max_models: int | None) -> list[str]:
        now = time.monotonic()
        healthy = [m for m in self.chain if self.state[m].cooldown_until <= now]
        cooling = sorted((m for m in self.chain if m not in healthy), key=lambda m: self.state[m].cooldown_until)
        order = healthy + cooling
        return order[:max_models] if max_models else order

    def _mark_ok(self, model: str) -> None:
        st = self.state[model]
        st.cooldown_until, st.last_ok, st.last_error = 0.0, time.time(), ""
        st.ok_calls += 1

    def _mark_failed(self, model: str, reason: str, cooldown_s: float) -> None:
        st = self.state[model]
        st.cooldown_until = time.monotonic() + cooldown_s
        st.last_error = reason[:200]
        st.failed_calls += 1
        log.warning("Model %s marked unavailable for %.0fs: %s", model, cooldown_s, reason[:120])

    @staticmethod
    def _backoff(attempt: int) -> float:
        return min(1.0 * 2 ** (attempt - 1), 6.0) + random.uniform(0, 0.5)

    def _cooldown_for(self, code: int | None, low_msg: str) -> float:
        compact = low_msg.replace(" ", "")
        if code == 429 and ("limit:0" in compact):
            return 900.0
        if code == 429 and ("perday" in compact or "daily" in compact):
            return 900.0
        return self.s.llm_cooldown_s

    def _run_chain(self, label: str, fn: Callable[[str], Any], deadline_s: float | None, max_models: int | None):
        budget = deadline_s or self.s.llm_call_deadline_s
        deadline = time.monotonic() + budget
        retries = self.s.llm_retries_per_model
        tried: list[str] = []

        for model in self._order(max_models):
            attempt = 0
            while attempt <= retries:
                if time.monotonic() >= deadline:
                    break
                try:
                    self._throttle()
                    resp = fn(model)
                    self._mark_ok(model)
                    return model, resp
                except _EmptyResponse:
                    tried.append(f"{model}: empty response")
                    self._mark_failed(model, "empty response", 10.0)
                    break
                except errors.APIError as e:
                    msg = (e.message or str(e))[:300]
                    low = msg.lower()
                    if e.code == 400 and model not in self._plain and any(h in low for h in CAPABILITY_HINTS):
                        self._plain.add(model)
                        continue
                    tried.append(f"{model}: {e.code} {msg[:70]}")
                    if e.code in RETRYABLE_CODES:
                        cooldown = self._cooldown_for(e.code, low)
                        if attempt < retries and cooldown <= self.s.llm_cooldown_s:
                            attempt += 1
                            time.sleep(max(0.0, min(self._backoff(attempt), deadline - time.monotonic())))
                            continue
                        self._mark_failed(model, f"{e.code} {msg}", cooldown)
                    else:
                        self._mark_failed(model, f"{e.code} {msg}", 600.0)
                    break
                except (httpx.TransportError, TimeoutError) as e:
                    tried.append(f"{model}: {type(e).__name__}")
                    if attempt < retries:
                        attempt += 1
                        time.sleep(max(0.0, min(self._backoff(attempt), deadline - time.monotonic())))
                        continue
                    self._mark_failed(model, type(e).__name__, self.s.llm_cooldown_s)
                    break
            if time.monotonic() >= deadline:
                break
        raise LLMError(f"{label}: no model answered within {budget:.0f}s. Tried: " + "; ".join(tried or ["none"]))

    def generate(
        self,
        prompt: str,
        system: str | None = None,
        json_mode: bool = False,
        temperature: float = 0.0,
        max_output_tokens: int = 2048,
        deadline_s: float | None = None,
        max_models: int | None = None,
    ) -> LLMResult:
        start = time.perf_counter()

        def call(model: str):
            plain = model in self._plain or model.lower().startswith("gemma")
            contents = prompt
            if plain:
                if system:
                    contents = f"{system}\n\n---\n\n{prompt}"
                if json_mode:
                    contents += "\n\nRespond with one JSON object only. No markdown fences, no commentary."
            cfg: dict[str, Any] = {"temperature": temperature, "max_output_tokens": max_output_tokens}
            if system and not plain:
                cfg["system_instruction"] = system
            if json_mode and not plain:
                cfg["response_mime_type"] = "application/json"
            low = model.lower()
            if "2.5" in low and "flash" in low and getattr(self.s, "llm_thinking_budget", -1) >= 0:
                cfg["thinking_config"] = types.ThinkingConfig(thinking_budget=self.s.llm_thinking_budget)
            resp = self.client.models.generate_content(
                model=model, contents=contents, config=types.GenerateContentConfig(**cfg)
            )
            if not (resp.text or "").strip():
                raise _EmptyResponse()
            return resp

        model, resp = self._run_chain("generate", call, deadline_s, max_models)
        usage = getattr(resp, "usage_metadata", None)
        return LLMResult(
            text=resp.text or "",
            prompt_tokens=getattr(usage, "prompt_token_count", 0) or 0,
            output_tokens=getattr(usage, "candidates_token_count", 0) or 0,
            latency_ms=int((time.perf_counter() - start) * 1000),
            model=model,
        )

    def generate_json(
        self,
        prompt: str,
        system: str | None = None,
        max_output_tokens: int = 2048,
        deadline_s: float | None = None,
        max_models: int | None = None,
    ):
        budget = deadline_s or self.s.llm_call_deadline_s
        t0 = time.monotonic()
        total = LLMResult(text="")
        last_err: Exception | None = None
        for i in range(2):
            remaining = budget if i == 0 else max(5.0, budget - (time.monotonic() - t0))
            res = self.generate(
                prompt, system=system, json_mode=True, max_output_tokens=max_output_tokens,
                deadline_s=remaining, max_models=max_models,
            )
            total.prompt_tokens += res.prompt_tokens
            total.output_tokens += res.output_tokens
            total.latency_ms += res.latency_ms
            total.text, total.model = res.text, res.model
            try:
                return _parse_json(res.text), total
            except LLMError as e:
                last_err = e
        raise LLMError(str(last_err))

    def embed(self, texts: list[str], task_type: str) -> list[list[float]]:
        key = texts[0] if (len(texts) == 1 and task_type == "RETRIEVAL_QUERY") else None
        if key is not None and key in self._embed_cache:
            return [self._embed_cache[key]]

        cfg = types.EmbedContentConfig(task_type=task_type, output_dimensionality=self.s.embed_dim)
        last: Exception | None = None
        for attempt in range(3):
            try:
                resp = self.client.models.embed_content(model=self.s.embed_model, contents=texts, config=cfg)
                vectors = [list(e.values) for e in resp.embeddings]
                if key is not None:
                    if len(self._embed_cache) > 256:
                        self._embed_cache.clear()
                    self._embed_cache[key] = vectors[0]
                return vectors
            except errors.APIError as e:
                last = e
                if e.code not in RETRYABLE_CODES:
                    raise LLMError(f"embed failed ({e.code}): {e.message}") from e
            except (httpx.TransportError, TimeoutError) as e:
                last = e
            time.sleep(1.0 * (attempt + 1))
        raise LLMError(f"embed failed after retries: {last}")

    def status(self) -> list[dict[str, Any]]:
        now = time.monotonic()
        return [
            {
                "model": m,
                "available": st.cooldown_until <= now,
                "cooldown_remaining_s": max(0, round(st.cooldown_until - now)),
                "last_error": st.last_error,
                "ok_calls": st.ok_calls,
                "failed_calls": st.failed_calls,
                "plain_mode": m in self._plain or m.lower().startswith("gemma"),
            }
            for m, st in self.state.items()
        ]
