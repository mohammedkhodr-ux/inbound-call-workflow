"""UAEPASS identity integration for the Digital Dubai inbound call workflow.

A citizen calling the Digital Dubai Authority contact centre is authenticated
with UAE PASS. In production the Genesys voice bot triggers a UAE PASS
verification (push notification in the UAE PASS mobile app or an OTP), the
citizen approves it, and UAE PASS calls back with an authorisation code that is
exchanged for the citizen's verified profile (UUID, name, mobile, email).
Unconfigured credentials fall back to a demo profile so the workflow can be
exercised end-to-end.

Third-party imports (httpx) happen inside the activities under
``workflows.unsafe.imports_passed_through()``: this module is imported by the
workflow module, which the Temporal determinism sandbox re-imports, so its
top level must stay free of third-party imports.
"""

from __future__ import annotations

import mistralai.workflows as workflows
import structlog
from pydantic import BaseModel

from integrations.settings import get_settings

logger = structlog.get_logger(__name__)


class UaePassProfile(BaseModel):
    uuid: str
    fullnameEN: str
    mobile: str
    email: str


class UaePassAuthResult(BaseModel):
    authenticated: bool
    profile: UaePassProfile | None = None
    failure_reason: str = ""


@workflows.activity(retry_policy_max_attempts=2)
async def start_uaepass_verification(phone_number: str) -> str:
    """Trigger a UAEPASS verification request for the caller's phone number.

    Returns the UAEPASS transaction reference that the callback will echo back.
    """
    settings = get_settings().uaepass
    if not settings.configured:
        logger.warning(
            "UAE PASS is not configured; returning a demo verification reference",
            phone_number=phone_number,
        )
        return "demo-verification"

    with workflows.unsafe.imports_passed_through():
        import httpx

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            f"{settings.host}/idprofile/verify/initiate",
            json={"mobileNumber": phone_number, "clientId": settings.client_id},
            auth=(settings.client_id, settings.client_secret),
        )
        response.raise_for_status()
        return response.json()["transactionId"]


@workflows.activity(retry_policy_max_attempts=2)
async def exchange_uaepass_code(code: str) -> UaePassAuthResult:
    """Exchange a UAEPASS authorisation code for the verified citizen profile."""
    settings = get_settings().uaepass
    if not settings.configured:
        logger.warning("UAE PASS is not configured; returning a demo profile", code=code)
        return UaePassAuthResult(
            authenticated=True,
            profile=UaePassProfile(
                uuid="demo-citizen-uuid",
                fullnameEN="Demo Citizen",
                mobile="",
                email="",
            ),
        )

    with workflows.unsafe.imports_passed_through():
        import httpx

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            f"{settings.host}/idprofile/verify/token",
            data={"code": code, "grant_type": "authorization_code", "redirect_uri": settings.redirect_uri},
            auth=(settings.client_id, settings.client_secret),
        )
        if response.status_code != 200:
            return UaePassAuthResult(
                authenticated=False,
                failure_reason=f"UAEPASS exchange failed: {response.status_code}",
            )
        token = response.json()["access_token"]
        profile_response = await client.get(
            f"{settings.host}/idprofile/userinfo",
            headers={"Authorization": f"Bearer {token}"},
        )
        profile_response.raise_for_status()
        profile = profile_response.json()
    return UaePassAuthResult(
        authenticated=True,
        profile=UaePassProfile(
            uuid=profile["uuid"],
            fullnameEN=profile.get("fullnameEN", ""),
            mobile=profile.get("mobile", ""),
            email=profile.get("email", ""),
        ),
    )
