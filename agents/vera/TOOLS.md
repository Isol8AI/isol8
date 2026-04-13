# Vera — Tool Usage Guide

## Lobster (Pipeline Orchestration)

Available pipelines:
- `intake-resolve.lobster` — main ticket handling (triggered per incoming message)
- `escalation.lobster` — full escalation with context handoff (triggered from intake)
- `agent-assist.lobster` — background assist for human agents (triggered when agent picks up ticket)
- `weekly-report.lobster` — Monday metrics + learning (cron: Monday 8am)

## llm-task (Structured LLM Subtasks)

- `thinking: "off"` — intake classification (ambiguous only ~30%), confidence checks
- `thinking: "low"` — response generation, escalation suggested resolution, agent assist drafts, weekly CSAT failure analysis, KB gap clustering
- Never use `thinking: "medium"` or higher in pipelines

## local-rag-qdrant (Knowledge Base)

Vera's architectural foundation. Every business-specific response queries this vector database. Collection: `vera-knowledge-base`. Documents include: policies, FAQs, product documentation, SOPs, pricing sheets, return/refund policies.

Ingestion: user uploads documents during setup. Vera indexes them into Qdrant with `last_updated` timestamps per document. Articles older than 90 days are flagged as potentially stale.

Query: semantic search with top-5 retrieval per customer question. Retrieved chunks feed into the confidence check and response generation.

## slack (Escalation + Notifications)

Channels:
- `#vera-escalations` — escalated tickets with full context packages (human agents monitor this)
- `#vera-digest` — daily status, weekly reports
- `#vera-admin` — escalation health alerts, system warnings

Agent assist surfaces in Slack threads within `#vera-escalations` — the human agent sees Vera's suggestions in-thread without the customer seeing them.

## gog (Google Workspace)

Gmail: email support channel — incoming support emails processed by Vera.
Google Sheets: weekly metrics reports with historical tracking.
Google Drive: weekly narrative reports, knowledge base document source files.

## summarize (Content Compression)

CLI tool, zero LLM. Used for: escalation transcript summaries, conversation history compression, weekly report formatting. Every escalation handoff uses summarize to create the tight summary the human agent reads.

## Helpdesk Integration (click-to-connect, singular)

The user connects one helpdesk in the Isol8 settings UI — Zendesk or Intercom. The connection is stored at `vera-config/connected-helpdesk` in fast-io. Pipelines branch on `$load-helpdesk-config.json.platform` at runtime and route all helpdesk operations through the matching direct API.

### Zendesk (direct API)
When `platform == "zendesk"`. Customer lookup, ticket creation, status updates via `curl` to `{subdomain}.zendesk.com/api/v2/` with Basic auth (`$ZENDESK_EMAIL/token:$ZENDESK_API_TOKEN`). Requires `ZENDESK_SUBDOMAIN`, `ZENDESK_EMAIL`, `ZENDESK_API_TOKEN`.

### Intercom (direct API)
When `platform == "intercom"`. Customer lookup, conversation management via `curl` to `api.intercom.io/` with Bearer `$INTERCOM_ACCESS_TOKEN`. Requires `INTERCOM_ACCESS_TOKEN`.

### Standalone mode
If no helpdesk is connected, Vera operates in standalone mode — tickets tracked in taskr + fast-io, customer data from `vera-customers/{{email}}`. When the user asks for something requiring a helpdesk, Vera says: "To do that, I need access to your helpdesk. You can connect Zendesk or Intercom in your settings."

## telcall-twilio (Voice Escalation)

Two uses:
1. Outbound emergency call to human contact when a customer is in genuine distress and Slack escalation isn't fast enough
2. Inbound voice support channel — processes phone calls with same classification and escalation logic

Only used for urgent priority escalations or when the user has configured voice as a support channel.

## Perplexity API (Structured Web Search)

Vera's structured-web-search engine for agent assist and KB freshness checks. Runs when a human agent needs current information not in the KB — recent policy changes, product updates, carrier status — and during weekly KB freshness verification.

**Not a ClawHub skill.** Called via direct `curl` from lobster `exec --shell` steps. The Perplexity `sonar` model returns structured web search with citations: `choices[0].message.content` plus a `citations[]` array of source URLs. This is a deterministic API — same query → same response shape — so every call is a deterministic step, NOT an llm-task call.

Canonical call shape:
```
curl -sS https://api.perplexity.ai/chat/completions \
  -H "Authorization: Bearer $PERPLEXITY_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"sonar","messages":[{"role":"user","content":"<query>"}]}'
```

In pipelines, curl is piped into an inline `node -e` normalizer that extracts `content`, `citations`, `top_urls`, `high_signal_urls`. Auth credential `PERPLEXITY_API_KEY` is set at the process environment level (not in `openclaw.json`).

For structured web search: Perplexity API. For raw page fetch / deep reading of a specific URL: agent-browser.

## agent-browser (Deep Web Reading + External Lookups)

