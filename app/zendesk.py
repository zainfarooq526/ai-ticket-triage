"""Zendesk: webhook signature verification and ticket updates."""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
from datetime import datetime, timezone

import httpx

from app.http import request_with_retry
from app.models import Classification

log = logging.getLogger(__name__)

TRIAGED_TAG = "ai_triaged"


def compute_signature(secret: str, body: bytes, timestamp: str) -> str:
    digest = hmac.new(secret.encode(), timestamp.encode() + body, hashlib.sha256).digest()
    return base64.b64encode(digest).decode()


def verify_signature(
    secret: str,
    body: bytes,
    signature: str | None,
    timestamp: str | None,
    tolerance_seconds: int = 300,
    now: datetime | None = None,
) -> bool:
    """Verify Zendesk's X-Zendesk-Webhook-Signature header.

    Zendesk signs base64(HMAC-SHA256(secret, timestamp + raw_body)). We also reject
    stale timestamps to blunt replay attacks.
    """
    if not signature or not timestamp:
        return False
    try:
        sent = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError:
        return False
    if sent.tzinfo is None:
        sent = sent.replace(tzinfo=timezone.utc)
    now = now or datetime.now(timezone.utc)
    if abs((now - sent).total_seconds()) > tolerance_seconds:
        return False
    expected = compute_signature(secret, body, timestamp)
    return hmac.compare_digest(expected, signature)


def build_internal_note(c: Classification) -> str:
    return (
        "🤖 AI triage\n"
        f"Category: {c.category.value}\n"
        f"Urgency: {c.urgency.value}\n"
        f"Sentiment: {c.sentiment.value}\n"
        f"Confidence: {c.confidence:.0%} ({c.source})\n\n"
        f"Summary: {c.summary}\n"
        f"Why: {c.reasoning}"
    )


class ZendeskClient:
    def __init__(self, subdomain: str, email: str, api_token: str, client: httpx.AsyncClient | None = None):
        self.base_url = f"https://{subdomain}.zendesk.com/api/v2"
        self.client = client or httpx.AsyncClient(timeout=10)
        self.auth = (f"{email}/token", api_token)

    def build_update(self, c: Classification) -> dict:
        return {
            "ticket": {
                "priority": c.urgency.value,  # Zendesk priorities: low/normal/high/urgent
                # additional_tags appends rather than replacing the ticket's existing tags.
                # The ai_triaged tag also stops our own update from re-firing the trigger.
                "additional_tags": [
                    TRIAGED_TAG,
                    f"ai_category_{c.category.value}",
                    f"ai_urgency_{c.urgency.value}",
                ],
                "comment": {"body": build_internal_note(c), "public": False},
            }
        }

    async def update_ticket(self, ticket_id: int, c: Classification) -> None:
        resp = await request_with_retry(
            self.client,
            "PUT",
            f"{self.base_url}/tickets/{ticket_id}.json",
            json=self.build_update(c),
            auth=self.auth,
        )
        resp.raise_for_status()
        log.info("Updated Zendesk ticket %s", ticket_id)

    async def aclose(self) -> None:
        await self.client.aclose()
