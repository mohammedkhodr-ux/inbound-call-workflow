"""Tests for the inbound call workflow's pure helpers and orchestration contract."""

from __future__ import annotations

import mistralai.workflows as workflows

from workflows.activities.servicenow import analyze_tickets_and_sentiment
from workflows.inbound_call import InboundCallWorkflow, _resolve_ticket
from workflows.models import CallSummary, Ticket, TicketContext


def _ticket(number: str = "INC001", sentiment: str | None = None) -> Ticket:
    return Ticket(
        sys_id="sysid-1",
        number=number,
        short_description="Permit application",
        state="New",
        opened_at="2026-09-01",
        priority="Low",
        sentiment=sentiment,
    )


def _summary(ticket_number: str = "", outcome: str = "resolved") -> CallSummary:
    return CallSummary(
        topic="Permit application status",
        resolution="Confirmed approval to the citizen.",
        outcome=outcome,
        ticket_number=ticket_number,
    )


class TestResolveTicket:
    def test_uses_summary_ticket_number(self):
        context = TicketContext(tickets=[_ticket("INC001")])
        ticket = _resolve_ticket(_summary(ticket_number="INC001"), context)
        assert ticket == {"sys_id": "sysid-1", "number": "INC001"}

    def test_falls_back_to_single_open_ticket(self):
        context = TicketContext(tickets=[_ticket("INC001")])
        ticket = _resolve_ticket(_summary(), context)
        assert ticket == {"sys_id": "sysid-1", "number": "INC001"}

    def test_no_ticket_when_summary_empty_and_multiple_open(self):
        context = TicketContext(tickets=[_ticket("INC001"), _ticket("INC002")])
        assert _resolve_ticket(_summary(), context) == {"sys_id": "", "number": ""}

    def test_summary_number_without_sys_id(self):
        context = TicketContext(tickets=[])
        assert _resolve_ticket(_summary(ticket_number="INC009"), context) == {
            "sys_id": "",
            "number": "INC009",
        }


class TestTicketContext:
    async def test_negative_sentiment(self):
        tickets = [_ticket(sentiment="negative"), _ticket(sentiment="frustrated")]
        context = await analyze_tickets_and_sentiment("Ahmed", tickets)
        assert context.overall_sentiment == "negative"
        assert "INC001" in context.summary

    async def test_no_tickets(self):
        context = await analyze_tickets_and_sentiment("Ahmed", [])
        assert context.overall_sentiment == "neutral"
        assert "no open tickets" in context.summary


class TestWorkflowRegistration:
    def test_workflow_definition(self):
        spec = workflows.get_workflow_definition(InboundCallWorkflow)
        assert spec.name == "dda-inbound-call"
        assert spec.display_name == "DDA Inbound Call"

    def test_input_model(self):
        from workflows.models import CallInput

        data = CallInput(call_id="c1", ani="+971501234567")
        assert data.language == "en"
        assert data.genesys_conversation_id is None
