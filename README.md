# DDA Inbound Call Workflow

A [Mistral Workflows](https://docs.mistral.ai/studio/workflows) project implementing the
Digital Dubai Authority (DDA) inbound contact-centre flow:

> A Dubai citizen calls the DDA call centre → **Genesys Cloud** routes the call to the
> **Mistral voice AI** → the caller is authenticated with **UAE PASS** → existing
> **ServiceNow** tickets and sentiment are loaded as context → the AI asks what the
> caller needs and attempts to resolve the request → the relevant ticket is closed or
> updated → the caller receives an **email and SMS summary** with a **feedback survey** link.

## Architecture

```
Citizen ──phone──▶ Genesys Cloud ──▶ Mistral AI Studio Voice AI (this workflow)
                                        │
                                        ├── 1. Fetch call info (ANI, queue)
                                        ├── 2. UAEPASS verification  ──signal──▶ uaepass_callback
                                        ├── 3. ServiceNow: tickets + sentiment context
                                        ├── 4. Ask "How can I help you today?"
                                        ├── 5. Intent triage (mistral-small, structured output)
                                        ├── 6. Resolution agent (mistral-medium + ServiceNow tools)
                                        ├── 7. Close / update ServiceNow ticket
                                        └── 8. Email + SMS summary with survey link
```

| Step | Component | Files |
|---|---|---|
| Voice routing context | `integrations/genesys.py` | conversation ID → ANI, queue, event logging |
| Identity | `integrations/uaepass.py` | verification initiation, code → profile exchange |
| Ticket context & actions | `integrations/servicenow.py` | fetch tickets, sentiment, create/update/close |
| Notifications | `integrations/notify.py` | email + SMS with survey link |
| AI steps | `workflows/ai_activities.py` | intent triage, call summary (structured output) |
| Orchestration | `workflows/inbound_call.py` | the `dda-inbound-call` workflow |

## Quick start

```bash
uv sync                     # or: pip install -e ".[dev]"
cp .env.example .env        # fill in credentials
make start-worker           # registers dda-inbound-call with Mistral Workflows
```

Trigger an execution from the Mistral Console (Workflows → DDA Inbound Call) with:

```json
{ "conversation_id": "<genesys-conversation-id>", "phone_number": "+971..." }
```

Or via the API:

```python
from mistralai import Mistral

client = Mistral(api_key="...")
execution = client.workflows.execute_workflow(
    workflow_identifier="dda-inbound-call",
    input={"conversation_id": "abc-123", "phone_number": "+971501234567"},
)
```

## Human-in-the-loop points

- **UAEPASS approval** — after verification is initiated, the workflow suspends on
  `wait_condition` until the UAEPASS callback webhook sends the `uaepass_callback`
  signal with the authorisation code (3-minute timeout).
- **Call dialogue** — the workflow converses through
  `InteractiveWorkflow.wait_for_input`, so each caller turn resumes a suspended
  execution; durable history survives worker restarts mid-call.

## UAEPASS callback (signal)

Wire the UAEPASS redirect endpoint to send the signal to the running execution:

```python
from mistralai import Mistral

client = Mistral(api_key="...")
client.workflows.executions.signal_workflow_execution(
    execution_id="<execution-id>",
    name="uaepass_callback",
    input={"code": "<uaepass-authorization-code>"},
)
```

## Development

```bash
make test     # unit tests (all external systems stubbed)
make lint     # ruff
```

## Configuration

All credentials and endpoints are environment variables — see [.env.example](.env.example).
Never commit real secrets; the workflow reads them at worker start.

## Notes

- The resolution agent uses `LocalSession` with `mistral-medium-latest`; switch to
  `RemoteSession(stream=True)` to stream responses to the voice UI.
- ServiceNow sentiment is currently a keyword heuristic over ticket descriptions;
  it can be upgraded to a Mistral classification call without changing the workflow.
- Ticket close-out uses ServiceNow incident states (1 New / 2 In Progress / 3 On Hold /
  7 Closed); adjust `close_ticket` if your instance uses custom states.
