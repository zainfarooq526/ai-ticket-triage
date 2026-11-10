"""Domain models shared across the service."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class Category(str, Enum):
    OUTAGE = "outage"
    BUG = "bug"
    BILLING = "billing"
    ACCOUNT_ACCESS = "account_access"
    FEATURE_REQUEST = "feature_request"
    HOW_TO = "how_to"
    OTHER = "other"


class Urgency(str, Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"

    @property
    def rank(self) -> int:
        return ["low", "normal", "high", "urgent"].index(self.value)

    def at_least(self, other: Urgency) -> bool:
        return self.rank >= other.rank


class Sentiment(str, Enum):
    POSITIVE = "positive"
    NEUTRAL = "neutral"
    NEGATIVE = "negative"
    FRUSTRATED = "frustrated"


class ZendeskTicketEvent(BaseModel):
    """Payload sent by the Zendesk webhook (see README for the trigger JSON body).

    Zendesk placeholders always render as strings, so we coerce IDs and split tags.
    """

    ticket_id: int
    subject: str = ""
    description: str = ""
    requester_name: str | None = None
    requester_email: str | None = None
    priority: str | None = None
    url: str | None = None
    tags: list[str] = Field(default_factory=list)

    @field_validator("tags", mode="before")
    @classmethod
    def _split_tags(cls, v: Any) -> list[str]:
        if v is None or v == "":
            return []
        if isinstance(v, str):
            return [t for t in v.replace(",", " ").split() if t]
        return list(v)

    @field_validator("priority", "requester_name", "requester_email", "url", mode="before")
    @classmethod
    def _blank_to_none(cls, v: Any) -> Any:
        return None if v in ("", "-") else v


class Classification(BaseModel):
    category: Category
    urgency: Urgency
    sentiment: Sentiment
    summary: str = Field(max_length=300)
    reasoning: str = Field(max_length=600)
    confidence: float = Field(ge=0, le=1)
    source: Literal["claude", "heuristic", "heuristic_fallback"] = "claude"


class TriageRecord(BaseModel):
    ticket: ZendeskTicketEvent
    classification: Classification
    zendesk_updated: bool = False
    slack_alerted: bool = False
    errors: list[str] = Field(default_factory=list)
    latency_ms: int = 0
    triaged_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
