"""ServiceNow integration for the Digital Dubai inbound call workflow.

Handles caller ticket lookup, sentiment context, ticket creation, updates,
and closure via the ServiceNow Table API.
"""

from __future__ import annotations

import base64
from datetime import UTC, datetime
from typing import Any

import httpx
import mistralai.workflows as workflows
from pydantic import BaseModel, Field

from integrations.settings import get_settings


class ServiceNowTicket(BaseModel):
    sys_id: str
    number: str
    short_description: str
    state: str
    priority: str
    sentiment: str = "unknown"
    opened_at: str = ""
    work_notes: str = ""


class ServiceNowQueryResult(BaseModel):
    caller_uuid: str
    tickets: list[ServiceNowTicket] = Field(default_factory=list)


class TicketContext(BaseModel):
    """Aggregated context derived from the caller's ServiceNow history."""

    open_tickets: list[ServiceNowTicket] = Field(default_factory=list)
    recent_closed_tickets: list[ServiceNowTicket] = Field(default_factory=list)
    overall_sentiment: str = "neutral"
    summary: str = ""


def _instance_url(instance: str) -> str:
    if instance.startswith("http"):
        return instance.rstrip("/")
    return f"https://{instance}.service-now.com"


def _auth_header(user: str, password: str) -> str:
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    return f"Basic {token}"


def _parse_ticket(record: dict[str, Any]) -> ServiceNowTicket:
    return ServiceNowTicket(
        sys_id=record["sys_id"],
        number=record.get("number", ""),
        short_description=record.get("short_description", ""),
        state=record.get("state", ""),
        priority=record.get("priority", ""),
        opened_at=record.get("opened_at", ""),
        work_notes=record.get("work_notes", ""),
    )


def _state_label(state: str) -> str:
    labels = {
        "1": "New",
        "2": "In Progress",
        "3": "On Hold",
        "6": "Resolved",
        "7": "Closed",
        "8": "Cancelled",
    }
    return labels.get(state, state)


def _sentiment_from_records(tickets: list[ServiceNowTicket]) -> str:
    negative_words = ("complaint", "delay", "wrong", "broken", "unhappy", "rejected", "escalat")
    positive_words = ("resolved", "thanks", "happy", "completed", "approved")
    negative = sum(1 for t in tickets for w in negative_words if w in t.short_description.lower())
    positive = sum(1 for t in tickets for w in positive_words if w in t.short_description.lower())
    if negative > positive:
        return "negative"
    if positive > negative:
        return "positive"
    return "neutral"


@workflows.activity(retry_policy_max_attempts=3)
async def fetch_caller_tickets(caller_uuid: str) -> ServiceNowQueryResult:
    """Fetch the caller's open and recently closed tickets from ServiceNow."""
    settings = get_settings().servicenow
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(
            f"{_instance_url(settings.instance)}/api/now/table/incident",
            params={
                "sysparm_query": f"caller_id={caller_uuid}^stateIN1,2,3^ORopened_atONLast 90 days",
                "sysparm_fields": "sys_id,number,short_description,state,priority,opened_at,work_notes",
                "sysparm_limit": "25",
                "sysparm_display_value": "false",
            },
            headers={"Authorization": _auth_header(settings.user, settings.password)},
        )
        response.raise_for_status()
        records = response.json().get("result", [])
    return ServiceNowQueryResult(
        caller_uuid=caller_uuid,
        tickets=[_parse_ticket(r) for r in records],
    )


@workflows.activity()
async def build_ticket_context(query_result: ServiceNowQueryResult) -> TicketContext:
    """Split tickets into open/recent-closed buckets and derive sentiment."""
    open_tickets = [t for t in query_result.tickets if t.state in ("1", "2", "3")]
    closed_tickets = [t for t in query_result.tickets if t.state not in ("1", "2", "3")]
    sentiment = _sentiment_from_records(query_result.tickets)
    lines = []
    if open_tickets:
        lines.append(
            "The caller has "
            + ", ".join(f"{t.number} ({_state_label(t.state)}, {_priority(t.priority)})" for t in open_tickets)
        )
    if closed_tickets:
        lines.append(f"Recently closed: {', '.join(t.number for t in closed_tickets[:5])}")
    summary = " ".join(lines) if lines else "No prior tickets on record for this caller."
    return TicketContext(
        open_tickets=open_tickets,
        recent_closed_tickets=closed_tickets,
        overall_sentiment=sentiment,
        summary=summary,
    )


def _priority(priority: str) -> str:
    labels = {"1": "Critical", "2": "High", "3": "Moderate", "4": "Low"}
    return labels.get(priority, priority)


@workflows.activity()
async def create_ticket(caller_uuid: str, description: str, priority: str = "4") -> ServiceNowTicket:
    """Create a new incident in ServiceNow for this caller."""
    settings = get_settings().servicenow
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            f"{_instance_url(settings.instance)}/api/now/table/incident",
            json={
                "caller_id": caller_uuid,
                "short_description": description[:160],
                "description": description,
                "priority": priority,
                "contact_type": "phone",
                "u_channel": "genesys_voice_ai",
            },
            headers={"Authorization": _auth_header(settings.user, settings.password)},
        )
        response.raise_for_status()
        record = response.json()["result"]
    return _parse_ticket(record)


@workflows.activity()
async def update_ticket(sys_id: str, work_note: str) -> None:
    """Append a work note to an existing ticket."""
    settings = get_settings().servicenow
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.patch(
            f"{_instance_url(settings.instance)}/api/now/table/incident/{sys_id}",
            json={"work_notes": work_note},
            headers={"Authorization": _auth_header(settings.user, settings.password)},
        )
        response.raise_for_status()


@workflows.activity()
async def close_ticket(sys_id: str, resolution_note: str, resolution_code: str = "Resolved by AI") -> None:
    """Resolve and close a ticket with a resolution note."""
    settings = get_settings().servicenow
    stamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.patch(
            f"{_instance_url(settings.instance)}/api/now/table/incident/{sys_id}",
            json={
                "state": "7",
                "close_code": resolution_code,
                "close_notes": f"{resolution_note}\n\nClosed by Digital Dubai voice AI on {stamp}.",
            },
            headers={"Authorization": _auth_header(settings.user, settings.password)},
        )
        response.raise_for_status()
