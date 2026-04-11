# BOOTSTRAP.md — Nexus First-Run Setup

You are being run for the first time. Work through these steps in order. If any step fails with a blocker, stop and tell the user what is missing. When every step passes, run `nexus-activation-check.js` as the final gate, then delete this file.

## Step 1 — Environment validation

Required environment:
- `PAPERCLIP_BOARD_KEY_PATH` — filesystem path where the Paperclip Board API Key is mounted by the backend provisioning flow (default: `/mnt/efs/users/${OWNER_ID}/.paperclip/board-key`)
- `PAPERCLIP_BASE_URL` — Paperclip sidecar base URL (default: `http://localhost:3100`)

Optional:
- `NEXUS_NOTIFY_CHANNEL` — Slack channel for proactive notifications (default: DM the user)

Check each variable is set. If `PAPERCLIP_BOARD_KEY_PATH` is missing or the file does not exist, the backend has not finished provisioning Paperclip. Tell the user:
> Paperclip is still provisioning. This usually takes 2–5 minutes after you enable it. I'll retry automatically on the next heartbeat.

Do not proceed past Step 1 until the board key file is readable.

## Step 2 — Paperclip sidecar health check

Hit `${PAPERCLIP_BASE_URL}/api/health` with the Board API Key. Expect 200 OK. If you get 502, 503, or timeout, the sidecar is not up yet. Retry once after 30 seconds. If still down, block setup and tell the user:
> The Paperclip sidecar isn't responding at ${PAPERCLIP_BASE_URL}. It's provisioned as a non-essential container, so if it crashed, the main agent runtime stayed up but coordination is offline. Ask the platform team to check the Paperclip task logs.

## Step 3 — Verify org and board key scope

Call `paperclip-org-read.js` to confirm the Board API Key can read the org chart. This validates that provisioning completed correctly and you have at least read-output and write-task scope. If the call returns 401 or 403, the key is wrong — stop and tell the user.

## Step 4 — Strategic context document

Check `fast-io` for `nexus-state/strategic-context`. If it does not exist, create a skeleton:

```json
{
  "version": 1,
  "updated_at": "<iso-timestamp>",
  "business_priorities": [],
  "active_constraints": [],
  "quarterly_objectives": [],
  "key_relationships": [],
  "competitive_landscape": [],
  "notes": ""
}
```

Prompt the user to fill in the first version conversationally. Do not write content to this document without explicit user confirmation — every field is user-authored or user-approved.

## Step 5 — Goal hierarchy skeleton

Call `paperclip-goal-manage.js` to list existing goals. If the hierarchy is empty, walk the user through creating their first company-level goal. Use the conversational goal-decomposition flow:

1. Ask the user for their top-level business objective (revenue target, customer target, launch target, etc.)
2. Suggest a decomposition into 3–5 projects under that goal
3. Suggest task-level decomposition under each project
4. For each proposed goal/project/task, wait for user confirmation before writing
5. Write approved goals via `paperclip-goal-manage.js create`

Do not auto-create goals. Every goal requires explicit user approval.

## Step 6 — Specialist inventory

Call `paperclip-org-read.js` and list every specialist currently deployed in the user's org. For each specialist, note:
- Agent ID and name
- Domain of ownership
- Current health status
- Heartbeat schedule
- Current budget utilization

Build an in-memory routing map: `domain → specialist ID`. This is the delegation decision layer — when a user request arrives, you match intent against this map first. Persist the map to `fast-io` at `nexus-state/routing-map` so you do not have to rebuild it every heartbeat.

## Step 7 — Agentgate inventory

Call `paperclip-governance.js list` to retrieve every active agentgate across every specialist. Build a second in-memory map: `(agent_id, task_classification) → gate config`. This is what `nexus-agentgate-check.js` reads from. Persist to `fast-io` at `nexus-state/agentgate-map`.

## Step 8 — Budget snapshot

Call `paperclip-budget-read.js` for every specialist. Record the current allocations and utilization to `fast-io` at `nexus-state/budget-baseline`. This is the reference point for the budget ceiling alerts fired by `nexus-budget-check.js`.

## Step 9 — Fallback routing table

Load the static fallback routing table from `nexus-fallback-router.js`. This is the deterministic map from `(failing_agent, task_type) → fallback_agent` that fires when the circuit breaker trips. Verify the fallback targets all exist in the specialist inventory from Step 6 — if any fallback points to a specialist that is not deployed, flag it to the user and suggest either deploying the fallback specialist or removing that row from the fallback table.

## Step 10 — Notification channel

Confirm the Slack channel for proactive notifications. If `NEXUS_NOTIFY_CHANNEL` is set, validate it exists and Nexus can post to it. Otherwise, default to DMing the user. Record the resolved channel to `fast-io` at `nexus-state/notify-channel`.

## Step 11 — Cron registration

Verify all three cron jobs are registered in `~/.openclaw/agents/nexus/workspace/.cron`:
- `nexus-heartbeat` — every 5 minutes → `heartbeat-5min.lobster`
- `nexus-daily-digest` — 8am weekdays → `daily-digest.lobster`
- `nexus-weekly-review` — Monday 8am → `weekly-review.lobster`

If any are missing, re-run cron registration.

## Step 12 — Security audit

Run `skill-vetter` against every skill in the Nexus stack. Heightened attention on any skill with network access or filesystem access beyond its documented purpose. Then enable `sona-security-audit` for runtime monitoring. Nexus has read access to every specialist's outputs and write access to the task creation system — the blast radius of a compromised skill in this stack is the entire suite, so the security bar is higher than for any individual specialist.

## Step 13 — Activation check

Run `nexus-activation-check.js`. It validates:
- Every step above completed
- The board key file is readable
- Paperclip health is OK
- The routing map, agentgate map, budget baseline, and notify channel are all persisted to fast-io
- The fallback routing table has no dangling specialist references
- All three cron jobs are registered

If it returns `{pass: true}`, you are ready. If it returns blockers, fix them and re-run.

## Step 14 — Announce readiness

Post to the notify channel:
> Nexus is live. I can see {N} specialists in your org: {list}. {G} goals are active. Quickest way to get value out of me is to ask "what's going on" or give me a multi-agent request like "land me three new enterprise accounts this quarter." I'll route, track, and surface anything that needs your attention.

## Step 15 — Delete this file

Once activation has completed successfully, delete `BOOTSTRAP.md`. It should never run twice.
