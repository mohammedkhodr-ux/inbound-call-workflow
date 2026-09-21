# DDA Inbound Call — Visual Workflow

## End-to-end call flow

```mermaid
flowchart TD
    subgraph ENTRY["📞 Inbound Call"]
        A["Dubai citizen calls<br/>DDA contact centre"]
        B["Genesys Cloud<br/>voice queue routing"]
        C["Triggers dda-inbound-call workflow<br/>input: conversation_id, phone_number"]
    end

    subgraph AUTH["🪪 Step 1–2 · Identity"]
        D["Fetch call info (Genesys API)<br/>ANI + queue"]
        E["Initiate UAE PASS verification<br/>push to citizen's app"]
        F{{"⏸️ Suspended: wait_condition<br/>uaepass_callback signal<br/>timeout: 3 min"}}
        G["Exchange code → verified profile<br/>UUID · name · mobile · email"]
    end

    subgraph CONTEXT["🗂️ Step 3 · ServiceNow Context"]
        H["Fetch caller's tickets"]
        I["Build ticket context:<br/>open tickets + recently closed<br/>+ sentiment (pos/neutral/neg)"]
    end

    subgraph DIALOGUE["💬 Step 4–5 · Dialogue & Triage"]
        J["Greeting: verified ✓<br/>open tickets + apology<br/>if negative sentiment"]
        K{{"⏸️ Suspended: wait_for_input<br/>'How can I help you today?'<br/>timeout: 2 min"}}
        L["Intent triage — mistral-small<br/>structured CallerIntent:<br/>category · ticket ref · priority"]
    end

    subgraph RESOLUTION["🤖 Step 6 · Resolution Agent"]
        M["mistral-medium agent<br/>with ServiceNow tools"]
        M -->|tool call| M1["create_ticket"]
        M -->|tool call| M2["update_ticket"]
        M -->|tool call| M3["close_ticket"]
        M -->|tool call| M4["fetch_caller_tickets"]
        N{"Resolved<br/>on this call?"}
    end

    subgraph CLOSEOUT["📤 Step 7–8 · Close-out"]
        O["Generate call summary — mistral-small<br/>summary · actions · outcome"]
        P["Close ServiceNow ticket<br/>with resolution notes"]
        Q["📧 Email summary<br/>+ survey link"]
        R["📱 SMS summary<br/>+ survey link"]
        S["Log workflow_completed<br/>event to Genesys"]
    end

    A --> B --> C --> D --> E --> F
    F -->|callback code| G
    F -->|timeout ❌| X1["Return: authentication_failed<br/>(graceful message)"]
    G --> H --> I --> J --> K
    K -->|caller speaks| L --> M
    K -->|timeout ❌| X2["Graceful early exit"]
    N -->|yes| P
    N -->|no — escalate| X3["Create/update ticket,<br/>agent will follow up"]
    M --> N
    X3 --> O
    P --> O --> Q --> R --> S
```

## Swimlane view (who does what)

```mermaid
flowchart LR
    subgraph CITIZEN["Citizen"]
        c1["Calls"]
        c2["Approves UAE PASS"]
        c3["States request"]
    end

    subgraph GENESYS["Genesys Cloud"]
        g1["IVR / routing"]
        g2["Conversation events"]
    end

    subgraph MISTRAL["Mistral AI Studio"]
        m1["dda-inbound-call<br/>(durable workflow)"]
        m2["Intent triage"]
        m3["Resolution agent"]
        m4["Call summary"]
    end

    subgraph EXTERNAL["External Systems"]
        u1["UAE PASS"]
        s1["ServiceNow"]
        n1["Email/SMS gateway"]
    end

    c1 --> g1 --> m1
    m1 --> u1 --> c2
    u1 -->|signal: uaepass_callback| m1
    m1 --> s1
    m1 --> m2 --> m3 -->|tools| s1
    c3 --> m1
    m1 --> m4 --> n1 --> c1
    m1 --> g2
```

## Execution timeline (what Studio shows)

```mermaid
sequenceDiagram
    participant C as Citizen
    participant W as Workflow (durable)
    participant U as UAE PASS
    participant S as ServiceNow
    participant N as Email/SMS

    C->>W: 📞 call routed from Genesys
    W->>W: fetch_call_info
    W->>U: initiate verification
    Note over W: ⏸️ suspended (no compute) —<br/>waiting for uaepass_callback signal
    C->>U: approves in UAE PASS app
    U-->>W: signal: uaepass_callback {code}
    W->>U: exchange code → profile
    W->>S: fetch tickets + sentiment
    W->>C: greeting (tickets, sentiment-aware)
    Note over W: ⏸️ suspended — wait_for_input<br/>"How can I help you today?"
    C->>W: states request
    W->>W: intent triage (mistral-small)
    W->>S: resolution agent tool calls<br/>(create / update / close)
    W->>S: close ticket + resolution notes
    W->>W: call summary (mistral-small)
    W->>N: email + SMS with survey link
    W->>W: log Genesys event → ✅ completed
```

Key visual points:
- The two ⏸️ **suspension points** (UAE PASS approval, caller dialogue) are where the
  durable workflow parks at zero compute until an external event resumes it.
- **Sentiment** from ServiceNow history shapes the greeting (apology on negative).
- The **resolution agent** acts on ServiceNow directly through tools — no human
  routing unless it decides to escalate.
- **Every branch, retry, and state change** appears on the live execution timeline
  in Mistral AI Studio.
