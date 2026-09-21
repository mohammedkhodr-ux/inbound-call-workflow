"""Genesys Cloud integration for the Digital Dubai inbound call workflow.

The inbound call lands in a Genesys Cloud voice queue, is answered by the
Mistral voice AI (via a Genesys Architect inbound flow that invokes this
workflow), and any events the workflow needs to surface back to the agent UI
are written through the Genesys Cloud API.
"""

from __future__ import annotations

import httpx
import mistralai.workflows as workflows
from pydantic import BaseModel

from integrations.settings import get_settings


class GenesysCallInfo(BaseModel):
    conversation_id: str
    ani: str
    queue_id: str = ""


class GenesysEvent(BaseModel):
    conversation_id: str
    event_type: str
    detail: str = ""


async def _get_access_token(client: httpx.AsyncClient) -> str:
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
    """Fetch the calling party (ANI) and queue for a Genesys conversation."""
    settings = get_settings().genesys
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
    """Write an external contact / conversation back to Genesys Cloud."""
    settings = get_settings().genesys
    async with httpx.AsyncClient(timeout=30) as client:
        token = await _get_access_token(client)
        response = await client.post(
            f"https://api.{settings.region}.genesys.cloud/api/v2/conversations/{event.conversation_id}/tags",
            headers={"Authorization": f"Bearer {token}"},
            json={"tagName": event.event_type, "value": event.detail[:255]},
        )
        response.raise_for_status()
