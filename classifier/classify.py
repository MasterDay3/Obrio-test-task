"""Ticket -> category / priority / next step. LLM is the core; code handles edges and failures."""

from __future__ import annotations

import hashlib
import re
from functools import cache as memo
from pathlib import Path

from classifier.rules import apply_rules
from classifier.schema import ROUTING, Category, Classification, Priority, Sentiment, TicketResult
from core.cache import Cache, make_key, normalize
from core.json_guard import StructuredCallFailed, structured_call
from core.llm import LLMClient

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"
DEFAULT_PROMPT = "v3"
MAX_TICKET_CHARS = 6000  # longer tickets keep their head and tail: greetings/context first, the actual ask often last


@memo
def load_prompt(version: str) -> str:
    return (PROMPTS_DIR / f"{version}.md").read_text()


def prompt_hash(version: str) -> str:
    return hashlib.sha256(load_prompt(version).encode()).hexdigest()[:12]


def clip_ticket(text: str, limit: int = MAX_TICKET_CHARS) -> str:
    if len(text) <= limit:
        return text
    half = limit // 2
    return f"{text[:half]}\n[… {len(text) - limit} characters omitted …]\n{text[-half:]}"


def wrap_ticket(text: str) -> str:
    """Wrap customer text in <ticket> tags, neutralising any tag inside it so the text cannot close the block."""
    return f"<ticket>\n{re.sub(r'<(/?)\s*ticket', r'<\1_ticket', text, flags=re.IGNORECASE)}\n</ticket>"


def build_messages(text: str, version: str) -> list[dict]:
    system = load_prompt(version)
    # From v3 on the ticket is wrapped in delimiters so instructions inside it read as data.
    user = wrap_ticket(text) if "<ticket>" in system else text
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _fallback(reason: str, priority: Priority = Priority.P3, category: Category = Category.unclassified,
              next_step: str = "Route to manual triage queue.") -> Classification:
    return Classification(category=category, priority=priority, language="und", sentiment=Sentiment.neutral,
                          next_step=next_step, confidence=0.0, needs_human=category == Category.unclassified,
                          reason=reason)


def classify(text: str, chain: list[LLMClient], prompt_version: str = DEFAULT_PROMPT,
             cache: Cache | None = None, use_rules: bool = True) -> TicketResult:
    text = clip_ticket((text or "").strip())

    if len(normalize(text)) < 3:
        # Nothing to classify: no model call, ask the customer for details.
        c = _fallback("Empty or near-empty ticket.", Priority.P4, Category.spam_other,
                      "Auto-reply asking the customer to describe the issue.")
        return TicketResult(classification=c, team=ROUTING[c.category], prompt_version=prompt_version)

    key = None
    if cache and chain:
        key = make_key("classify", prompt_hash(prompt_version), chain[0].alias, normalize(text))
        if (hit := cache.get(key)) is not None:
            # Only the model's raw answer is trusted from cache; rules are re-applied so rule edits apply at once.
            cached = TicketResult.model_validate(hit)
            raw = cached.raw_classification
            final, hits = apply_rules(text, raw) if use_rules else (raw, [])
            return cached.model_copy(update={"classification": final, "rule_hits": hits,
                                             "team": ROUTING[final.category], "cached": True})

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
        cached_input_tokens=sum(c.cached_input_tokens for c in res.calls),
        errors=res.errors,
    )
    # Only cache clean answers from the primary model; a fallback answer should be retried next time.
    if key and not res.errors and res.model_alias == chain[0].alias:
        cache.set(key, result.model_dump(mode="json"))
    return result
