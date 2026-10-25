"""Agent assistant: summary + 3 tone variants grounded in KB citations + human-judgment flags.

Pipeline: (analyze ticket || classify ticket) -> retrieve KB sections -> draft replies -> verify citations.
"""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from functools import cache as memo
from pathlib import Path

from pydantic import BaseModel, Field, model_validator

from assistant.retrieval import MIN_SCORE, Chunk, KnowledgeBase, get_kb, kb_version, tokenize
from classifier.classify import classify, clip_ticket, wrap_ticket
from classifier.rules import HIGH_AMOUNT
from classifier.schema import Category, TicketResult
from core.cache import Cache, make_key, normalize
from core.json_guard import StructuredCallFailed, structured_call
from core.llm import LLMClient

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"
ANALYZE_PROMPT = "analyze_v1"
DRAFT_PROMPT = "draft_v4"  # draft_v5 (explicit "no past tense" rule) tried: no gain on the eval, see docs
CLASSIFIER_PROMPT = "v3"
TOP_K = 4
TONES = ("formal", "empathetic", "short")
LANGUAGES = {"en": "English", "uk": "Ukrainian", "ru": "Russian", "es": "Spanish", "de": "German", "pl": "Polish",
             "fr": "French", "it": "Italian", "pt": "Portuguese"}
_NUMBER = re.compile(r"\d+(?:[.,]\d+)?(?:\s?[-–—‑]\s?\d+(?:[.,]\d+)?)?")  # ranges like "5–10" are one unit
_CYRILLIC = {"uk", "ru"}
# Agent-only facts that leaked into customer replies during eval (approval limits, admin tools). Kept narrow: a plain
# "limit" can be customer-facing (e.g. birth data can be changed 3 times a month).
INTERNAL = re.compile(
    r"admin[- ‑]?(panel|system|tool)|адмін[- ‑]?панел|админ[- ‑]?панел|\bagents? (can|cannot|may|must|are allowed)|"
    r"approval limit|without escalation|\$\s?100 (limit|ліміт|лимит)|(limit|ліміт|лимит)\w*\s+(of\s+|в\s+|у\s+)?\$\s?100",
    re.IGNORECASE)
# Drafts that state an action as already done (eval v1: "I can approve the refund right away... being processed now").
# The agent may send it before doing the action, which turns a draft into a false promise.
CLAIMED_ACTION = re.compile(
    r"\b(i|we)(\s+have|'ve)?\s+(already\s+)?(processed|issued|refunded|approved|cancell?ed|initiated|escalated)\b|"
    r"\b(is|are)\s+being\s+processed\b|\bhas\s+been\s+(processed|issued|refunded|approved|cancell?ed)\b|"
    r"\bi\s+can\s+approve\b|"
    # Ukrainian / Russian past tense, seen live: "Ми підтвердили наявність подвійного списання", "служба перевірила".
    r"\b(перевірил[иа]|підтвердил[иа]|оформил[иа]|повернул[иа]|скасувал[иа]|ініціювал[иа]|"
    r"проверил[иа]|подтвердил[иа]|оформил[иа]|вернул[иа]|отменил[иа])\b",
    re.IGNORECASE)


def script_matches(lang: str, text: str) -> bool:
    """Cheap language check: Cyrillic tickets must get Cyrillic replies, Latin-script tickets Latin replies."""
    cyrillic = bool(re.search(r"[а-яіїєґё]", text.lower()))
    return cyrillic if lang in _CYRILLIC else not cyrillic


def _numbers(text: str) -> set[str]:
    return {re.sub(r"\s?[-–—‑]\s?", "-", n) for n in _NUMBER.findall(text)}


