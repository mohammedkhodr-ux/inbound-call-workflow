"""Voice AI conversation agent and post-call summary activities."""

import mistralai.workflows as workflows
import mistralai.workflows.plugins.mistralai as workflows_mistralai
from mistralai.workflows.client import get_mistral_client

from ..agents import guardrails, prompts
from ..models import CallSummary, CitizenIdentity, TicketContext
from .servicenow import (
    create_ticket,
    escalate_ticket,
    get_ticket_details,
    update_ticket,
)


@workflows.activity(name="run_voice_conversation")
async def run_voice_conversation(
    identity: CitizenIdentity,
    ticket_context: TicketContext,
    language: str,
) -> str:
    """Run the AI voice conversation with the authenticated caller.

    Args:
        identity: UAEPASS-verified citizen identity.
        ticket_context: Existing tickets and sentiment for context.
        language: Conversation language (en or ar).
    """
    session = workflows_mistralai.RemoteSession()

    agent = workflows_mistralai.Agent(
        model=guardrails.CHAT_MODEL,
        name=guardrails.AGENT_NAME,
        description=guardrails.AGENT_DESCRIPTION,
        instructions=guardrails.AGENT_INSTRUCTIONS,
        tools=[get_ticket_details, create_ticket, update_ticket, escalate_ticket],
    )

    opening = prompts.GREETING_AR if language == "ar" else prompts.GREETING_EN
    context_prompt = (
        f"Caller context (UAEPASS verified):\n"
        f"- Name: {identity.full_name_en} / {identity.full_name_ar}\n"
        f"- Conversation language: {language}\n"
        f"- Existing tickets and sentiment: {ticket_context.summary}\n"
        f"- Overall caller sentiment: {ticket_context.overall_sentiment}\n\n"
        f"Start the call now with this greeting (you may adapt it naturally):\n"
        f'"{opening}"'
    )

    outputs = await workflows_mistralai.Runner.run(
        agent=agent,
        inputs=context_prompt,
        session=session,
        max_turns=guardrails.MAX_CONVERSATION_TURNS,
    )

    return "\n".join(output.text for output in outputs if hasattr(output, "text"))


@workflows.activity(name="generate_call_summary", retry_policy_max_attempts=2)
async def generate_call_summary(
    identity: CitizenIdentity,
    ticket_context: TicketContext,
    transcript: str,
    language: str,
) -> CallSummary:
    """Generate a structured summary of the completed call.

    Args:
        identity: Verified citizen identity.
        ticket_context: Ticket context captured at call start.
        transcript: Full conversation transcript.
        language: Call language (en or ar).
    """
    client = get_mistral_client()
    response = await client.chat.parse_async(
        model=guardrails.SUMMARY_MODEL,
        messages=[
            {
                "role": "user",
                "content": prompts.SUMMARY_PROMPT.format(
                    citizen_name=identity.full_name_en,
                    ticket_context=ticket_context.summary,
                    language=language,
                    transcript=transcript,
                ),
            }
        ],
        response_format=CallSummary,
    )
    summary = response.choices[0].message.parsed
    if summary.citizen_name == "":
        summary.citizen_name = identity.full_name_en
    if summary.language == "en" and language == "ar":
        summary.language = "ar"
    return summary
