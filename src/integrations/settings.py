"""Settings for the Digital Dubai inbound call workflow integrations.

All values are read from environment variables (or an .env file) so the worker
can run unchanged across local, staging and production environments.
"""

from __future__ import annotations

import os
from functools import lru_cache

from pydantic import BaseModel, Field


class GenesysSettings(BaseModel):
    region: str = Field(default="mcs2", alias="GENESYS_REGION")
    client_id: str = Field(default="", alias="GENESYS_CLIENT_ID")
    client_secret: str = Field(default="", alias="GENESYS_CLIENT_SECRET")
    queue_id: str = Field(default="", alias="GENESYS_VOICE_QUEUE_ID")


class UaePassSettings(BaseModel):
    host: str = Field(default="https://id.uaepass.ae", alias="UAEPASS_HOST")
    client_id: str = Field(default="", alias="UAEPASS_CLIENT_ID")
    client_secret: str = Field(default="", alias="UAEPASS_CLIENT_SECRET")
    redirect_uri: str = Field(default="", alias="UAEPASS_REDIRECT_URI")


class ServiceNowSettings(BaseModel):
    instance: str = Field(default="", alias="SERVICENOW_INSTANCE")
    user: str = Field(default="", alias="SERVICENOW_USER")
    password: str = Field(default="", alias="SERVICENOW_PASSWORD")


class EmailSettings(BaseModel):
    smtp_host: str = Field(default="localhost", alias="SMTP_HOST")
    smtp_port: int = Field(default=587, alias="SMTP_PORT")
    sender: str = Field(default="contactcentre@dda.gov.ae", alias="EMAIL_SENDER")


class SmsSettings(BaseModel):
    provider_host: str = Field(default="", alias="SMS_PROVIDER_HOST")
    api_key: str = Field(default="", alias="SMS_API_KEY")
    sender_id: str = Field(default="DDA-GOV", alias="SMS_SENDER_ID")


class Settings(BaseModel):
    genesys: GenesysSettings = Field(default_factory=GenesysSettings)
    uaepass: UaePassSettings = Field(default_factory=UaePassSettings)
    servicenow: ServiceNowSettings = Field(default_factory=ServiceNowSettings)
    email: EmailSettings = Field(default_factory=EmailSettings)
    sms: SmsSettings = Field(default_factory=SmsSettings)
    survey_url_template: str = Field(
        default="https://surveys.dda.gov.ae/f/{execution_id}",
        alias="SURVEY_URL_TEMPLATE",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Load settings once per process from environment variables."""
    values: dict = {}
    for field in Settings.model_fields.values():
        if field.default_factory is None:
            env_name = field.alias.upper()
            values[field.alias] = os.environ.get(env_name, field.default)
    for section in (GenesysSettings, UaePassSettings, ServiceNowSettings, EmailSettings, SmsSettings):
        section_fields = {}
        for field in section.model_fields.values():
            env_name = field.alias.upper()
            if env_name in os.environ:
                section_fields[field.alias] = os.environ[env_name]
        values[section.__name__.lower().removesuffix("settings")] = section_fields
    return Settings.model_validate(values)
