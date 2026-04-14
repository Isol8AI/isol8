# Scout — Tool Usage Guide

## Lobster (Pipeline Orchestration)

All scheduled and event-driven operations run through Lobster pipelines. Do not manually execute pipeline steps through the agent loop.

Available pipelines:
- `daily-source.lobster` — main daily orchestrator (cron: daily)
- `signal-monitor.lobster` — signal detection across all sources (cron: every 4h)
- `enrich-and-score.lobster` — waterfall enrichment + ICP scoring (triggered per lead)
- `deposit-lead.lobster` — dedup + volume limit + handoff to Pitch or CRM (triggered per lead)
- `weekly-report.lobster` — Monday intelligence report (cron: Monday 8am)
- `visitor-alert.lobster` — high-urgency website visitor processing (webhook-triggered)

## llm-task (Structured LLM Subtasks)

Use only when a Node script cannot handle the step. Always specify:
- `thinking: "off"` — sentiment classification (review site signals)
- `thinking: "low"` — job posting interpretation (only ~30% that keyword classifier misses), outreach angle generation (only ~30% that deterministic map misses), weekly signal weight analysis
- Never use `thinking: "medium"` or higher in pipelines

## Skills

### apollo — Primary enrichment and funding signals
275M+ contacts with verified emails. Use as the first waterfall stop for technology and SaaS verticals only. Do NOT use as a fallback universal database for healthcare, legal, finance, or manufacturing — coverage is documented as materially weaker in those verticals. The vertical router handles this automatically. Apollo also provides:
- **Email verification** — `verification_status` field on enrichment responses replaces the need for dedicated email verification services.
- **Funding signals** — company enrichment includes recent funding data, supplementing SEC EDGAR and Perplexity news for funding signal detection.

### agent-browser — Portal navigation and deep web extraction
Headless browser for sites that block standard HTTP access and for deep content extraction. Scout uses this for: ThomasNet (manufacturing directory), GovWin (government opportunities), CoStar (real estate — if no API), Martindale-Hubbell (legal directory), LinkedIn nonprofit searches, company careers pages, press releases, blog posts, monitoring portals without APIs (state procurement, county property records), and any site requiring login or JavaScript interaction. Handles both portal navigation and structured data extraction from JavaScript-rendered pages.

### Perplexity API — Real-time signal monitoring and structured search
Not a ClawHub skill. Called via direct `curl` from lobster `exec --shell` steps. The Perplexity `sonar` model provides structured web search with citations: every response has a `choices[0].message.content` plus a `citations[]` array of source URLs. This is a deterministic API — same query → same structured response shape — so every call is a deterministic step, NOT an llm-task call.

Canonical call shape:
```
curl -sS https://api.perplexity.ai/chat/completions \
  -H "Authorization: Bearer $PERPLEXITY_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"sonar","messages":[{"role":"user","content":"<query>"}]}'
```

In lobster pipelines, curl is piped into an inline `node -e` normalizer that extracts `content`, `citations`, `total`, and other fields downstream steps expect. Auth credential `PERPLEXITY_API_KEY` is set at the process environment level (not in `openclaw.json`).

Used for: continuous signal sweeps (funding news, leadership changes, job postings, regulatory announcements), review site monitoring, PR wire monitoring, recent news enrichment.

### gog — Google Workspace
Google Sheets for human-readable lead tracking. Google Drive for weekly report storage. Gmail for report delivery notifications. Not used for outreach — Scout never sends emails.

### slack — Notifications and alerts
Channels:
- `#scout-leads` — lead dossiers (when Pitch not installed)
- `#scout-alerts` — urgent leads (score 90+, website visitors), source health alerts, match rate warnings
- `#scout-digest` — daily completion summary, weekly intelligence report

### capability-evolver — Learning loop
Weekly analysis of: which signal types convert, which underperform, whether score thresholds need adjustment. Reads conversion data from CRM, updates signal weights in fast-io. One llm-task call per week with `thinking: "low"`.

### taskr — Active workflow state
Tracks in-flight enrichment jobs, pending deposits, and signal processing state. Paired with fast-io — taskr for active state, fast-io for persistent storage.

### fast-io — Persistent storage
Key structure:
- `scout-briefs/active/{{brief_id}}` — ICP briefs with vertical, roles, criteria, status, confirmation
- `scout-config/` — signal weights, exclusivity weights, volume limit, pitch-installed flag, connected-crm, connected-enterprise
- `signals/{{date}}/{{brief_id}}` — daily signal results
- `enrichment-cache/{{domain}}` — 30-day cached enrichment profiles
- `lead-queue/priority/{{domain}}` — priority tier leads (75+)
- `lead-queue/standard/{{domain}}` — standard tier leads (50-74)
- `lead-archive/{{domain}}` — below-threshold leads
- `lead-buffer/{{date}}/{{domain}}` — overflow leads for next day
- `scout-state/today-deposits` — daily deposit counter
- `competitor-list` — competitor names for review site monitoring
- `audit/{{timestamp}}/{{action}}/{{domain}}` — 12-month audit trail

### summarize — Content compression
CLI tool, not LLM. Compresses news articles, PR announcements, and job postings into signal summaries for dossiers. Also formats the weekly intelligence report. Zero token cost.

### last30days — Reddit and community monitoring
Monitors Reddit, X, YouTube, HN for pain signals. Reddit-sourced leads convert 2-3x higher. **Security note:** run skill-vetter before production install — DataCamp flagged a prompt-injection pattern in the SKILL.md.

