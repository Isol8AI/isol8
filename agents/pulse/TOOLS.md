# Pulse — Tool Usage Guide

## Lobster (Pipeline Orchestration)

- `content-generate.lobster` — research → draft → voice score → GEO check → queue (triggered per content request)
- `monitoring-sweep.lobster` — mentions, competitors, subreddits, freshness, calendar conflicts (daily cron)
- `weekly-digest.lobster` — Monday intelligence briefing with performance, GEO, voice drift, action items (Monday 7 AM cron)

## llm-task

- `thinking: "off"` — voice tone scoring, repurposing adaptations, email pattern synthesis, sensitive claim edge cases, mention sentiment, community response drafts
- `thinking: "low"` — content draft generation, weekly digest narrative
- Never `thinking: "medium"` or higher in pipelines

## Perplexity API (Research + Monitoring Engine)

Pulse's primary structured-web-search engine. Runs before every draft (competitor content, community questions, search trends) and through the daily monitoring sweep (brand mentions, competitor activity, subreddit scanning, active news cycles, community follow-ups) and the weekly GEO Share of Model tracking (one call per configured query).

**Not a ClawHub skill.** Called via direct `curl` from lobster `exec --shell` steps. The Perplexity `sonar` model is designed for structured web search with citations: every response has a `choices[0].message.content` plus a `citations[]` array of source URLs. This is a deterministic API — same query → same structured response shape — so every call is a deterministic step, NOT an llm-task call. The deterministic / LLM split is preserved exactly.

Canonical call shape:
```
curl -sS https://api.perplexity.ai/chat/completions \
  -H "Authorization: Bearer $PERPLEXITY_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"sonar","messages":[{"role":"user","content":"<query>"}]}'
```

