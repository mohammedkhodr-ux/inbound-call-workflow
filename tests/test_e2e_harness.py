"""End-to-end workflow test through the Temporal test harness.

Runs the real durable workflow (sandboxed workflow code + activities) against
the in-process time-skipping Temporal environment, exercising:

- the UAE PASS signal (``uaepass_callback``) resuming a suspended execution
- the caller's spoken request submitted through ``__submit_input``
- the 1-5 feedback rating submitted through ``__submit_input``
- the final output contract of ``dda-inbound-call``

All external effects (Genesys, UAE PASS, ServiceNow, email/SMS gateways) are
stubbed by same-named activities; the Mistral LLM activities are replaced with
deterministic fakes so no credentials are needed.

Requires the Temporal test server (downloaded automatically by the SDK). In
environments where the download is blocked, set ``SKIP_E2E_HARNESS=1``.
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import timedelta
from pathlib import Path

import pytest

SRC = str(Path(__file__).resolve().parents[1] / "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

import mistralai.workflows as workflows  # noqa: E402
from mistralai.workflows.testing import create_test_worker  # noqa: E402

from integrations.genesys import GenesysCallInfo, GenesysEvent  # noqa: E402
from integrations.servicenow import ServiceNowQueryResult, TicketContext  # noqa: E402
from integrations.uaepass import UaePassAuthResult, UaePassProfile  # noqa: E402
from workflows.inbound_call import InboundCallWorkflow  # noqa: E402

WORKFLOW_EXECUTION_TIMEOUT = timedelta(seconds=10)
WAIT_RESULT_TIMEOUT = 15


@pytest.fixture
def recorded() -> dict:
    return {"feedback": [], "events": []}


@pytest.fixture
def temporal_env(request):
    """The SDK's in-process time-skipping Temporal environment."""
    return request.getfixturevalue("temporal_env")


def _stub_activities(recorded: dict) -> list:
    """Build same-named stub activities for every external effect and LLM call."""

    @workflows.activity()
    async def fetch_call_info(conversation_id: str) -> GenesysCallInfo:
        return GenesysCallInfo(conversation_id=conversation_id, ani="+971500000000", queue_id="q1")

    @workflows.activity()
    async def start_uaepass_verification(phone_number: str) -> str:
        return "txn-123"

    @workflows.activity()
    async def exchange_uaepass_code(code: str) -> UaePassAuthResult:
        return UaePassAuthResult(
            authenticated=True,
            profile=UaePassProfile(
                uuid="uuid-1",
                fullnameEN="Ahmed Al Mansouri",
                mobile="+971500000000",
                email="ahmed@example.ae",
            ),
        )

    @workflows.activity()
    async def fetch_caller_tickets(caller_uuid: str) -> ServiceNowQueryResult:
        return ServiceNowQueryResult(caller_uuid=caller_uuid, tickets=[])

    @workflows.activity()
    async def build_ticket_context(query_result: ServiceNowQueryResult) -> TicketContext:
        return TicketContext()

    @workflows.activity()
    async def create_ticket(caller_uuid: str, description: str, priority: str = "4") -> dict:
        return {"sys_id": "sysid-1", "number": "INC0100"}

    @workflows.activity()
    async def update_ticket(sys_id: str, work_note: str) -> None:
        return None

    @workflows.activity()
    async def close_ticket(sys_id: str, resolution_note: str, resolution_code: str = "x") -> None:
        return None

    @workflows.activity()
    async def build_survey_url(execution_id: str, phone: str = "") -> str:
        return f"https://surveys.dda.gov.ae/f/{execution_id}"

    @workflows.activity()
    async def send_summary_email(to_email: str, subject: str, body: str) -> None:
        recorded.setdefault("emails", []).append((to_email, subject, body))

    @workflows.activity()
    async def send_summary_sms(to_number: str, body: str) -> None:
        recorded.setdefault("smss", []).append((to_number, body))

    @workflows.activity()
    async def log_call_event(event: GenesysEvent) -> None:
        recorded["events"].append(event.event_type)

    @workflows.activity()
    async def record_call_feedback(conversation_id: str, rating: str, comment: str = "") -> None:
        recorded["feedback"].append((conversation_id, rating))

    @workflows.activity()
    async def analyse_intent(request_text: str, ticket_context_summary: str) -> dict:
        return {
            "category": "new_request",
            "related_ticket_number": "",
            "priority": "4",
            "request_summary": "Citizen needs help with a permit.",
        }

    @workflows.activity()
    async def summarise_call(transcript: str, caller_name: str, ticket_numbers: list) -> dict:
        return {
            "summary": "We addressed your request and created a ticket.",
            "actions_taken": ["Created ticket INC0100"],
            "outcome": "resolved",
            "survey_url": "",
        }

    @workflows.activity(name="mistralai_chat_complete")
    async def fake_chat_complete(params) -> dict:
        # Plain assistant reply (no tool calls) so the agent loop ends in one turn.
        return {
            "id": "resp-1",
            "model": "test",
            "created": 1,
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "stop",
                    "message": {"role": "assistant", "content": "Your request is registered."},
                }
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }

    return [
        fetch_call_info,
        start_uaepass_verification,
        exchange_uaepass_code,
        fetch_caller_tickets,
        build_ticket_context,
        create_ticket,
        update_ticket,
        close_ticket,
        build_survey_url,
        send_summary_email,
        send_summary_sms,
        log_call_event,
        record_call_feedback,
        analyse_intent,
        summarise_call,
        fake_chat_complete,
    ]


async def _submit_pending_input(handle, text: str) -> None:
    """Answer the oldest pending wait_for_input prompt with the given text."""
    pending = await handle.query("__get_pending_inputs")
    inputs = pending.get("pending_inputs", [])
    assert inputs, "expected a pending input prompt"
    await handle.execute_update(
        "__submit_input",
        {"task_id": inputs[0]["task_id"], "input": {"message": [{"type": "text", "text": text}]}},
    )


@pytest.mark.skipif(bool(os.environ.get("SKIP_E2E_HARNESS")), reason="Temporal test server unavailable")
async def test_inbound_call_full_flow(temporal_env, recorded) -> None:
    """Full happy path: UAEPASS signal -> request -> feedback -> close-out."""
    async with create_test_worker(
        temporal_env,
        workflows=[InboundCallWorkflow],
        activities=_stub_activities(recorded),
    ):
        handle = await temporal_env.client.start_workflow(
            "dda-inbound-call",
            {"conversation_id": "conv-1", "phone_number": "+971500000000"},
            id="test-inbound-call-full",
            task_queue="test-task-queue",
            execution_timeout=WORKFLOW_EXECUTION_TIMEOUT,
        )

        # 1. Citizen approves UAE PASS: webhook sends the signal.
        await handle.signal("uaepass_callback", {"code": "auth-code-1"})
        # 2. Caller states the request.
        await _submit_pending_input(handle, "I need help with my business permit")
        # 3. Caller rates the call.
        await _submit_pending_input(handle, "5 - Excellent")

        result = await asyncio.wait_for(handle.result(), timeout=WAIT_RESULT_TIMEOUT)

    assert result["status"] == "completed"
    assert result["caller_name"] == "Ahmed Al Mansouri"
    assert result["caller_uuid"] == "uuid-1"
    assert result["feedback_rating"] == "5 - Excellent"
    assert result["survey_url"].startswith("https://surveys.dda.gov.ae/f/")
    assert recorded["feedback"] == [("conv-1", "5 - Excellent")]
    assert "call_feedback" in recorded["events"]
    assert "workflow_completed" in recorded["events"]
    assert recorded.get("emails") and recorded.get("smss")
