"""Structured output with a safety net: parse -> validate -> one repair retry -> next model -> caller's safe default."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from pydantic import BaseModel, ValidationError

from core.llm import LLMClient, LLMError, LLMResult

_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE)


class StructuredCallFailed(Exception):
    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


@dataclass
class StructuredResult[T: BaseModel]:
    value: T
    calls: list[LLMResult]
    errors: list[str] = field(default_factory=list)

    @property
    def model_alias(self) -> str:
        return self.calls[-1].model_alias

    @property
    def cost_usd(self) -> float:
        return sum(c.cost_usd for c in self.calls)

    @property
    def latency_s(self) -> float:
        return sum(c.latency_s for c in self.calls)


def parse_json[T: BaseModel](text: str, schema: type[T]) -> T:
    """Lenient parse: strips markdown fences and surrounding prose, then validates against the schema."""
    cleaned = _FENCE.sub("", text.strip())
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON object in model output")
    return schema.model_validate(json.loads(cleaned[start:end + 1]))


def structured_call[T: BaseModel](chain: list[LLMClient], messages: list[dict], schema: type[T]) -> StructuredResult[T]:
    errors: list[str] = []
    calls: list[LLMResult] = []
    for client in chain:
        attempt_messages = list(messages)
        for repair in (False, True):
            try:
                result = client.complete(attempt_messages)
            except LLMError as exc:
                errors.append(str(exc))
                break  # provider is down / rate limited past retries -> next model
            calls.append(result)
            try:
                return StructuredResult(parse_json(result.text, schema), calls, errors)
            except (ValueError, ValidationError) as exc:
                errors.append(f"{client.alias}: invalid output{' after repair' if repair else ''}: {_short(exc)}")
                attempt_messages = messages + [
                    {"role": "assistant", "content": result.text},
                    {"role": "user", "content": "Your previous reply was not valid JSON for the required schema. "
                                                f"Error: {_short(exc)}. Reply again with ONLY the corrected JSON object."},
                ]
    raise StructuredCallFailed(errors or ["empty model chain (no credentials configured?)"])


def _short(exc: Exception, limit: int = 300) -> str:
    return str(exc).replace("\n", " ")[:limit]
