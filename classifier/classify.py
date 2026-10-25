"""Ticket -> category / priority / next step. LLM is the core; code handles edges and failures."""

from __future__ import annotations

import hashlib
from functools import cache as memo
from pathlib import Path

from classifier.rules import apply_rules
from classifier.schema import ROUTING, Category, Classification, Priority, Sentiment, TicketResult
from core.cache import Cache, make_key, normalize
from core.json_guard import StructuredCallFailed, structured_call
from core.llm import LLMClient

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"
DEFAULT_PROMPT = "v1"
MAX_TICKET_CHARS = 6000  # long threads are truncated; the head carries the request in practice


@memo
def load_prompt(version: str) -> str:
    return (PROMPTS_DIR / f"{version}.md").read_text()


def prompt_hash(version: str) -> str:
    return hashlib.sha256(load_prompt(version).encode()).hexdigest()[:12]


def build_messages(text: str, version: str) -> list[dict]:
    system = load_prompt(version)
    # From v3 on the ticket is wrapped in delimiters so instructions inside it read as data.
    user = f"<ticket>\n{text}\n</ticket>" if "<ticket>" in system else text
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _fallback(reason: str, priority: Priority = Priority.P3, category: Category = Category.unclassified,
              next_step: str = "Route to manual triage queue.") -> Classification:
    return Classification(category=category, priority=priority, language="und", sentiment=Sentiment.neutral,
                          next_step=next_step, confidence=0.0, needs_human=category == Category.unclassified,
                          reason=reason)


def classify(text: str, chain: list[LLMClient], prompt_version: str = DEFAULT_PROMPT,
             cache: Cache | None = None, use_rules: bool = True) -> TicketResult:
    text = (text or "").strip()[:MAX_TICKET_CHARS]

    if len(normalize(text)) < 3:
        # Nothing to classify: no model call, ask the customer for details.
        c = _fallback("Empty or near-empty ticket.", Priority.P4, Category.spam_other,
                      "Auto-reply asking the customer to describe the issue.")
        return TicketResult(classification=c, team=ROUTING[c.category], prompt_version=prompt_version)

    key = None
    if cache and chain:
        key = make_key("classify", prompt_hash(prompt_version), chain[0].alias, normalize(text))
        if (hit := cache.get(key)) is not None:
            return TicketResult.model_validate({**hit, "cached": True})

    try:
        res = structured_call(chain, build_messages(text, prompt_version), Classification)
    except StructuredCallFailed as exc:
        c = _fallback("All models failed; needs manual triage.")
        c, hits = apply_rules(text, c) if use_rules else (c, [])
        return TicketResult(classification=c, team=ROUTING[c.category], rule_hits=hits,
                            prompt_version=prompt_version, errors=exc.errors)

    raw = res.value
    final, hits = apply_rules(text, raw) if use_rules else (raw, [])
    result = TicketResult(
        classification=final, raw_classification=raw, team=ROUTING[final.category],
        rule_hits=hits, model=res.model_alias, prompt_version=prompt_version,
        latency_s=res.latency_s, cost_usd=res.cost_usd,
        input_tokens=sum(c.input_tokens for c in res.calls), output_tokens=sum(c.output_tokens for c in res.calls),
        errors=res.errors,
    )
    # Only cache clean answers from the primary model; a fallback answer should be retried next time.
    if key and not res.errors and res.model_alias == chain[0].alias:
        cache.set(key, result.model_dump(mode="json"))
    return result
