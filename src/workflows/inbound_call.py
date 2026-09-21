"""Digital Dubai Authority inbound call workflow.

Orchestrates an inbound call center conversation: UAEPASS authentication,
ServiceNow ticket context, AI voice conversation, ticket closure, and
email/SMS summary with a feedback survey.
"""

import os
from datetime import timedelta

import mistralai.workflows as workflows

from .activities.agent import generate_call_summary, run_voice_conversation
from .activities.notifications import (
    send_email_summary,
    send_sms_summary,
    send_survey_invitation,
)
from .activities.servicenow import (
    analyze_tickets_and_sentiment,
    close_ticket,
    fetch_open_tickets,
)
from .activities.uaepass import authenticate_uaepass
from .models import CallInput, WorkflowResult


def _resolve_ticket(summary, ticket_context) -> dict:
    """Pick the ticket the conversation worked on: from the summary or the single open ticket."""
    if summary.ticket_number:
        for ticket in ticket_context.tickets:
            if ticket.number == summary.ticket_number:
                return {"sys_id": ticket.sys_id, "number": ticket.number}
        return {"sys_id": "", "number": summary.ticket_number}
    if len(ticket_context.tickets) == 1:
        return {
            "sys_id": ticket_context.tickets[0].sys_id,
            "number": ticket_context.tickets[0].number,
        }
    return {"sys_id": "", "number": ""}


@workflows.workflow.define(
    name="dda-inbound-call",
    workflow_display_name="DDA Inbound Call",
    workflow_description=(
        "Digital Dubai Authority inbound call center workflow: Genesys routes a "
        "citizen call to the Mistral voice AI, which authenticates via UAEPASS, "
        "reviews existing ServiceNow tickets and sentiment, resolves the request, "
        "closes the ticket, and sends an email/SMS summary with a feedback survey."
    ),
    execution_timeout=timedelta(minutes=30),
)
class InboundCallWorkflow:
    @workflows.workflow.entrypoint
    async def run(self, input: CallInput) -> WorkflowResult:
        """Handle one inbound call from routing to post-call follow-up.

        Args:
            input: Genesys call metadata (call ID, caller ANI, language).
        """
        result = WorkflowResult(call_id=input.call_id, authenticated=False)

        identity = await authenticate_uaepass(input.ani)
        result.authenticated = True
        result.citizen_name = (
            identity.full_name_ar if input.language == "ar" else identity.full_name_en
        )

        tickets = await fetch_open_tickets(identity.uuid)
        result.open_tickets_found = len(tickets)
        ticket_context = await analyze_tickets_and_sentiment(result.citizen_name, tickets)

        transcript = await run_voice_conversation(identity, ticket_context, input.language)

        summary = await generate_call_summary(identity, ticket_context, transcript, input.language)
        result.resolution = summary.resolution
        result.outcome = summary.outcome
        result.ticket_number = summary.ticket_number

        ticket = _resolve_ticket(summary, ticket_context)
        result.ticket_number = ticket["number"] or result.ticket_number

        if ticket["sys_id"] and summary.outcome == "resolved":
            result.ticket_closed = await close_ticket(
                ticket["sys_id"],
                f"{summary.topic}: {summary.resolution}",
            )
        elif ticket["sys_id"]:
            await close_ticket(
                ticket["sys_id"],
                f"Escalated after call. Outcome: {summary.outcome}. "
                f"Follow-up: {'; '.join(summary.follow_up_actions) or 'none'}",
            )
            result.ticket_closed = True

        survey_url = (
            os.environ.get("SURVEY_URL_TEMPLATE", "https://survey.digitaldubai.gov.ae/call/{ticket}")
            .format(ticket=result.ticket_number or "na")
        )

        if identity.email:
            result.email_sent = await send_email_summary(identity, summary, survey_url)
        if identity.mobile:
            result.sms_sent = await send_sms_summary(identity, summary, survey_url)
        result.survey_sent = await send_survey_invitation(identity, summary, survey_url)
        result.survey_url = survey_url

        return result
