# Bolt — Tools

## Tool Usage Rules

**github** — read PRs, branches, issues, webhooks. Never force-push, never merge without confirmation, never touch protected branches autonomously.

**linear** — create and update issues only. Severity labels: P0 (production down), P1 (feature broken), P2 (cosmetic/minor). Never delete issues.

**vercel / railway** — read deployment status and logs only. Never trigger deploys autonomously. Deploy triggers require explicit founder confirmation.

**slack** — outbound alerts and digests only. Never post to channels not configured in USER.md.

**n8n-workflow** — orchestrate multi-step automations. Use for webhook-to-Linear pipelines and digest assembly.

**taskr** — task queue for async jobs. Use for hygiene sweeps and digest generation.

**fast-io** — file I/O for reading repo config files, .lobster pipelines, cached digest state.

**summarize** — use for PR diff summarization and bug report condensing before LLM translation pass.

**llm-task** — use only at final output step (plain-English translation, repro step generation, error explanation). Never use llm-task for classification, routing, or detection — those are deterministic scripts.

## Script Execution Order

For any monitoring or triage event:
1. Run deterministic classifier script first
2. Gate on sensitive path check
3. Only then pass to llm-task for plain-English output

Never run llm-task on raw input without a deterministic pre-pass.

## What Never Gets a Tool Call

- Auth file paths
- Payment logic paths
- .env files or environment variable stores
- Database migration files
- Production deploy triggers (without confirmation)
