"""Email, SMS, and survey notification activities."""

import os

import httpx
import mistralai.workflows as workflows

from ..agents import prompts
from ..models import CallSummary, CitizenIdentity


def _require(keys: tuple[str, ...]) -> dict[str, str]:
    missing = [key for key in keys if not os.environ.get(key)]
    if missing:
        raise RuntimeError(f"Missing required environment variables: {', '.join(missing)}")
    return {key: os.environ[key] for key in keys}


def _survey_url(ticket_number: str) -> str:
    template = os.environ.get("SURVEY_URL_TEMPLATE", "https://survey.digitaldubai.gov.ae/call/{ticket}")
    return template.format(ticket=ticket_number or "na")


def _localized(summary: CallSummary) -> tuple:
    if summary.language == "ar":
        subject = prompts.EMAIL_SUBJECT_AR
        body = prompts.EMAIL_BODY_AR
        sms = prompts.SMS_AR
        invite = prompts.SURVEY_INVITE_AR
        name = summary.citizen_name
    else:
        subject = prompts.EMAIL_SUBJECT_EN
        body = prompts.EMAIL_BODY_EN
        sms = prompts.SMS_EN
        invite = prompts.SURVEY_INVITE_EN
        name = summary.citizen_name
    return subject, body, sms, invite, name


@workflows.activity(name="send_email_summary", retry_policy_max_attempts=3)
async def send_email_summary(identity: CitizenIdentity, summary: CallSummary, survey_url: str) -> bool:
    """Email the caller a summary of the call with the survey link.

    Args:
        identity: Verified citizen identity with the registered email.
        summary: Structured call summary.
        survey_url: Feedback survey link for this ticket.
    """
    if not identity.email:
        return False
    config = _require(("EMAIL_API_URL", "EMAIL_API_KEY"))
    subject_template, body_template, _, _, name = _localized(summary)

    follow_up_section = ""
    if summary.follow_up_actions:
        follow_up_section = "Next steps:\n" + "\n".join(f"- {action}" for action in summary.follow_up_actions)

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            config["EMAIL_API_URL"],
            headers={"Authorization": f"Bearer {config['EMAIL_API_KEY']}"},
            json={
                "to": identity.email,
                "subject": subject_template.format(ticket=summary.ticket_number),
                "body": body_template.format(
                    citizen_name=name,
                    topic=summary.topic,
                    ticket=summary.ticket_number,
                    resolution=summary.resolution,
                    follow_up_section=follow_up_section,
                    survey_url=survey_url,
                ),
            },
        )
        response.raise_for_status()
    return True


@workflows.activity(name="send_sms_summary", retry_policy_max_attempts=3)
async def send_sms_summary(identity: CitizenIdentity, summary: CallSummary, survey_url: str) -> bool:
    """SMS the caller a summary of the call with the survey link.

    Args:
        identity: Verified citizen identity with the registered mobile number.
        summary: Structured call summary.
        survey_url: Feedback survey link for this ticket.
    """
    if not identity.mobile:
        return False
    config = _require(("SMS_API_URL", "SMS_API_KEY"))
    _, _, sms_template, _, _ = _localized(summary)
    sms_text = sms_template.format(
        topic=summary.topic,
        ticket=summary.ticket_number,
        resolution=summary.resolution,
        survey_url=survey_url,
    )

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            config["SMS_API_URL"],
            headers={"Authorization": f"Bearer {config['SMS_API_KEY']}"},
            json={"to": identity.mobile, "message": sms_text},
        )
        response.raise_for_status()
    return True


@workflows.activity(name="send_survey_invitation", retry_policy_max_attempts=3)
async def send_survey_invitation(
    identity: CitizenIdentity, summary: CallSummary, survey_url: str
) -> bool:
    """Send a dedicated feedback survey invitation (email + SMS).

    Args:
        identity: Verified citizen identity.
        summary: Structured call summary (used for language).
        survey_url: Feedback survey link for this ticket.
    """
    _, _, _, invite_template, _ = _localized(summary)
    invite_text = invite_template.format(survey_url=survey_url)
    sent = False

    email_config_ok = all(os.environ.get(key) for key in ("EMAIL_API_URL", "EMAIL_API_KEY"))
    sms_config_ok = all(os.environ.get(key) for key in ("SMS_API_URL", "SMS_API_KEY"))

    async with httpx.AsyncClient(timeout=30) as client:
        if email_config_ok and identity.email:
            response = await client.post(
                os.environ["EMAIL_API_URL"],
                headers={"Authorization": f"Bearer {os.environ['EMAIL_API_KEY']}"},
                json={
                    "to": identity.email,
                    "subject": "Rate your Digital Dubai Authority experience",
                    "body": invite_text,
                },
            )
            response.raise_for_status()
            sent = True
        if sms_config_ok and identity.mobile:
            response = await client.post(
                os.environ["SMS_API_URL"],
                headers={"Authorization": f"Bearer {os.environ['SMS_API_KEY']}"},
                json={"to": identity.mobile, "message": invite_text},
            )
            response.raise_for_status()
            sent = True
    return sent
