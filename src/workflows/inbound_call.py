"""Digital Dubai Authority inbound call workflow.

End-to-end flow:
1. A citizen calls the DDA contact centre; Genesys Cloud routes the call to the
   Mistral voice AI (this workflow, triggered by the Genesys inbound flow).
2. The workflow authenticates the citizen with UAE PASS.
3. It fetches the citizen's existing ServiceNow tickets and sentiment context.
4. It asks what the citizen needs and attempts to resolve the request using a
   tool-calling resolution agent backed by ServiceNow.
5. It closes/updates the relevant ServiceNow ticket, then emails and SMSes the
   citizen a call summary with a feedback survey link.

Human-in-the-loop: the UAEPASS callback arrives as a signal; the conversation
turns arrive via InteractiveWorkflow.wait_for_input().
"""

from __future__ import annotations

from datetime import timedelta

import mistralai.workflows as workflows
import mistralai.workflows.plugins.mistralai as workflows_mistralai
from pydantic import BaseModel

from integrations.genesys import GenesysEvent, fetch_call_info, log_call_event
from integrations.notify import send_summary_email, send_summary_sms
from integrations.servicenow import (
    TicketContext,
    build_ticket_context,
    close_ticket,
    create_ticket,
    fetch_caller_tickets,
    update_ticket,
)
from integrations.settings import get_settings
from integrations.uaepass import UaePassAuthResult, UaePassProfile, exchange_uaepass_code
from workflows.ai_activities import CallerIntent, analyse_intent, summarise_call


class InboundCallInput(BaseModel):
    conversation_id: str
    phone_number: str = ""


class InboundCallOutput(BaseModel):
    status: str
    caller_name: str = ""
    caller_uuid: str = ""
    ticket_numbers: list[str] = []
    summary: str = ""
    outcome: str = ""
    survey_url: str = ""


class UaePassCallback(BaseModel):
    code: str


