# Pulse — Tool Usage Guide

## Lobster (Pipeline Orchestration)

- `content-generate.lobster` — research → draft → voice score → GEO check → queue (triggered per content request)
- `monitoring-sweep.lobster` — mentions, competitors, subreddits, freshness, calendar conflicts (daily cron)
- `weekly-digest.lobster` — Monday intelligence briefing with performance, GEO, voice drift, action items (Monday 7 AM cron)

## llm-task

- `thinking: "off"` — voice tone scoring, repurposing adaptations, email pattern synthesis, sensitive claim edge cases, mention sentiment, community response drafts
- `thinking: "low"` — content draft generation, weekly digest narrative
- Never `thinking: "medium"` or higher in pipelines

## tavily (Research + Monitoring Engine)

Primary research tool. Runs before every draft: competitor content, community questions, search trends, industry data. Also runs the daily monitoring sweep: brand mentions, competitor activity, subreddit scanning. Weekly GEO monitoring: queries AI platforms for Share of Model tracking. 132 stars on ClawHub. Requires `TAVILY_API_KEY`.

## agent-browser (Deep Web Reading)

Navigates to actual pages when Tavily snippets aren't enough: competitor blog posts, Reddit threads, industry publications. Used in monitoring sweep for deep reading high-signal results. Safest high-download skill per ClawHavoc analysis.

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

## Security

- `skill-vetter` — run before production, especially social scheduling skills holding platform OAuth tokens
- `sona-security-audit` — runtime monitoring; a compromised social skill with posting permissions is a brand disaster
- Social scheduling configured in draft mode by default — Pulse cannot post without approval
- Do NOT install any skill that posts through unofficial platform APIs or browser automation
- Do NOT install any skill claiming autonomous community engagement
