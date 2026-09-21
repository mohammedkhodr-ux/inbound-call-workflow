"""Tests for the inbound call workflow's pure helpers."""

from __future__ import annotations

from integrations.servicenow import ServiceNowTicket, TicketContext
from integrations.uaepass import UaePassProfile
from workflows.inbound_call import InboundCallWorkflow


def _profile(name: str = "Ahmed Al Mansouri") -> UaePassProfile:
    return UaePassProfile(uuid="uuid-1", fullnameEN=name, mobile="+971500000000", email="a@example.ae")


def _context(sentiment: str = "neutral") -> TicketContext:
    return TicketContext(
        open_tickets=[
            ServiceNowTicket(
                sys_id="s1", number="INC001", short_description="Passport renewal", state="1", priority="4"
            )
        ],
        recent_closed_tickets=[],
        overall_sentiment=sentiment,
        summary="The caller has INC001 (New, Low).",
    )


class TestGreeting:
    def test_includes_first_name_and_tickets(self):
        wf = InboundCallWorkflow()
        greeting = wf._greeting(_profile(), _context())
        assert greeting.startswith("Thank you Ahmed")
        assert "INC001" in greeting
        assert "How can I help you today?" in greeting

    def test_apologises_for_negative_sentiment(self):
        wf = InboundCallWorkflow()
        greeting = wf._greeting(_profile(), _context(sentiment="negative"))
        assert "sorry" in greeting

    def test_no_tickets(self):
        wf = InboundCallWorkflow()
        greeting = wf._greeting(_profile(), TicketContext())
        assert "open tickets" not in greeting

    def test_falls_back_when_no_name(self):
        wf = InboundCallWorkflow()
        greeting = wf._greeting(_profile(name=""), TicketContext())
        assert greeting.startswith("Thank you there")


class TestCloseOut:
    async def test_sends_email_and_sms(self, mock_llm, mock_servicenow, monkeypatch):
        from workflows import inbound_call as wf_module

        emails: list[tuple[str, str, str]] = []
        smss: list[tuple[str, str]] = []

        async def fake_email(to_email, subject, body):
            emails.append((to_email, subject, body))

        async def fake_sms(to_number, body):
            smss.append((to_number, body))

        async def fake_log(event):
            pass

        monkeypatch.setattr(wf_module, "send_summary_email", fake_email)
        monkeypatch.setattr(wf_module, "send_summary_sms", fake_sms)
        monkeypatch.setattr(wf_module, "log_call_event", fake_log)

        from workflows.ai_activities import CallSummary

        summary = CallSummary(
            summary="Your request was handled.",
            actions_taken=["Created ticket INC0100"],
            outcome="resolved",
            survey_url="https://surveys.dda.gov.ae/f/abc",
        )
        wf = InboundCallWorkflow()
        await wf._close_out(_profile(), summary, conversation_id="conv-1")

        assert len(emails) == 1
        to, subject, body = emails[0]
        assert to == "a@example.ae"
        assert "Digital Dubai" in subject
        assert "surveys.dda.gov.ae" in body
        assert "INC0100" in body
        assert len(smss) == 1
        assert "surveys.dda.gov.ae" in smss[0][1]


class TestWorkflowRegistration:
    def test_workflow_definition(self):
        import mistralai.workflows as workflows

        spec = workflows.get_workflow_definition(InboundCallWorkflow)
        assert spec.name == "dda-inbound-call"
        assert spec.display_name == "DDA Inbound Call"

    def test_input_output_models(self):
        from workflows.inbound_call import InboundCallInput, InboundCallOutput

        data = InboundCallInput(conversation_id="conv-1")
        assert data.phone_number == ""
        out = InboundCallOutput(status="completed")
        assert out.ticket_numbers == []
