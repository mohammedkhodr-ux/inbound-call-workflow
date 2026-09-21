"""UAEPASS identity verification activity.

Exchanges the caller's phone number for a UAEPASS-verified identity using the
backchannel (service) flow: the call center resolves the caller's UAEPASS UUID
from the verified phone number (ANI), then fetches their profile. In production
this hits the UAEPASS OIDC endpoints; credentials are read from the worker
environment and never appear in workflow inputs.
"""

import os

import httpx
import mistralai.workflows as workflows

from ..models import CitizenIdentity


def _config() -> dict[str, str]:
    required = (
        "UAEPASS_TOKEN_URL",
        "UAEPASS_USERINFO_URL",
        "UAEPASS_CLIENT_ID",
        "UAEPASS_CLIENT_SECRET",
    )
    missing = [key for key in required if not os.environ.get(key)]
    if missing:
        raise RuntimeError(f"Missing required environment variables: {', '.join(missing)}")
    return {key: os.environ[key] for key in required}


@workflows.activity(
    name="authenticate_uaepass",
    retry_policy_max_attempts=3,
    retry_policy_backoff_coefficient=2.0,
)
async def authenticate_uaepass(phone_number: str) -> CitizenIdentity:
    """Verify the caller's identity via UAEPASS.

    Args:
        phone_number: The caller's verified phone number (ANI from Genesys).
    """
    config = _config()
    async with httpx.AsyncClient(timeout=30) as client:
        token_response = await client.post(
            config["UAEPASS_TOKEN_URL"],
            data={
                "grant_type": "client_credentials",
                "client_id": config["UAEPASS_CLIENT_ID"],
                "client_secret": config["UAEPASS_CLIENT_SECRET"],
                "scope": "urn:uaepass:profile",
            },
        )
        token_response.raise_for_status()
        access_token = token_response.json()["access_token"]

        lookup = await client.get(
            config["UAEPASS_USERINFO_URL"],
            params={"phone": phone_number},
            headers={"Authorization": f"Bearer {access_token}"},
        )
        lookup.raise_for_status()
        profile = lookup.json()

    return CitizenIdentity(
        uuid=profile["uuid"],
        full_name_en=profile.get("fullnameEN", ""),
        full_name_ar=profile.get("fullnameAR", ""),
        email=profile.get("email"),
        mobile=profile.get("mobile") or phone_number,
        emirates_id=profile.get("emiratesId"),
    )
