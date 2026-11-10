from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.classifier import TRIAGE_TOOL, ClaudeClassifier, HeuristicClassifier, render_ticket
from app.models import Category, Sentiment, Urgency, ZendeskTicketEvent
from app.samples import SAMPLE_TICKETS


class FakeMessages:
    def __init__(self, content):
        self.content = content
        self.kwargs = None

    async def create(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(content=self.content)


def fake_client(tool_input):
    return SimpleNamespace(messages=FakeMessages([SimpleNamespace(type="tool_use", input=tool_input)]))


async def test_claude_classifier_parses_tool_call(ticket):
    client = fake_client({
        "category": "outage", "urgency": "urgent", "sentiment": "frustrated",
        "summary": "Checkout down", "reasoning": "502 on every checkout", "confidence": 0.9,
    })
    result = await ClaudeClassifier("key", "claude-test", client=client).classify(ticket)

    assert result.category is Category.OUTAGE
    assert result.urgency is Urgency.URGENT
    assert result.source == "claude"
    sent = client.messages.kwargs
    assert sent["tool_choice"] == {"type": "tool", "name": "record_triage"}
    assert sent["tools"] == [TRIAGE_TOOL]
    assert "<ticket>" in sent["messages"][0]["content"]


async def test_claude_classifier_rejects_invalid_enum(ticket):
    client = fake_client({
        "category": "nonsense", "urgency": "urgent", "sentiment": "neutral",
        "summary": "x", "reasoning": "y", "confidence": 0.5,
    })
    with pytest.raises(ValidationError):
        await ClaudeClassifier("key", "m", client=client).classify(ticket)


async def test_claude_classifier_requires_tool_use(ticket):
    client = SimpleNamespace(messages=FakeMessages([SimpleNamespace(type="text", text="hi")]))
    with pytest.raises(ValueError):
        await ClaudeClassifier("key", "m", client=client).classify(ticket)


def test_render_ticket_truncates_long_descriptions():
    t = ZendeskTicketEvent(ticket_id=1, subject="s", description="a" * 20000)
    out = render_ticket(t)
    assert "[...truncated]" in out and len(out) < 9000


@pytest.mark.parametrize(
    "idx,category,urgency",
    [
        (0, Category.OUTAGE, Urgency.URGENT),
        (1, Category.BILLING, Urgency.HIGH),
        (2, Category.FEATURE_REQUEST, Urgency.LOW),
        (3, Category.ACCOUNT_ACCESS, Urgency.HIGH),
        (4, Category.BUG, Urgency.NORMAL),
        (5, Category.HOW_TO, Urgency.LOW),
    ],
)
async def test_heuristic_on_samples(idx, category, urgency):
    result = await HeuristicClassifier().classify(ZendeskTicketEvent.model_validate(SAMPLE_TICKETS[idx]))
    assert result.category is category
    assert result.urgency is urgency
    assert result.source == "heuristic"


async def test_heuristic_detects_frustration():
    t = ZendeskTicketEvent(ticket_id=1, subject="Login broken", description="This is unacceptable!!!")
    assert (await HeuristicClassifier().classify(t)).sentiment is Sentiment.FRUSTRATED
