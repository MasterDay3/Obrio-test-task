"""Agent assistant: summary + 3 tone variants grounded in KB citations + human-judgment flags.

Pipeline: (analyze ticket || classify ticket) -> retrieve KB sections -> draft replies -> verify citations.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from functools import cache as memo
from pathlib import Path

from pydantic import BaseModel, Field

from assistant.retrieval import MIN_SCORE, Chunk, KnowledgeBase, get_kb, kb_version, tokenize
from classifier.classify import classify
from classifier.rules import HIGH_AMOUNT
from classifier.schema import Category, TicketResult
from core.cache import Cache, make_key, normalize
from core.json_guard import StructuredCallFailed, structured_call
from core.llm import LLMClient

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"
ANALYZE_PROMPT = "analyze_v1"
DRAFT_PROMPT = "draft_v1"
CLASSIFIER_PROMPT = "v1"
TOP_K = 4
TONES = ("formal", "empathetic", "short")

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
    warnings: list[str] = Field(default_factory=list)


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
    ranked = sorted(((s + (MIN_SCORE if c.article_id in picked else 0.0), c) for c, s in zip(kb.chunks, scores)),
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
    user = (f"<ticket>\n{text}\n</ticket>\n\nCustomer language: {analysis.language}\n"
            f"Summary: {analysis.summary}\nCustomer wants: {analysis.customer_wants}\n{flags}\n"
            f"Knowledge base passages:\n{kb_block}")
    return [{"role": "system", "content": load_prompt(DRAFT_PROMPT)}, {"role": "user", "content": user}]


def _verify(kb: KnowledgeBase, draft: Draft) -> dict[str, Reply]:
    replies = {}
    for tone in TONES:
        reply = draft.replies.get(tone)
        if reply is None:
            replies[tone] = Reply(text="", warnings=["Model did not produce this variant."])
            continue
        for c in reply.citations:
            c.verified = kb.verify_quote(c.article_id, c.quote)
        bad = [c for c in reply.citations if not c.verified]
        if bad:
            reply.warnings.append(f"{len(bad)} citation(s) not found in the KB were removed: possible invented policy.")
            reply.citations = [c for c in reply.citations if c.verified]
        if not reply.citations and not draft.kb_gap:
            reply.warnings.append("No verified KB citation: check every fact in this reply.")
        replies[tone] = reply
    return replies


def _human_reasons(cls: TicketResult | None, passages: list[Passage], replies: dict[str, Reply]) -> list[str]:
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
    if not passages:
        reasons.append("No relevant KB article: the drafts cannot be checked against policy, write the answer yourself.")
    if any(any("not found in the KB" in w for w in r.warnings) for r in replies.values()):
        reasons.append("A draft cited text that does not exist in the KB: verify facts before sending.")
    return list(dict.fromkeys(reasons))


def assist(text: str, chain: list[LLMClient], cache: Cache | None = None) -> AssistResult:
    text = (text or "").strip()
    kb = get_kb()
    key = None
    if cache and chain:
        key = make_key("assist", ANALYZE_PROMPT, load_prompt(ANALYZE_PROMPT), DRAFT_PROMPT, load_prompt(DRAFT_PROMPT),
                       CLASSIFIER_PROMPT, kb_version(), chain[0].alias, normalize(text))
        if (hit := cache.get(key)) is not None:
            return AssistResult.model_validate({**hit, "cached": True})

    errors: list[str] = []
    cost = analyze_latency = draft_latency = 0.0
    analyze_msgs = [{"role": "system", "content": load_prompt(ANALYZE_PROMPT).format(kb_index=kb_index(kb))},
                    {"role": "user", "content": f"<ticket>\n{text}\n</ticket>"}]
    # Classification (Task 1) and analysis are independent: run them in parallel to save latency.
    with ThreadPoolExecutor(max_workers=2) as pool:
        cls_future = pool.submit(classify, text, chain, CLASSIFIER_PROMPT)
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
    try:
        res = structured_call(chain, _draft_messages(text, analysis, passages, cls), Draft)
        replies, note = _verify(kb, res.value), res.value.agent_note
        cost += res.cost_usd
        draft_latency = res.latency_s
        errors += res.errors
    except StructuredCallFailed as exc:
        errors += exc.errors

    reasons = _human_reasons(cls, passages, replies)
    if not replies:
        reasons.append("AI drafts unavailable: write the reply manually.")
    result = AssistResult(
        summary=analysis.summary, language=analysis.language, customer_wants=analysis.customer_wants,
        passages=passages, replies=replies, agent_note=note, classification=cls,
        human_required=bool(reasons), human_reasons=reasons, errors=errors + cls.errors,
        cost_usd=round(cost, 7), latency_s=round(max(analyze_latency, cls.latency_s) + draft_latency, 2),
    )
    if key and replies and not errors:
        cache.set(key, result.model_dump(mode="json"))
    return result
