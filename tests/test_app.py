import json
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.models import Urgency
from app.triage import TriageService
from app.zendesk import compute_signature

from .conftest import FakeClassifier, Recorder, make_classification

SECRET = "test-secret"
PAYLOAD = {
    "ticket_id": "555",
    "subject": "Checkout is down",
    "description": "502 everywhere",
    "requester_name": "Priya",
    "tags": "enterprise vip",
}


def signed(body: bytes, secret: str = SECRET) -> dict:
    ts = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return {
        "X-Zendesk-Webhook-Signature": compute_signature(secret, body, ts),
        "X-Zendesk-Webhook-Signature-Timestamp": ts,
        "Content-Type": "application/json",
    }


@pytest.fixture
def parts():
    zendesk, slack = Recorder(), Recorder()
    service = TriageService(FakeClassifier(), zendesk=zendesk, slack=slack)
    settings = Settings(_env_file=None, zendesk_webhook_secret=SECRET, demo_mode=True)
    with TestClient(create_app(settings, service)) as client:
        yield client, service, zendesk, slack


def test_health(parts):
    client, *_ = parts
    body = client.get("/health").json()
    assert body["status"] == "ok" and body["signature_verification"] is True


def test_webhook_rejects_bad_signature(parts):
    client, *_ = parts
    body = json.dumps(PAYLOAD).encode()
    r = client.post("/webhooks/zendesk", content=body, headers=signed(body, "wrong"))
    assert r.status_code == 401


def test_webhook_end_to_end(parts):
    client, _, zendesk, slack = parts
    body = json.dumps(PAYLOAD).encode()
    r = client.post("/webhooks/zendesk", content=body, headers=signed(body))
    assert r.status_code == 202 and r.json()["status"] == "accepted"

    # TestClient runs background tasks before returning.
    assert zendesk.calls[0][0] == 555
    assert slack.calls[0][0] == 555
    data = client.get("/api/tickets").json()
    assert data["stats"]["total"] == 1 and data["stats"]["alerted"] == 1
    assert data["tickets"][0]["ticket"]["tags"] == ["enterprise", "vip"]


def test_webhook_skips_already_triaged(parts):
    client, _, zendesk, _ = parts
    body = json.dumps({**PAYLOAD, "tags": "ai_triaged"}).encode()
    r = client.post("/webhooks/zendesk", content=body, headers=signed(body))
    assert r.json()["status"] == "skipped"
    assert zendesk.calls == []


def test_webhook_rejects_bad_payload(parts):
    client, *_ = parts
    body = b'{"subject": "no id"}'
    assert client.post("/webhooks/zendesk", content=body, headers=signed(body)).status_code == 422


def test_demo_endpoint(parts):
    client, *_ = parts
    r = client.post("/api/demo")
    assert r.status_code == 200 and r.json()["classification"]["category"] == "outage"


def test_dashboard_served(parts):
    client, *_ = parts
    r = client.get("/")
    assert r.status_code == 200 and "AI Ticket Triage" in r.text


# --- TriageService routing ---------------------------------------------------------------

async def test_low_urgency_not_sent_to_slack(ticket):
    slack = Recorder()
    service = TriageService(FakeClassifier(make_classification(Urgency.LOW)), slack=slack)
    record = await service.process(ticket)
    assert slack.calls == [] and record.slack_alerted is False


async def test_classifier_failure_falls_back(ticket):
    service = TriageService(FakeClassifier(error=TimeoutError("slow")), slack=Recorder())
    record = await service.process(ticket)
    assert record.classification.source == "heuristic_fallback"
    assert record.classification.urgency is Urgency.URGENT
    assert any("classifier" in e for e in record.errors)


async def test_downstream_failure_is_recorded_not_raised(ticket):
    service = TriageService(FakeClassifier(), zendesk=Recorder(fail=True), slack=Recorder())
    record = await service.process(ticket)
    assert record.zendesk_updated is False and record.slack_alerted is True
    assert any(e.startswith("zendesk") for e in record.errors)


async def test_duplicate_delivery_is_claimed_once():
    service = TriageService(FakeClassifier())
    assert service.claim(1) is True
    assert service.claim(1) is False
