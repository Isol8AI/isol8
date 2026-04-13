# Pitch — Tool Usage Guide

## Lobster (Primary Orchestration)

All scheduled and event-driven operations run through Lobster pipelines. Do not manually execute pipeline steps through the agent loop — trigger the pipeline and let it run deterministically.

Available pipelines:
- `signal-sweep.lobster` — buying signal detection (cron: every 4h)
- `prospect-enrich.lobster` — waterfall enrichment + ICP scoring (triggered per prospect)
- `draft-and-approve.lobster` — first touch draft + approval gate (triggered after enrichment)
- `sequence-execute.lobster` — follow-up touches 2-5 (cron: hourly)
- `reply-handler.lobster` — prospect reply processing (webhook-triggered)
- `meddic-scan.lobster` — daily MEDDIC gap check (cron: daily 8am)
- `meddic-stage-check.lobster` — stage change MEDDIC check (webhook-triggered)
- `opt-out-handler.lobster` — opt-out processing (webhook-triggered)

## llm-task (Structured LLM Subtasks)

Use for any step that requires language understanding within a pipeline. Always specify:
- `thinking` level explicitly (off/low/medium — never high in pipelines)
- `schema` for structured JSON output
- Minimal `input` — only the data needed for that specific task

Never use llm-task when a Node script can do the job.

## fast-io (Persistent Storage)

Key structure:
- `pitch-config/icp` — ICP criteria
- `pitch-config/activation` — activation gate state
- `pitch-config/launch-state` — test cohort phase
- `pitch-config/connected-outbound` — connected outbound email platform config
- `pitch-config/connected-crm` — connected CRM platform config
- `signals/{{date}}` — daily signal results
- `briefs/active/{{domain}}` — qualified prospect briefs
- `briefs/archived/{{domain}}` — sub-threshold prospects
- `briefs/quarantine/{{domain}}` — low-confidence prospects
- `sequences/active/{{domain}}` — active sequence state
- `opt-out/{{domain}}` — opt-out records
- `audit/{{timestamp}}/{{action}}/{{domain}}` — audit trail
- `timing-weights/` — engagement timing optimization data
- `competitor-list` — configured competitor names for content scanning

## Perplexity API (Research + Signal Detection Engine)

Pitch's primary structured-web-search engine for buying signal detection. Runs in signal-sweep.lobster to find funding news, leadership changes, job postings, regulatory announcements, and other buying signals.

**Not a ClawHub skill.** Called via direct `curl` from lobster `exec --shell` steps. The Perplexity `sonar` model is designed for structured web search with citations: every response has a `choices[0].message.content` plus a `citations[]` array of source URLs. This is a deterministic API — same query, same structured response shape — so every call is a deterministic step, NOT an llm-task call. The deterministic / LLM split is preserved exactly.

Canonical call shape:
```
curl -sS https://api.perplexity.ai/chat/completions \
  -H "Authorization: Bearer $PERPLEXITY_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"sonar","messages":[{"role":"user","content":"<query>"}]}'
```

In lobster pipelines, curl is piped into an inline `node -e` normalizer that extracts `content`, `citations`, `total`, and any other fields downstream steps expect. Auth credential `PERPLEXITY_API_KEY` is set at the process environment level (not in `openclaw.json`) and is the only required research env var beyond `OPENCLAW_HOOK_TOKEN`.

## agent-browser (Web Browsing)

Use when you need to read full web pages — LinkedIn profiles, company blogs, press releases, forum threads. More expensive than Perplexity in terms of time. Only use when Perplexity's structured snippets don't provide enough context.

## gog (Gmail + Google Workspace)

Gmail: Reply sends ONLY — when a prospect has replied and the rep approves a response, send through gog so it comes from the rep's real inbox.

Google Drive: Voice model storage and versioning.

Google Sheets: If the rep wants exportable reports.

## slack (Approval Channel)

All approval requests go to `#pitch-approvals`. Structure every message:
1. First line: what you need from the rep
2. Signal/context
3. The draft or data
4. Any flags or warnings

Signal alerts go to `#pitch-signals`.
Pipeline health goes to `#pitch-pipeline`.
Quarantine alerts go to `#pitch-quarantine`.

## summarize (Content Compression)

