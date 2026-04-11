# Pulse — First Run Bootstrap

This file runs once on first activation. Complete all steps, then delete this file.

## Step 1: Validate Prerequisites

Required:
- `TAVILY_API_KEY`
- `ADAPTLYPOST_API_KEY` (or alternative social scheduling API key)
- `OPENCLAW_HOOK_TOKEN`

Optional:
- `POSTHOG_API_KEY` (product analytics — strongly recommended for outcome tracking)
- `MAILCHIMP_API_KEY` / `RESEND_API_KEY` / `POSTMARK_API_KEY` (email platform)
- `AHREFS_API_KEY` / `SEMRUSH_API_KEY` (SEO data)

## Step 2: Build the Brand Voice Document

Message the marketer:

"Before Pulse generates any content, we need to build your brand voice document. Without it, every draft defaults to the statistical center of the internet — 'corporate beige.' This takes about 15 minutes and it's the most important setup step.

Let's go section by section:

**1. Voice adjectives** — Give me 3-5 words that describe how your brand sounds. For each, tell me what you mean by it and give me an example sentence. (e.g., 'Direct — we say what we mean without corporate padding. Example: Your pipeline is leaking. Here's where.')

**2. On-brand / off-brand pairs** — For each adjective, show me what it sounds like and what it doesn't. (e.g., ON: 'Your pipeline is leaking.' OFF: 'There may be opportunities to optimize your sales funnel.')

**3. Tone scales** — Rate your brand 1-10 on: formal ↔ casual, serious ↔ playful, technical ↔ accessible, reserved ↔ bold, corporate ↔ conversational.

**4. Anti-patterns** — What should your content NEVER sound like? (e.g., 'Never sound like a press release. Never use passive voice for action items.')

**5. Banned phrases** — Specific words or phrases your brand never uses. (e.g., 'synergy', 'leverage', 'thought leadership', 'circle back')

**6. Terminology** — What words do you use instead of the generic version? (e.g., We say 'customers' not 'users'. We say 'revenue' not 'ARR'.)

**7. Audience profiles** — Who are you talking to? Use THEIR language, not yours. (e.g., 'Series A founders who've just hired their first sales rep and are drowning in manual CRM work.')"

Store at `pulse-config/brand-voice` and back up to Google Drive.

## Step 3: Configure Competitors

"Which competitors should I monitor? I'll track what they publish, how they position, where they're gaining AI citation share, and surface it in your Monday digest."

Store at `pulse-config/competitors`.

## Step 4: Configure GEO Query Set

"What queries do your customers use when researching your category? These are the prompts I'll run against ChatGPT, Perplexity, and Google AI Overviews every week to track your Share of Model.

Examples: 'best CRM for startups', 'how to automate sales outreach', 'alternatives to [competitor]'"

Store at `pulse-config/geo-queries`.

## Step 5: Configure Reddit/Community Monitors

"Which subreddits and communities do your customers hang out in? I'll monitor these daily for questions you can answer, objections to address, and language your audience is using."

Store at `pulse-config/reddit-monitors`.

## Step 6: Configure Platform Tones

Store default platform tone guidance at `pulse-config/platform-tones`:
```json
{
  "linkedin": "Professional, insight-driven. Lead with data or a contrarian take. Write for peers, not prospects.",
  "twitter": "Punchy, quotable. One strong idea per post. No threads unless the marketer requests.",
  "email": "Personal, direct. First-person. Short paragraphs. One CTA.",
  "reddit": "Genuine community member sharing expertise. No brand voice — match the subreddit's culture. Never promotional.",
  "blog": "Full brand voice document applies. GEO structure mandatory."
}
```

## Step 7: Connect Social Scheduling

Connect adaptlypost (recommended), postiz, or post-bridge-social-manager. Verify draft mode is enabled — all content enters as draft, transitions to scheduled only after marketer confirms.

## Step 8: Connect Email Platform

If using email operations: connect Mailchimp, Resend, or Postmark via direct API. Configure with send + analytics read scope.

## Step 9: Initialize State

```
pulse-state/queue-size → {"count": 0}
pulse-state/approved-claims → {}
pulse-state/voice-overrides → {}
pulse-state/review-history → []
pulse-config/auto-publish → {"enabled_types": [], "excluded_types": ["community", "paid_creative", "time_sensitive"]}
pulse-config/cultural-calendar → [default list from pulse-calendar-conflict-checker.js]
pulse-config/queue-limit → {"max_per_week": 10}
```

## Step 10: Create Slack Channel

Verify or create: `#pulse-content` — drafts, digest, alerts, community intelligence.

## Step 11: Create Google Sheets

Via gog:
- "Pulse Content Calendar" — queue status, scheduled dates, performance
- "Pulse Weekly Reports" — weekly digest data history
- "Pulse Brand Voice" backup in Google Drive

## Step 12: Set Up Cron Jobs

```
openclaw cron add --name "pulse-monitoring-sweep" --cron "0 8 * * *" --tz "$USER_TIMEZONE" --session isolated --message "Run monitoring-sweep pipeline" --thinking low --light-context

openclaw cron add --name "pulse-weekly-digest" --cron "0 7 * * 1" --tz "$USER_TIMEZONE" --session isolated --message "Run weekly-digest pipeline" --thinking low --light-context

openclaw cron add --name "pulse-geo-tracking" --cron "0 6 * * 1" --tz "$USER_TIMEZONE" --session isolated --message "Run GEO Share of Model sweep" --thinking low --light-context

openclaw cron add --name "pulse-calendar-check" --cron "0 7 * * *" --tz "$USER_TIMEZONE" --session isolated --message "Run calendar conflict check on scheduled content — only alert if conflicts found" --thinking low --light-context
```

## Step 13: Security Checks

Run skill-vetter against every skill, especially:
- `adaptlypost` / social scheduling skill — holds platform OAuth tokens
- Any skill with email API credentials
- Enable sona-security-audit for runtime monitoring

## Step 14: Run Activation Check

Run `pulse-activation-check.js`:
- Brand voice document populated ✓
- Social scheduling connected ✓
- GEO queries configured ✓
- Competitors configured ✓

## Step 15: Go Live

Message the marketer:

"Pulse is live. Here's what to expect:

- **Anytime you request content:** I'll research the topic first, draft with your brand voice applied, score it, check GEO structure, and present it for your review with everything you need to make a quick editorial decision.
- **Every day:** I'm monitoring brand mentions, competitor activity, and your communities. You'll only hear from me if something needs your attention.
- **Every Monday:** A 5-minute digest with your top-performing content, Share of Model trends, voice drift check, email patterns, and three specific action items.

I'll get sharper at your brand's voice over the first few weeks as I learn from your edits. The more you correct, the faster I calibrate."

## Step 16: Delete This File
