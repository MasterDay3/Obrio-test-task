"""Taxonomy and output schema. Categories map to the team that owns the ticket, not to its topic."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field, field_validator


class Category(StrEnum):
    billing_subscription = "billing_subscription"
    refund_request = "refund_request"
    technical_bug = "technical_bug"
    account_access = "account_access"
    expert_complaint = "expert_complaint"
    reading_content = "reading_content"
    feedback_feature_request = "feedback_feature_request"
    legal_privacy = "legal_privacy"
    safety_crisis = "safety_crisis"
    spam_other = "spam_other"
    # Never offered to the model: set by code when every model failed.
    unclassified = "unclassified"


class Priority(StrEnum):
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"
    P4 = "P4"


class Sentiment(StrEnum):
    positive = "positive"
    neutral = "neutral"
    negative = "negative"
    angry = "angry"


ROUTING = {
    Category.billing_subscription: "Billing",
    Category.refund_request: "Billing (refunds)",
    Category.technical_bug: "Tech support",
    Category.account_access: "Tech support (accounts)",
    Category.expert_complaint: "Expert quality / Trust & Safety",
    Category.reading_content: "Content team",
    Category.feedback_feature_request: "Product (feedback inbox)",
    Category.legal_privacy: "Legal & Privacy",
    Category.safety_crisis: "Trust & Safety (urgent)",
    Category.spam_other: "Auto-close / ask for details",
    Category.unclassified: "Manual triage queue",
}


class Classification(BaseModel):
    """What the model must return."""

    category: Category
    secondary_categories: list[Category] = Field(default_factory=list)
    priority: Priority
    language: str = Field(description="ISO 639-1 code of the ticket language")
    sentiment: Sentiment
    next_step: str = Field(description="One concrete action for the support agent")
    confidence: float = Field(ge=0.0, le=1.0)
    needs_human: bool
    reason: str

    @field_validator("secondary_categories", mode="before")
    @classmethod
    def _drop_unknown_secondary(cls, v):
        # Secondary labels are advisory; an invented one should not fail the whole ticket.
        valid = {c.value for c in Category}
        return [c for c in (v or []) if c in valid]

    @field_validator("confidence", mode="before")
    @classmethod
    def _percent_to_fraction(cls, v):
        # Some models answer 95 instead of 0.95; rescale instead of failing the whole ticket.
        return v / 100 if isinstance(v, (int, float)) and 1 < v <= 100 else v

    @field_validator("language", mode="before")
    @classmethod
    def _lower_lang(cls, v):
        return str(v).strip().lower()[:5]


class TicketResult(BaseModel):
    """Classification plus what the pipeline did around it (rules, model, cost)."""

    classification: Classification
    raw_classification: Classification | None = None  # model output before rules
    team: str
    rule_hits: list[str] = Field(default_factory=list)
    model: str | None = None
    prompt_version: str
    latency_s: float = 0.0
    cost_usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    cached_input_tokens: int = 0  # provider prompt-cache hits, billed at the cached rate
    errors: list[str] = Field(default_factory=list)
    cached: bool = False
