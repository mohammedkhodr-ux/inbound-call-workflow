"""AI activities for the Digital Dubai inbound call workflow.

Uses the Mistral Agents API (via the mistralai workflows plugin) for:
- intent triage of the caller's request
- generating the end-of-call summary
- the conversational resolution agent (defined in the workflow with tools)
"""

from __future__ import annotations

import mistralai.workflows as workflows
import mistralai.workflows.plugins.mistralai as workflows_mistralai
from pydantic import BaseModel, Field


class CallerIntent(BaseModel):
    category: str = Field(description="One of: existing_ticket, new_request, general_enquiry, complaint, other")
    related_ticket_number: str = ""
    priority: str = Field(default="4", description="ServiceNow priority 1-4")
    request_summary: str = ""


@workflows.activity()
async def analyse_intent(request_text: str, ticket_context_summary: str) -> CallerIntent:
    """Classify the caller's request against their ServiceNow ticket context."""
    request = workflows_mistralai.ChatCompletionRequest(
        model="mistral-small-latest",
        messages=[
            workflows_mistralai.SystemMessage(
                content=(
                    "You triage calls for the Digital Dubai Authority contact centre. "
                    "Given the caller's request and their ServiceNow ticket context, classify the intent. "
                    "If the request clearly relates to one of the open tickets, set related_ticket_number."
                )
            ),
            workflows_mistralai.UserMessage(
                content=f"Ticket context: {ticket_context_summary}\n\nCaller request: {request_text}"
            ),
        ],
    )
    return await workflows_mistralai.chat_parse_to_model(CallerIntent, request)


class CallSummary(BaseModel):
    summary: str = Field(description="Three-to-five sentence summary of the call, addressed to the citizen")
    actions_taken: list[str] = Field(default_factory=list)
    outcome: str = Field(description="One of: resolved, escalated, pending, unresolved")
    survey_url: str = ""


@workflows.activity()
async def summarise_call(
    transcript: str,
    caller_name: str,
    ticket_numbers: list[str],
) -> CallSummary:
    """Generate a citizen-facing summary of the completed call."""
    tickets = ", ".join(ticket_numbers) if ticket_numbers else "none"
    request = workflows_mistralai.ChatCompletionRequest(
        model="mistral-small-latest",
        messages=[
            workflows_mistralai.SystemMessage(
                content=(
                    "You write call summaries for the Digital Dubai Authority contact centre. "
                    "Write a warm, professional summary in English for the citizen. "
                    "List the actions taken and state the outcome as one of: resolved, escalated, pending, unresolved."
                )
            ),
            workflows_mistralai.UserMessage(
                content=f"Citizen: {caller_name}\nTickets referenced: {tickets}\n\nCall transcript:\n{transcript}"
            ),
        ],
    )
    return await workflows_mistralai.chat_parse_to_model(CallSummary, request)