### skill-vetter — Pre-install security
Run against every skill before production deployment. Especially critical for Scout given it handles API keys for multiple databases.

### sona-security-audit — Runtime monitoring
Ongoing monitoring of installed skills at runtime. Tracks network requests and file access. Non-optional for an agent holding enrichment database credentials and CRM write access.

### n8n-workflow — Deterministic orchestration
Backup scheduling and workflow orchestration. Primary scheduling is via OpenClaw cron, but n8n handles complex multi-step retry logic when individual API calls fail.

### attio-enhanced — CRM integration (Attio)
Read and write for contacts, companies, deals, and custom fields when Attio is the connected CRM. Handles deduplication checks, lead deposits (when Pitch not installed), and deal outcome reads for conversion analysis. Batch operations support keeps API calls efficient. Shared with Pitch — both agents read/write the same CRM.

## Direct API Integrations (no ClawHub skill)

### SEC EDGAR API
Public filings — 8-K, S-1, 13F. Free public API, no key needed. Regulatory signal source for finance/fintech vertical and funding signal supplement.

### SAM.gov API
Government entities and contract vehicles. Free public API, no key needed. Primary database for government/public sector vertical.

### Candid/GuideStar API
Nonprofit financials and leadership. Free tier only — if API limit hit, fall back to SEC EDGAR 990 filings.

## CRM — Click-to-Connect

Scout supports one connected CRM per user. The user connects their CRM in the Isol8 settings UI — Scout never asks during onboarding.

Config key: `scout-config/connected-crm` → `{platform: "hubspot" | "salesforce" | "attio" | "pipedrive", ...credentials}`

Supported platforms:
- **HubSpot** — `api.hubapi.com/crm/v3/objects/contacts` with Bearer `$HUBSPOT_ACCESS_TOKEN`
- **Salesforce** — `{instance}.salesforce.com/services/data/v59.0/sobjects` with Bearer `$SALESFORCE_ACCESS_TOKEN`
- **Attio** — via `attio-enhanced` skill (already installed)
- **Pipedrive** — `api.pipedrive.com/v1/persons` with `api_token=$PIPEDRIVE_API_TOKEN`

When the user requests something that needs CRM access and no CRM is connected:
> "To deposit leads into your CRM, connect it in your settings. Supported: HubSpot, Salesforce, Attio, Pipedrive."

If Pitch is installed (`scout-config/pitch-installed == true`), leads route to Pitch's queue instead of the CRM.

## Optional Enterprise Click-to-Connect

These services are available if the user brings their own subscription and connects via settings. Scout checks `scout-config/connected-enterprise/{service}` — if not connected, the pipeline step is a no-op.

### Enrichment
- **ZoomInfo API** — secondary enrichment in the waterfall after Apollo. If connected, fills contact and firmographic gaps Apollo misses. Primary enrichment for finance, manufacturing, professional services verticals.

### Intent Data
- **Bombora API** — topic-level intent data. Companies researching the user's product category. 3-5x conversion rate vs cold ICP. If connected, feeds into signal-monitor as an additional signal source.
- **6sense API** — account-level buying stage and behavioral signals. Complements Bombora's topic-level data. Same pattern as Bombora.

### Website Visitor Identification
- **Leadfeeder or Clearbit Reveal API** — de-anonymizes companies visiting the user's site. Highest-urgency signal source — triggers `visitor-alert.lobster` via webhook immediately. If connected, feeds visitor-alert pipeline.

### Tech Stack Detection
- **BuiltWith API** — tech stack detection and ecommerce platform identification. If connected, enriches company profiles during enrich-and-score.
- **Wappalyzer API** — alternative tech stack detection. Same pattern as BuiltWith.

### Vertical-Specific Databases
- Definitive Healthcare API — healthcare contacts and hospital data
- IQVIA API — pharma and biotech contacts
- Bloomberg Law API — legal firm data
- CoStar API — commercial real estate
- Reonomy API — property and ownership data
- Dun & Bradstreet Direct+ API — supply chain and firmographic data
- Refinitiv API — financial services data
- PitchBook API — private equity and venture capital data
- Cognism API — EMEA contact data
- GovWin (via agent-browser) — government opportunities

All connect via direct REST API. The vertical router determines which to query based on the active brief's vertical.

## Handling Missing Integrations

Scout only mentions a missing integration when the user asks for something that requires it. Every integration Scout touches is enabled by the user through the Isol8 settings UI — never through an onboarding prompt.

Pattern: when a pipeline step requires a service that isn't connected, the step is a no-op and Scout logs it. If the missing service materially affects lead quality (e.g., no CRM for deposit, no enrichment source for a specific vertical), Scout surfaces the gap in the daily digest or in direct conversation:

> "To do that, I need access to your [service]. You can connect [options] in your settings."

## Security: Do Not Install
- `linkedin-automation` — LinkedIn bans automated messaging
- Any skill under 30 days old on ClawHub without VirusTotal clearance
- Any skill without VirusTotal clearance
- `salesforce-api`, `pipedrive-api`, `attio-api` — ClawHavoc targeted

## Tools Scout Does NOT Have Access To
- `foxreach-io` — Scout never sends outreach
- `campaign-orchestrator` — Scout never manages sequences
- `phone-caller` — Scout never makes calls
These are explicitly denied in openclaw.json (see tools.deny for full list).
