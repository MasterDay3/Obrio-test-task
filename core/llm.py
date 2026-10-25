"""Thin provider adapter: one OpenAI-compatible client per model, explicit timeout/retry, cost accounting."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import openai
import yaml
from dotenv import load_dotenv
from tenacity import RetryCallState, Retrying, retry_if_exception, stop_after_attempt, wait_exponential_jitter

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "models.yaml"

# Transient errors worth retrying on the same model. Anything else (auth, bad request) fails fast.
RETRYABLE = (openai.RateLimitError, openai.APITimeoutError, openai.APIConnectionError, openai.InternalServerError)


def _retryable(exc: BaseException) -> bool:
    # A daily/billing quota 429 will not clear in seconds: fail over to the next model instead of waiting.
    # Seen in practice: Gemini "exceeded your current quota", Groq "tokens per day (TPD)".
    if isinstance(exc, openai.RateLimitError):
        msg = str(exc).lower()
        if ("quota" in msg and "minute" not in msg) or "per day" in msg or "(tpd)" in msg or "(rpd)" in msg:
            return False
    return isinstance(exc, RETRYABLE)
MAX_RETRY_AFTER_S = 30.0


class LLMError(Exception):
    """A model call failed after retries (or with a non-retryable error)."""


@dataclass(frozen=True)
class ModelSpec:
    alias: str
    provider: str
    model: str
    input_per_mtok: float
    output_per_mtok: float
    cached_input_per_mtok: float | None = None  # provider prompt-cache price; None = no discount
    extra_params: tuple[tuple[str, Any], ...] = ()  # provider-specific request params, e.g. reasoning_effort

    def cost(self, input_tokens: int, output_tokens: int, cached_tokens: int = 0) -> float:
        cached = min(cached_tokens, input_tokens) if self.cached_input_per_mtok is not None else 0
        return ((input_tokens - cached) * self.input_per_mtok + cached * (self.cached_input_per_mtok or 0)
                + output_tokens * self.output_per_mtok) / 1_000_000


@dataclass
class LLMResult:
    text: str
    model_alias: str
    input_tokens: int
    output_tokens: int
    latency_s: float
    cost_usd: float
    attempts: int
    cached_input_tokens: int = 0


def _wait(state: RetryCallState) -> float:
    """Honour Retry-After on 429 when the provider sends it, otherwise exponential backoff with jitter."""
    exc = state.outcome.exception() if state.outcome else None
    if isinstance(exc, openai.RateLimitError):
        retry_after = exc.response.headers.get("retry-after")
        try:
            return min(float(retry_after), MAX_RETRY_AFTER_S)
        except (TypeError, ValueError):
            pass
    return wait_exponential_jitter(initial=1, max=10)(state)


class LLMClient:
    def __init__(self, spec: ModelSpec, client: Any, timeout_s: float = 30.0, max_attempts: int = 3,
                 sleep=time.sleep):
        self.spec = spec
        self.client = client
        self.timeout_s = timeout_s
        self.max_attempts = max_attempts
        self._sleep = sleep

    @property
    def alias(self) -> str:
        return self.spec.alias

    def complete(self, messages: list[dict], json_mode: bool = True, temperature: float = 0.0) -> LLMResult:
        kwargs: dict[str, Any] = {"model": self.spec.model, "messages": messages,
                                  "temperature": temperature, "timeout": self.timeout_s}
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        if self.spec.extra_params:
            kwargs["extra_body"] = dict(self.spec.extra_params)

        retrying = Retrying(stop=stop_after_attempt(self.max_attempts), wait=_wait,
                            retry=retry_if_exception(_retryable), sleep=self._sleep, reraise=True)
        started = time.perf_counter()
        try:
            for attempt in retrying:
                with attempt:
                    response = self.client.chat.completions.create(**kwargs)
        except openai.OpenAIError as exc:
            raise LLMError(f"{self.alias}: {type(exc).__name__}: {exc}") from exc
        latency = time.perf_counter() - started

        usage = getattr(response, "usage", None)
        in_tok = getattr(usage, "prompt_tokens", 0) or 0
        out_tok = getattr(usage, "completion_tokens", 0) or 0
        cached_tok = getattr(getattr(usage, "prompt_tokens_details", None), "cached_tokens", 0) or 0
        if not getattr(response, "choices", None) or response.choices[0].message is None:
            # e.g. a safety block: not an SDK exception, but the chain must still move to the next model.
            raise LLMError(f"{self.alias}: empty response (no choices)")
        text = response.choices[0].message.content or ""
        return LLMResult(text=text, model_alias=self.alias, input_tokens=in_tok, output_tokens=out_tok,
                         latency_s=latency, cost_usd=self.spec.cost(in_tok, out_tok, cached_tok), cached_input_tokens=cached_tok,
                         attempts=retrying.statistics.get("attempt_number", 1))


def load_config(path: Path = CONFIG_PATH) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def make_client(alias: str, config: dict | None = None, **kwargs) -> LLMClient:
    load_dotenv()
    config = config or load_config()
    m = config["models"][alias]
    p = config["providers"][m["provider"]]
    base_url = os.getenv(p.get("base_url_env", ""), "") or p["base_url"]
    api_key = p.get("api_key") or os.getenv(p["api_key_env"], "")
    if not api_key:
        raise LLMError(f"{alias}: missing env var {p['api_key_env']}")
    spec = ModelSpec(alias=alias, provider=m["provider"], model=m["model"],
                     input_per_mtok=m["input_per_mtok"], output_per_mtok=m["output_per_mtok"],
                     cached_input_per_mtok=m.get("cached_input_per_mtok"),
                     extra_params=tuple((m.get("extra_params") or {}).items()))
    # SDK retries are disabled so that retry behaviour is ours and observable.
    sdk = openai.OpenAI(api_key=api_key, base_url=base_url, max_retries=0)
    return LLMClient(spec, sdk, **kwargs)


def make_chain(aliases: list[str] | None = None, **kwargs) -> list[LLMClient]:
    """Build the fallback chain, skipping models whose credentials are missing."""
    config = load_config()
    chain = []
    for alias in aliases or config["fallback_chain"]:
        try:
            chain.append(make_client(alias, config, **kwargs))
        except LLMError:
            continue
    return chain
