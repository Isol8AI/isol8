# TOOLS.md — Nexus Skill & Script Reference

Everything Nexus can reach. Read this before you reach for a tool you don't see listed — if it's not here, you do not have it, and that is by design. The coordinator/executor separation means Nexus's toolset is deliberately restricted to coordination primitives.

---

## Paperclip API wrappers (local `.js` scripts)

These wrap the Paperclip sidecar at `http://localhost:3100/api/*` with the Board API Key read from `PAPERCLIP_BOARD_KEY_PATH`. They are plain Node.js scripts invoked via `exec` from `.lobster` pipelines. Each takes a JSON argument on stdin and returns JSON on stdout; non-zero exit means the call failed.

### paperclip-task-create.js
Nexus's primary write operation. Every delegation decision materializes as an **issue** created through this script. Paperclip's domain object is "issue" (think Linear/Jira-style tickets) — this script keeps the Nexus-facing name ("task") while wrapping the real endpoint `POST /api/companies/:companyId/issues`. Required fields: `title`, `assignee_agent_id`. Optional: `description`, `status`, `execution_policy` (drives Paperclip's server-side approval behavior), `blocked_by` (array of issue IDs this issue depends on — Paperclip enforces execution order via `blockedByIssueIds` on the issue graph). The `companyId` is resolved lazily from `GET /api/companies` on first call and cached for the script's lifetime. Paperclip validates the agent's permissions and the execution policy before the issue enters the queue; a rejection returns `{ok: false, reason: <string>}` and you surface the reason to the user rather than retrying.

### paperclip-task-read.js
Nexus's primary read operation for cross-agent synthesis. Wraps `GET /api/companies/:companyId/issues` (list + by_agent via `?assigneeAgentId=`) and `GET /api/issues/:id` (by_id + heartbeat_ctx). Modes: `list` (all issues in the company with optional query filters), `by_agent` (single specialist's issues), `by_id` (single issue with ancestors, relations, documents, workspaces), `heartbeat_ctx` (compressed issue summary via `/api/issues/:id/heartbeat-context` — ideal as synthesis input). Read-only. Scope is every specialist's outputs, never their tools, credentials, or internal state. Failed-recent detection is done via `paperclip-activity-feed.js` with `entity_type=issue` + a cutoff, not here.

### paperclip-goal-manage.js
CRUD on the goal hierarchy. Wraps `GET /api/companies/:companyId/goals` (list), `GET /api/goals/:id` (get), `POST /api/companies/:companyId/goals` (create), `PATCH /api/goals/:id` (update), `DELETE /api/goals/:id`. Create and modify are gated — always surface the proposed change to the user for explicit confirmation before writing. List and read are autonomous — the goal drift cron uses them to check every issue's ancestry. Goals have a `level` field (company/project/personal) and a progress percentage, which is what the daily digest uses for the on-track / at-risk / blocked classification.

### paperclip-budget-read.js
Read-only budget/cost query. Paperclip does not expose a single "remaining budget for agent" endpoint — the script wraps the primitives that together yield that view. Modes: `by_agent` (`GET /api/companies/:companyId/costs/by-agent` — consumed spend per agent), `overview` (`GET /api/companies/:companyId/budgets/overview` — company-level rollup), `window_spend` (`GET /api/companies/:companyId/costs/window-spend` — quota-window spend), `quota_windows` (`GET /api/companies/:companyId/costs/quota-windows` — window definitions), `agent_allocation` (`GET /api/agents/:id` — reads `budgetMonthlyCents`). `nexus-budget-check.js` combines these to compute remaining balance before every issue creation. The daily cron calls the same primitives to detect agents trending toward 80%+ utilization.

### paperclip-activity-feed.js
Event stream for the proactive sweep. Wraps `GET /api/companies/:companyId/activity` with filters `agentId`, `entityType`, `entityId`. Paperclip's activity endpoint does not natively accept a "since" cursor — the script takes a `since` input (ISO timestamp or epoch ms) and applies client-side cutoff against each event's `createdAt`. Returns filtered events plus a `cursor` field (latest event timestamp) that the 5-minute heartbeat persists to `taskr` so the next sweep only sees new events. Covers issue completions, failures, comments, agent status changes, approval events, heartbeat runs.

