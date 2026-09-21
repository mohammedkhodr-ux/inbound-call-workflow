# Digital Dubai Authority — AI Inbound Call Workflow

An inbound call center workflow for Digital Dubai Authority, where a citizen's call enters through **Genesys**, is handed to a **Mistral AI Voice Agent (AI Studio)**, authenticated via **UAEPASS**, resolved against **ServiceNow**, and closed with an **email + SMS summary and a feedback survey**.

## Call flow

```
Citizen call
    │
    ▼
Genesys Cloud (IVR / routing)
    │  Architect flow invokes the Mistral workflow via webhook
    ▼
Mistral Workflow: dda-inbound-call
    │
    1. authenticate_uaepass ──────────► UAEPASS (identity verification)
    │
    2. fetch_open_tickets ────────────► ServiceNow (open cases)
    3. analyze_tickets_and_sentiment ─► Mistral LLM (context + sentiment)
    │
    4. conversation loop (voice AI): greet, ask "how can we help",
    │   resolve the request using ServiceNow tools
    │
    5. generate_call_summary ────────► Mistral LLM (structured summary)
    6. close_ticket ─────────────────► ServiceNow (close + attach summary)
    7. send_email_summary ───────────► Email service (registered contact)
    8. send_sms_summary ─────────────► SMS gateway (registered contact)
    9. send_survey_link ─────────────► Email + SMS feedback survey
    ▼
Return result to Genesys (call disposition, survey sent, ticket closed)
```

## Repository layout

```
.
├── README.md
├── pyproject.toml
├── .env.example                 # Environment variables for the worker
├── Makefile
├── genesys/
│   └── architect-flow.md        # Genesys Cloud integration contract
└── src/
    ├── entrypoints/worker.py
    └── workflows/
        ├── inbound_call.py      # Workflow orchestration + input/output models
        ├── activities/
        │   ├── uaepass.py       # UAEPASS identity verification
        │   ├── servicenow.py    # ServiceNow ticket operations
        │   ├── agent.py         # Voice AI conversation agent + summary
        │   └── notifications.py # Email / SMS / survey
        └── agents/
            ├── guardrails.py    # Instructions, guardrails, model config
            └── prompts.py       # Voice prompts and survey copy
```

## Setup

```bash
uvx mistralai-workflows-cli@latest setup   # one-time: register API key & scaffold env
uv sync
cp .env.example .env                        # fill in integration credentials
```

## Run

```bash
make start-worker
```

The worker registers the `dda-inbound-call` workflow with Mistral and waits for executions triggered by Genesys.

## Trigger (test / Genesys)

From the Mistral Console → Workflows → `dda-inbound-call` → Start Workflow, or via API:

```json
{
  "call_id": "genesys-call-123",
  "ani": "+971501234567",
  "genesys_conversation_id": "conv-abc-789",
  "language": "en"
}
```

The workflow returns:

```json
{
  "authenticated": true,
  "citizen_name": "Ahmed Al Mansoori",
  "open_tickets_found": 2,
  "ticket_number": "INC0010012",
  "resolution": "...",
  "ticket_closed": true,
  "email_sent": true,
  "sms_sent": true,
  "survey_sent": true
}
```

## Environment variables

| Variable | Purpose |
| --- | --- |
| `MISTRAL_API_KEY` | Mistral API key (set by the setup CLI) |
| `UAEPASS_CLIENT_ID` / `UAEPASS_CLIENT_SECRET` | UAEPASS OIDC service credentials |
| `UAEPASS_ISSUER_URL` | UAEPASS OIDC issuer |
| `UAEPASS_TOKEN_URL` | UAEPASS token endpoint |
| `UAEPASS_USERINFO_URL` | UAEPASS userinfo endpoint |
| `SERVICENOW_INSTANCE` | ServiceNow instance FQDN |
| `SERVICENOW_USER` / `SERVICENOW_PASSWORD` | ServiceNow service account |
| `EMAIL_API_URL` / `EMAIL_API_KEY` | Outbound email API |
| `SMS_API_URL` / `SMS_API_KEY` | Outbound SMS gateway API |
| `SURVEY_URL_TEMPLATE` | Feedback survey link template (`{ticket}` placeholder) |

Secrets are read from the worker environment inside activities; they are never passed as workflow inputs or serialized into execution history.

## Verification

```bash
make verify      # lint + import checks
make start-worker
```
