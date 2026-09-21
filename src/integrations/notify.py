"""Email and SMS notifications for the Digital Dubai inbound call workflow.

After the call ends the caller receives an email and an SMS containing a
summary of the call plus a link to a feedback survey.
"""

from __future__ import annotations

import smtplib
from email.message import EmailMessage

import httpx
import mistralai.workflows as workflows

from integrations.settings import get_settings


@workflows.activity()
async def send_summary_email(to_email: str, subject: str, body: str) -> None:
    """Send the call summary email to the citizen."""
    settings = get_settings().email
    message = EmailMessage()
    message["From"] = settings.sender
    message["To"] = to_email
    message["Subject"] = subject
    message.set_content(body)
    smtp = smtplib.SMTP(settings.smtp_host, settings.smtp_port)
    try:
        smtp.starttls()
        smtp.send_message(message)
    finally:
        smtp.quit()


@workflows.activity()
async def send_summary_sms(to_number: str, body: str) -> None:
    """Send the call summary SMS to the citizen via the SMS gateway."""
    settings = get_settings().sms
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            f"{settings.provider_host}/v1/messages",
            json={"to": to_number, "from": settings.sender_id, "text": body[:1000]},
            headers={"Authorization": f"Bearer {settings.api_key}"},
        )
        response.raise_for_status()
