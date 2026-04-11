# TOOLS.md — Nexus Skill & Script Reference

Everything Nexus can reach. Read this before you reach for a tool you don't see listed — if it's not here, you do not have it, and that is by design. The coordinator/executor separation means Nexus's toolset is deliberately restricted to coordination primitives.

---

## Paperclip API wrappers (local `.js` scripts)

These wrap the Paperclip sidecar at `http://localhost:3100/api/*` with the Board API Key read from `PAPERCLIP_BOARD_KEY_PATH`. They are plain Node.js scripts invoked via `exec` from `.lobster` pipelines. Each takes a JSON argument on stdin and returns JSON on stdout; non-zero exit means the call failed.

### paperclip-task-create.js
Nexus's primary write operation. Every delegation decision materializes as a task created through this script. Wraps `POST /api/tasks`. Required fields: `title`, `assignee_agent_id`, `goal_id`, `priority`. Optional: `dependencies` (array of task IDs), `description`, `estimated_cost`, `context` (string — compressed context from other agents' recent work). Response includes the created task ID, the resolved goal ancestry, and the scheduled heartbeat window — use all three when templating the delegation confirmation back to the user. Paperclip validates budget, governance gates, and goal alignment before the task enters the queue; a rejection returns `{ok: false, reason: <string>}` and you surface the reason to the user rather than retrying.

### paperclip-task-read.js
Nexus's primary read operation for cross-agent synthesis. Wraps `GET /api/tasks` with query filters. Modes: `list` (all active tasks across all specialists), `by_agent` (single specialist's tasks), `by_id` (single task with outputs and comments), `by_goal` (all tasks under a goal), `failed_recent` (tasks that failed in the last N minutes — used by the circuit breaker cron). Read-only. Scope is every specialist's outputs, never their tools, credentials, or internal state.

### paperclip-goal-manage.js
CRUD on the goal hierarchy. Wraps `GET/POST/PATCH/DELETE /api/goals`. Create and modify are gated — always surface the proposed change to the user for explicit confirmation before writing. List and read are autonomous — the goal drift cron uses them to check every task's ancestry. Response includes progress percentage on every goal, which is what the daily digest uses for the on-track / at-risk / blocked classification.

### paperclip-budget-read.js
Read-only budget query. Wraps `GET /api/budgets/{agent_id}`. Returns: `allocated`, `consumed`, `remaining`, `utilization_percent`, `projected_burn`, `days_remaining_in_cycle`. `nexus-budget-check.js` calls this before every task creation. The daily cron calls this to detect agents trending toward 80%+ utilization.

### paperclip-activity-feed.js
Real-time event stream. Wraps `GET /api/activity?since=<cursor>`. Returns task completions, failures, comments, agent status changes, governance gate triggers, heartbeat events. The 5-minute heartbeat pipeline reads this with the cursor from the previous heartbeat — only new events since last check. Use the cursor — do not re-read the whole feed.

### paperclip-org-read.js
Org chart + agent config + health status + heartbeat schedule for every specialist. Wraps `GET /api/agents`. Used by the routing map builder in bootstrap, by the fallback router when the circuit breaker trips, and by the weekly review to flag overloaded / underutilized specialists.

### paperclip-governance.js
Read-only access to agentgate configurations and pending approvals. Wraps `GET /api/governance/gates` and `GET /api/governance/pending`. `nexus-agentgate-check.js` calls this before every task creation to look up whether the target (agent, task_type) pair has an active gate. You cannot modify gate configurations through this wrapper — gates are set per-specialist based on that specialist's own PRD and failure case research, and changing them requires user action in the specialist's configuration.

---

## Deterministic Nexus scripts (local `.js` scripts)

These encode the deterministic logic the vet doc pushed out of the LLM path. Invoked via `exec` from the `.lobster` pipelines. Stdin JSON in, stdout JSON out.

### nexus-budget-check.js
Pre-flight budget validation before any task creation. Reads `paperclip-budget-read.js` for the target specialist. If estimated task cost would exceed remaining balance, returns `{block: true, alternatives: [...]}` with the template alert data. The `.lobster` pipeline branches on this and fires the budget alert template instead of creating the task.

### nexus-agentgate-check.js
Pre-flight governance check before any task creation. Reads `paperclip-governance.js` for the target specialist. If the (agent, task_classification) pair has an active gate, returns `{gate: true, reason: <string>, agent: <id>}` and the `.lobster` pipeline fires the agentgate escalation template and waits for user approval.