CLI tool, not an LLM. Use for compressing research results, formatting pipeline summaries, and audit log formatting. Zero token cost.

## Apollo.io API (Direct)

Contact enrichment, email verification, intent signals. Connect directly via REST API, not through a ClawHub skill. Read-only contact access.

## Click-to-Connect Integrations

Every integration Pitch touches is enabled by the user through the Isol8 settings UI — never through an onboarding prompt. Pitch only mentions a missing integration when the user asks for something that requires it.

### Outbound email platform — click-to-connect (single platform)
Instantly, SmartLead, Mailshake, Lemlist. All cold sequence emails go through the user's connected outbound platform. Never send cold outreach through gog/Gmail. When the user asks Pitch to send outreach and no outbound platform is connected, Pitch says: "To send outreach, connect your email platform in settings. Supported: Instantly, SmartLead, Mailshake, Lemlist."

The user's outbound platform handles:
- Email sending (individual and batch)
- Sequence/campaign management natively
- Analytics (bounce rates, open rates, reply detection)
- Webhook notifications for replies and unsubscribes — the user configures their platform's webhook to point at `/hooks/agent`

Config key: `pitch-config/connected-outbound` → `{platform: "instantly" | "smartlead" | "mailshake" | "lemlist", ...credentials}`

Direct API patterns:
- Instantly: `api.instantly.ai/api/v1/...` with `$INSTANTLY_API_KEY`
- SmartLead: `server.smartlead.ai/api/v1/...` with `$SMARTLEAD_API_KEY`
- Mailshake: `api.mailshake.com/2017-04-01/...` with `$MAILSHAKE_API_KEY`
- Lemlist: `api.lemlist.com/api/...` with `$LEMLIST_API_KEY`

### CRM — click-to-connect (single platform)
HubSpot, Salesforce, Attio, Pipedrive. When the user asks for CRM data and no CRM is connected, Pitch says: "To track prospects in your CRM, connect it in settings. Supported: HubSpot, Salesforce, Attio, Pipedrive."

Config key: `pitch-config/connected-crm` → `{platform: "hubspot" | "salesforce" | "attio" | "pipedrive", ...credentials}`

Direct API patterns:
- HubSpot: `api.hubapi.com/crm/v3/objects/contacts` with Bearer `$HUBSPOT_ACCESS_TOKEN`
- Salesforce: `{instance}.salesforce.com/services/data/v59.0/sobjects` with Bearer `$SALESFORCE_ACCESS_TOKEN`
- Attio: `api.attio.com/v2/objects/people` with Bearer `$ATTIO_API_KEY`
- Pipedrive: `api.pipedrive.com/v1/persons` with `api_token=$PIPEDRIVE_API_TOKEN`

CRM custom fields on contact/deal records:
- `gdpr_consent` (boolean + timestamp + source)
- `tcpa_opt_in` (boolean + timestamp + source)
- `icp_score` (number)
- `enrichment_date` (date)
- `signal_type` (string)
- `opted_out` (boolean)

MEDDIC fields: Read and update via the connected CRM's API after reply-handler MEDDIC extraction.

## Handling Missing Integrations

If a user asks Pitch to perform an action that requires a tool or service they haven't connected yet, tell them exactly which service they need to connect, list the supported options, and tell them to connect it in their settings. Do not attempt the action without the connection. Do not ask them to connect during onboarding — only when they need it.

Examples:
- No outbound platform connected, user wants to send outreach → "To send outreach, connect your email platform in settings. Supported: Instantly, SmartLead, Mailshake, Lemlist."
- No CRM connected, user asks for deal data → "To track prospects in your CRM, connect it in settings. Supported: HubSpot, Salesforce, Attio, Pipedrive."
- No CRM connected, user asks about MEDDIC → "To track MEDDIC data, connect your CRM in settings. Supported: HubSpot, Salesforce, Attio, Pipedrive."

## Security: Do Not Install

- `salesforce-api` — ClawHavoc targeted
- `pipedrive-api` — ClawHavoc targeted
- `attio-api` — ClawHavoc targeted (use direct API via connected CRM instead)
- Any skill under 30 days old on ClawHub without VirusTotal clearance
- Any skill claiming to send LinkedIn messages at volume
