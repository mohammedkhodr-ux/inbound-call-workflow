"""Models shared across the Digital Dubai inbound call workflow."""

from pydantic import BaseModel, Field


class CallInput(BaseModel):
    """Triggered by Genesys when a call is routed to the Mistral voice AI."""

    model_config = {"extra": "forbid"}

    call_id: str = Field(description="Genesys call identifier")
    ani: str = Field(description="Caller phone number (Automatic Number Identification)")
    genesys_conversation_id: str | None = Field(
        default=None, description="Genesys conversation ID for transcript correlation"
    )
    language: str = Field(default="en", description="Conversation language: en or ar")


class CitizenIdentity(BaseModel):
    """Verified identity returned by UAEPASS."""

    uuid: str = Field(description="UAEPASS unique identifier")
    full_name_en: str = Field(description="Citizen name in English")
    full_name_ar: str = Field(description="Citizen name in Arabic")
    email: str | None = Field(default=None, description="Registered email address")
    mobile: str | None = Field(default=None, description="Registered mobile number")
    emirates_id: str | None = Field(default=None, description="Masked Emirates ID")


class Ticket(BaseModel):
    """A ServiceNow incident/request opened by the citizen."""

    sys_id: str = Field(description="ServiceNow sys_id")
    number: str = Field(description="Human-readable ticket number")
    short_description: str = Field(description="Ticket short description")
    state: str = Field(description="Ticket state label")
    opened_at: str = Field(description="Opened timestamp")
    priority: str = Field(description="Ticket priority")
    sentiment: str | None = Field(default=None, description="Sentiment of recent work notes")


class TicketContext(BaseModel):
    """Aggregated context about the citizen's existing tickets."""

    tickets: list[Ticket] = Field(default_factory=list)
    overall_sentiment: str = Field(default="neutral")
    summary: str = Field(default="")


class CallSummary(BaseModel):
    """Structured summary of the completed conversation."""

    ticket_number: str = Field(default="")
    topic: str = Field(description="Main topic of the call")
    citizen_name: str = Field(default="")
    resolution: str = Field(description="How the request was resolved")
    follow_up_actions: list[str] = Field(default_factory=list)
    outcome: str = Field(default="resolved", description="resolved | escalated | unresolved")
    language: str = Field(default="en")


class WorkflowResult(BaseModel):
    """Final result returned to Genesys."""

    model_config = {"extra": "forbid"}

    call_id: str
    authenticated: bool
    citizen_name: str = ""
    open_tickets_found: int = 0
    ticket_number: str = ""
    resolution: str = ""
    outcome: str = "resolved"
    ticket_closed: bool = False
    email_sent: bool = False
    sms_sent: bool = False
    survey_sent: bool = False
    survey_url: str = ""