HUMAN_REASONS = {
    "safety_keywords": "Possible self-harm or threat of violence: escalate to Trust & Safety, do not send a template.",
    "category_safety": "Possible self-harm or threat of violence: escalate to Trust & Safety, do not send a template.",
    "legal_threat": "Legal threat, chargeback or regulator mentioned: the Legal team decides the response.",
    "category_legal": "Legal or privacy matter: route to Legal & Privacy, agent must not commit to anything.",
    "privacy_request": "Personal-data request (GDPR): only the Privacy team can action it.",
    "account_takeover": "Possible account takeover: lock the account and verify ownership before any change.",
    "repeat_contact": "Repeat contact: earlier answers failed, read the ticket history before replying.",
    "possible_prompt_injection": "Ticket contains instructions aimed at the AI: check the drafts carefully.",
    "high_amount": f"Amount above ${HIGH_AMOUNT:.0f}: refund requires Billing specialist approval.",
    "minor_involved": "A minor is involved: refunds are reviewed case by case by Billing.",
    "low_confidence": "The classifier is unsure about this ticket: confirm the category yourself.",
}


class Analysis(BaseModel):
    summary: str
    language: str = "en"
    customer_wants: str = ""
    search_query: str
    candidate_articles: list[str] = Field(default_factory=list)


class Citation(BaseModel):
    article_id: str
    quote: str
    verified: bool = False


class Reply(BaseModel):
    text: str
    citations: list[Citation] = Field(default_factory=list)
    removed_citations: int = 0  # quotes the model invented; dropped by the verifier
    unsupported_numbers: list[str] = Field(default_factory=list)  # numbers in the text not in KB passages or ticket
    internal_leaks: list[str] = Field(default_factory=list)  # agent-only phrases found in a customer reply
    claimed_actions: list[str] = Field(default_factory=list)  # "refund processed" etc.: true only once the agent acts
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _accept_plain_string(cls, v):
        # Seen in eval: models sometimes return a tone as a bare string instead of {text, citations}.
        return {"text": v} if isinstance(v, str) else v


class Draft(BaseModel):
    replies: dict[str, Reply]
    kb_gap: bool = False
    agent_note: str = ""


class Passage(BaseModel):
    ref: str
    article_id: str
    title: str
    section: str
    text: str
    score: float


class AssistResult(BaseModel):
    summary: str
    language: str
    customer_wants: str = ""
    passages: list[Passage]
    replies: dict[str, Reply] = Field(default_factory=dict)
    agent_note: str = ""
    kb_gap: bool = False
    classification: TicketResult | None = None
    human_required: bool = False
    human_reasons: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    cost_usd: float = 0.0
    latency_s: float = 0.0
    cached: bool = False


@memo
def load_prompt(name: str) -> str:
    return (PROMPTS_DIR / f"{name}.md").read_text()


def kb_index(kb: KnowledgeBase) -> str:
    return "\n".join(f"- {aid}: {chunks[0].title}" for aid, chunks in kb.by_article.items())


def retrieve(kb: KnowledgeBase, analysis: Analysis, k: int = TOP_K) -> list[Passage]:
    """BM25 on the English rewrite, with a boost for the articles the model picked from the title list.
    Lexical search misses synonyms ("child" vs "minor"); the title-picking step covers that."""
    picked = {a for a in analysis.candidate_articles if a in kb.by_article}
    scores = kb._bm25.get_scores(tokenize(f"{analysis.search_query} {analysis.customer_wants}"))
    # The boost needs some lexical overlap (s > 0): a model pick with zero matching words is a guess, and letting it
    # through hid "no relevant article" cases (eval: "dark mode please" retrieved refund-policy).
    ranked = sorted(((s + (MIN_SCORE if c.article_id in picked and s > 0 else 0.0), c) for c, s in zip(kb.chunks, scores)),
                    key=lambda x: x[0], reverse=True)
    return [_passage(c, s) for s, c in ranked[:k] if s >= MIN_SCORE]


def _passage(c: Chunk, score: float) -> Passage:
    return Passage(ref=c.ref, article_id=c.article_id, title=c.title, section=c.section, text=c.text,
                   score=round(score, 2))


