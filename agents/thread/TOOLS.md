# Thread — Tool Usage Guide

## gog (Gmail + Google Workspace)

Thread's primary email channel. Gmail read: incoming emails surface in the unified stream. Gmail send: confirmed outbound emails sent from the user's real address. Contacts: feeds the relationship model. Calendar: provides time-sensitivity context for triage (meetings happening today boost message priority). 14K+ downloads.

### Gmail real-time delivery via Google Pub/Sub push

Thread does not poll Gmail. Real-time inbound delivery is handled by gog's `users.watch` API, which registers a Google Cloud Pub/Sub topic as the destination for mailbox change notifications. When a new message arrives, Google Pub/Sub pushes a notification containing the latest `historyId` to Thread's `/hooks/agent` endpoint. The hook handler then:

1. Calls `gog --action gmail-history-list` with the stored prior `historyId` to discover new message IDs.
2. Calls `gog --action gmail-get-message` for each new ID to fetch the full message.
3. Invokes the `message-inbound` lobster once per message with `channel`, `sender`, `content`, `message_id` args.
4. Persists the new `historyId` so the next push continues from the correct point.

The `users.watch` registration expires after 7 days per Google policy and must be renewed. The `thread-watch-renewal` cron (registered in BOOTSTRAP) calls `gog --action gmail-watch` daily to keep the subscription live. Pub/Sub topic name, subscription name, and service-account permissions are configured in the user's Google Cloud project and linked from the isol8 settings UI — click-to-connect, not an onboarding prompt.

This replaces the legacy webhook-provider layer: no third-party inbox infrastructure, no extra API key, no extra skill. `gog` is the only dependency for Gmail real-time delivery.

## email-security (Mandatory Security Layer)

Runs on every inbound email before the AI layer sees content. Sanitizes email content: sender verification, HTML stripping, threat pattern detection, invisible formatting removal. Implements Thread's PRD requirement that all email content is cleaned before AI processing. The EchoLeak vulnerability (CVE-2025-32711) was delivered through invisible HTML — email-security eliminates that vector. Non-negotiable: Thread must not read a raw email body.

## slack (Internal Channel + Notification Surface)

Inbound: Slack DMs and mentions surface in the stream labeled "Slack · [sender]." Outbound: sends confirmed messages through the user's Slack workspace. Internal auto-send: the only channel category eligible for send-without-confirmation. Thread's notification channel: morning briefings, follow-up suggestions, draft approvals, security alerts all deliver here.

## himalaya (Optional — IMAP/SMTP)

For non-Google email accounts (custom domains, non-Gmail). Terminal-based IMAP/SMTP. Install only if the user has email accounts gog doesn't cover. Confirm VirusTotal clearance.

## Native OpenClaw Channels

WhatsApp, Telegram, Signal, iMessage, Discord, Microsoft Teams, Google Chat, Matrix, LINE, Mattermost — platform-level integrations, no skill install required. Each surfaces in the stream with its channel tag.

## Direct APIs

### LinkedIn Messaging API
Professional communication channel. Inbound: "LinkedIn · [contact]" in stream. Outbound: confirmed replies via API. OAuth with `w_messages` scope. LinkedIn terms restrict automated messaging — Thread routes confirmed user-approved replies only.

### Twilio SMS API
Highest-response-rate channel for time-sensitive communication. Inbound: "SMS · [contact]" in stream. Outbound: confirmed messages via Twilio. Almost always requires confirmation — SMS is the most interruptive channel.

## fast-io (Persistent Memory)

Key structure:
- `thread-stream/{{timestamp}}/{{id}}` — unified message stream
- `thread-contacts/{{id}}/history` — relationship thread per contact
- `thread-contacts/{{id}}/preferences` — channel preference model
- `thread-contacts/by-name/{{name}}` — contact lookup index
- `thread-contacts/by-address/{{address}}` — contact lookup index
- `thread-outbound/{{timestamp}}/{{id}}` — tracked outbound for follow-up
- `thread-config/connected-channels` — authorized channels with scopes
- `thread-config/auto-send-channels` — internal Slack auto-send list
- `thread-config/triage-weights` — configurable triage dimension weights
- `thread-config/relationship-tiers` — tier definitions and scores
- `thread-config/history-window` — message history access limit
- `thread-state/safe-senders` — injection detection safe list
- `thread-state/user-overrides` — channel routing overrides per contact
- `thread-audit/{{date}}/{{action}}` — 12-month audit trail

## Click-to-Connect Channels

Every channel Thread touches beyond the built-in defaults is enabled by the user through the Isol8 settings UI — never through an onboarding prompt. Thread only mentions a missing channel when the user asks for something that requires it.

- **Gmail** — click-to-connect via gog (Google OAuth). Activates Gmail read + send and registers the `gmail.watch` Pub/Sub subscription in a single step.
- **Slack** — click-to-connect. DMs and mentions surface in the stream; the only channel eligible for internal auto-send.
- **WhatsApp, Telegram, Signal, iMessage, Discord, Microsoft Teams, Google Chat, Matrix, LINE, Mattermost** — click-to-connect via native OpenClaw channels, one toggle per platform.
- **LinkedIn Messaging** — click-to-connect. Requires `w_messages` OAuth scope. Outbound only via user-confirmed replies (LinkedIn's terms).
- **SMS / Voice (Twilio)** — click-to-connect. Outbound SMS always requires confirmation — SMS is the most interruptive channel.
- **Other email (IMAP/SMTP via himalaya)** — click-to-connect for custom domains and non-Google email. Disabled by default; enable from settings when the user has a non-Gmail account.

## Handling Missing Integrations

If a user asks Thread to perform an action that requires a channel or integration they haven't connected yet, tell them exactly which service they need to connect, list the supported options, and tell them to connect it in their settings. Do not attempt the action without the connection. Do not ask them to connect during onboarding — only when they need it.

Examples:
- User asks Thread to send an email, no email channel connected → "To send email, connect Gmail in settings (via gog). For non-Gmail accounts, enable himalaya for IMAP/SMTP."
- User asks Thread to message someone on WhatsApp, WhatsApp not connected → "To message on WhatsApp, connect WhatsApp in your settings."
- User asks for an SMS reply, Twilio not connected → "To send SMS, connect Twilio in settings (you'll need a Twilio account, number, and auth token)."
- User asks Thread to read Teams DMs, Teams not connected → "To read Microsoft Teams messages, connect Teams in your settings."

Never proceed past the "you need to connect X" response until the user confirms the connection is in place.

## Security — Highest Priority in the Suite

Thread has send access to email and Slack on the user's behalf, processes every incoming message, and maintains full relationship history. This is the highest-risk agent.

- `skill-vetter` — run against every skill. Pay special attention to `gog` (Gmail read + send + Pub/Sub push scope) and any outbound channel skill with send permissions. Verify network calls match declared endpoints (`googleapis.com`, `slack.com`, `api.linkedin.com`, `api.twilio.com`).
- `sona-security-audit` — runtime monitoring; any skill making calls outside declared scope pauses Thread and alerts the user
- `email-security` — mandatory; runs on every inbound email before the AI layer. Non-negotiable defense against EchoLeak-class invisible-HTML injection.
- Do NOT install any unified messaging skill without verifiable ClawHub page, download count, and author history
- Do NOT install any skill under 30 days old without VirusTotal clearance
