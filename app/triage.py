"""Orchestrates classify -> update Zendesk -> alert Slack, and keeps recent results."""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from typing import Protocol

from app.classifier import Classifier, HeuristicClassifier
from app.models import Classification, TriageRecord, Urgency, ZendeskTicketEvent

log = logging.getLogger(__name__)


class TicketUpdater(Protocol):
    async def update_ticket(self, ticket_id: int, c: Classification) -> None: ...


class Notifier(Protocol):
    async def notify(self, ticket: ZendeskTicketEvent, c: Classification) -> None: ...


class TriageStore:
    """In-memory ring buffer of recent triage results (powers the dashboard)."""

    def __init__(self, maxlen: int = 200):
        self._items: deque[TriageRecord] = deque(maxlen=maxlen)
        self.total = 0

    def add(self, record: TriageRecord) -> None:
        self._items.appendleft(record)
        self.total += 1

    def recent(self, limit: int = 50) -> list[TriageRecord]:
        return list(self._items)[:limit]

    def stats(self) -> dict:
        items = list(self._items)
        by_urgency = {u.value: 0 for u in Urgency}
        by_category: dict[str, int] = {}
        for r in items:
            by_urgency[r.classification.urgency.value] += 1
            cat = r.classification.category.value
            by_category[cat] = by_category.get(cat, 0) + 1
        return {
            "total": self.total,
            "alerted": sum(r.slack_alerted for r in items),
            "by_urgency": by_urgency,
            "by_category": dict(sorted(by_category.items(), key=lambda kv: -kv[1])),
            "avg_latency_ms": round(sum(r.latency_ms for r in items) / len(items)) if items else 0,
        }


class TriageService:
    def __init__(
        self,
        classifier: Classifier,
        *,
        zendesk: TicketUpdater | None = None,
        slack: Notifier | None = None,
        store: TriageStore | None = None,
        alert_min_urgency: Urgency = Urgency.HIGH,
        fallback: Classifier | None = None,
    ):
        self.classifier = classifier
        self.fallback = fallback or HeuristicClassifier(source="heuristic_fallback")
        self.zendesk = zendesk
        self.slack = slack
        self.store = store or TriageStore()
        self.alert_min_urgency = alert_min_urgency
        self._in_flight: set[int] = set()

    def is_in_flight(self, ticket_id: int) -> bool:
        return ticket_id in self._in_flight

    def claim(self, ticket_id: int) -> bool:
        """Reserve a ticket so duplicate webhook deliveries are dropped. False if already claimed."""
        if ticket_id in self._in_flight:
            return False
        self._in_flight.add(ticket_id)
        return True

    async def process(self, ticket: ZendeskTicketEvent) -> TriageRecord:
        self._in_flight.add(ticket.ticket_id)
        start = time.perf_counter()
        errors: list[str] = []
        try:
            try:
                classification = await self.classifier.classify(ticket)
            except Exception as exc:  # never drop a ticket because the LLM hiccuped
                log.exception("Classifier failed for ticket %s; using fallback", ticket.ticket_id)
                errors.append(f"classifier: {type(exc).__name__}: {exc}"[:200])
                classification = await self.fallback.classify(ticket)

            should_alert = self.slack is not None and classification.urgency.at_least(self.alert_min_urgency)
            zd_task = (
                self._run("zendesk", self.zendesk.update_ticket(ticket.ticket_id, classification))
                if self.zendesk
                else None
            )
            sl_task = self._run("slack", self.slack.notify(ticket, classification)) if should_alert else None
            results = await asyncio.gather(*(t for t in (zd_task, sl_task) if t is not None))
            it = iter(results)
            zendesk_ok = next(it) if zd_task else (False, None)
            slack_ok = next(it) if sl_task else (False, None)
            errors += [e for _, e in (zendesk_ok, slack_ok) if e]

            record = TriageRecord(
                ticket=ticket,
                classification=classification,
                zendesk_updated=zendesk_ok[0],
                slack_alerted=slack_ok[0],
                errors=errors,
                latency_ms=int((time.perf_counter() - start) * 1000),
            )
            self.store.add(record)
            log.info(
                "Triaged #%s category=%s urgency=%s slack=%s zendesk=%s in %sms",
                ticket.ticket_id, classification.category.value, classification.urgency.value,
                record.slack_alerted, record.zendesk_updated, record.latency_ms,
            )
            return record
        finally:
            self._in_flight.discard(ticket.ticket_id)

    @staticmethod
    async def _run(name: str, coro) -> tuple[bool, str | None]:
        try:
            await coro
            return True, None
        except Exception as exc:
            log.exception("%s step failed", name)
            return False, f"{name}: {type(exc).__name__}: {exc}"[:200]
