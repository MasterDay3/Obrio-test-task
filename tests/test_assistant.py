import json
import threading
from types import SimpleNamespace

from assistant.assist import Analysis, assist, retrieve
from assistant.retrieval import get_kb
from core.llm import LLMClient, ModelSpec
from tests.test_core import ok

DUPLICATE_QUOTE = "If two identical completed charges appear for the same period, the duplicate is a billing error."


class RoutingSDK:
    """Answers by prompt type, because classify and analyze run in parallel threads."""

    def __init__(self, analyze: dict, draft: dict | str, classify: dict):
        self.responses = {"analyze": analyze, "draft": draft, "classify": classify}
        self.lock = threading.Lock()
        self.calls: list[str] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, messages, **_):
        system = messages[0]["content"]
        kind = "analyze" if "understand a customer ticket" in system else "draft" if "three reply" in system else "classify"
        with self.lock:
            self.calls.append(kind)
        body = self.responses[kind]
        return ok(body if isinstance(body, str) else json.dumps(body))


def chain(sdk):
    return [LLMClient(ModelSpec("fake", "fake", "fake", 1.0, 1.0), sdk, sleep=lambda s: None)]


def classification(category="billing_subscription", priority="P2", needs_human=False):
    return {"category": category, "priority": priority, "language": "en", "sentiment": "negative",
            "next_step": "refund duplicate", "confidence": 0.9, "needs_human": needs_human, "reason": "x"}


ANALYSIS = {"summary": "Charged twice.", "language": "en", "customer_wants": "refund of duplicate charge",
            "search_query": "duplicate charge twice refund", "candidate_articles": ["double-charge"]}


def draft(quote=DUPLICATE_QUOTE, article="double-charge"):
    reply = {"text": "We will refund the duplicate.", "citations": [{"article_id": article, "quote": quote}]}
    return {"replies": {"formal": reply, "empathetic": reply, "short": reply}, "kb_gap": False, "agent_note": ""}


def test_retrieval_boosts_model_picked_article_over_lexical_noise():
    kb = get_kb()
    hits = retrieve(kb, Analysis(summary="", search_query="child used my card to buy credits",
                                 candidate_articles=["minor-purchases", "not-a-real-article"]))
    assert hits[0].article_id == "minor-purchases"


def test_retrieval_returns_nothing_for_off_topic_query():
    assert retrieve(get_kb(), Analysis(summary="", search_query="weather in paris tomorrow")) == []


def test_happy_path_has_verified_citations_and_no_human_flag():
    sdk = RoutingSDK(ANALYSIS, draft(), classification())
    r = assist("I was charged twice for my subscription", chain(sdk))
    assert sorted(sdk.calls) == ["analyze", "classify", "draft"]
    assert all(r.replies[t].citations[0].verified for t in ("formal", "empathetic", "short"))
    assert r.passages[0].article_id == "double-charge"
    assert not r.human_required


def test_invented_quote_is_removed_and_flags_human():
    sdk = RoutingSDK(ANALYSIS, draft(quote="All customers get a full refund within 60 days, no questions asked."),
                     classification())
    r = assist("I was charged twice", chain(sdk))
    assert r.replies["formal"].citations == []
    assert any("not found in the KB" in w for w in r.replies["formal"].warnings)
    assert r.human_required and any("does not exist in the KB" in h for h in r.human_reasons)


def test_rule_hits_become_human_reasons():
    sdk = RoutingSDK(ANALYSIS, draft(), classification("legal_privacy", "P1", True))
    r = assist("I've already filed a chargeback with my bank", chain(sdk))
    assert r.human_required and any("chargeback" in h for h in r.human_reasons)


def test_draft_failure_degrades_to_manual_reply():
    sdk = RoutingSDK(ANALYSIS, "not json at all", classification())
    r = assist("I was charged twice", chain(sdk))
    assert r.replies == {} and r.summary == "Charged twice."
    assert any("write the reply manually" in h for h in r.human_reasons)
