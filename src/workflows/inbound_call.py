"""Digital Dubai Authority inbound call workflow.

Orchestrates an inbound call center conversation: UAEPASS authentication,
ServiceNow ticket context, AI voice conversation, ticket closure, and
email/SMS summary with a feedback survey.
"""

import os
from datetime import timedelta

import mistralai.workflows as workflows
import temporalio.workflow

# The activity modules import httpx (for external HTTP calls) which is not
# allowed at the top level inside the Temporal workflow sandbox.  We pass the
# imports through so the sandbox does not reject them; the modules are only
# referenced as activity callables and never executed inside the workflow
# itself.
with temporalio.workflow.unsafe.imports_passed_through():
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

# Activity execution timeout shared across all activities.
_ACTIVITY_TIMEOUT = timedelta(seconds=30)


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

        identity = await temporalio.workflow.execute_activity(
            authenticate_uaepass,
            input.ani,
            start_to_close_timeout=_ACTIVITY_TIMEOUT,
        )
        result.authenticated = True
        result.citizen_name = (
            identity.full_name_ar if input.language == "ar" else identity.full_name_en
        )

        tickets = await temporalio.workflow.execute_activity(
            fetch_open_tickets,
            identity.uuid,
            start_to_close_timeout=_ACTIVITY_TIMEOUT,
        )
        result.open_tickets_found = len(tickets)

        ticket_context = await temporalio.workflow.execute_activity(
            analyze_tickets_and_sentiment,
            result.citizen_name,
            tickets,
            start_to_close_timeout=_ACTIVITY_TIMEOUT,
        )

        transcript = await temporalio.workflow.execute_activity(
            run_voice_conversation,
            identity,
            ticket_context,
            input.language,
            start_to_close_timeout=timedelta(minutes=10),
        )

        summary = await temporalio.workflow.execute_activity(
            generate_call_summary,
            identity,
            ticket_context,
            transcript,
            input.language,
            start_to_close_timeout=timedelta(minutes=2),
        )
        result.resolution = summary.resolution
        result.outcome = summary.outcome
        result.ticket_number = summary.ticket_number

        ticket = _resolve_ticket(summary, ticket_context)
        result.ticket_number = ticket["number"] or result.ticket_number

        if ticket["sys_id"] and summary.outcome == "resolved":
            result.ticket_closed = await temporalio.workflow.execute_activity(
                close_ticket,
                ticket["sys_id"],
                f"{summary.topic}: {summary.resolution}",
                start_to_close_timeout=_ACTIVITY_TIMEOUT,
            )
        elif ticket["sys_id"]:
            await temporalio.workflow.execute_activity(
                close_ticket,
                ticket["sys_id"],
                f"Escalated after call. Outcome: {summary.outcome}. "
                f"Follow-up: {'; '.join(summary.follow_up_actions) or 'none'}",
                start_to_close_timeout=_ACTIVITY_TIMEOUT,
            )
            result.ticket_closed = True

        survey_url = (
            os.environ.get(
                "SURVEY_URL_TEMPLATE", "https://survey.digitaldubai.gov.ae/call/{ticket}"
            )
        ).format(ticket=result.ticket_number or "na")

        if identity.email:
            result.email_sent = await temporalio.workflow.execute_activity(
                send_email_summary,
                identity,
                summary,
                survey_url,
                start_to_close_timeout=_ACTIVITY_TIMEOUT,
            )
        if identity.mobile:
            result.sms_sent = await temporalio.workflow.execute_activity(
                send_sms_summary,
                identity,
                summary,
                survey_url,
                start_to_close_timeout=_ACTIVITY_TIMEOUT,
            )

        result.survey_sent = await temporalio.workflow.execute_activity(
            send_survey_invitation,
            identity,
            summary,
            survey_url,
            start_to_close_timeout=_ACTIVITY_TIMEOUT,
        )
        result.survey_url = survey_url
        return result
