"""Genesys Cloud integration for the Digital Dubai inbound call workflow.

The inbound call lands in a Genesys Cloud voice queue, is answered by the
Mistral voice AI (via a Genesys Architect inbound flow that invokes this
workflow), and any events the workflow needs to surface back to the agent UI
are written through the Genesys Cloud API. Unconfigured credentials fall back
to demo values so the workflow can be exercised end-to-end.

Third-party imports (httpx) happen inside the activities under
``workflows.unsafe.imports_passed_through()``: this module is imported by the
workflow module, which the Temporal determinism sandbox re-imports, so its
top level must stay free of third-party imports.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import mistralai.workflows as workflows
import structlog
from pydantic import BaseModel

from integrations.settings import get_settings

if TYPE_CHECKING:
    from httpx import AsyncClient

logger = structlog.get_logger(__name__)


class GenesysCallInfo(BaseModel):
    conversation_id: str
    ani: str
    queue_id: str = ""


class GenesysEvent(BaseModel):
    conversation_id: str
    event_type: str
    detail: str = ""


async def _get_access_token(client: AsyncClient) -> str:
    settings = get_settings().genesys
    response = await client.post(
        f"https://login.{settings.region}.genesys.cloud/oauth/token",
        data={"grant_type": "client_credentials"},
        auth=(settings.client_id, settings.client_secret),
    )
    response.raise_for_status()
    return response.json()["access_token"]


@workflows.activity()
async def fetch_call_info(conversation_id: str) -> GenesysCallInfo:
    """Fetch the calling party (ANI) and queue for a Genesys conversation.

    When Genesys Cloud credentials are not configured the activity returns demo
    values so the workflow can be exercised without a live contact centre.
    """
    settings = get_settings().genesys
    if not settings.configured:
        logger.warning(
            "Genesys Cloud is not configured; returning demo call info",
            conversation_id=conversation_id,
        )
        return GenesysCallInfo(conversation_id=conversation_id, ani="", queue_id="")

    with workflows.unsafe.imports_passed_through():
        import httpx

    async with httpx.AsyncClient(timeout=30) as client:
        token = await _get_access_token(client)
        response = await client.get(
            f"https://api.{settings.region}.genesys.cloud/api/v2/conversations/{conversation_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        response.raise_for_status()
        data = response.json()
    participants = data.get("participants", [])
    ani = next((p.get("ani", "") for p in participants if p.get("purpose") == "customer"), "")
    return GenesysCallInfo(
        conversation_id=conversation_id,
        ani=ani,
        queue_id=next((p.get("queue", {}).get("id", "") for p in participants if p.get("queue")), ""),
    )


@workflows.activity()
async def log_call_event(event: GenesysEvent) -> None:
    """Write a conversation event back to Genesys Cloud.

    Unconfigured credentials log the event instead of failing the call.
    """
    settings = get_settings().genesys
    if not settings.configured:
        logger.info(
            "Genesys Cloud is not configured; logging demo event",
            conversation_id=event.conversation_id,
            event_type=event.event_type,
            detail=event.detail,
        )
        return

    with workflows.unsafe.imports_passed_through():
        import httpx

    async with httpx.AsyncClient(timeout=30) as client:
        token = await _get_access_token(client)
        response = await client.post(
            f"https://api.{settings.region}.genesys.cloud/api/v2/conversations/{event.conversation_id}/tags",
            headers={"Authorization": f"Bearer {token}"},
            json={"tagName": event.event_type, "value": event.detail[:255]},
        )
        response.raise_for_status()


@workflows.activity()
async def record_call_feedback(conversation_id: str, rating: str, comment: str = "") -> None:
    """Record the caller's end-of-call feedback as a Genesys conversation tag."""
    await log_call_event(
        GenesysEvent(
            conversation_id=conversation_id,
            event_type="call_feedback",
            detail=f"rating={rating}" + (f"; comment={comment[:180]}" if comment else ""),
        )
    )
