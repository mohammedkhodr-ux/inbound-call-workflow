# DDA Inbound Call — Visual Workflow

## End-to-end call flow

```mermaid
flowchart TD
    subgraph ENTRY["📞 Inbound Call"]
        A["Dubai citizen calls<br/>DDA contact centre"]
        B["Genesys Cloud routing<br/>(Architect inbound flow)"]
        C["Call Data Action triggers<br/>dda-inbound-call workflow<br/>input: call_id, ani, language"]
    end

    subgraph AUTH["🪪 Step 1 · Identity"]
        D["authenticate_uaepass<br/>OIDC backchannel lookup by ANI<br/>→ CitizenIdentity"]
    end

    subgraph CONTEXT["🗂️ Step 2 · ServiceNow Context"]
        E["fetch_open_tickets<br/>by u_epass_uuid"]
        F["analyze_tickets_and_sentiment<br/>tickets + overall sentiment<br/>(pos/neutral/neg)"]
    end

    subgraph DIALOGUE["💬 Step 3 · Voice AI Conversation"]
        G["Durable agent (RemoteSession)<br/>mistral-large, EN/AR<br/>voice-channel guardrails"]
        G -->|tool call| G1["get_ticket_details"]
        G -->|tool call| G2["create_ticket"]
        G -->|tool call| G3["update_ticket"]
        G -->|tool call| G4["escalate_ticket"]
        H{"Resolved<br/>on this call?"}
    end

    subgraph CLOSEOUT["📤 Step 4 · Close-out"]
        I["generate_call_summary<br/>chat.parse → CallSummary<br/>topic · resolution · outcome"]
        J["close_ticket<br/>state=7 + summary notes"]
        K["📧 send_email_summary<br/>EN/AR + survey link"]
        L["📱 send_sms_summary<br/>EN/AR + survey link"]
        M["⭐ send_survey_invitation<br/>email + SMS"]
        N["Return WorkflowResult<br/>to Genesys"]
    end

    X1["escalate_ticket →<br/>DDA Human Support queue<br/>outcome=escalated"]

    A --> B --> C --> D
    D -->|lookup failed ❌| X2["Return: authenticated=false"]
    D -->|verified ✓| E --> F --> G
    G --> H
    H -->|yes ✓| I --> J --> K --> L --> M --> N
    H -->|no — cannot resolve| X1
    X1 --> I
```

## Swimlane view

```mermaid
flowchart LR
    subgraph CITIZEN["Citizen"]
        A1["Calls DDA"]
        A2["Speaks with the AI<br/>(EN or AR)"]
        A3["Receives email/SMS<br/>+ survey link"]
    end
    subgraph GENESYS["Genesys Cloud"]
        B1["Routes call,<br/>passes ANI + language"]
    end
    subgraph MISTRAL["Mistral voice AI + workflow"]
        C1["UAEPASS backchannel auth"]
        C2["Ticket context + sentiment"]
        C3["Voice agent with<br/>ServiceNow tools"]
        C4["Summary + close-out<br/>orchestration"]
    end
    subgraph SNOW["ServiceNow"]
        D1["Open tickets"]
        D2["Create/update/<br/>escalate/close"]
    end
    subgraph NOTIFY["Email / SMS"]
        E1["Call summary"]
        E2["Survey invitation"]
    end

    A1 --> B1 --> C1 --> C2 --> C3
    C2 --> D1
    C3 --> D2
    C3 --> C4
    C4 --> E1 --> A3
    C4 --> E2
```

## Sequence

See [architecture.md](architecture.md) for the full sequence diagram and
activity-by-activity description.
