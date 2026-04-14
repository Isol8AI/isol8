# Echo — Tool Usage Guide

## Meeting Platforms (click-to-connect in the UI)

Echo pulls transcripts directly from whichever meeting platform hosted the meeting. The user enables each platform from the Isol8 settings UI — no onboarding prompts, no transcription middleman. The pipelines branch on `echo-config/connected-meeting-platforms.<platform>.connected` at runtime and route the transcript fetch through the matching integration. Multiple platforms can be connected simultaneously (e.g. Zoom for external clients + Google Meet for internal calls) — Echo pulls from whichever hosted the meeting it's processing.

### Zoom (direct API)
Primary path when `connected-meeting-platforms.zoom.connected == true`. Echo calls the Zoom Cloud Recording Transcript API directly: `GET https://api.zoom.us/v2/meetings/{meetingId}/recordings/transcript`. OAuth access token stored per-user via the settings UI. No ClawHub skill involved — direct curl in the pipeline step.

### Google Meet (via gog)
Primary path when `connected-meeting-platforms.gmeet.connected == true`. Google Meet recordings + captions live in Drive and are pulled via the existing `gog` skill using `drive-get-meet-captions` against the meeting's recording folder. Users who have `gog` connected for calendar already get Meet transcripts through the same token.

### Microsoft Teams (via ms365)
Primary path when `connected-meeting-platforms.teams.connected == true`. Teams recordings are pulled via the `ms365` skill using the Graph API: `/me/onlineMeetings/{id}/transcripts/{transcriptId}/content`. `ms365` is click-to-connect (disabled by default; enabled per-user in settings).

**If no meeting platform is connected** and the user asks Echo to process anything, Echo responds: "To process meeting transcripts, connect a meeting platform in your settings. Supported: Zoom, Google Meet, Microsoft Teams." Echo does not attempt the fetch until the connection exists.

## Deterministic Scripts (local, stdin-JSON → stdout-JSON)

Echo's processing brain is six deterministic scripts plus llm-task for natural-language synthesis. Every script is zero-LLM, zero external dependencies.

### echo-transcript-normalizer.js
Converts provider-specific transcript responses (Zoom Cloud Recording, Google Meet captions via Drive, Teams via Graph) into the canonical segment shape that the preprocessor consumes. Handles timestamp format differences (ISO 8601 duration, HH:MM:SS, raw seconds) and speaker-label differences across providers.

### echo-audio-preprocessor.js
Silence trimming validation, confidence flagging, speaker-attribution mapping. Flags segments with >500ms adjacent silence as hallucination-risk elevated (per Cornell research on Whisper). Marks low-confidence segments for reviewer. Maps speaker labels to calendar attendees — returns `[UNCERTAIN — possibly X or Y]` when attribution confidence <0.7, never guesses.

### echo-commitment-classifier.js
Keyword-based classification of commitments into `definitive`, `tentative`, `declined`, `ambiguous`, or `not_action_item`. ~60% hit rate on defaults; custom thresholds extend the pattern lists from `echo-config/commitment-thresholds`. Ambiguous statements get `needs_llm: true` and flow to the llm-task classifier in the pipeline.

### echo-action-extractor.js
Builds action items from classified statements with attribution verification (Req 19): if the speaker was mentioned in third-person by someone else, they aren't committing — flagged instead. Deadline extraction via regex. Delegation detection ("Sarah, can you handle the proposal?") creates a separate action item owned by the delegatee.

### echo-synthesis-formatter.js
Per-meeting-type template application (board / standup / sales_call / design_review / 1:1). Assembles flags for reviewer: low-confidence segments, tentative items, uncertain attributions. Built-in defaults live in `TEMPLATE_DEFAULTS` in the script; `echo-config/templates` can override.

### echo-deadline-tracker.js
Date comparison against PM-tool status map. Classifies items as `completed`, `overdue`, `approaching_deadline`, `in_progress`, or `stale_no_deadline`. Generates alert payloads for the weekly digest.

### echo-activation-check.js
Bootstrap validator — meeting platform connection, templates configured, reviewer assigned, consent confirmed.

## ClawHub Infrastructure Skills

### gog (Google Workspace)
Gmail: distributes approved summaries to attendees, drafts customer follow-up emails. Drive: institutional memory archive (every summary, decision, action item as human-readable records) AND the Google Meet recording + caption source. Calendar: attendee lists, meeting type detection, scheduling context for meeting-prep.

### slack (Primary Interface)
Channel: `#echo-meetings` — reviewer queue (summary + flags), action item notifications, deadline alerts, weekly digest. Mention-only policy. Every Tier 2 action (distribute, route to PM, write to CRM) runs after the reviewer approves in Slack.

