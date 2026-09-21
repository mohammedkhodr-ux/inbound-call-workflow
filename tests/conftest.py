"""Shared test fixtures: stub every external system and the Mistral LLM calls."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


class ServiceNowStub:
    def __init__(self):
        self.tickets: dict[str, dict] = {}
        self.closed: list[str] = []
        self.work_notes: list[tuple[str, str]] = []
        self.created: list[str] = []
        self.counter = 0

    def add_ticket(self, number: str, description: str, state: str = "1", priority: str = "4") -> str:
        self.counter += 1
        sys_id = f"sysid-{self.counter}"
        self.tickets[number] = {
            "sys_id": sys_id,
            "number": number,
            "short_description": description,
            "state": state,
            "priority": priority,
            "opened_at": "2026-09-01 09:00:00",
            "work_notes": "",
        }
        return sys_id


@pytest.fixture
def servicenow_stub():
    return ServiceNowStub()


@pytest.fixture
def mock_servicenow(monkeypatch, servicenow_stub):
    """Patch httpx calls inside servicenow.py to use the in-memory stub."""
    from integrations import servicenow

    async def fake_fetch(caller_uuid: str):
        from integrations.servicenow import ServiceNowQueryResult, ServiceNowTicket

        tickets = [ServiceNowTicket.model_validate(t) for t in servicenow_stub.tickets.values()]
        return ServiceNowQueryResult(caller_uuid=caller_uuid, tickets=tickets)

    async def fake_create(caller_uuid: str, description: str, priority: str = "4"):
        from integrations.servicenow import ServiceNowTicket

        servicenow_stub.counter += 1
        ticket = ServiceNowTicket(
            sys_id=f"sysid-{servicenow_stub.counter}",
            number=f"INC{1000 + servicenow_stub.counter}",
            short_description=description[:160],
            state="1",
            priority=priority,
        )
        servicenow_stub.created.append(ticket.number)
        return ticket

    async def fake_update(sys_id: str, work_note: str):
        servicenow_stub.work_notes.append((sys_id, work_note))

    async def fake_close(sys_id: str, resolution_note: str, resolution_code: str = "Resolved by AI"):
        servicenow_stub.closed.append(sys_id)

    monkeypatch.setattr(servicenow, "fetch_caller_tickets", fake_fetch)
    monkeypatch.setattr(servicenow, "create_ticket", fake_create)
    monkeypatch.setattr(servicenow, "update_ticket", fake_update)
    monkeypatch.setattr(servicenow, "close_ticket", fake_close)
    return servicenow_stub


@pytest.fixture
def mock_llm(monkeypatch):
    """Stub the Mistral chat-parse activity used by analyse_intent / summarise_call."""
    import mistralai.workflows.plugins.mistralai as workflows_mistralai

    async def fake_parse(model_class, request):
        if model_class.__name__ == "CallerIntent":
            return model_class(
                category="new_request",
                related_ticket_number="",
                priority="4",
                request_summary="Citizen needs help with a service.",
            )
        if model_class.__name__ == "CallSummary":
            return model_class(
                summary="Thank you for calling Digital Dubai Authority. We addressed your request.",
                actions_taken=["Ticket created"],
                outcome="resolved",
            )
        raise AssertionError(f"Unexpected model {model_class}")

    monkeypatch.setattr(workflows_mistralai, "chat_parse_to_model", fake_parse)
    return fake_parse