def _draft_messages(text: str, analysis: Analysis, passages: list[Passage], cls: TicketResult | None) -> list[dict]:
    kb_block = "\n\n".join(f"[{p.article_id}] {p.title} / {p.section}\n{p.text}" for p in passages) \
        or "(no relevant knowledge base passages found)"
    flags = ""
    if cls and cls.classification.needs_human:
        flags = (f"\nThis ticket needs a human decision ({', '.join(cls.rule_hits) or cls.classification.reason}). "
                 "Do not promise refunds, bans, or outcomes; say the case is being reviewed.\n")
    # The language is named and repeated last: with only an ISO code, Ukrainian tickets got English replies (eval).
    lang = LANGUAGES.get(analysis.language, analysis.language)
    if lang == "und":  # analysis failed: let the model infer it rather than asking for a language called "und"
        lang = "the same language as the ticket"
    user = (f"{wrap_ticket(text)}\n\nCustomer language: {lang}\n"
            f"Summary: {analysis.summary}\nCustomer wants: {analysis.customer_wants}\n{flags}\n"
            f"Knowledge base passages:\n{kb_block}\n\nWrite all three replies in {lang}.")
    return [{"role": "system", "content": load_prompt(DRAFT_PROMPT)}, {"role": "user", "content": user}]


def _verify(kb: KnowledgeBase, draft: Draft, passages: list[Passage] | None = None, ticket: str = "",
            lang: str = "und") -> dict[str, Reply]:
    """Checks the drafts, not only the citations: a reply can cite real quotes and still state a wrong number
    (eval: KB says "5-10 business days", reply said "5-7") or reveal agent-only rules."""
    known_numbers = _numbers(" ".join(p.text for p in passages or []) + " " + ticket)
    replies = {}
    for tone in TONES:
        reply = draft.replies.get(tone)
        if reply is None:
            replies[tone] = Reply(text="", warnings=["Model did not produce this variant."])
            continue
        for c in reply.citations:
            c.verified = kb.verify_quote(c.article_id, c.quote)
        bad = [c for c in reply.citations if not c.verified]
        reply.removed_citations = len(bad)
        if bad:
            reply.warnings.append(f"{len(bad)} citation(s) not found in the KB were removed: possible invented policy.")
            reply.citations = [c for c in reply.citations if c.verified]
        if not reply.citations and not draft.kb_gap:
            reply.warnings.append("No verified KB citation: check every fact in this reply.")
        reply.unsupported_numbers = sorted(_numbers(reply.text) - known_numbers)
        if reply.unsupported_numbers:
            reply.warnings.append(f"Numbers not found in the KB passages or the ticket: "
                                  f"{', '.join(reply.unsupported_numbers)}. Check before sending.")
        reply.internal_leaks = sorted({m.group(0) for m in INTERNAL.finditer(reply.text)})
        if reply.internal_leaks:
            reply.warnings.append(f"May reveal internal agent rules ({', '.join(reply.internal_leaks)}): rephrase.")
        reply.claimed_actions = sorted({m.group(0) for m in CLAIMED_ACTION.finditer(reply.text)})
        if reply.claimed_actions:
            reply.warnings.append(f"States an action as done ({', '.join(reply.claimed_actions)}): send only after "
                                  "you have actually done it.")
        if lang != "und" and reply.text and not script_matches(lang, reply.text):
            reply.warnings.append(f"Not written in the customer's language ({LANGUAGES.get(lang, lang)}).")
        replies[tone] = reply
    return replies


def _human_reasons(cls: TicketResult | None, passages: list[Passage], replies: dict[str, Reply],
                   kb_gap: bool = False) -> list[str]:
    reasons: list[str] = []
    if cls:
        reasons += [HUMAN_REASONS[h] for h in cls.rule_hits if h in HUMAN_REASONS]
        c = cls.classification
        if c.category == Category.expert_complaint and c.needs_human:
            reasons.append("Possible expert misconduct: Expert Quality reviews the transcript, do not promise an outcome.")
        elif c.category == Category.unclassified:
            reasons.append("AI could not classify this ticket: triage manually.")
        elif c.needs_human and not cls.rule_hits:
            reasons.append(f"Classifier flagged for review: {c.reason}")
    if not passages or kb_gap:
        reasons.append("No relevant KB article: the drafts cannot be checked against policy, write the answer yourself.")
    if any(any("not found in the KB" in w for w in r.warnings) for r in replies.values()):
        reasons.append("A draft cited text that does not exist in the KB: verify facts before sending.")
    return list(dict.fromkeys(reasons))


