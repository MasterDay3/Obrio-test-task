"""Deterministic safety net applied after the model.

Rules can only make a ticket MORE cautious (raise priority, force human review, force the safety
category). They never lower anything, so a rule false-positive costs an agent a minute, while a
model false-negative on a suicide note or a chargeback would cost far more.
"""

from __future__ import annotations

import re

from classifier.schema import Category, Classification, Priority

LOW_CONFIDENCE = 0.6
HIGH_AMOUNT = 100.0  # USD/EUR; refunds above this go to a human

_F = re.IGNORECASE | re.UNICODE

SELF_HARM = re.compile(
    r"suicid|kill myself|end my life|end it all|no point (in )?living|point of living|don'?t want to live|"
    r"self[- ]harm|hurt myself|не хочу жити|покінчити з|суїцид|не хочу жить|покончить с|"
    r"quitarme la vida|no quiero vivir|umbringen|nicht mehr leben|nie chcę żyć", _F)
VIOLENCE = re.compile(
    r"\b(find|hunt) (her|him|you|them) (down )?and\b|make (her|him|them) pay|\bkill (her|him|you|them)\b|"
    r"i will hurt|знайду (її|його|тебе)|найду (её|его|тебя)", _F)
LEGAL = re.compile(
    r"charge ?back|(bank|card|payment) dispute|open (a |the )?dispute|dispute (the|this|a|my) (charge|payment|transaction)|call my bank|contact my bank|lawyer|attorney|\bsue\b|lawsuit|\bcourt\b|\bFTC\b|regulator|consumer protection|ombudsman|"
    r"legal action|юрист|адвокат|\bсуд\b|чарджбек|abogad|demanda|anwalt|klage|verbraucherschutz|prawnik", _F)
PRIVACY = re.compile(
    r"gdpr|dsgvo|rgpd|ccpa|personal data|delete (my )?(account|data)|erase my data|"
    r"видал\w* (мій |мої )?(акаунт|дан)|удал\w* (мой |мои )?(аккаунт|данн)|persönliche daten|datos personales", _F)
TAKEOVER = re.compile(
    r"someone (else )?(logged|log) in|someone (has )?(accessed|hacked)|\bhacked\b|account (was )?stolen|"
    r"зламали|взломали|unauthori[sz]ed (access|login)", _F)
REPEAT = re.compile(
    r"\b(second|third|fourth|fifth|[2-9](nd|rd|th)?|\d{2,}(st|nd|rd|th)?) time\b|already (wrote|written|contacted|asked|emailed)|"
    r"втретє|вдруге|вже писав|вже писала|уже писал|третий раз|третій раз", _F)
MINOR = re.compile(
    r"\b(1[0-7]|[5-9])[- ]?(year|yr)s?[- ]old\b|my (son|daughter|kid|child)\b|моя донька|мій син|моя дочь|мой сын", _F)
INJECTION = re.compile(
    r"ignore (all |any )?(the )?(previous|prior|above) (instructions|rules)|disregard (your|the) (instructions|rules)|"
    r"you are now|system prompt|classify this (ticket )?as|ігноруй (попередні )?інструкції|игнорируй", _F)
_NUM = r"\d{1,3}(?:[ ,.]\d{3})+(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?"
AMOUNT = re.compile(rf"([$€£])\s?({_NUM})|({_NUM})\s?(\$|€|£|usd|eur|euros?|gbp|грн|uah)(?!\w)", _F)
# Rough rates, used only to compare against HIGH_AMOUNT; not for anything customer-facing.
TO_USD = {"$": 1.0, "usd": 1.0, "€": 1.1, "eur": 1.1, "euro": 1.1, "euros": 1.1, "£": 1.3, "gbp": 1.3,
          "грн": 1 / 41, "uah": 1 / 41}

_ORDER = [Priority.P1, Priority.P2, Priority.P3, Priority.P4]


def _raise_to(current: Priority, floor: Priority) -> Priority:
    return min(current, floor, key=_ORDER.index)


def _parse_number(s: str) -> float:
    """'1,299' / '1.299,00' / '2 000' / '19.99' -> float. A 3-digit group after a separator means thousands."""
    s = s.replace(" ", "")
    if "," in s and "." in s:
        dec = "," if s.rfind(",") > s.rfind(".") else "."
        return float(s.replace("." if dec == "," else ",", "").replace(dec, "."))
    for sep in ",.":
        if sep in s:
            parts = s.split(sep)
            return float("".join(parts)) if len(parts) > 2 or len(parts[-1]) == 3 else float(s.replace(sep, "."))
    return float(s)


def max_amount(text: str) -> float:
    """Largest money amount in the text, converted to approximate USD."""
    values = [_parse_number(n1 or n2) * TO_USD[(c1 or c2).lower()] for c1, n1, n2, c2 in AMOUNT.findall(text)]
    return max(values, default=0.0)


def apply_rules(text: str, c: Classification) -> tuple[Classification, list[str]]:
    c = c.model_copy(deep=True)
    hits: list[str] = []

    def flag(name: str, priority: Priority | None = None, human: bool = True):
        hits.append(name)
        if priority:
            c.priority = _raise_to(c.priority, priority)
        if human:
            c.needs_human = True

    if SELF_HARM.search(text) or VIOLENCE.search(text):
        if c.category != Category.safety_crisis:
            c.secondary_categories = [c.category, *[s for s in c.secondary_categories if s != c.category]]
            c.category = Category.safety_crisis
        flag("safety_keywords", Priority.P1)
    if LEGAL.search(text):
        flag("legal_threat", Priority.P1)
    if PRIVACY.search(text):
        flag("privacy_request", Priority.P2)
    if TAKEOVER.search(text):
        flag("account_takeover", Priority.P1)
    if REPEAT.search(text):
        flag("repeat_contact")
    if INJECTION.search(text):
        flag("possible_prompt_injection")

    # Money rules also apply when billing/refund is secondary, or the ticket became legal (e.g. "refund or I call my
    # bank"): seen in the UI test, where a $180 purchase by a minor lost both flags after being routed to legal.
    money_cats = {Category.refund_request, Category.billing_subscription, Category.legal_privacy}
    money = c.category in money_cats or bool(money_cats & set(c.secondary_categories))
    if money and max_amount(text) > HIGH_AMOUNT:
        flag("high_amount")
    if money and MINOR.search(text):
        flag("minor_involved")

    # Category-level policy: these are never auto-resolved regardless of what the model said.
    if c.category == Category.safety_crisis:
        flag("category_safety", Priority.P1)
    if c.category == Category.legal_privacy:
        flag("category_legal")
    if c.confidence < LOW_CONFIDENCE:
        flag("low_confidence")

    return c, list(dict.fromkeys(hits))
