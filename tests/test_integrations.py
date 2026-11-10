import json
from datetime import datetime, timedelta, timezone

import httpx

from app.models import Urgency
from app.slack import SlackNotifier, build_message
from app.zendesk import ZendeskClient, compute_signature, verify_signature

from .conftest import make_classification


def mock_client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


SECRET = "dGhpc19zZWNyZXQ="
BODY = b'{"ticket_id": "1"}'


def test_signature_roundtrip():
    ts = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    sig = compute_signature(SECRET, BODY, ts)
    assert verify_signature(SECRET, BODY, sig, ts)


def test_signature_rejects_tampered_body():
    ts = datetime.now(timezone.utc).isoformat()
    sig = compute_signature(SECRET, BODY, ts)
    assert not verify_signature(SECRET, b'{"ticket_id": "2"}', sig, ts)


def test_signature_rejects_stale_timestamp():
    ts = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    sig = compute_signature(SECRET, BODY, ts)
    assert not verify_signature(SECRET, BODY, sig, ts, tolerance_seconds=300)


def test_signature_rejects_missing_headers():
    assert not verify_signature(SECRET, BODY, None, None)
    assert not verify_signature(SECRET, BODY, "abc", "not-a-date")


async def test_zendesk_update_payload():
    seen = {}

    def handler(request: httpx.Request):
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"ticket": {}})

    client = ZendeskClient("acme", "bot@acme.com", "tok", client=mock_client(handler))
    await client.update_ticket(42, make_classification())

    assert seen["url"] == "https://acme.zendesk.com/api/v2/tickets/42.json"
    assert seen["auth"].startswith("Basic ")
    t = seen["body"]["ticket"]
    assert t["priority"] == "urgent"
    assert "ai_triaged" in t["additional_tags"] and "ai_category_outage" in t["additional_tags"]
    assert t["comment"]["public"] is False


async def test_zendesk_retries_on_429():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, headers={"Retry-After": "0"})
        return httpx.Response(200, json={})

    client = ZendeskClient("acme", "e", "t", client=mock_client(handler))
    await client.update_ticket(1, make_classification())
    assert calls["n"] == 2


def test_slack_message_shape(ticket):
    msg = build_message(ticket, make_classification(Urgency.URGENT))
    assert "URGENT" in msg["text"]
    kinds = [b["type"] for b in msg["blocks"]]
    assert kinds == ["header", "section", "section", "context", "actions"]
    assert msg["blocks"][-1]["elements"][0]["url"] == ticket.url


def test_slack_escapes_customer_text(ticket):
    ticket.subject = "<!channel> help"
    msg = build_message(ticket, make_classification())
    assert "<!channel>" not in json.dumps(msg)


async def test_slack_posts_to_webhook(ticket):
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, text="ok")

    notifier = SlackNotifier("https://hooks.slack.com/x", client=mock_client(handler))
    await notifier.notify(ticket, make_classification())
    assert seen["body"]["blocks"][0]["type"] == "header"
