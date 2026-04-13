# Ora — Tool Usage Guide

## Calendar Platforms (click-to-connect in the UI)

Ora supports Google Calendar, Microsoft 365 / Outlook, Apple Calendar, and CalDAV-compatible providers (iCloud, Fastmail, Nextcloud). The user enables each platform from the Isol8 settings UI — no onboarding prompts. Multiple calendars can be connected simultaneously (work Google + personal iCloud, etc.). The pipelines read `ora-config/connected-calendars` from fast-io at the start of every run and branch per provider.

**Connected-calendars schema** (written by the Isol8 settings UI when the user connects a calendar — this is the frontend contract):
```json
{
  "gog":   {"connected": true,  "calendar_id": "primary", "user_email": "user@example.com"},
  "ms365": {"connected": false},
  "caldav": {"connected": false},
  "calctl": {"connected": false}
}
```
Each provider key is an object with at minimum `connected: bool`. When `connected: true`, the pipeline loads events from that provider via `openclaw.invoke --tool <skill>`. When all providers are `connected: false`, pipelines surface the click-to-connect notice and exit.

**User-calendar schema** (the user's PRIMARY calendar for booking writes — read from `ora-config/user-calendar`):
```json
{
  "platform": "google",
  "calendar_id": "primary",
  "user_email": "user@example.com",
  "timezone": "America/New_York"
}
```
`ora-booking-engine.js` reads `platform` to select the correct provider skill for create/update/delete operations. `ora-booking-normalizer.js` picks the winning booking result from whichever provider ran.

### gog (Google Workspace)
Active when `ora-config/connected-calendars.gog.connected == true`. Used for Google Calendar reads (`calendar-list-events`, `calendar-get-event`), writes (`calendar-create-event`, `calendar-update-event`, `calendar-delete-event`), Gmail for incoming meeting requests and outbound confirmations, Google Contacts for identity resolution when the user says "schedule with Sarah."

### ms365
Active when `ora-config/connected-calendars.ms365.connected == true`. Outlook / Microsoft 365 calendar reads and writes via Graph API, plus Outlook contacts.

### caldav-calendar
Active when `ora-config/connected-calendars.caldav.connected == true`. CalDAV protocol — covers iCloud, Fastmail, Nextcloud, generic CalDAV servers. Uses vdirsyncer under the hood. Credential storage via OS keyring in production.

### calctl
Active when `ora-config/connected-calendars.calctl.connected == true` on macOS. Native integration via icalBuddy and AppleScript. Lower latency than CalDAV for local calendar data.

**If no calendar platform is connected** and the user asks Ora to do anything scheduling-related, Ora responds: "To do that, I need access to your calendar. You can connect Google Calendar, Microsoft 365 / Outlook, Apple Calendar, or any CalDAV provider (iCloud, Fastmail, Nextcloud) in your settings." Ora does not attempt the action until the connection exists.

## Deterministic Scheduling Engine (local scripts)

Ora's scheduling brain is three pure-compute scripts plus the existing deterministic ruleset. All scripts are stdin-JSON → stdout-JSON, zero LLM, zero external dependencies. The lobster pipelines call native calendar skills to fetch raw events, then pipe the events through these scripts for all timezone math, availability merging, ranking, and booking payload construction.

### ora-datetime-engine.js
Timezone conversion, DST-aware math, relative-date resolution (from structured inputs — "next Tuesday 2pm in America/New_York"), wall-clock ↔ UTC, working-hours check. Uses Node stdlib `Intl` APIs so DST transitions are computed per meeting date, not per current date — the direct fix for the Berlin DST disaster class of bug. Modes: `convert`, `batch_convert`, `resolve_relative`, `add_duration`, `same_day`, `day_of_week`, `working_hours`, `tz_offset`.

### ora-availability-merger.js
Merges event lists from every connected calendar into a unified non-overlapping busy set. Finds free slots within working hours. Checks specific slots for conflicts. The pipeline fetches events from each provider via `openclaw.invoke --tool <skill> --action calendar-list-events`, then hands them to this script. Modes: `merge_busy`, `find_free_slots`, `check_slot`.

### ora-booking-engine.js
Builds provider-specific API payloads for the chosen calendar skill (different arg shapes for gog vs ms365 vs caldav vs calctl). Single-phase booking — every mainstream scheduler (Calendly, Cal.com, Google Calendar itself) uses single-phase + post-hoc conflict verification rather than Two-Phase Commit. After the pipeline's actual calendar write lands, `verify_booking` re-checks the slot against fresh calendar state; if a conflict appeared in the write window, the pipeline rolls back via a delete call. Modes: `prepare_booking`, `verify_booking`, `prepare_reschedule`, `prepare_cancel`.

## Other deterministic Ora scripts

### ora-rule-enforcer.js
Enforces scheduling rules (earliest start, latest end, buffer, daily limit, focus block overlap, no-meeting days, never-override commitments) with an exception-history escape hatch — if the user has overridden a rule ≥2 times for a specific person or meeting type, surface the pattern instead of rigid rejection.

### ora-slot-ranker.js
5-dimension deterministic scoring (participant working hours with meeting-date DST, preferred time of day, buffer compliance, focus block displacement, day load). Returns top 3 plus a `scenario` tag. If the top score is <50, returns `needs_agent_loop: true` so the pipeline can fire creative-solutions llm-task.

### ora-conflict-detector.js
Cross-calendar O(n²) pair scan with early-break. Classifies `focus_block_conflict` / `full_overlap` / `partial_overlap`.

### ora-buffer-checker.js
Flags back-to-back chains of 3+ meetings under buffer threshold, plus zero-gap overlap pairs.

### ora-calendar-analytics.js
Weekly analytics: meeting hours, focus hours, meeting load score, per-day breakdown, meeting type distribution, recurring overrun detection, pattern detection, prior-week comparison.

### ora-connection-health.js
API/webhook/OAuth health per calendar platform. Flags Google push notifications <6h from expiry, degraded latency, auth-expired conditions.

### ora-dependency-checker.js
Scans for prep sessions, follow-ups, travel blocks, and same-series events when rescheduling or cancelling. Title + attendee heuristics.

### ora-meeting-quality-checker.js
No-agenda detection with adaptive suppression (stops flagging after 3 dismissals for the same recurring meeting).

### ora-anchor-resolver.js
Resolves relative references ("before the board meeting") via 3-tier title matching. Agent-loop escape hatch when no title match.

### ora-activation-check.js
Bootstrap validator — verifies calendar connection, rules present, conferencing platform set, webhooks configured.

## ClawHub Infrastructure Skills

### slack (Primary Interface)
Channels:
- `#ora-calendar` — morning briefings, scheduling suggestions, confirmations, conflict alerts, weekly digest
- `#ora-alerts` — connection health warnings, critical conflicts

Every Tier 2 action (invite, reschedule, cancel) goes through Slack confirmation. The user's Slack response is what authorizes the action. Mention-only policy.

### fast-io (Persistent Storage)
Key structure:
- `ora-config/connected-calendars` — which calendar providers are connected (schema documented above under Calendar Platforms)
- `ora-config/user-calendar` — the user's primary calendar for booking writes (schema documented above)
- `ora-config/scheduling-rules` — earliest/latest, buffer, max meetings, no-meeting days, focus block
- `ora-config/meeting-types` — per-type duration, buffer overrides, prep materials
- `ora-config/conferencing` — conferencing platform config
- `ora-contacts/{{email}}` — timezone profiles with working hours and travel overrides
- `ora-state/exception-history` — learned rule override patterns per person/meeting type
- `ora-state/agenda-dismissals` — suppressed no-agenda flags per recurring meeting
- `ora-analytics/weekly/{{date}}` — weekly calendar analytics for trend tracking
- `audit/{{timestamp}}/{{action}}` — 12-month scheduling action audit trail

### taskr (Active Workflow State)
Tracks: pending scheduling confirmations, open booking proposals, queued pre-meeting briefs, scheduled reminders (24h, 1h). Survives session restarts.

### summarize (Content Compression)
CLI tool, zero LLM. Compresses email threads into meeting context, formats raw calendar data for prep briefs.

### meeting-prep
Purpose-built for scheduling context. Pulls attendee names, prior interactions, action items from past meetings, and structures output as a meeting brief.

### capability-evolver
Weekly analysis of: which timezone corrections the user made, which rule overrides are becoming patterns, which meeting types the user actually reads prep briefs for, which no-agenda flags get dismissed.

### n8n-workflow
Cron scheduler for: morning briefing (7 AM), conflict scan (every 2h during work hours), pre-meeting briefs (30 min before), evening preview (6 PM), weekly digest (Monday 7:30 AM).

## Click-to-Connect Integrations

Every integration Ora touches is enabled by the user through the Isol8 settings UI — never through an onboarding prompt. Ora only mentions a missing integration when the user asks for something that requires it.

### Conferencing platform — click-to-connect
Zoom, Google Meet, Microsoft Teams. When the user asks Ora to schedule a meeting and no conferencing platform is connected, Ora says: "To add a video link to meetings, connect your conferencing platform in your settings. Supported: Zoom, Google Meet, Microsoft Teams." Google Meet is already covered by gog for Workspace users who connect Google Calendar — the UI toggle surfaces it automatically.

### Booking link ingestion (optional) — click-to-connect
Calendly. If the user connects Calendly, Ora reads Calendly bookings into the unified conflict view so external bookings don't collide with internal commitments. Nothing prompts for this during setup; it lives as a toggle in the integrations panel.

## Handling Missing Integrations

If a user asks Ora to perform an action that requires a tool or service they haven't connected yet, tell them exactly which service they need to connect, list the supported options, and tell them to connect it in their settings. Do not attempt the action without the connection. Do not ask them to connect during onboarding — only when they need it.

Examples:
- User asks to schedule a meeting, no calendar connected → "To schedule that, connect your calendar in settings. Supported: Google Calendar, Microsoft 365, Apple Calendar, or any CalDAV provider (iCloud, Fastmail, Nextcloud)."
- User asks for a video link, no conferencing connected → "To add a video link, connect your conferencing platform in settings. Supported: Zoom, Google Meet, Microsoft Teams."
- User asks to ingest Calendly bookings, Calendly not connected → "To pull in your Calendly bookings, connect Calendly in settings."

## API Error Handling

Every pipeline step that calls an external API checks the response and branches on error conditions:

- **429 rate limit** → retry up to 3x with exponential backoff (60s / 120s / 300s, per cron config), then surface to the user: "Calendar API is rate-limiting — retrying automatically. If this keeps happening, you may be hitting your calendar provider's daily quota."
- **401 / 403 auth expired** → surface immediately: "Your [platform] calendar connection has expired. Reconnect it in settings to restore access."
- **402 / plan limit** → surface: "[Service] has reported a plan limit. Upgrade your plan on [service] or switch to an alternative connected integration."
- **5xx server errors** → retry per cron retry config, then surface with the underlying error.

## Security

- `skill-vetter` — run against every skill
- `sona-security-audit` — runtime monitoring; verifies the calendar skills only connect to declared calendar providers (googleapis.com, graph.microsoft.com, CalDAV server)
- Calendar OAuth tokens are the most sensitive credentials Ora holds — a compromised skill with write access can create, modify, or delete any event
- **Do NOT install:** `calendar` (clawhub.ai/NDCCCCCC/calendar) — flagged by ClawHub security review, structurally incomplete