### paperclip-org-read.js
Agent roster + health + execution state. Paperclip splits this across several endpoints, and the script exposes each as a mode: `agents` (`GET /api/companies/:companyId/agents` — flat roster), `org` (`GET /api/companies/:companyId/org` — hierarchical tree), `heartbeats` (`GET /api/instance/scheduler-heartbeats` — per-agent scheduler health), `agent` (`GET /api/agents/:id` — full detail including `budgetMonthlyCents`), `runtime_state` (`GET /api/agents/:id/runtime-state` — current execution context). The bootstrap routing-map builder calls `roster_with_health`, which joins the roster with scheduler heartbeats in one response.

### paperclip-governance.js
Read-only access to Paperclip's approval system. Wraps `GET /api/companies/:companyId/approvals?status=pending` (all pending approvals in the company), `GET /api/issues/:id/approvals` (approvals linked to a specific issue), and `GET /api/approvals/:id` (single approval detail).

**Important model correction vs. the PRD assumption:** Paperclip does not have per-agent "gate configurations" that Nexus can pre-check before issue creation. Instead, gate behavior is policy-based — every issue is created with an `executionPolicy` and Paperclip's server dynamically creates an Approval record for the issue if the policy, the agent's permissions, or the issue classification require one. `nexus-agentgate-check.js` is therefore a POST-creation check: after `paperclip-task-create.js` returns a new issue, check `/api/issues/:id/approvals` to see if any approval was auto-generated, and if so, surface it to the user. The 5-minute heartbeat also polls `mode: "pending"` each cycle to surface anything the user still needs to decide on.

---

## Deterministic Nexus scripts (local `.js` scripts)

These encode the deterministic logic the vet doc pushed out of the LLM path. Invoked via `exec` from the `.lobster` pipelines. Stdin JSON in, stdout JSON out.

### nexus-budget-check.js
Pre-flight budget validation before any issue creation. Combines `paperclip-budget-read.js` modes `agent_allocation` (to get `budgetMonthlyCents` for the target agent) and `by_agent` (to get current-cycle consumed spend), and computes remaining balance locally. If estimated task cost would exceed remaining, returns `{block: true, alternatives: [...]}` with the template alert data. The `.lobster` pipeline branches on this and fires the budget alert template instead of calling `paperclip-task-create.js`.

### nexus-agentgate-check.js
Post-creation governance check. Paperclip's approval model is dynamic — an issue's approval requirement is determined server-side from the `executionPolicy`, agent permissions, and issue classification, so there is no useful pre-flight lookup. After `paperclip-task-create.js` returns a new issue, this script calls `paperclip-governance.js` in `by_issue` mode to see if any approval was auto-generated. If yes, it returns `{gate: true, approval: {...}, issue_id: ...}` and the pipeline fires the agentgate escalation template.

### nexus-circuit-breaker.js
Consecutive failure detector. Calls `paperclip-activity-feed.js` with `entity_type=issue` and a short `since` window, filters events for action == failed grouped by `assigneeAgentId`, and counts consecutive failures per agent. If any specialist has ≥ 3 consecutive failures, marks that specialist as "paused" in `fast-io` at `nexus-state/paused-agents` and returns the circuit-breaker template data. The delegation logic checks the paused list before every issue creation and routes to the fallback from `nexus-fallback-router.js` if the primary is paused.

### nexus-goal-drift.js
Drift detection cron. Reads every active issue via `paperclip-task-read.js list`, resolves each issue's project → goal ancestry from the issue's ancestors field (returned by the by_id endpoint), and flags any issue whose ancestry does not trace to an active goal in `paperclip-goal-manage.js list`. Returns a list of drifted issues with agent/issue metadata for the drift alert template.

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
