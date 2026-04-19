# Pitch & Scout — Tool Usage Guide

## Lobster (Primary Orchestration)

All scheduled and event-driven operations run through Lobster pipelines. Never manually execute pipeline steps through the agent loop — trigger the pipeline and let it run deterministically.

### Scout Pipelines
- `daily-source.lobster` — main daily sourcing orchestrator (cron: daily)
- `signal-monitor.lobster` — signal detection across all sources (cron: every 4h)
- `enrich-and-score.lobster` — waterfall enrichment + ICP scoring (triggered per lead)
- `deposit-lead.lobster` — dedup + volume limit + handoff to Pitch queue or CRM (triggered per lead)
- `weekly-report.lobster` — Monday intelligence report (cron: Monday 8am)
- `visitor-alert.lobster` — high-urgency website visitor processing (webhook-triggered)

### Pitch Pipelines
- `signal-sweep.lobster` — buying signal detection (cron: every 4h)
- `prospect-enrich.lobster` — waterfall enrichment + ICP scoring (triggered per prospect)
- `draft-and-approve.lobster` — first touch draft + approval gate (triggered after enrichment)
- `sequence-execute.lobster` — follow-up touches 2-5 (cron: hourly)
- `reply-handler.lobster` — prospect reply processing (webhook-triggered)
- `meddic-scan.lobster` — daily MEDDIC gap check (cron: daily 8am)
- `meddic-stage-check.lobster` — stage change MEDDIC check (webhook-triggered)
- `opt-out-handler.lobster` — opt-out processing (webhook-triggered)

---

## llm-task

Use only when a Node script cannot handle the step. Always specify thinking level explicitly. Never use `thinking: "high"` in automated pipelines.

| Level | When to use |
|---|---|
| `off` | Sentiment classification, signal strength scoring |
| `low` | Job posting interpretation (~30%), outreach angle generation (~30%), research briefs, follow-up drafts, MEDDIC extraction, signal weight analysis |
| `medium` | First touches, reply drafts (Pitch only — high-stakes) |

---

## fast-io (Persistent Storage)

### Scout keys
- `scout-briefs/active/{{brief_id}}` — confirmed ICP briefs
- `scout-config/signal-weights` — signal performance weights (updated weekly)
- `scout-config/exclusivity-weights` — source exclusivity map
- `scout-config/volume-limit` — daily deposit cap
- `scout-config/pitch-installed` — whether to route to Pitch queue or CRM directly
- `scout-config/connected-crm` — connected CRM config
- `scout-config/connected-enterprise` — optional enrichment services config
- `scout-state/today-deposits` — daily counter
- `signals/{{date}}/{{brief_id}}` — daily signal results
- `enrichment-cache/{{domain}}` — 30-day cached enrichment profiles
- `lead-queue/priority/{{domain}}` — score 75+ leads
- `lead-queue/standard/{{domain}}` — score 50-74 leads
- `lead-archive/{{domain}}` — below-threshold leads
- `lead-buffer/{{date}}/{{domain}}` — overflow for next day
- `competitor-list` — competitor names for review site monitoring
- `audit/{{timestamp}}/{{action}}/{{domain}}` — 12-month audit trail

### Pitch keys
- `pitch-config/icp` — ICP criteria
- `pitch-config/activation` — activation gate state
- `pitch-config/launch-state` — test cohort phase
- `pitch-config/connected-outbound` — connected outbound platform config
- `pitch-config/connected-crm` — connected CRM config
- `signals/{{date}}` — daily signal results
- `briefs/active/{{domain}}` — qualified prospect briefs
- `briefs/archived/{{domain}}` — sub-threshold prospects
- `briefs/quarantine/{{domain}}` — low-confidence prospects
- `sequences/active/{{domain}}` — active sequence state
- `opt-out/{{domain}}` — opt-out records
- `timing-weights/` — engagement timing optimization data

---

## Perplexity API (Signal Detection + Research)

**Not a ClawHub skill.** Called via direct `curl` from lobster `exec --shell` steps. The `sonar` model provides structured web search with citations — deterministic API, same query → same response shape. Every Perplexity call is a deterministic step, NOT an llm-task call.

```bash
curl -sS https://api.perplexity.ai/chat/completions \
  -H "Authorization: Bearer $PERPLEXITY_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"sonar","messages":[{"role":"user","content":"<query>"}]}'
```

Pipe into an inline `node -e` normalizer to extract `content`, `citations`, `total`, and any other fields downstream steps need. `PERPLEXITY_API_KEY` is set at process environment level, not in `openclaw.json`.

Used for: signal sweeps (funding news, leadership changes, job postings, regulatory announcements), review site monitoring, PR wire monitoring, recent news enrichment, prospect research.

---

## apollo — Enrichment + Email Verification + Funding Signals

275M+ contacts with verified emails. Use as first waterfall stop for technology and SaaS verticals only. Do NOT use as a fallback universal database for healthcare, legal, finance, or manufacturing — coverage is documented as materially weaker. The vertical router handles this automatically.

- `verification_status` field on enrichment responses handles email verification — no separate service needed
- Company enrichment includes recent funding data, supplementing SEC EDGAR and Perplexity

---

## agent-browser — Portal Navigation + Deep Web Extraction

Headless browser for sites that block standard HTTP access. Use for: ThomasNet, GovWin, CoStar (if no API), Martindale-Hubbell, LinkedIn nonprofit searches, company careers pages, press releases, monitoring portals without APIs, sites requiring login or JavaScript interaction. Also use when Perplexity's structured snippets don't provide enough depth on a prospect.

