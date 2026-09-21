"""Unit tests for the ServiceNow integration logic."""

from __future__ import annotations

from integrations.servicenow import (
    ServiceNowQueryResult,
    ServiceNowTicket,
    _instance_url,
    _sentiment_from_records,
    _state_label,
    build_ticket_context,
)


def _ticket(number: str = "INC001", description: str = "desc", state: str = "1") -> ServiceNowTicket:
    return ServiceNowTicket(sys_id="sysid-1", number=number, short_description=description, state=state, priority="4")


class TestInstanceUrl:
    def test_plain_instance_name(self):
        assert _instance_url("dda") == "https://dda.service-now.com"

    def test_full_url_passthrough(self):
        assert _instance_url("https://dda.example.com/") == "https://dda.example.com"


class TestSentiment:
    def test_negative(self):
        tickets = [_ticket(description="Complaint about delay"), _ticket(description="Broken portal")]
        assert _sentiment_from_records(tickets) == "negative"

    def test_positive(self):
        tickets = [_ticket(description="Issue resolved, thanks"), _ticket(description="Request approved")]
        assert _sentiment_from_records(tickets) == "positive"

    def test_neutral_when_empty(self):
        assert _sentiment_from_records([]) == "neutral"

    def test_neutral_when_balanced(self):
        tickets = [_ticket(description="delay complaint"), _ticket(description="resolved thanks")]
        assert _sentiment_from_records(tickets) == "neutral"


class TestStateLabel:
    def test_known_states(self):
        assert _state_label("1") == "New"
        assert _state_label("2") == "In Progress"
        assert _state_label("7") == "Closed"

    def test_unknown_state_passthrough(self):
        assert _state_label("99") == "99"


class TestBuildTicketContext:
    async def test_splits_open_and_closed(self):
        result = ServiceNowQueryResult(
            caller_uuid="uuid-1",
            tickets=[
                _ticket(number="INC001", state="1"),
                _ticket(number="INC002", state="2"),
                _ticket(number="INC003", state="7"),
            ],
        )
        context = await build_ticket_context(result)
        assert [t.number for t in context.open_tickets] == ["INC001", "INC002"]
        assert [t.number for t in context.recent_closed_tickets] == ["INC003"]
        assert "INC001" in context.summary
        assert "INC003" in context.summary

    async def test_empty_history(self):
        context = await build_ticket_context(ServiceNowQueryResult(caller_uuid="uuid-1", tickets=[]))
        assert context.open_tickets == []
        assert context.summary == "No prior tickets on record for this caller."
        assert context.overall_sentiment == "neutral"
