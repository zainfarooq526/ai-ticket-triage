"""Slack alerts via an Incoming Webhook, formatted with Block Kit."""

from __future__ import annotations

import logging

import httpx

from app.http import request_with_retry
from app.models import Classification, Urgency, ZendeskTicketEvent

log = logging.getLogger(__name__)

URGENCY_EMOJI = {
    Urgency.URGENT: ":rotating_light:",
    Urgency.HIGH: ":warning:",
    Urgency.NORMAL: ":large_blue_circle:",
    Urgency.LOW: ":white_circle:",
}


def _esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def build_message(ticket: ZendeskTicketEvent, c: Classification) -> dict:
    emoji = URGENCY_EMOJI[c.urgency]
    title = f"{emoji} {c.urgency.value.upper()} · #{ticket.ticket_id} {_esc(ticket.subject)[:120]}"
    blocks: list[dict] = [
        {"type": "header", "text": {"type": "plain_text", "text": title[:150], "emoji": True}},
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*{_esc(c.summary)}*"}},
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Category*\n{c.category.value.replace('_', ' ')}"},
                {"type": "mrkdwn", "text": f"*Sentiment*\n{c.sentiment.value}"},
                {"type": "mrkdwn", "text": f"*Requester*\n{_esc(ticket.requester_name or 'unknown')}"},
                {"type": "mrkdwn", "text": f"*Confidence*\n{c.confidence:.0%} ({c.source})"},
            ],
        },
        {"type": "context", "elements": [{"type": "mrkdwn", "text": f"_Why:_ {_esc(c.reasoning)}"}]},
    ]
    if ticket.url:
        blocks.append(
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Open in Zendesk"},
                        "url": ticket.url,
                        "style": "danger" if c.urgency is Urgency.URGENT else "primary",
                    }
                ],
            }
        )
    return {"text": title, "blocks": blocks}  # `text` is the notification fallback


class SlackNotifier:
    def __init__(self, webhook_url: str, client: httpx.AsyncClient | None = None):
        self.webhook_url = webhook_url
        self.client = client or httpx.AsyncClient(timeout=10)

    async def notify(self, ticket: ZendeskTicketEvent, c: Classification) -> None:
        resp = await request_with_retry(self.client, "POST", self.webhook_url, json=build_message(ticket, c))
        resp.raise_for_status()
        log.info("Posted Slack alert for ticket %s", ticket.ticket_id)

    async def aclose(self) -> None:
        await self.client.aclose()
