"""ServiceNow ticket activities exposed as agent tools.

Uses the ServiceNow Table API against the instance configured in the worker
environment. Credentials are read from the environment inside each activity.
"""

import base64
import os
from datetime import UTC, datetime

import httpx
import mistralai.workflows as workflows

from ..models import Ticket, TicketContext

TABLE = "/api/now/table"
CLOSE_STATE = "7"
CLOSE_CODE = "Solved (Permanently)"
OPEN_STATES = "1,2,3,4,5,6"


def _client_config() -> tuple[str, httpx.Headers]:
    instance = os.environ.get("SERVICENOW_INSTANCE")
    user = os.environ.get("SERVICENOW_USER")
    password = os.environ.get("SERVICENOW_PASSWORD")
    if not instance or not user or not password:
        raise RuntimeError("SERVICENOW_INSTANCE, SERVICENOW_USER and SERVICENOW_PASSWORD are required")
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    headers = {
        "Authorization": f"Basic {token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    return f"https://{instance}", headers


def _to_ticket(record: dict) -> Ticket:
    return Ticket(
        sys_id=record["sys_id"],
        number=record.get("number", ""),
        short_description=record.get("short_description", ""),
        state=record.get("state", ""),
        opened_at=record.get("opened_at", ""),
        priority=record.get("priority", ""),
        sentiment=record.get("sentiment"),
    )


@workflows.activity(name="fetch_open_tickets", retry_policy_max_attempts=3)
async def fetch_open_tickets(citizen_uuid: str) -> list[Ticket]:
    """Fetch the citizen's open ServiceNow tickets.

    Args:
        citizen_uuid: UAEPASS UUID stored on the caller's ServiceNow user record.
    """
    base, headers = _client_config()
    async with httpx.AsyncClient(timeout=30, headers=headers) as client:
        response = await client.get(
            f"{base}{TABLE}/incident",
            params={
                "sysparm_query": f"caller_id.u_epass_uuid={citizen_uuid}^stateIN{OPEN_STATES}",
                "sysparm_fields": "sys_id,number,short_description,state,opened_at,priority,sentiment",
                "sysparm_limit": "10",
                "sysparm_display_value": "true",
            },
        )
        response.raise_for_status()
        return [_to_ticket(record) for record in response.json()["result"]]


@workflows.activity(name="analyze_tickets_and_sentiment")
async def analyze_tickets_and_sentiment(citizen_name: str, tickets: list[Ticket]) -> TicketContext:
    """Build conversational context and overall sentiment from existing tickets.

    Args:
        citizen_name: Verified citizen name for the context summary.
        tickets: The citizen's open tickets from ServiceNow.
    """
    if not tickets:
        return TicketContext(
            tickets=[],
            overall_sentiment="neutral",
            summary=f"{citizen_name} has no open tickets with Digital Dubai Authority.",
        )

    lines = [
        f"- {t.number}: {t.short_description} (state: {t.state}, "
        f"opened: {t.opened_at}, priority: {t.priority}, sentiment: {t.sentiment or 'unknown'})"
        for t in tickets
    ]

    negative = sum(1 for t in tickets if (t.sentiment or "").lower() in ("negative", "frustrated", "angry"))
    if negative >= max(1, len(tickets) // 2):
        overall = "negative"
    elif any((t.sentiment or "").lower() in ("positive",) for t in tickets):
        overall = "positive"
    else:
        overall = "neutral"

    summary = (
        f"{citizen_name} has {len(tickets)} open ticket(s) with Digital Dubai Authority. "
        + " ".join(lines)
    )
    return TicketContext(tickets=tickets, overall_sentiment=overall, summary=summary)


@workflows.activity(name="get_ticket_details", retry_policy_max_attempts=3)
async def get_ticket_details(ticket_number: str) -> dict:
    """Get full details and work notes of a specific ticket.

    Args:
        ticket_number: ServiceNow ticket number, e.g. INC0010012.
    """
    base, headers = _client_config()
    async with httpx.AsyncClient(timeout=30, headers=headers) as client:
        response = await client.get(
            f"{base}{TABLE}/incident",
            params={
                "sysparm_query": f"number={ticket_number}",
                "sysparm_fields": "sys_id,number,short_description,description,state,priority,work_notes,comments",
                "sysparm_display_value": "true",
                "sysparm_limit": "1",
            },
        )
        response.raise_for_status()
        results = response.json()["result"]
    if not results:
        raise ValueError(f"Ticket {ticket_number} not found")
    return results[0]


@workflows.activity(name="create_ticket", retry_policy_max_attempts=2)
async def create_ticket(
    citizen_uuid: str,
    short_description: str,
    description: str,
    priority: str = "4",
) -> dict:
    """Open a new ServiceNow incident for the citizen.

    Args:
        citizen_uuid: UAEPASS UUID to identify the caller record.
        short_description: One-line summary of the request.
        description: Full description captured during the call.
        priority: ServiceNow priority (1 critical - 5 low).
    """
    base, headers = _client_config()
    async with httpx.AsyncClient(timeout=30, headers=headers) as client:
        caller = await client.get(
            f"{base}{TABLE}/sys_user",
            params={
                "sysparm_query": f"u_epass_uuid={citizen_uuid}",
                "sysparm_fields": "sys_id",
                "sysparm_limit": "1",
            },
        )
        caller.raise_for_status()
        callers = caller.json()["result"]
        caller_sys_id = callers[0]["sys_id"] if callers else None

        response = await client.post(
            f"{base}{TABLE}/incident",
            json={
                "caller_id": caller_sys_id,
                "short_description": short_description,
                "description": description,
                "priority": priority,
                "contact_type": "phone",
                "u_epass_uuid": citizen_uuid,
            },
        )
        response.raise_for_status()
        return response.json()["result"]


@workflows.activity(name="update_ticket", retry_policy_max_attempts=3)
async def update_ticket(ticket_sys_id: str, work_note: str) -> bool:
    """Add a work note to an existing ticket.

    Args:
        ticket_sys_id: ServiceNow sys_id of the ticket.
        work_note: Note to append to the ticket's work notes.
    """
    base, headers = _client_config()
    async with httpx.AsyncClient(timeout=30, headers=headers) as client:
        response = await client.patch(
            f"{base}{TABLE}/incident/{ticket_sys_id}",
            json={"work_notes": work_note},
        )
        response.raise_for_status()
    return True


@workflows.activity(name="escalate_ticket", retry_policy_max_attempts=3)
async def escalate_ticket(ticket_sys_id: str, reason: str) -> dict:
    """Escalate a ticket to the human support queue.

    Args:
        ticket_sys_id: ServiceNow sys_id of the ticket.
        reason: Why the request could not be resolved by the AI assistant.
    """
    base, headers = _client_config()
    async with httpx.AsyncClient(timeout=30, headers=headers) as client:
        response = await client.patch(
            f"{base}{TABLE}/incident/{ticket_sys_id}",
            json={
                "assignment_group": "DDA Human Support",
                "impact": "2",
                "urgency": "2",
                "work_notes": f"Escalated by AI voice agent: {reason}",
            },
        )
        response.raise_for_status()
        return response.json()["result"]


@workflows.activity(name="close_ticket", retry_policy_max_attempts=3)
async def close_ticket(ticket_sys_id: str, close_note: str) -> bool:
    """Close a ticket as resolved, attaching the call summary.

    Args:
        ticket_sys_id: ServiceNow sys_id of the ticket to close.
        close_note: Resolution summary to record on the ticket.
    """
    base, headers = _client_config()
    now = datetime.now(UTC).isoformat()
    async with httpx.AsyncClient(timeout=30, headers=headers) as client:
        response = await client.patch(
            f"{base}{TABLE}/incident/{ticket_sys_id}",
            json={
                "state": CLOSE_STATE,
                "close_code": CLOSE_CODE,
                "close_notes": close_note,
                "resolved_at": now,
                "work_notes": f"Resolved by AI voice agent during inbound call: {close_note}",
            },
        )
        response.raise_for_status()
    return True