### nexus-circuit-breaker.js
Consecutive failure counter. Reads `paperclip-task-read.js` in `failed_recent` mode for each specialist. If any specialist has ≥ 3 consecutive failures, marks that specialist as "paused" in `fast-io` at `nexus-state/paused-agents` and returns the circuit-breaker template data. The delegation logic checks the paused list before every task creation and routes to the fallback from `nexus-fallback-router.js` if the primary is paused.

### nexus-goal-drift.js
Drift detection cron. Reads every active task via `paperclip-task-read.js list`, checks each task's goal ancestry via `paperclip-goal-manage.js`. Any task without a parent goal is drift. Returns a list of drifted tasks with agent/task metadata for the drift alert template.

### nexus-fallback-router.js
Static fallback routing table. Maps `(failing_agent, task_type) → fallback_agent`. Deterministic lookup — no LLM. If the lookup returns a fallback target, the task is rerouted automatically. If the lookup returns nothing, the task surfaces to the user with "no automatic fallback for this task type, pick manually."

### nexus-activation-check.js
Bootstrap validator. Runs at the end of `BOOTSTRAP.md` and returns `{pass: true}` or a list of blockers. Also callable on demand as a health check.

---

## ClawHub skills

### fast-io (clawhub.ai/dbalve/fast-io)
Nexus's audit log and state store. Every delegation, every synthesis, every user escalation, every cross-agent conflict, every budget alert, every governance gate surfaced — logged with timestamp, source data, the Paperclip state that informed the decision, and the user authorization for anything that required approval. Append-only. Key prefixes in use:
- `nexus-state/*` — strategic-context, routing-map, agentgate-map, budget-baseline, paused-agents, notify-channel
- `nexus-audit/*` — timestamped per-decision records
- `nexus-delegations/*` — delegation history for capability-evolver review

### taskr (clawhub.ai/skills/taskr)
Active workflow state for in-flight operations across heartbeats. Approval requests queued for user confirmation, cross-agent workflows with pending dependencies, synthesis reports in progress, budget alerts surfaced but not yet acknowledged, governance gates awaiting user response. Without taskr, Nexus would lose track of all of this between heartbeats and produce duplicate notifications or missed actions.

### summarize (clawhub.ai/skills/summarize)
Content compression for synthesis reports. Called on every specialist's raw output before the LLM sees it — compresses detailed outputs to the decision-relevant signal. The daily and weekly digests also use summarize to produce brief action-oriented reports rather than comprehensive data dumps the user has to interpret.

### n8n-workflow (clawhub.ai/skills/n8n-workflow)
Deterministic orchestration for every scheduled operation. The 5-minute heartbeat, the daily digest, the weekly review, the budget projection refresh — all run as n8n-registered crons, not as LLM loops. Retry logic and failure alerting live here. If the research on multi-agent failures is right about anything, it is right that unreliable orchestration is a root cause of cascade failures, and the deterministic layer is what makes the scheduled operations reliable.

### capability-evolver (clawhub.ai/skills/capability-evolver)
Reviews Nexus's delegation accuracy over time. Which task routings the user accepted without modification (correct routing), which the user redirected to a different specialist (routing error to learn from), which synthesis reports the user engaged with versus dismissed, which proactive alerts the user acted on versus ignored. The routing model compounds toward accuracy rather than staying static.

### skill-vetter (clawhub.ai/spclaudehome/skill-vetter)
Pre-install vetting. Run against every skill in the Nexus stack before production deployment. Heightened attention on any skill with network access or filesystem access beyond documented purpose. Nexus's blast radius is the entire suite, so the bar is higher.

### sona-security-audit (clawhub.ai/skills/sona-security-audit)
Runtime monitoring. Any skill making network calls outside its declared scope is an immediate security event. The ClawHavoc campaign targeted 99 of the top 100 ClawHub skills — runtime monitoring is the layer that catches post-install compromise.

### slack
Proactive notification channel. The notification templates in `notifications/` get dispatched here via `nexus-notify.js`. Default channel is set in bootstrap at `nexus-state/notify-channel`.

---

## What Nexus does NOT have

Explicitly missing, by design:

- **No CRM** (Pitch and Scout own CRM)
- **No email/messaging send** (Thread and Pitch own outreach)
- **No calendar** (Ora owns scheduling)
- **No financial tools** (Tally owns finance)
- **No HR/employee records** (Ember owns HR)
- **No meeting/transcript tools** (Echo owns meeting capture)
- **No marketing tools** (Pulse owns marketing)
- **No research/analysis tools** (Lens owns deep research)
- **No customer support tools** (Vera owns support)
- **No file-edit or shell-write tools** (the coordinator/executor separation is enforced at the tool profile level — Nexus has the coordinator profile, which strips execution permissions)

If you find yourself wanting to reach for one of these, stop. There is a specialist whose entire existence is built around that domain. Route to them.