@workflows.workflow.define(
    name="dda-inbound-call",
    workflow_display_name="DDA Inbound Call",
    workflow_description=(
        "Digital Dubai Authority inbound call: Genesys voice routing, UAEPASS "
        "authentication, ServiceNow ticket context and resolution, email/SMS "
        "summary with feedback survey."
    ),
)
class InboundCallWorkflow(workflows.InteractiveWorkflow):
    def __init__(self) -> None:
        self.uaepass_callback: UaePassCallback | None = None

    @workflows.workflow.signal(name="uaepass_callback")
    async def on_uaepass_callback(self, callback: UaePassCallback) -> None:
        """Called by the UAEPASS integration webhook when the citizen approves verification."""
        self.uaepass_callback = callback

    @workflows.workflow.entrypoint
    async def run(self, input: InboundCallInput) -> InboundCallOutput:
        await workflows_mistralai.send_assistant_message(
            "Welcome to Digital Dubai Authority. Please wait while I verify your identity with UAE PASS."
        )

        call_info = await fetch_call_info(input.conversation_id)
        phone = input.phone_number or call_info.ani

        profile = await self._authenticate_with_uaepass(phone)
        if profile is None:
            return InboundCallOutput(
                status="authentication_failed",
                summary="UAEPASS verification did not complete. Please call again or visit a service centre.",
            )

        query_result = await fetch_caller_tickets(profile.uuid)
        ticket_context = await build_ticket_context(query_result)

        greeting = self._greeting(profile, ticket_context)
        await workflows_mistralai.send_assistant_message(greeting)

        request_text = await self._ask_what_they_need()
        transcript = [f"Citizen: {request_text}"]

        intent = await analyse_intent(request_text, ticket_context.summary)
        transcript.append(f"AI triage: {intent.category} — {intent.request_summary}")

        ticket_numbers = [t.number for t in ticket_context.open_tickets]
        agent = self._build_resolution_agent(profile, ticket_context)

        resolution = await self._resolve_request(agent, request_text, intent, ticket_context, transcript)
        transcript.extend(resolution["new_transcript"])
        conversation_id = input.conversation_id

        summary = await summarise_call(
            "\n".join(transcript), profile.fullnameEN, resolution["ticket_numbers"] or ticket_numbers
        )
        survey_url = get_settings().survey_url_template.format(
            execution_id=workflows.get_execution_id(), phone=profile.mobile
        )
        summary.survey_url = survey_url

        await self._close_out(profile, summary, conversation_id)

        return InboundCallOutput(
            status="completed",
            caller_name=profile.fullnameEN,
            caller_uuid=profile.uuid,
            ticket_numbers=resolution["ticket_numbers"] or ticket_numbers,
            summary=summary.summary,
            outcome=summary.outcome,
            survey_url=survey_url,
        )

    async def _authenticate_with_uaepass(self, phone: str) -> UaePassProfile | None:
        from integrations.uaepass import start_uaepass_verification

        await start_uaepass_verification(phone)
        await workflows_mistralai.send_assistant_message(
            "I have sent a verification request to your UAE PASS app. Please approve it to continue."
        )
        try:
            await workflows.workflow.wait_condition(
                lambda: self.uaepass_callback is not None,
                timeout=timedelta(minutes=3),
                timeout_summary="uaepass_verification",
            )
        except TimeoutError:
            return None

        callback = self.uaepass_callback
        assert callback is not None
        auth_result: UaePassAuthResult = await exchange_uaepass_code(callback.code)
        if not auth_result.authenticated or auth_result.profile is None:
            return None
        return auth_result.profile

    async def _ask_what_they_need(self) -> str:
        user_input = await self.wait_for_input(
            workflows_mistralai.ChatInput("How can I help you today?"),
            timeout=timedelta(minutes=2),
        )
        return "".join(chunk.text for chunk in user_input.message) if user_input.message else ""

    def _greeting(self, profile: UaePassProfile, ticket_context: TicketContext) -> str:
        name = profile.fullnameEN.split()[0] if profile.fullnameEN else "there"
        greeting = f"Thank you {name}, your identity is verified. "
        if ticket_context.open_tickets:
            numbers = ", ".join(t.number for t in ticket_context.open_tickets)
            greeting += f"I can see you have open tickets {numbers}. "
        if ticket_context.overall_sentiment == "negative":
            greeting += "I'm sorry for the inconvenience you've experienced. "
        return greeting + "How can I help you today?"

    def _build_resolution_agent(
        self, profile: UaePassProfile, ticket_context: TicketContext
    ) -> workflows_mistralai.Agent:
        open_tickets = (
            "\n".join(f"- {t.number}: {t.short_description} (state={t.state})" for t in ticket_context.open_tickets)
            or "none"
        )

        return workflows_mistralai.Agent(
            model="mistral-medium-latest",
            name="dda-call-resolver",
            description="Resolves Digital Dubai Authority citizen requests during an inbound call.",
            instructions=(
                "You are a contact-centre assistant for the Digital Dubai Authority. "
                f"The verified citizen is {profile.fullnameEN} (UUID {profile.uuid}). "
                f"Their open ServiceNow tickets:\n{open_tickets}\n\n"
                "Resolve the citizen's request using the available ServiceNow tools: "
                "update an existing ticket, create a new ticket, or close a ticket once resolved. "
                "Be concise; this is a voice call. Never invent ticket numbers. "
                "If the request cannot be resolved on this call, create or update a ticket "
                "and tell the citizen an agent will follow up."
            ),
            tools=[create_ticket, update_ticket, close_ticket, fetch_caller_tickets],
        )

    async def _resolve_request(
        self,
        agent: workflows_mistralai.Agent,
        request_text: str,
        intent: CallerIntent,
        ticket_context: TicketContext,
        transcript: list[str],
    ) -> dict:
        session = workflows_mistralai.LocalSession()
        new_transcript: list[str] = []

        result = await workflows_mistralai.Runner.run(
            agent=agent,
            inputs=request_text,
            session=session,
            max_turns=8,
        )
        for output in result:
            text = getattr(output, "text", "")
            if text:
                new_transcript.append(f"AI: {text}")

        affected_tickets: list[str] = []
        if intent.category == "existing_ticket" and intent.related_ticket_number:
            affected_tickets = [intent.related_ticket_number]
        elif intent.category == "new_request":
            affected_tickets = []

        return {"new_transcript": new_transcript, "ticket_numbers": affected_tickets}

    async def _close_out(self, profile: UaePassProfile, summary, conversation_id: str) -> None:
        survey_url = summary.survey_url
        actions = "\n".join(f"- {a}" for a in summary.actions_taken) or "- none"
        email_body = (
            f"Dear {profile.fullnameEN or 'Sir/Madam'},\n\n"
            f"{summary.summary}\n\n"
            f"Actions taken:\n{actions}\n\n"
            f"We would appreciate your feedback on this call: {survey_url}\n\n"
            "Digital Dubai Authority Contact Centre"
        )
        sms_body = (
            f"Digital Dubai Authority: thank you for your call. {summary.summary} Share your feedback: {survey_url}"
        )

        if profile.email:
            await send_summary_email(profile.email, "Your Digital Dubai call summary", email_body)
        if profile.mobile:
            await send_summary_sms(profile.mobile, sms_body)

        await log_call_event(
            GenesysEvent(
                conversation_id=conversation_id,
                event_type="workflow_completed",
                detail=f"outcome={summary.outcome}",
            )
        )
