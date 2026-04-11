name: weekly-review
# Nexus Monday 8am comprehensive weekly review.
# Requirements 10, 12, 27: deeper pass than the daily — goal progress over
# the week, budget utilization trends, cross-agent contradictions, recommended
# org changes. Drift detection runs deterministically before the LLM. The LLM
# fires once (thinking: low) for the comprehensive narrative + recommendations.

steps:
  # ──────────────────────────────────────────────
  # Step 1 — pull the full week of data
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

  - id: load-budget-baseline
    command: >
      openclaw.invoke --tool fast-io --action read --args-json '{"key": "nexus-state/budget-baseline"}'

  - id: load-budget-overview
    command: >
      exec --json --shell 'node scripts/paperclip-budget-read.js'
    stdin: '{"mode": "overview"}'

  - id: load-activity-week
    command: >
      exec --json --shell 'node scripts/paperclip-activity-feed.js'
    stdin: '{"since": "{{timestamp_7d_ago}}"}'

  - id: load-org
    command: >
      exec --json --shell 'node scripts/paperclip-org-read.js'
    stdin: '{"mode": "roster_with_health"}'

  - id: load-pending-approvals
    command: >
      exec --json --shell 'node scripts/paperclip-governance.js'
    stdin: '{"mode": "pending"}'

  # ──────────────────────────────────────────────
  # Step 2 — deterministic drift + circuit state snapshot
  # ──────────────────────────────────────────────
  - id: goal-drift
    command: >
      exec --json --shell 'node scripts/nexus-goal-drift.js'
    stdin: '{"max_fetches": 50}'

  - id: load-paused-agents
    command: >
      openclaw.invoke --tool fast-io --action read --args-json '{"key": "nexus-state/paused-agents"}'

  # ──────────────────────────────────────────────
  # Step 3 — compress raw data for the LLM context window
  # ──────────────────────────────────────────────
  - id: compress-issues
    command: >
      openclaw.invoke --tool summarize --action compress --args-json '{
        "input": $load-issues.json,
        "format": "structured-by-agent",
        "focus": "completion-rate-and-blockers"
      }'

  - id: compress-activity
    command: >
      openclaw.invoke --tool summarize --action compress --args-json '{
        "input": $load-activity-week.json.events,
        "format": "weekly-narrative",
        "focus": "notable-patterns"
      }'

  - id: compress-costs
    command: >
      openclaw.invoke --tool summarize --action compress --args-json '{
        "input": $load-costs-by-agent.json.by_agent,
        "format": "utilization-table",
        "focus": "over-and-under-utilized"
      }'

  # ──────────────────────────────────────────────
  # Step 4 — LLM comprehensive review (the only LLM call)
  # ──────────────────────────────────────────────
  - id: draft-review
    command: >
      openclaw.invoke --tool llm-task --action json --args-json '{
        "prompt": "Write a comprehensive weekly business review for Nexus. For every goal, note progress this week vs last week (use the baseline). For each specialist agent, classify as on_track / at_risk / blocked based on completion rate and utilization. Surface any cross-agent conflicts — if two agents are working on contradictory timelines, name both and explain the contradiction. Recommend budget reallocations when one agent is over 80% and another is under 40%. Recommend org changes (add/remove/reconfigure specialists) only when metrics clearly support it — explain the metrics. Mark confidence low if any data is missing or conflicting. Every recommendation must cite the data point that justifies it.",
        "thinking": "low",
        "input": {
          "goals": $load-goals.json.goals,
          "issues_summary": $compress-issues.stdout,
          "costs_summary": $compress-costs.stdout,
          "cost_baseline": $load-budget-baseline.json,
          "budget_overview": $load-budget-overview.json.overview,
          "activity_narrative": $compress-activity.stdout,
          "org_health": $load-org.json.agents,
          "paused_agents": $load-paused-agents.json,
          "drifted_issues": $goal-drift.json.drifted,
          "pending_approvals_count": $load-pending-approvals.json.count
        },
        "schema": {
          "type": "object",
          "properties": {
            "headline": {"type": "string"},
            "goal_progress": {"type": "array", "items": {"type": "string"}},
            "on_track_agents": {"type": "array", "items": {"type": "string"}},
            "at_risk_agents": {"type": "array", "items": {"type": "string"}},
            "blocked_agents": {"type": "array", "items": {"type": "string"}},
            "cross_agent_conflicts": {"type": "array", "items": {"type": "string"}},
            "budget_utilization": {"type": "string"},
            "recommended_reallocations": {"type": "array", "items": {"type": "string"}},
            "recommended_org_changes": {"type": "array", "items": {"type": "string"}},
            "confidence": {"type": "string", "enum": ["high", "medium", "low"]}
          },
          "required": ["headline", "goal_progress", "confidence"]
        }
      }'

  # ──────────────────────────────────────────────
  # Step 5 — render + post the review via the template
  # ──────────────────────────────────────────────
  - id: render-review
    command: >
      exec --json --shell 'node scripts/nexus-notify.js'
    stdin: '{"template": "weekly-review", "data": $draft-review.json}'

  - id: post-review
    command: >
      openclaw.invoke --tool slack --action post --args-json '{
        "channel": "{{NEXUS_NOTIFY_CHANNEL}}",
        "text": "$render-review.json.text"
      }'
    condition: $render-review.json.text

  # ──────────────────────────────────────────────
  # Step 6 — snapshot current costs for next week's comparison
  # ──────────────────────────────────────────────
  - id: snapshot-budget-baseline
    command: >
      openclaw.invoke --tool fast-io --action write --args-json '{
        "key": "nexus-state/budget-baseline",
        "data": {
          "captured_at": "{{timestamp}}",
          "by_agent": $load-costs-by-agent.json.by_agent,
          "overview": $load-budget-overview.json.overview
        }
      }'

  # ──────────────────────────────────────────────
  # Step 7 — audit log
  # ──────────────────────────────────────────────
  - id: audit-log
    command: >
      openclaw.invoke --tool fast-io --action write --args-json '{
        "key": "nexus-audit/{{timestamp}}/weekly-review",
        "data": {
          "action": "weekly_review",
          "goals_tracked": $load-goals.json.count,
          "issues_reviewed": $load-issues.json.count,
          "drifted_issues": $goal-drift.json.drifted_count,
          "pending_approvals": $load-pending-approvals.json.count,
          "review_confidence": $draft-review.json.confidence,
          "timestamp": "{{timestamp}}"
        }
      }'