### fast-io (Persistent Storage)
Key structure:
- `echo-config/consent` — recording consent configuration (Tier 2 hard-block if not confirmed)
- `echo-config/templates` — meeting type templates with capture/omit rules
- `echo-config/commitment-thresholds` — definitive vs tentative language config
- `echo-config/connected-meeting-platforms` — `{zoom: {connected, ...}, gmeet: {connected, ...}, teams: {connected, ...}}` — multi-connect
- `echo-config/connected-pm-tool` — `{platform: "asana"|"linear"|"jira", ...}` — single
- `echo-config/connected-crm` — `{platform: "hubspot"|"salesforce"|"attio"|"pipedrive", ...}` — single
- `echo-archive/{{meeting_id}}` — approved summary, decisions, action items, transcript ref
- `echo-transcripts/{{meeting_id}}` — full speaker-attributed transcript
- `echo-state/commitment-overrides` — reviewer corrections to classifications
- `echo-state/template-edits` — reviewer edits for capability-evolver learning
- `echo-audit/{{date}}/{{meeting_id}}` — review actions: who, what changed, when

### taskr
Tracks: pending reviewer approvals, queued action item routing, scheduled deadline alerts. Survives session restarts.

### meeting-prep
Pre-meeting context: prior summaries with same attendees, open action items, meeting purpose from calendar. Feeds the summary generation so Echo knows when a decision represents a change vs continuation. This skill reads from Drive archive history, not from live transcripts.

### capability-evolver
Weekly analysis of: which action item extractions reviewers consistently remove, which tentative items reviewers consistently promote to definitive, which template sections get heavily edited.

### n8n-workflow
Cron scheduler for: calendar sweep (6 PM weekdays), weekly digest (Monday 8 AM), daily deadline alerts (9 AM weekdays).

## Click-to-Connect Integrations

Every integration Echo writes to is enabled by the user through the Isol8 settings UI — never through an onboarding prompt. Echo only mentions a missing integration when the user asks for something that requires it.

### PM tools — click-to-connect (single platform)
Asana, Linear, Jira. All three are **direct API** integrations — no ClawHub skill stub in `openclaw.json`. The pipelines call each tool's native API directly (Asana REST, Linear GraphQL, Jira REST). Auth credentials (`ASANA_ACCESS_TOKEN`, `LINEAR_API_KEY`, `JIRA_EMAIL`/`JIRA_API_TOKEN`) are stored per-user via settings. When no PM tool is connected and action items are approved, Echo says: "To auto-route approved action items, connect your project tracker in settings. Supported: Asana, Linear, Jira." The summary still distributes and action items are still archived — only the auto-routing is gated.

### CRM — click-to-connect (single platform)
HubSpot, Salesforce, Attio, Pipedrive. Two paths:

- **HubSpot** — click-to-connect ClawHub skill stub (`skills.entries.hubspot`, enabled-per-user). Called via `openclaw.invoke --tool hubspot --action upsert-engagement`.
- **Attio** — click-to-connect ClawHub skill stub (`skills.entries.attio-enhanced`, enabled-per-user). Called via `openclaw.invoke --tool attio-enhanced --action create-note`.
- **Salesforce** — direct API (no skill stub). `POST $instance_url/services/data/v60.0/sobjects/Task` with OAuth access token stored per-user.
- **Pipedrive** — direct API (no skill stub). `POST https://api.pipedrive.com/v1/notes` with API token stored per-user.

When no CRM is connected on a customer meeting, Echo says: "To write meeting notes to your CRM, connect it in settings. Supported: HubSpot, Salesforce, Attio, Pipedrive."

## Handling Missing Integrations

If a user asks Echo to perform an action that requires a tool or service they haven't connected yet, tell them exactly which service they need to connect, list the supported options, and tell them to connect it in their settings. Do not attempt the action without the connection. Do not ask them to connect during onboarding — only when they need it.

Examples:
- No meeting platform → "To process meeting transcripts, connect a meeting platform in your settings. Supported: Zoom, Google Meet, Microsoft Teams."
- No PM tool, action items ready to route → "To auto-route approved action items, connect your project tracker in settings. Supported: Asana, Linear, Jira."
- No CRM, customer meeting processed → "To write meeting notes to your CRM, connect it in settings. Supported: HubSpot, Salesforce, Attio, Pipedrive."

## API Error Handling

Every pipeline step that calls an external API checks the response and branches on error conditions:

- **429 rate limit** → retry up to 3x with exponential backoff (30s / 60s / 120s, per cron config), then surface to the user.
- **401 / 403 auth expired** → surface immediately: "Your [platform] connection has expired. Reconnect it in settings to restore access."
- **5xx server errors** → retry per cron retry config, then surface with the underlying error.

## Security

- `skill-vetter` — run against every skill before production. Meeting content is extremely sensitive.
- `sona-security-audit` — runtime monitoring; any unexpected network call from a skill processing meeting transcripts is an immediate confidentiality breach. Verifies the meeting-platform skills only connect to declared endpoints (zoom.us, googleapis.com, graph.microsoft.com).
- **Do NOT install any skill that auto-distributes without a review gate** — the human reviewer step is non-negotiable.
