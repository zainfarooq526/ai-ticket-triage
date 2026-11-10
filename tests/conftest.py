import pytest

from app.models import Category, Classification, Sentiment, Urgency, ZendeskTicketEvent


@pytest.fixture
def ticket() -> ZendeskTicketEvent:
    return ZendeskTicketEvent(
        ticket_id=123,
        subject="Checkout is down",
        description="Every checkout returns a 502. Nobody can pay.",
        requester_name="Priya",
        url="https://acme.zendesk.com/agent/tickets/123",
    )


def make_classification(urgency: Urgency = Urgency.URGENT) -> Classification:
    return Classification(
        category=Category.OUTAGE,
        urgency=urgency,
        sentiment=Sentiment.FRUSTRATED,
        summary="Checkout is returning 502s for all customers.",
        reasoning="Customer reports all payments failing.",
        confidence=0.92,
    )


class FakeClassifier:
    def __init__(self, result: Classification | None = None, error: Exception | None = None):
        self.result = result or make_classification()
        self.error = error
        self.calls = 0

    async def classify(self, ticket):
        self.calls += 1
        if self.error:
            raise self.error
        return self.result


class Recorder:
    """Stands in for ZendeskClient / SlackNotifier."""

    def __init__(self, fail: bool = False):
        self.fail = fail
        self.calls: list = []

    async def update_ticket(self, ticket_id, c):
        self.calls.append((ticket_id, c))
        if self.fail:
            raise RuntimeError("boom")

    async def notify(self, ticket, c):
        self.calls.append((ticket.ticket_id, c))
        if self.fail:
            raise RuntimeError("boom")