---

## slack — Channels

| Channel | Purpose |
|---|---|
| `#pitch-approvals` | All approval requests from Pitch |
| `#pitch-signals` | Signal notifications |
| `#pitch-pipeline` | Pipeline health and MEDDIC alerts |
| `#pitch-quarantine` | Low-confidence prospect alerts |
| `#scout-leads` | Lead dossiers (when Pitch not installed) |
| `#scout-alerts` | Urgent leads (90+ score, website visitors), source health alerts |
| `#scout-digest` | Daily completion summary, weekly intelligence report |

**Approval message format (Pitch):** First line = what you need from the rep. Signal/context. Draft or data. Any flags or warnings.

**Lead alert format (Scout):** One line — domain, score, signal, urgency. Full dossier follows.

---

## gog — Google Workspace

Gmail: Reply sends ONLY (Pitch) — when a prospect has replied and the rep approves a response, send through gog so it comes from the rep's real inbox. Never send cold outreach through gog.

Google Drive: Voice model storage and versioning. Weekly report storage.

Google Sheets: Human-readable lead tracking, exportable reports.

---

## CRM — Click-to-Connect (Single Platform)

Supported: HubSpot, Salesforce, Attio, Pipedrive. One platform per user, connected via settings.

Config keys: `scout-config/connected-crm` and `pitch-config/connected-crm`

| Platform | API pattern |
|---|---|
| HubSpot | `api.hubapi.com/crm/v3/objects/contacts` + Bearer `$HUBSPOT_ACCESS_TOKEN` |
| Salesforce | `{instance}.salesforce.com/services/data/v59.0/sobjects` + Bearer `$SALESFORCE_ACCESS_TOKEN` |
| Attio | via `attio-enhanced` skill |
| Pipedrive | `api.pipedrive.com/v1/persons` + `api_token=$PIPEDRIVE_API_TOKEN` |

CRM custom fields required on contact/deal records: `gdpr_consent`, `tcpa_opt_in`, `icp_score`, `enrichment_date`, `signal_type`, `opted_out`.

---

## Outbound Email Platform — Click-to-Connect (Pitch Only)

Supported: Instantly, SmartLead, Mailshake, Lemlist. Config key: `pitch-config/connected-outbound`.

All cold sequence emails go through the connected outbound platform — never through gog/Gmail.

| Platform | API pattern |
|---|---|
| Instantly | `api.instantly.ai/api/v1/...` + `$INSTANTLY_API_KEY` |
| SmartLead | `server.smartlead.ai/api/v1/...` + `$SMARTLEAD_API_KEY` |
| Mailshake | `api.mailshake.com/2017-04-01/...` + `$MAILSHAKE_API_KEY` |
| Lemlist | `api.lemlist.com/api/...` + `$LEMLIST_API_KEY` |

---

## Optional Enterprise Click-to-Connect

Check `scout-config/connected-enterprise/{service}` — if not connected, pipeline step is a no-op.

**Enrichment:** ZoomInfo (secondary waterfall, fills Apollo gaps — primary for finance/manufacturing/professional services)

**Intent Data:** Bombora (topic-level intent, 3-5x conversion vs cold ICP), 6sense (account-level buying stage)

**Visitor ID:** Leadfeeder or Clearbit Reveal (highest-urgency signal — triggers `visitor-alert.lobster` immediately via webhook)

**Tech Stack:** BuiltWith, Wappalyzer

**Vertical-Specific Databases:** Definitive Healthcare, IQVIA, Bloomberg Law, CoStar, Reonomy, D&B Direct+, Refinitiv, PitchBook, Cognism (EMEA), GovWin (via agent-browser)

---

## Direct Public APIs (No Key Required)

- **SEC EDGAR** — 8-K, S-1, 13F filings. Finance/fintech vertical + funding signal supplement
- **SAM.gov** — government entities and contract vehicles. Government/public sector vertical
- **Candid/GuideStar** — nonprofit financials and leadership. Falls back to SEC EDGAR 990 if API limit hit

---

## summarize

CLI tool, not an LLM. Use for compressing research results, formatting pipeline summaries, weekly reports, and audit log formatting. Zero token cost.

---

## capability-evolver

Weekly analysis of which signal types convert, which underperform, whether score thresholds need adjustment. Reads conversion data from CRM, updates signal weights in fast-io. One llm-task call per week with `thinking: "low"`.

---

## taskr + n8n-workflow

**taskr** — active workflow state. Tracks in-flight enrichment jobs, pending deposits, signal processing state.

**n8w-workflow** — backup orchestration for complex multi-step retry logic when individual API calls fail. Primary scheduling is via OpenClaw cron.

---

## Security: Do Not Install

- `salesforce-api`, `pipedrive-api`, `attio-api` — ClawHavoc AMOS Stealer targets. Use direct API via connected CRM instead
- `gmail`, `mailchimp`, `fathom-api` — ClawHavoc targeted
- `linkedin-automation` — LinkedIn bans automated messaging
- `foxreach-io`, `campaign-orchestrator`, `phone-caller` — explicitly denied in openclaw.json
- Any skill under 30 days old on ClawHub without VirusTotal clearance
- `last30days` — run skill-vetter before production install; DataCamp flagged a prompt-injection pattern in the SKILL.md
