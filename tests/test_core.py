from types import SimpleNamespace

import httpx2
import openai
import pytest
from pydantic import BaseModel

from core.cache import Cache, make_key, normalize
from core.json_guard import StructuredCallFailed, parse_json, structured_call
from core.llm import LLMClient, LLMError, ModelSpec

REQ = httpx2.Request("POST", "https://example.test/v1/chat/completions")


def rate_limit(retry_after: str | None = None):
    headers = {"retry-after": retry_after} if retry_after else {}
    return openai.RateLimitError("429", response=httpx2.Response(429, request=REQ, headers=headers), body=None)


def ok(text: str, in_tok: int = 100, out_tok: int = 20):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))],
                           usage=SimpleNamespace(prompt_tokens=in_tok, completion_tokens=out_tok))


class FakeSDK:
    """Returns (or raises) the scripted outcomes in order."""

    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.calls: list[dict] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def client(alias, sdk, sleeps=None):
    spec = ModelSpec(alias, "fake", alias, input_per_mtok=1.0, output_per_mtok=2.0)
    return LLMClient(spec, sdk, max_attempts=3, sleep=(sleeps.append if sleeps is not None else lambda s: None))


class Out(BaseModel):
    label: str


def test_complete_reports_tokens_and_cost():
    result = client("m", FakeSDK(ok('{"label":"a"}', 1_000_000, 500_000))).complete([])
    assert (result.input_tokens, result.output_tokens) == (1_000_000, 500_000)
    assert result.cost_usd == pytest.approx(2.0)


def test_rate_limit_retries_and_honours_retry_after():
    sleeps = []
    sdk = FakeSDK(rate_limit("2"), ok('{"label":"a"}'))
    result = client("m", sdk, sleeps).complete([])
    assert result.attempts == 2 and sleeps == [2.0]


def test_timeout_exhausts_retries_then_raises_llm_error():
    sdk = FakeSDK(*[openai.APITimeoutError(REQ)] * 3)
    with pytest.raises(LLMError):
        client("m", sdk).complete([])
    assert len(sdk.calls) == 3


def test_auth_error_is_not_retried():
    err = openai.AuthenticationError("401", response=httpx2.Response(401, request=REQ), body=None)
    sdk = FakeSDK(err)
    with pytest.raises(LLMError):
        client("m", sdk).complete([])
    assert len(sdk.calls) == 1


def test_parse_json_strips_fences_and_prose():
    assert parse_json('Sure!\n```json\n{"label": "x"}\n```', Out).label == "x"


def test_invalid_json_is_repaired_on_same_model():
    sdk = FakeSDK(ok("not json"), ok('{"label":"fixed"}'))
    result = structured_call([client("m", sdk)], [{"role": "user", "content": "hi"}], Out)
    assert result.value.label == "fixed" and len(result.calls) == 2
    assert "not valid JSON" in sdk.calls[1]["messages"][-1]["content"]


def test_falls_back_to_next_model_when_first_is_down():
    down = FakeSDK(*[rate_limit()] * 3)
    up = FakeSDK(ok('{"label":"b"}'))
    result = structured_call([client("a", down), client("b", up)], [], Out)
    assert result.model_alias == "b" and result.errors


def test_falls_back_after_failed_repair_and_raises_when_all_fail():
    bad = FakeSDK(ok("{}"), ok("{}"))
    dead = FakeSDK(*[openai.APIConnectionError(request=REQ)] * 3)
    with pytest.raises(StructuredCallFailed) as exc:
        structured_call([client("a", bad), client("b", dead)], [], Out)
    assert len(exc.value.errors) == 3


def test_cache_roundtrip_and_key_sensitivity(tmp_path):
    cache = Cache(tmp_path / "c.sqlite")
    key = make_key("v3", "model-a", normalize("  Refund   ME "))
    cache.set(key, {"label": "refund"})
    assert cache.get(make_key("v3", "model-a", normalize("refund me"))) == {"label": "refund"}
    assert cache.get(make_key("v4", "model-a", normalize("refund me"))) is None


def test_cache_ttl_expiry(tmp_path):
    cache = Cache(tmp_path / "c.sqlite", ttl_s=-1)
    cache.set("k", {"a": 1})
    assert cache.get("k") is None


def test_cached_input_tokens_are_priced_at_cache_rate():
    spec = ModelSpec("m", "fake", "m", input_per_mtok=1.0, output_per_mtok=2.0, cached_input_per_mtok=0.5)
    assert spec.cost(1_000_000, 0, cached_tokens=400_000) == pytest.approx(0.6 + 0.2)
    plain = ModelSpec("m", "fake", "m", input_per_mtok=1.0, output_per_mtok=2.0)
    assert plain.cost(1_000_000, 0, cached_tokens=400_000) == pytest.approx(1.0)


def test_extra_params_are_sent_in_extra_body():
    sdk = FakeSDK(ok('{"label":"a"}'))
    spec = ModelSpec("m", "fake", "m", 1.0, 1.0, extra_params=(("reasoning_effort", "low"),))
    LLMClient(spec, sdk, sleep=lambda s: None).complete([])
    assert sdk.calls[0]["extra_body"] == {"reasoning_effort": "low"}


def test_empty_choices_raise_llm_error_so_chain_moves_on():
    empty = SimpleNamespace(choices=[], usage=None)
    up = FakeSDK(ok('{"label":"b"}'))
    result = structured_call([client("a", FakeSDK(empty)), client("b", up)], [], Out)
    assert result.model_alias == "b" and "empty response" in result.errors[0]


def test_daily_quota_429_is_not_retried():
    quota = openai.RateLimitError("You exceeded your current quota, please check your plan",
                                  response=httpx2.Response(429, request=REQ), body=None)
    sdk = FakeSDK(quota)
    with pytest.raises(LLMError):
        client("m", sdk).complete([])
    assert len(sdk.calls) == 1


def test_groq_tokens_per_day_429_is_not_retried():
    tpd = openai.RateLimitError("Rate limit reached for model on tokens per day (TPD): Limit 200000",
                                response=httpx2.Response(429, request=REQ, headers={"retry-after": "313"}), body=None)
    sdk = FakeSDK(tpd)
    with pytest.raises(LLMError):
        client("m", sdk).complete([])
    assert len(sdk.calls) == 1

