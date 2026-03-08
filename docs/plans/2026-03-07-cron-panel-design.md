# Cron Panel Enhancement Design

**Date:** 2026-03-07
**Status:** Approved

## Overview

Enhance the existing CronPanel to support full CRUD (create, edit, delete) and run history viewing. All operations use the existing OpenClaw gateway WebSocket RPC — no new backend endpoints needed.

## RPC Methods

| Action | Method | Key Params |
|--------|--------|-----------|
| List | `cron.list` | `{includeDisabled: true}` |
| Create | `cron.add` | `{name, schedule, payload, enabled, sessionTarget, wakeMode}` |
| Edit | `cron.update` | `{id, patch: {...}}` |
| Delete | `cron.remove` | `{id}` |
| Run now | `cron.run` | `{id, mode: "force"}` |
| History | `cron.runs` | `{scope: "job", id, limit: 10}` |

## UI Structure

### Header
- Title "Cron Jobs" + refresh button + "+ New Job" button

### Job Cards (list)
Each card shows:
- Name, human-readable schedule, enabled status badge, last run status indicator
- Actions: Run (play icon), Enable/Disable toggle, Edit (pencil), Delete (trash)
- Expandable: click card to show run history inline

### Create/Edit Form (inline, not modal)
- **Name**: text input (required)
- **Schedule type**: radio tabs — "Cron Expression" | "Every Interval" | "One-time"
  - Cron: expression input + optional timezone select
  - Every: number + unit dropdown (minutes/hours/days)
  - At: datetime-local input
- **Message**: textarea — the prompt/instruction for the agent
- **Enabled**: toggle (default true)
- Save / Cancel buttons

### Run History (expandable per job)
- Fetched via `cron.runs` with `scope: "job"`, `limit: 10`
- Shows: timestamp, status badge (ok/error/skipped), duration, summary text
- "Load more" button if `hasMore`

### Delete Confirmation
- Inline alert within the card (not browser confirm)
- "Delete job X? This cannot be undone." + Cancel / Delete buttons

## Schedule Types (OpenClaw CronSchedule)

```typescript
// Cron expression
{ kind: "cron", expr: "0 9 * * *", tz?: "America/New_York" }

// Interval
{ kind: "every", everyMs: 3600000 }

// One-time
{ kind: "at", at: "2026-03-10T15:00:00Z" }
```

## Human-Readable Schedule Display

- `{kind: "cron", expr: "0 9 * * *"}` → "Every day at 9:00 AM"
- `{kind: "every", everyMs: 3600000}` → "Every 1 hour"
- `{kind: "at", at: "..."}` → formatted date/time

## Payload Shape (for cron.add)

```typescript
{
  name: "Daily summary",
  schedule: { kind: "cron", expr: "0 9 * * *" },
  payload: { kind: "agentTurn", message: "Summarize today's tasks" },
  enabled: true,
  sessionTarget: "main",
  wakeMode: "now",
}
```

## Default Values for Create

- `sessionTarget`: `"main"`
- `wakeMode`: `"now"`
- `payload.kind`: `"agentTurn"`
- `enabled`: `true`

## File Changes

- `frontend/src/components/control/panels/CronPanel.tsx` — full rewrite with CRUD + history
- No backend changes needed
- No new files needed (single-component enhancement)
