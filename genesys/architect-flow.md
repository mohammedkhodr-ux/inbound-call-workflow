# Genesys Cloud integration

The Genesys Cloud Architect inbound flow hands the call to the Mistral voice AI
and triggers this workflow.

## Call routing

1. **Inbound route** `DDA Call Center` points to an Architect inbound flow.
2. The Architect flow plays the welcome prompt, detects the caller's language
   (English/Arabic), then invokes a **Call Data Action** `Start DDA AI Call`.
3. The data action calls the Mistral workflow execution API:

   ```json
   POST /v1/workflow_executions/dda-inbound-call
   {
     "input": {
       "call_id": "${pc.call.callId}",
       "ani": "${pc.call.callerId}",
       "genesys_conversation_id": "${pc.conversationId}",
       "language": "${Flow.language}"
     }
   }
   ```

4. The workflow returns a `WorkflowResult`; the Architect flow branches on
   `outcome`:
   - `resolved` → closing prompt and disconnect
   - `escalated`/`unresolved` → transfer to the `DDA Human Support` queue

## Voice bridge

The voice AI leg can run either way:

- **AI Studio voice agent**: Genesys AudioConnect bridges the call to the Mistral
  voice agent endpoint configured with the `dda-voice-agent`; the workflow drives
  the same agent loop for tool use and durable state.
- **Genesys bot + workflow tools**: the Architect flow drives the dialog and
  calls workflow updates for each turn; the transcript is accumulated in the
  workflow.

## Data Action contract

| Input | Source | Output |
| --- | --- | --- |
| `call_id` | `pc.call.callId` | `call_id` |
| `ani` | `pc.call.callerId` | `authenticated`, `citizen_name` |
| `genesys_conversation_id` | `pc.conversationId` | `open_tickets_found` |
| `language` | flow variable | `ticket_number`, `resolution`, `outcome` |

Genesys disconnects the caller only after the workflow returns; post-call email,
SMS, and survey steps continue after call end and are recorded in the result.
