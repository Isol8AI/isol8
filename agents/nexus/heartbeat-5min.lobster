name: heartbeat-5min
# Nexus 5-minute cron sweep.
# Requirements 4, 6, 8, 15, 19, 22, 26: pulls activity feed, counts consecutive
# failures for the circuit breaker, flags goal drift, surfaces new pending
# approvals. Zero LLM on the common path — every notification fires through
# a deterministic template via nexus-notify.js.

steps:
  # ──────────────────────────────────────────────
  # Step 1 — load heartbeat state from fast-io
  # ──────────────────────────────────────────────
  - id: load-cursor
    command: >
      openclaw.invoke --tool fast-io --action read --args-json '{"key": "nexus-state/cursor"}'

  - id: load-paused
    command: >
      openclaw.invoke --tool fast-io --action read --args-json '{"key": "nexus-state/paused-agents"}'

  - id: load-notified-approvals
    command: >
      openclaw.invoke --tool fast-io --action read --args-json '{"key": "nexus-state/notified-approvals"}'

  # ──────────────────────────────────────────────
  # Step 2 — deterministic coordination checks
  # ──────────────────────────────────────────────
  - id: circuit-breaker
    command: >
      exec --json --shell 'node scripts/nexus-circuit-breaker.js'
    stdin: '{"paused_agents": $load-paused.json, "threshold": 3, "window_minutes": 60}'

  - id: goal-drift
    command: >
      exec --json --shell 'node scripts/nexus-goal-drift.js'
    stdin: '{"max_fetches": 20}'

  - id: pending-approvals
    command: >
      exec --json --shell 'node scripts/paperclip-governance.js'
    stdin: '{"mode": "pending"}'

  - id: approval-diff
    command: >
      exec --json --shell 'node scripts/nexus-approval-diff.js'
    stdin: '{"current_approvals": $pending-approvals.json.approvals, "notified_ids": $load-notified-approvals.json}'

  # ──────────────────────────────────────────────
  # Step 3 — fire template notifications (conditional, deterministic)
  # ──────────────────────────────────────────────
  - id: notify-circuit-breaker
    command: >
      exec --json --shell 'node scripts/nexus-notify.js'
    stdin: '{"template": "circuit-breaker", "data": $circuit-breaker.json.new_pauses}'
    condition: $circuit-breaker.json.new_pauses.length > 0

  - id: notify-goal-drift
    command: >
      exec --json --shell 'node scripts/nexus-notify.js'
    stdin: '{"template": "goal-drift", "data": $goal-drift.json.drifted}'
    condition: $goal-drift.json.drifted_count > 0

  - id: notify-new-approvals
    command: >
      exec --json --shell 'node scripts/nexus-notify.js'
    stdin: '{"template": "agentgate-escalation", "data": $approval-diff.json.new_approvals}'
    condition: $approval-diff.json.new_count > 0

  # ──────────────────────────────────────────────
  # Step 4 — persist updated state back to fast-io
  # ──────────────────────────────────────────────
  - id: persist-paused
    command: >
      openclaw.invoke --tool fast-io --action write --args-json '{
        "key": "nexus-state/paused-agents",
        "data": $circuit-breaker.json.failure_counts
      }'

  - id: persist-notified-approvals
    command: >
      openclaw.invoke --tool fast-io --action write --args-json '{
        "key": "nexus-state/notified-approvals",
        "data": $approval-diff.json.updated_notified_ids
      }'

  - id: persist-cursor
    command: >
      openclaw.invoke --tool fast-io --action write --args-json '{
        "key": "nexus-state/cursor",
        "data": "{{timestamp}}"
      }'

  # ──────────────────────────────────────────────
  # Step 5 — audit log
  # ──────────────────────────────────────────────
  - id: audit-log
    command: >
      openclaw.invoke --tool fast-io --action write --args-json '{
        "key": "nexus-audit/{{timestamp}}/heartbeat",
        "data": {
          "action": "heartbeat_sweep",
          "circuit_breaker_new_pauses": $circuit-breaker.json.new_pauses.length,
          "goal_drift_count": $goal-drift.json.drifted_count,
          "new_approvals_count": $approval-diff.json.new_count,
          "stale_approvals_cleared": $approval-diff.json.stale_count,
          "timestamp": "{{timestamp}}"
        }
      }'