When a human agent handling an escalated ticket needs information from external systems — live order status from a logistics portal, carrier tracking pages, account balances from payment providers. Vera retrieves it via agent-browser so the human doesn't have to open a separate tab.

Also used for KB gap research — when Vera flags a question she can't answer, agent-browser can research the correct answer from authoritative sources so the user can add it to the KB. Paired with Perplexity API: Perplexity for broad search, agent-browser for deep extraction.

## capability-evolver (Learning Loop)

Weekly analysis of: CSAT failure patterns, escalation rate trends, KB gap accumulation, confidence threshold calibration. Reads from weekly report data, identifies recurring issues, and recommends specific improvements.

## taskr (Active Ticket State)

Tracks: open tickets, pending confirmation tickets (48-hour timer), active escalations, conversation exchange counts, sentiment history per conversation. Paired with fast-io for long-term storage.

## fast-io (Persistent Storage)

Key structure:
- `vera-config/escalation-path` — escalation channel configuration
- `vera-config/business-hours` — staffed hours, timezone, out-of-hours behavior
- `vera-config/authorized-actions` — max refund amount, allowed autonomous actions
- `vera-config/confidence-threshold` — default 0.85
- `vera-state/escalation-health` — current health status (green/yellow/red)
- `vera-conversations/{{id}}` — conversation history and sentiment trail
- `vera-csat/{{ticket_id}}` — CSAT scores with ticket metadata
- `vera-kb-gaps/{{date}}/{{id}}` — unanswered questions
- `vera-kb-conflicts/{{date}}/{{id}}` — contradicting KB articles
- `vera-kb-stale/{{date}}` — articles not updated in 90+ days
- `vera-callbacks/{{id}}` — out-of-hours callback queue
- `audit/{{timestamp}}/{{action}}/{{id}}` — 12-month audit trail

## Direct API Integrations

### Stripe API
Refund processing. When Vera determines a refund is eligible within authorized scope, Stripe executes the transaction. Requires `STRIPE_API_KEY`. Only processes refunds within the configured max amount.

### Twilio SMS API
SMS support channel. Inbound messages processed by intake-resolve, outbound responses sent via Twilio. Requires `TWILIO_ACCOUNT_SID` and `TWILIO_AUTH_TOKEN`.

### SendGrid or Postmark API
Transactional email: CSAT survey delivery, escalation confirmations, ticket reference numbers, callback scheduling confirmations, weekly report delivery. Requires `SENDGRID_API_KEY` or `POSTMARK_API_KEY`.

### Survey Tools (click-to-connect)
CSAT survey collection for email-channel resolutions. The user connects one survey tool in settings: Delighted, Typeform, or Google Forms. If the user asks for CSAT and no survey tool is connected, Vera says: "To send CSAT surveys, connect a survey tool in your settings. Supported: Delighted, Typeform, Google Forms." Until connected, Vera skips the CSAT-send step and logs the gap.

## Security

- `skill-vetter` — run against every skill before production
- `sona-security-audit` — runtime monitoring of all installed skills
- Vera handles customer PII, payment data, and complaint history — the attack surface for a compromised skill is significant

## Click-to-Connect Integrations

Every integration Vera touches is enabled by the user through the Isol8 settings UI — never through an onboarding prompt. Vera only mentions a missing integration when the user asks for something that requires it.

### Helpdesk — click-to-connect (singular)
Zendesk, Intercom. One helpdesk per user. Stored at `vera-config/connected-helpdesk`. See "Helpdesk Integration" section above.

### CRM — click-to-connect
HubSpot, Salesforce, Attio, Pipedrive. For customer lookup and history enrichment. When the user asks for CRM data and none is connected, Vera says: "To look up customer history in your CRM, connect one in your settings. Supported: HubSpot, Salesforce, Attio, Pipedrive."

### Survey tools — click-to-connect
Delighted, Typeform, Google Forms. For CSAT survey delivery. See "Survey Tools" under Direct API Integrations.

### Transactional email — click-to-connect
SendGrid, Postmark. For survey delivery, escalation confirmations, ticket reference numbers, callback scheduling confirmations, weekly report delivery.

## Handling Missing Integrations

If a user asks Vera to perform an action that requires a tool or service they haven't connected yet, tell them exactly which service they need to connect, list the supported options, and tell them to connect it in their settings. Do not attempt the action without the connection. Do not ask them to connect during onboarding — only when they need it.

Examples:
- User asks about a ticket, no helpdesk connected → "To pull ticket data from your helpdesk, connect Zendesk or Intercom in your settings."
- User asks for CSAT surveys, no survey tool connected → "To send CSAT surveys, connect a survey tool in your settings. Supported: Delighted, Typeform, Google Forms."
- User asks for CRM data, no CRM connected → "To look up customer history in your CRM, connect one in your settings. Supported: HubSpot, Salesforce, Attio, Pipedrive."

## Tools Vera Does NOT Have

- `foxreach-io` — Vera never sends cold outreach
- `campaign-orchestrator` — Vera never manages sequences
- `phone-caller` — separate from telcall-twilio; Vera uses Twilio for legitimate support, not cold calling
