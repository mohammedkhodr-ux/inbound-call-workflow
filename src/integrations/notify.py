"""Email and SMS notifications for the Digital Dubai inbound call workflow.

After the call ends the caller receives an email and an SMS containing a
summary of the call plus a link to a feedback survey. Unconfigured gateways
log the notification instead of failing the call close-out, so the workflow
can be exercised end-to-end without live credentials.

Third-party imports (smtplib, httpx) happen inside the activities under
``workflows.unsafe.imports_passed_through()``: this module is imported by the
workflow module, which the Temporal determinism sandbox re-imports, so its
top level must stay free of third-party imports.
"""

from __future__ import annotations

import asyncio

import mistralai.workflows as workflows
import structlog

from integrations.settings import get_settings

logger = structlog.get_logger(__name__)


@workflows.activity()
async def build_survey_url(execution_id: str, phone: str = "") -> str:
    """Render the feedback-survey URL for this call.

    Runs as an activity so workflow code never reads environment settings.
    """
    template = get_settings().survey_url_template
    try:
        return template.format(execution_id=execution_id, phone=phone)
    except (KeyError, IndexError):
        # The template does not use the phone placeholder
        return template.format(execution_id=execution_id)


@workflows.activity()
async def send_summary_email(to_email: str, subject: str, body: str) -> None:
    """Send the call summary email to the citizen.

    Without SMTP settings or a recipient address the email is logged as a demo
    notification instead of failing the call close-out.
    """
    settings = get_settings().email
    if not to_email or not settings.configured:
        logger.info(
            "Email gateway is not configured; logging demo email",
            to=to_email or "(no address)",
            subject=subject,
            body=body,
        )
        return

    with workflows.unsafe.imports_passed_through():
        import smtplib
        from email.message import EmailMessage

    message = EmailMessage()
    message["From"] = settings.sender
    message["To"] = to_email
    message["Subject"] = subject
    message.set_content(body)

    def _send() -> None:
        smtp = smtplib.SMTP(settings.smtp_host, settings.smtp_port)
        try:
            smtp.starttls()
            smtp.send_message(message)
        finally:
            smtp.quit()

    await asyncio.to_thread(_send)


@workflows.activity()
async def send_summary_sms(to_number: str, body: str) -> None:
    """Send the call summary SMS to the citizen via the SMS gateway.

    Without gateway settings or a number the SMS is logged as a demo
    notification instead of failing the call close-out.
    """
    settings = get_settings().sms
    if not to_number or not settings.configured:
        logger.info(
            "SMS gateway is not configured; logging demo SMS",
            to=to_number or "(no number)",
            body=body,
        )
        return

    with workflows.unsafe.imports_passed_through():
        import httpx

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            f"{settings.provider_host}/v1/messages",
            json={"to": to_number, "from": settings.sender_id, "text": body[:1000]},
            headers={"Authorization": f"Bearer {settings.api_key}"},
        )
        response.raise_for_status()
