name: daily-digest
# Nexus weekday 8am business summary.
# Requirements 10, 11: synthesizes goals/budget/activity into a brief,
# action-oriented status report. Data collection is deterministic. The
# LLM fires once (thinking: low) to turn the structured Paperclip data
# into readable prose — classification (>80% on_track, 50-80% at_risk,
# <50% blocked) happens in the prompt, not in a separate script.

steps:
  # ──────────────────────────────────────────────
  # Step 1 — pull the data for the last 24 hours
  # ──────────────────────────────────────────────
  - id: load-goals
    command: >
      exec --json --shell 'node scripts/paperclip-goal-manage.js'
    stdin: '{"action": "list"}'

  - id: load-issues
    command: >
      exec --json --shell 'node scripts/paperclip-task-read.js'
    stdin: '{"mode": "list"}'

  - id: load-costs-by-agent
    command: >
      exec --json --shell 'node scripts/paperclip-budget-read.js'
    stdin: '{"mode": "by_agent"}'

  - id: load-budget-overview
    command: >
      exec --json --shell 'node scripts/paperclip-budget-read.js'
    stdin: '{"mode": "overview"}'

  - id: load-pending-approvals
    command: >
      exec --json --shell 'node scripts/paperclip-governance.js'
    stdin: '{"mode": "pending"}'

  - id: load-activity-24h
    command: >
      exec --json --shell 'node scripts/paperclip-activity-feed.js'
    stdin: '{"since": "{{timestamp_24h_ago}}"}'

  - id: load-org
    command: >
      exec --json --shell 'node scripts/paperclip-org-read.js'
    stdin: '{"mode": "roster_with_health"}'

  # ──────────────────────────────────────────────
  # Step 2 — compress the raw data before the LLM sees it
  # ──────────────────────────────────────────────
  - id: compress-issues
    command: >
      openclaw.invoke --tool summarize --action compress --args-json '{
        "input": $load-issues.json,
        "format": "bullet-points",
        "focus": "by-agent-status"
      }'

  - id: compress-activity
    command: >
      openclaw.invoke --tool summarize --action compress --args-json '{
        "input": $load-activity-24h.json.events,
        "format": "bullet-points",
        "focus": "notable-events"
      }'

  # ──────────────────────────────────────────────
  # Step 3 — LLM narrative (the only LLM call in this pipeline)
  # ──────────────────────────────────────────────
  - id: draft-digest
    command: >
      openclaw.invoke --tool llm-task --action json --args-json '{
        "prompt": "Write a daily business digest for Nexus. Classify each goal by progress: >80% = on_track, 50-80% = at_risk, <50% = blocked. Lead with a three-line headline capturing the single most decision-relevant signal. List on_track / at_risk / blocked goals by name. Note any budget trends (agents over 80% utilization, agents under 40%). Recommend 1-3 concrete next actions. Mark confidence low if cross-agent data conflicts or if any critical field is missing. Every claim must trace to the structured input — do not invent numbers.",
        "thinking": "low",
        "input": {
          "goals": $load-goals.json.goals,
          "issues_summary": $compress-issues.stdout,
          "costs_by_agent": $load-costs-by-agent.json.by_agent,
          "budget_overview": $load-budget-overview.json.overview,
          "pending_approvals_count": $load-pending-approvals.json.count,
          "activity_summary": $compress-activity.stdout,
          "org_health": $load-org.json.agents
        },
        "schema": {
          "type": "object",
          "properties": {
            "headline": {"type": "string"},
            "on_track": {"type": "array", "items": {"type": "string"}},
            "at_risk": {"type": "array", "items": {"type": "string"}},
            "blocked": {"type": "array", "items": {"type": "string"}},
            "budget_notes": {"type": "string"},
            "recommended_actions": {"type": "array", "items": {"type": "string"}},
            "confidence": {"type": "string", "enum": ["high", "medium", "low"]}
          },
          "required": ["headline", "on_track", "at_risk", "blocked", "confidence"]
        }
      }'

  # ──────────────────────────────────────────────
  # Step 4 — render + post the digest via the template
  # ──────────────────────────────────────────────
  - id: render-digest
    command: >
      exec --json --shell 'node scripts/nexus-notify.js'
    stdin: '{"template": "daily-digest", "data": $draft-digest.json}'

  - id: post-digest
    command: >
      openclaw.invoke --tool slack --action post --args-json '{
        "channel": "{{NEXUS_NOTIFY_CHANNEL}}",
        "text": "$render-digest.json.text"
      }'
    condition: $render-digest.json.text

  # ──────────────────────────────────────────────
  # Step 5 — audit log
  # ──────────────────────────────────────────────
  - id: audit-log
    command: >
      openclaw.invoke --tool fast-io --action write --args-json '{
        "key": "nexus-audit/{{timestamp}}/daily-digest",
        "data": {
          "action": "daily_digest",
          "goals_tracked": $load-goals.json.count,
          "issues_reviewed": $load-issues.json.count,
          "pending_approvals": $load-pending-approvals.json.count,
          "digest_confidence": $draft-digest.json.confidence,
          "timestamp": "{{timestamp}}"
        }
      }'
