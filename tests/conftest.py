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
def mock_uaepass(monkeypatch):
    """Patch the UAEPASS activity to return a verified profile for any phone number."""
    from workflows.activities import uaepass

    async def fake_auth(phone_number: str):
        from workflows.models import CitizenIdentity

        return CitizenIdentity(
            uuid="uuid-1",
            full_name_en="Ahmed Al Mansouri",
            full_name_ar="أحمد المنصوري",
            email="ahmed@example.ae",
            mobile=phone_number,
            emirates_id="784-XXXX-XXXX-X",
        )

    monkeypatch.setattr(uaepass, "authenticate_uaepass", fake_auth)
    return fake_auth


@pytest.fixture
def mock_servicenow(monkeypatch, servicenow_stub):
    """Patch ServiceNow HTTP calls with the in-memory stub."""
    from workflows.activities import servicenow

    async def fake_fetch(citizen_uuid: str):
        from workflows.models import Ticket

        return [
            Ticket.model_validate(
                {
                    "sys_id": t["sys_id"],
                    "number": t["number"],
                    "short_description": t["short_description"],
                    "state": t["state"],
                    "opened_at": t["opened_at"],
                    "priority": t["priority"],
                }
            )
            for t in servicenow_stub.tickets.values()
        ]

    async def fake_create(citizen_uuid: str, short_description: str, description: str, priority: str = "4"):
        servicenow_stub.counter += 1
        number = f"INC{1000 + servicenow_stub.counter}"
        servicenow_stub.created.append(number)
        return {"sys_id": f"sysid-{servicenow_stub.counter}", "number": number}

    async def fake_update(sys_id: str, work_note: str):
        servicenow_stub.work_notes.append((sys_id, work_note))
        return True

    async def fake_close(sys_id: str, close_note: str):
        servicenow_stub.closed.append(sys_id)
        return True

    monkeypatch.setattr(servicenow, "fetch_open_tickets", fake_fetch)
    monkeypatch.setattr(servicenow, "create_ticket", fake_create)
    monkeypatch.setattr(servicenow, "update_ticket", fake_update)
    monkeypatch.setattr(servicenow, "close_ticket", fake_close)
    return servicenow_stub


@pytest.fixture
def mock_agent(monkeypatch):
    """Patch the voice conversation activity to return a fixed transcript."""
    from workflows.activities import agent

    async def fake_conversation(identity, ticket_context, language):
        return (
            "AI: Thank you Ahmed, your identity is verified. I can see your ticket INC001. "
            "How can I help you today?\n"
            "Citizen: I need an update on my permit application.\n"
            "AI: Your permit application was approved yesterday. Anything else?"
        )

    monkeypatch.setattr(agent, "run_voice_conversation", fake_conversation)

    async def fake_summary(identity, ticket_context, transcript, language):
        from workflows.models import CallSummary

        return CallSummary(
            topic="Permit application status",
            citizen_name=identity.full_name_en,
            resolution="Confirmed the permit application was approved and informed the citizen.",
            follow_up_actions=[],
            outcome="resolved",
            language=language,
        )

    monkeypatch.setattr(agent, "generate_call_summary", fake_summary)
    return fake_summary


@pytest.fixture
def mock_notifications(monkeypatch):
    """Patch email/SMS activities and capture what was sent."""
    from workflows.activities import notifications

    emails: list[tuple[str, str, str]] = []
    smss: list[tuple[str, str]] = []

    async def fake_email(identity, summary, survey_url):
        emails.append((identity.email or "", summary.ticket_number, survey_url))
        return True

    async def fake_sms(identity, summary, survey_url):
        smss.append((identity.mobile or "", survey_url))
        return True

    async def fake_survey(identity, summary, survey_url):
        return True

    monkeypatch.setattr(notifications, "send_email_summary", fake_email)
    monkeypatch.setattr(notifications, "send_sms_summary", fake_sms)
    monkeypatch.setattr(notifications, "send_survey_invitation", fake_survey)
    return {"emails": emails, "smss": smss}