def assist(text: str, chain: list[LLMClient], cache: Cache | None = None,
           classify_chain: list[LLMClient] | None = None) -> AssistResult:
    """`chain` drafts the replies; `classify_chain` (default: the same) runs the Task 1 classifier, so the app can
    use the model that measured best for each job."""
    text = clip_ticket((text or "").strip())
    classify_chain = classify_chain if classify_chain is not None else chain
    if len(normalize(text)) < 3:
        # Nothing to answer: no model calls, ask the customer for details (same rule as the classifier).
        cls = classify(text, classify_chain, CLASSIFIER_PROMPT)
        return AssistResult(summary="Empty or near-empty ticket.", language="und", passages=[], classification=cls,
                            human_required=True,
                            human_reasons=["Ticket has no content: ask the customer to describe the issue."])
    kb = get_kb()
    key = None
    if cache and chain:
        key = make_key("assist", ANALYZE_PROMPT, load_prompt(ANALYZE_PROMPT), DRAFT_PROMPT, load_prompt(DRAFT_PROMPT),
                       CLASSIFIER_PROMPT, kb_version(), chain[0].alias,
                       classify_chain[0].alias if classify_chain else "-", normalize(text))
        if (hit := cache.get(key)) is not None:
            return AssistResult.model_validate({**hit, "cached": True})

    errors: list[str] = []
    cost = analyze_latency = draft_latency = 0.0
    analyze_msgs = [{"role": "system", "content": load_prompt(ANALYZE_PROMPT).format(kb_index=kb_index(kb))},
                    {"role": "user", "content": wrap_ticket(text)}]
    # Classification (Task 1) and analysis are independent: run them in parallel to save latency.
    with ThreadPoolExecutor(max_workers=2) as pool:
        cls_future = pool.submit(classify, text, classify_chain, CLASSIFIER_PROMPT)
        try:
            res = structured_call(chain, analyze_msgs, Analysis)
            analysis, cost, analyze_latency = res.value, res.cost_usd, res.latency_s
        except StructuredCallFailed as exc:
            errors += exc.errors
            analysis = Analysis(summary=text[:300], language="und", search_query=text)
        cls = cls_future.result()
    cost += cls.cost_usd

    passages = retrieve(kb, analysis)
    replies: dict[str, Reply] = {}
    note = ""
    kb_gap = False
    try:
        msgs = _draft_messages(text, analysis, passages, cls)
        res = structured_call(chain, msgs, Draft)
        cost, draft_latency, errors = cost + res.cost_usd, res.latency_s, errors + res.errors
        lang = analysis.language
        if lang != "und" and any(r.text and not script_matches(lang, r.text) for r in res.value.replies.values()):
            # Eval: Ukrainian tickets got English replies. One targeted re-ask is cheaper than a human rewrite.
            name = LANGUAGES.get(lang, lang)
            retry_msgs = msgs + [{"role": "assistant", "content": res.value.model_dump_json()},
                                 {"role": "user", "content": f"Some replies are not in {name}. Rewrite all three "
                                  f"replies entirely in {name}, keeping the same facts and citations. Same JSON."}]
            try:
                res = structured_call(chain, retry_msgs, Draft)
                cost, draft_latency = cost + res.cost_usd, draft_latency + res.latency_s
            except StructuredCallFailed as exc:
                errors += exc.errors  # keep the first draft; _verify will flag the language
        replies, note, kb_gap = _verify(kb, res.value, passages, text, lang), res.value.agent_note, res.value.kb_gap
    except StructuredCallFailed as exc:
        errors += exc.errors

    reasons = _human_reasons(cls, passages, replies, kb_gap)
    if not replies:
        reasons.append("AI drafts unavailable: write the reply manually.")
    result = AssistResult(
        summary=analysis.summary, language=analysis.language, customer_wants=analysis.customer_wants,
        passages=passages, replies=replies, agent_note=note, kb_gap=kb_gap, classification=cls,
        human_required=bool(reasons), human_reasons=reasons, errors=errors + cls.errors,
        cost_usd=round(cost, 7), latency_s=round(max(analyze_latency, cls.latency_s) + draft_latency, 2),
    )
    if key and replies and not (errors or cls.errors):  # never make a degraded answer sticky
        cache.set(key, result.model_dump(mode="json"))
    return result
