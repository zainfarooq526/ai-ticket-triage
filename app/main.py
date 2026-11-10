"""FastAPI entrypoint: Zendesk webhook receiver, JSON API and dashboard."""

from __future__ import annotations

import json
import logging
import random
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import ValidationError

from app import __version__
from app.classifier import ClaudeClassifier, HeuristicClassifier
from app.config import Settings, get_settings
from app.models import ZendeskTicketEvent
from app.samples import SAMPLE_TICKETS
from app.slack import SlackNotifier
from app.triage import TriageService
from app.zendesk import TRIAGED_TAG, ZendeskClient, verify_signature

log = logging.getLogger("triage")
STATIC_DIR = Path(__file__).parent / "static"


def build_service(settings: Settings) -> TriageService:
    if settings.anthropic_api_key:
        classifier = ClaudeClassifier(
            settings.anthropic_api_key, settings.anthropic_model, settings.classifier_timeout_seconds
        )
    else:
        log.warning("ANTHROPIC_API_KEY not set: using the offline heuristic classifier")
        classifier = HeuristicClassifier()

    zendesk = None
    if settings.zendesk_enabled:
        zendesk = ZendeskClient(settings.zendesk_subdomain, settings.zendesk_email, settings.zendesk_api_token)
    else:
        log.warning("Zendesk credentials not set: tickets will not be updated")

    slack = SlackNotifier(settings.slack_webhook_url) if settings.slack_webhook_url else None
    if slack is None:
        log.warning("SLACK_WEBHOOK_URL not set: urgent tickets will not be posted to Slack")

    return TriageService(classifier, zendesk=zendesk, slack=slack, alert_min_urgency=settings.slack_alert_min_urgency)


def create_app(settings: Settings | None = None, service: TriageService | None = None) -> FastAPI:
    settings = settings or get_settings()
    logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.service = service or build_service(settings)
        yield
        for client in (app.state.service.zendesk, app.state.service.slack):
            if client is not None and hasattr(client, "aclose"):
                await client.aclose()

    app = FastAPI(title="AI Ticket Triage", version=__version__, lifespan=lifespan)
    app.state.settings = settings

    def svc(request: Request) -> TriageService:
        return request.app.state.service

    @app.get("/health")
    async def health(request: Request):
        s = svc(request)
        return {
            "status": "ok",
            "version": __version__,
            "classifier": type(s.classifier).__name__,
            "zendesk": s.zendesk is not None,
            "slack": s.slack is not None,
            "signature_verification": bool(settings.zendesk_webhook_secret),
        }

    @app.post("/webhooks/zendesk", status_code=202)
    async def zendesk_webhook(request: Request, background: BackgroundTasks):
        body = await request.body()
        if settings.zendesk_webhook_secret:
            ok = verify_signature(
                settings.zendesk_webhook_secret,
                body,
                request.headers.get("X-Zendesk-Webhook-Signature"),
                request.headers.get("X-Zendesk-Webhook-Signature-Timestamp"),
                settings.signature_tolerance_seconds,
            )
            if not ok:
                raise HTTPException(status_code=401, detail="Invalid webhook signature")

        try:
            ticket = ZendeskTicketEvent.model_validate(json.loads(body or b"{}"))
        except (json.JSONDecodeError, ValidationError) as exc:
            raise HTTPException(status_code=422, detail=f"Invalid payload: {exc}") from exc

        if TRIAGED_TAG in ticket.tags:
            return {"status": "skipped", "reason": "already triaged", "ticket_id": ticket.ticket_id}

        service = svc(request)
        if not service.claim(ticket.ticket_id):
            return {"status": "skipped", "reason": "already processing", "ticket_id": ticket.ticket_id}

        # Respond fast (Zendesk times out after ~12s) and do the LLM + API work after.
        background.add_task(service.process, ticket)
        return {"status": "accepted", "ticket_id": ticket.ticket_id}

    @app.get("/api/tickets")
    async def list_tickets(request: Request, limit: int = 50):
        s = svc(request)
        return {
            "stats": s.store.stats(),
            "tickets": [r.model_dump(mode="json") for r in s.store.recent(min(limit, 200))],
        }

    @app.post("/api/demo")
    async def demo(request: Request):
        """Triage a random sample ticket synchronously (for the dashboard demo button)."""
        if not settings.demo_mode:
            raise HTTPException(status_code=404, detail="Demo mode disabled")
        sample = dict(random.choice(SAMPLE_TICKETS))
        sample["ticket_id"] = random.randint(20000, 99999)
        record = await svc(request).process(ZendeskTicketEvent.model_validate(sample))
        return record.model_dump(mode="json")

    @app.get("/", include_in_schema=False)
    async def dashboard():
        return FileResponse(STATIC_DIR / "dashboard.html")

    return app


app = create_app()
