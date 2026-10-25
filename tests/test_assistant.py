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
        kind = ("analyze" if "understand a customer ticket" in system
                else "draft" if "draft replies for a Nebula support agent" in system else "classify")
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


def test_model_pick_without_lexical_overlap_is_not_boosted():
    """Eval regression: 'dark mode' had no KB article, but model-picked articles slipped through."""
    hits = retrieve(get_kb(), Analysis(summary="", search_query="dark mode feature request",
                                       candidate_articles=["cancel-ios"]))
    assert "cancel-ios" not in {h.article_id for h in hits}


def test_kb_gap_from_model_requires_human():
    gap = {"replies": {t: {"text": "We will check.", "citations": []} for t in ("formal", "empathetic", "short")},
           "kb_gap": True, "agent_note": ""}
    r = assist("Please add dark mode", chain(RoutingSDK(ANALYSIS, gap, classification("feedback_feature_request", "P4"))))
    assert r.kb_gap and r.human_required and any("No relevant KB article" in h for h in r.human_reasons)


def test_plain_string_reply_is_accepted():
    sdk = RoutingSDK(ANALYSIS, {"replies": {"formal": "Hello", "empathetic": "Hi", "short": "Ok"}}, classification())
    r = assist("I was charged twice", chain(sdk))
    assert r.replies["short"].text == "Ok"


def test_wrong_number_and_internal_rule_are_flagged_even_with_valid_citation():
    """Eval regression: reply cited a real quote but said "5-7 days" (KB: 5-10) and mentioned the agent $100 limit."""
    reply = {"text": "We confirmed it in the admin panel; the refund is not counted against the $100 limit "
                     "and arrives in 5-7 days.",
             "citations": [{"article_id": "double-charge", "quote": DUPLICATE_QUOTE}]}
    bad = {"replies": {t: reply for t in ("formal", "empathetic", "short")}, "kb_gap": False, "agent_note": ""}
    r = assist("I was charged twice", chain(RoutingSDK(ANALYSIS, bad, classification())))
    formal = r.replies["formal"]
    assert formal.citations[0].verified
    assert "5-7" in formal.unsupported_numbers and "100" not in formal.unsupported_numbers
    assert any("admin" in x.lower() for x in formal.internal_leaks)


def test_wrong_language_draft_is_regenerated_once():
    """Eval regression: a Ukrainian ticket got English replies; the assistant re-asks once in Ukrainian."""
    english = {"replies": {t: {"text": "We will refund the duplicate.", "citations": []} for t in ("formal", "empathetic", "short")},
               "kb_gap": False, "agent_note": ""}
    ukrainian = {"replies": {t: {"text": "Ми повернемо зайве списання.", "citations": []} for t in ("formal", "empathetic", "short")},
                 "kb_gap": False, "agent_note": ""}

    class TwoDrafts(RoutingSDK):
        def _create(self, messages, **kw):
            if "draft replies for a Nebula support agent" in messages[0]["content"]:
                self.responses["draft"] = english if len(messages) == 2 else ukrainian
            return super()._create(messages, **kw)

    sdk = TwoDrafts({**ANALYSIS, "language": "uk"}, english, classification())
    r = assist("Мене двічі списали, поверніть кошти", chain(sdk))
    assert sdk.calls.count("draft") == 2
    assert r.replies["short"].text.startswith("Ми") and not any("language" in w for w in r.replies["short"].warnings)


def test_empty_ticket_makes_no_model_calls():
    sdk = RoutingSDK(ANALYSIS, draft(), classification())
    r = assist("   ", chain(sdk))
    assert sdk.calls == [] and r.replies == {} and r.human_required


def test_claimed_action_is_flagged_and_customer_facing_limit_is_not_a_leak():
    reply = {"text": "We have refunded the duplicate. Birth data has a limit of 3 changes per month.",
             "citations": [{"article_id": "double-charge", "quote": DUPLICATE_QUOTE}]}
    d = {"replies": {t: reply for t in ("formal", "empathetic", "short")}, "kb_gap": False, "agent_note": "x"}
    r = assist("I was charged twice", chain(RoutingSDK(ANALYSIS, d, classification())))
    assert r.replies["formal"].claimed_actions and r.replies["formal"].internal_leaks == []
    assert r.agent_note == "x"


def test_unknown_language_is_not_sent_to_the_model_as_und():
    from assistant.assist import Analysis, _draft_messages
    msgs = _draft_messages("hola", Analysis(summary="s", language="und", search_query="q"), [], None)
    assert "language: und" not in msgs[1]["content"] and "same language as the ticket" in msgs[1]["content"]


def test_classification_uses_its_own_chain():
    drafting = RoutingSDK(ANALYSIS, draft(), classification())
    classifying = RoutingSDK(ANALYSIS, draft(), classification("refund_request"))
    r = assist("I was charged twice", chain(drafting), classify_chain=chain(classifying))
    assert "classify" not in drafting.calls and classifying.calls == ["classify"]
    assert r.classification.classification.category.value == "refund_request"


def test_claimed_actions_detected_in_ukrainian():
    from assistant.assist import CLAIMED_ACTION
    assert CLAIMED_ACTION.search("Ми підтвердили наявність подвійного списання")
    assert CLAIMED_ACTION.search("Наша служба перевірила інформацію")
    assert not CLAIMED_ACTION.search("Ми перевіримо транзакції та повернемо кошти")  # future tense is fine

