"""Tests for ServiceNow activity helpers and notification copy."""

from __future__ import annotations

from workflows.activities.notifications import _localized, _survey_url
from workflows.agents import prompts
from workflows.models import CallSummary


def _summary(language: str = "en", ticket: str = "INC001") -> CallSummary:
    return CallSummary(
        topic="Permit",
        citizen_name="Ahmed",
        resolution="Approved.",
        outcome="resolved",
        ticket_number=ticket,
        language=language,
    )


class TestSurveyUrl:
    def test_uses_env_template(self, monkeypatch):
        monkeypatch.setenv("SURVEY_URL_TEMPLATE", "https://s.example.ae/t/{ticket}")
        assert _survey_url("INC001") == "https://s.example.ae/t/INC001"

    def test_fallback_when_missing(self, monkeypatch):
        monkeypatch.delenv("SURVEY_URL_TEMPLATE", raising=False)
        assert _survey_url("INC001") == "https://survey.digitaldubai.gov.ae/call/INC001"

    def test_empty_ticket_uses_na(self, monkeypatch):
        monkeypatch.delenv("SURVEY_URL_TEMPLATE", raising=False)
        assert _survey_url("") == "https://survey.digitaldubai.gov.ae/call/na"


class TestLocalized:
    def test_english(self):
        subject, _, sms, _, _ = _localized(_summary("en"))
        assert subject is prompts.EMAIL_SUBJECT_EN
        assert sms is prompts.SMS_EN

    def test_arabic(self):
        subject, _, sms, _, _ = _localized(_summary("ar"))
        assert subject is prompts.EMAIL_SUBJECT_AR
        assert sms is prompts.SMS_AR


class TestPrompts:
    def test_sms_text_includes_ticket_and_survey(self):
        text = prompts.SMS_EN.format(
            topic="Permit",
            ticket="INC001",
            resolution="Approved.",
            survey_url="https://s.example.ae/t/INC001",
        )
        assert "INC001" in text
        assert "https://s.example.ae/t/INC001" in text
        assert "Digital Dubai Authority" in text
