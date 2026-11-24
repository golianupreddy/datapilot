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


class LLMError(RuntimeError):
    pass


@dataclass
class LLMResult:
    text: str
    prompt_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0


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
    """Thin Gemini wrapper: rate-limit retry with exponential backoff, JSON mode, token accounting, embeddings."""

    def __init__(self) -> None:
        self.s = get_settings()
        self.client = genai.Client(api_key=self.s.gemini_api_key)
        self._lock = threading.Lock()
        self._last_call = 0.0

    def _throttle(self) -> None:
        gap = self.s.llm_min_interval_seconds
        if gap <= 0:
            return
        with self._lock:
            wait = self._last_call + gap - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self._last_call = time.monotonic()

    def _with_retry(self, label: str, fn: Callable[[], Any]) -> Any:
        last: Exception | None = None
        for attempt in range(self.s.llm_max_retries + 1):
            self._throttle()
            try:
                return fn()
            except errors.APIError as e:
                last = e
                if e.code not in RETRYABLE_CODES:
                    raise LLMError(f"{label} failed ({e.code}): {e.message}") from e
            except (httpx.TransportError, TimeoutError) as e:
                last = e
            if attempt == self.s.llm_max_retries:
                break
            delay = min(2 ** (attempt + 1), 30) + random.uniform(0, 1)
            log.warning("%s: transient error (%s). Retry %d in %.1fs", label, last, attempt + 1, delay)
            time.sleep(delay)
        raise LLMError(f"{label} failed after {self.s.llm_max_retries} retries: {last}")

    def generate(
        self,
        prompt: str,
        system: str | None = None,
        json_mode: bool = False,
        temperature: float = 0.0,
        max_output_tokens: int = 2048,
    ) -> LLMResult:
        is_gemini = self.s.llm_model.lower().startswith("gemini-")
        cfg: dict[str, Any] = {"temperature": temperature, "max_output_tokens": max_output_tokens}
        if system:
            cfg["system_instruction"] = system
        if json_mode and is_gemini:
            cfg["response_mime_type"] = "application/json"
        if is_gemini and self.s.llm_thinking_budget >= 0:
            cfg["thinking_config"] = types.ThinkingConfig(thinking_budget=self.s.llm_thinking_budget)
        config = types.GenerateContentConfig(**cfg)
        start = time.perf_counter()
        resp = self._with_retry(
            "generate",
            lambda: self.client.models.generate_content(model=self.s.llm_model, contents=prompt, config=config),
        )
        text = resp.text or ""
        if not text.strip():
            raise LLMError("Model returned an empty response.")
        usage = getattr(resp, "usage_metadata", None)
        return LLMResult(
            text=text,
            prompt_tokens=(getattr(usage, "prompt_token_count", 0) or 0),
            output_tokens=(getattr(usage, "candidates_token_count", 0) or 0),
            latency_ms=int((time.perf_counter() - start) * 1000),
        )

    def generate_json(self, prompt: str, system: str | None = None, max_output_tokens: int = 2048):
        last_err: Exception | None = None
        total = LLMResult(text="")
        for _ in range(2):
            res = self.generate(prompt, system=system, json_mode=True, max_output_tokens=max_output_tokens)
            total.prompt_tokens += res.prompt_tokens
            total.output_tokens += res.output_tokens
            total.latency_ms += res.latency_ms
            total.text = res.text
            try:
                return _parse_json(res.text), total
            except LLMError as e:
                last_err = e
        raise LLMError(str(last_err))

    def embed(self, texts: list[str], task_type: str) -> list[list[float]]:
        cfg = types.EmbedContentConfig(task_type=task_type, output_dimensionality=self.s.embed_dim)
        resp = self._with_retry(
            "embed",
            lambda: self.client.models.embed_content(model=self.s.embed_model, contents=texts, config=cfg),
        )
        return [list(e.values) for e in resp.embeddings]
