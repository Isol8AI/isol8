# Lens — First Run Bootstrap

This file runs once on first activation. Complete all steps, then delete this file.

Lens does not interrogate the user during bootstrap. Research verticals, confidence thresholds, freshness thresholds, and monitoring topics are configured through the Isol8 settings UI — Lens only mentions them when the user actually asks for something that needs them.

## Step 1: Validate Prerequisites

Required:
- `PERPLEXITY_API_KEY`
- `OPENCLAW_HOOK_TOKEN`

No other API keys are required at bootstrap. Semantic Scholar API is free with no key. agent-browser is a built-in skill. Vertical-specific skills (arxiv-search-collector, pubmed-edirect, depo-bot, social-intelligence, etc.) are click-to-connect — the user enables them in settings when they need them.

## Step 2: Initialize State

```
lens-config/verticals → {}
lens-config/confidence-thresholds → {}
lens-config/freshness-thresholds → {}
lens-config/monitoring → {}
lens-state/source-overrides → {}
lens-state/historical-research → {}
lens-state/degradation-dismissals → {}
lens-state/user-format-preference → null
lens-state/confidence-overrides → {}
```

No vertical is required at bootstrap — the user configures verticals from the settings UI before asking Lens to research anything.

## Step 3: Create Slack Channel

Verify or create: `#lens-research` — research plan approvals, findings delivery, monitoring alerts, confidence reviews.

## Step 4: Create Google Sheets + Drive

Via gog:
- "Lens Confidence Tracker" — confidence tier status for all active research
- "Lens Research Archive" folder in Drive — every deliverable with source appendix

## Step 5: Set Up Cron Jobs

```
openclaw cron add --name "lens-monitoring-sweep" --cron "0 6 * * *" --tz "$USER_TIMEZONE" --session isolated --message "Run monitoring-sweep pipeline — alert only on meaningful changes" --thinking low --light-context

openclaw cron add --name "lens-weekly-maintenance" --cron "0 20 * * 0" --tz "$USER_TIMEZONE" --session isolated --message "Run weekly-maintenance pipeline — confidence degradation check" --thinking low --light-context
```

## Step 6: Security Checks

Run skill-vetter against every enabled skill. Enable sona-security-audit for runtime monitoring.

## Step 7: Run Activation Check

Run `lens-activation-check.js`:
- Exit code 0 = go, exit code 1 = blocker

## Step 8: Go Live

Post one message to Slack:

"Lens is live. When you want me to research something, just tell me — I'll decompose the question, show you my plan, wait for your approval, then run multi-pass verification. Every finding comes with a confidence tier and source citation. If you haven't configured your research verticals yet, you can do that in settings — no setup paperwork up front."

## Step 9: Delete This File