In lobster pipelines, curl is piped into an inline `node -e` normalizer that extracts `content`, `citations`, `total`, `top_urls`, `high_signal_urls`, and any other fields downstream steps expect. For the weekly GEO sweep, iteration over N queries happens inside an inline `node -e` fetch loop (curl can't loop) — same Perplexity API, same deterministic character. Auth credential `PERPLEXITY_API_KEY` is set at the process environment level (not in `openclaw.json`) and is the only required env var beyond `OPENCLAW_HOOK_TOKEN`.

Pattern reference for other agents migrating off legacy search skills: this is the canonical replacement for category (a) structured web search. For raw page fetch / deep reading of a specific URL, use agent-browser instead (category b).

## agent-browser (Deep Web Reading)

Navigates to actual pages when a Perplexity citation needs deeper reading: competitor blog posts, Reddit threads, industry publications. Used in monitoring sweep for deep reading high-signal mention URLs and competitor content URLs. Safest high-download skill per ClawHavoc analysis.

## Content Production Skills

### reef-copywriting
Direct-response frameworks for conversion-focused content: landing pages, product descriptions, ads. Provides persuasive structure that overlaps with GEO requirements (BLUF, definitive language, specific claims).

### content-creator
SEO/GEO-optimized long-form content: blog posts, pillar pages, topic clusters. Builds the domain authority foundation GEO citation depends on. Applies GEO structural requirements at the architecture level.

### b2c-marketing
Organic growth playbook behind 300K+ app downloads. Strategic context for distribution decisions: channel prioritization, community engagement structures, growth tactics that feel human.

### brw-newsletter-creation-curation
Industry-adaptive B2B newsletter production. Stage, role, and geography-aware segmentation. Applies audience intelligence to produce newsletters adapted to segments rather than uniform across the list.

## Social Scheduling (install one)

### adaptlypost (recommended)
Instagram, X, TikTok, Threads, LinkedIn, Facebook, Bluesky. Verified in official openclaw/skills repo. Draft mode (`saveAsDraft: true`) maps to Pulse's approval gate — all content enters as draft, transitions to scheduled only after marketer confirms. Requires `ADAPTLYPOST_API_KEY` with post creation + scheduling scope only.

### postiz (self-hosted alternative)
28+ channels including Reddit, Medium, WordPress. Full data sovereignty. Self-hosting note: if VPS goes down, scheduled posts don't go out.

### post-bridge-social-manager
10 platforms with queue-based scheduling. Alternative if adaptlypost coverage is insufficient.

## Analytics

### biz-reporter
GA4, Search Console, Stripe reports. Provides web traffic and conversion data that connects content to business outcomes. Weekly digest uses this to show which content drove traffic that converted.

### posthog
Product analytics via REST API. Tracks post-arrival behavior: what visitors do, where they drop off, which content drives engaged sessions. Closes the gap between engagement metrics and business outcomes.

### performance-reporter
Synthesizes biz-reporter + posthog into formatted reports for the digest. SEO performance, traffic analysis, GEO tracking.

## gog (Google Workspace)

Gmail: incoming press mentions, subscriber replies, partnership opportunities. Google Sheets: content calendar, performance data, weekly reports. Google Drive: brand voice doc backup, content archive, GEO audit history.

## slack (Primary Interface)

Channel: `#pulse-content` — draft review presentations, Monday digest, brand mention alerts, calendar conflict warnings, community intelligence, queue status.

## fast-io (Persistent Storage)

Key structure:
- `pulse-config/brand-voice` — machine-readable brand voice document
- `pulse-config/platform-tones` — per-platform voice guidance
- `pulse-config/cultural-calendar` — sensitive dates (expandable by marketer)
- `pulse-config/geo-queries` — query set for Share of Model tracking
- `pulse-config/competitors` — competitor list for monitoring
- `pulse-config/reddit-monitors` — subreddit list + queries
- `pulse-config/auto-publish` — auto-publish configuration (off by default)
- `pulse-content/drafts/{{id}}` — content in draft state
- `pulse-content/approved/{{id}}` — approved, awaiting scheduling
- `pulse-content/published/{{id}}` — published content archive
- `pulse-state/queue-size` — current draft queue count
- `pulse-state/approved-claims` — previously verified claims (for adaptive suppression)
- `pulse-state/voice-overrides` — marketer's voice score corrections
- `pulse-state/review-history` — review actions for queue limiter analysis
- `pulse-geo/share-of-model/{{date}}` — weekly Share of Model results
- `pulse-monitoring/{{date}}` — daily monitoring results
- `pulse-community/engagements/{{id}}` — tracked community threads
- `audit/{{timestamp}}/{{action}}` — 12-month audit trail

## Direct API Integrations

### Mailchimp / Resend / Postmark
Email operations: timing, segmentation, A/B testing, delivery scheduling, list hygiene, performance data. Connect to user's existing platform. Minimum scope: send + analytics read.

### Ahrefs / Semrush
SEO foundation data: keyword rankings, backlink profile, domain authority. Complements GEO monitoring — traditional SEO contributes to AI citation probability. Read-only API credentials.

## Click-to-Connect Integrations

Every integration Pulse touches is enabled by the user through the Isol8 settings UI — never through an onboarding prompt. Pulse only mentions a missing integration when the user asks for something that requires it.

### Social scheduling — click-to-connect (install one)
adaptlypost (recommended), postiz (self-hosted), post-bridge-social-manager. When the user asks Pulse to schedule or draft content and no social scheduler is connected, Pulse says: "To schedule content, connect your social scheduling platform in settings. Supported: adaptlypost, postiz, post-bridge-social-manager." Content can still be researched, drafted, and voice-scored without a social scheduler.

### Email platform — click-to-connect (install one)
Mailchimp, Resend, Postmark. When the user asks about email operations and no email platform is connected, Pulse says: "To run email operations, connect your email platform in settings. Supported: Mailchimp, Resend, Postmark."

### SEO data — click-to-connect (install one, optional)
Ahrefs, Semrush. Read-only API credentials. When the user asks about keyword data, backlink profiles, or domain authority and no SEO tool is connected, Pulse says: "To pull SEO data, connect your SEO platform in settings. Supported: Ahrefs, Semrush."

### CRM — click-to-connect (single platform)
HubSpot, Salesforce, Attio, Pipedrive. Pulse doesn't write to CRM directly in its current pipelines, but if marketing campaign targeting or lead intelligence requires CRM data, Pulse says: "To access CRM data, connect your CRM in settings. Supported: HubSpot, Salesforce, Attio, Pipedrive."

### Outbound email — click-to-connect (single platform)
Instantly, SmartLead, Mailshake, Lemlist. Pulse's focus is content, not outbound sequences, but if the user asks about outbound integration: "To connect outbound email, configure it in settings. Supported: Instantly, SmartLead, Mailshake, Lemlist."

## Handling Missing Integrations

If a user asks Pulse to perform an action that requires a tool or service they haven't connected yet, tell them exactly which service they need to connect, list the supported options, and tell them to connect it in their settings. Do not attempt the action without the connection. Do not ask them to connect during onboarding — only when they need it.

Examples:
- No social scheduler connected, user wants content scheduled → "To schedule content, connect your social scheduling platform in settings. Supported: adaptlypost, postiz, post-bridge-social-manager."
- No brand voice doc configured, user wants a draft → "To draft content, I need your brand voice document. Configure it in settings — it takes about 15 minutes and is the most important setup step."
- No competitors configured, user asks for competitive intelligence → "To track competitors, configure your competitor list in settings."
- No GEO queries configured, user asks about Share of Model → "To track Share of Model, configure your GEO query set in settings."

## API Error Handling

Every pipeline step that calls an external API checks the response and branches on error conditions:

- **429 rate limit** → retry up to 3x with exponential backoff (60s / 120s / 300s, per cron config), then surface to the user: "Research API is rate-limiting — retrying automatically. If this keeps happening, check your Perplexity plan usage."
- **401 / 403 auth expired** → surface immediately: "Your Perplexity API key is invalid or expired. Update `PERPLEXITY_API_KEY` in your environment to restore research and monitoring."
- **5xx server errors** → retry per cron retry config, then surface with the underlying error.

## Security

- `skill-vetter` — run before production, especially social scheduling skills holding platform OAuth tokens
- `sona-security-audit` — runtime monitoring; a compromised social skill with posting permissions is a brand disaster
- Social scheduling configured in draft mode by default — Pulse cannot post without approval
- Do NOT install any skill that posts through unofficial platform APIs or browser automation
- Do NOT install any skill claiming autonomous community engagement
