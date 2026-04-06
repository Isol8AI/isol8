# PRD Agent: Dedicated Product Requirements Agent for Isol8

**Date:** 2026-04-05
**Status:** Approved

## Overview

A dedicated OpenClaw agent available to all Isol8 users that generates Product Requirements Documents and audits project backlogs. The agent uses three specialized skills (`prd-generate`, `prd-audit`, `prd-template`) to cover the full PRD lifecycle — from interactive document creation to backlog scanning to template customization.

All interactions are conversational first, command shortcuts second. Non-technical users can use natural language; power users can use slash commands.

## Goals

- Every Isol8 user gets a PRD Writer agent in their sidebar
- Agent produces tiered PRDs (lean/medium/full) scaled to feature complexity
- Agent audits remaining work by scanning GitHub issues, specs, git history, codebase TODOs, and manual input
- Master backlog documents are organized hybrid-style: by system area, then dependency order, with priority tags
- Agent writes files and creates git branches when possible, degrades gracefully when not
- Templates are customizable via conversational UI

## Non-Goals

- Replacing project management tools (Jira, Linear, etc.)
- Auto-assigning work to developers
- Generating implementation code from PRDs
- Real-time sync with external issue trackers (one-time scan, not live integration)

---

## Architecture

### Agent Definition

Injected into every user's `openclaw.json` via `config.py` at provision time:

```json
{
  "id": "prd-agent",
  "name": "PRD Writer",
  "identity": {
    "name": "PRD Writer",
    "emoji": "\ud83d\udccb",
    "theme": "blue"
  },
  "skills": ["prd-generate", "prd-audit", "prd-template"],
  "tools": {
    "profile": "full",
    "exec": { "ask": "auto" },
    "fs": { "enabled": true },
    "web": {
      "search": { "enabled": true },
      "fetch": { "enabled": true }
    }
  },
  "thinkingDefault": "high",
  "memorySearch": { "enabled": true }
}
```

**Key decisions:**
- `tools.exec.ask: "auto"` — agent can run git, grep, gh CLI without asking every time. Required for codebase analysis and git commits.
- `thinkingDefault: "high"` — PRD work benefits from deeper reasoning (research, gap analysis, dependency mapping).
- `memorySearch: enabled` — agent remembers previous PRD conversations for cross-reference.
- Model not hardcoded — inherits from `agents.defaults.model`, user switches at runtime via model selector.

### Skill Delivery

Skills are written to each user's EFS workspace at provision time and updated via Track 1 silent config patches.

```
/mnt/efs/users/{user_id}/
  .agents/skills/
    prd-generate/SKILL.md
    prd-audit/SKILL.md
    prd-template/SKILL.md
  docs/prds/templates/
    lean.md
    medium.md
    full.md
    backlog.md
```

**Source of truth:** `apps/backend/skill_templates/prd-agent/` in the Isol8 repo. `config.py` reads from there and writes to EFS. One place to update, rolled out to all users via Track 1.

**No frontend changes required.** Agent appears in sidebar via existing `agents.list` RPC. Skills appear as slash commands in the agent's chat.

---

## Skill 1: `prd-generate`

Interactive PRD creation. User describes a feature, agent researches and produces a tiered PRD.

### Workflow

1. User invokes `/prd-generate` with a feature description, or just chats naturally about a feature
2. Agent silently classifies scope (user sees natural language, not tier names):
   - "This looks like a small config change" vs. "This is a significant feature touching multiple services"
   - User can say "make it shorter" or "add more detail" to adjust
3. Agent researches — reads relevant code, checks git history, searches issues
4. Agent asks 3-5 clarifying questions, one at a time
5. Agent produces the PRD using the appropriate template tier
6. Agent writes to `docs/prds/<YYYY-MM-DD>-<slug>.md` and commits (if git available)

### Tier Classification

| Tier | Criteria | Template |
|------|----------|----------|
| Small | Single service, <5 files, bug fix or config change | Lean: problem, solution, scope, acceptance criteria |
| Medium | 2-3 services, new feature or integration, moderate risk | Lean + technical requirements, dependencies, user stories |
| Large | Cross-stack, infra migration, billing change, new system | Full: background, user stories, functional reqs, technical reqs, dependencies, risks, milestones, acceptance criteria |

Classification is based on: number of services touched, cross-service dependencies, risk level (infra/billing/auth = higher). Agent communicates this conversationally, not with tier labels.

### Output Format

All tiers share this header:

```markdown
# PRD: <Title>

**Tier:** Small | Medium | Large
**Date:** YYYY-MM-DD
**Author:** PRD Agent + <user>
**Status:** Draft
**System Areas:** Backend, Frontend, Infra, ...
**Priority:** P0 | P1 | P2
**Dependencies:** [list of blocking items]

---
<tier-specific sections>
```

### Git Behavior

When in full mode:
- Creates branch `prd/<slug>` from current branch
- Commits with message `docs: add PRD for <title>`
- Reports branch name to user for review/PR

### Graceful Degradation

Agent detects environment capabilities at invocation:

| Mode | Condition | Behavior |
|------|-----------|----------|
| Full | Git available + write access | Write file + commit on branch |
| File-only | Workspace writable, no git | Write PRD to `docs/prds/`, skip git, notify user |
| Chat-only | Read-only workspace or no workspace | Output full PRD as chat message |

Agent announces which mode it's operating in at the start.

---

## Skill 2: `prd-audit`

Backlog auditor. Scans all available sources and produces a master document of remaining work.

### Workflow

1. User invokes `/prd-audit` — optionally with a scope filter (e.g., "just the backend" or "billing stuff")
2. Agent scans sources in order:
   - **GitHub Issues** — open issues via `gh issue list` (skips with notice if `gh` CLI unavailable)
   - **Existing specs** — reads `docs/superpowers/specs/*.md`, checks status
   - **Git history** — recent branches, open PRs, stale branches with unmerged work
   - **Codebase** — greps for `TODO`, `FIXME`, `HACK`, `XXX` comments
   - **Manual input** — asks user "Any planned features or priorities not captured in code/issues?"
3. Agent deduplicates — matches TODOs to issues, specs to PRs
4. Agent classifies each item by system area and priority
5. Agent sorts by dependency order within each group
6. Outputs the master backlog document
7. Warns user before starting: "This will scan your codebase and may use significant tokens. Proceed?"

### Output Structure

```markdown
# Backlog Audit

**Generated:** YYYY-MM-DD
**Scope:** All | <filtered area>
**Sources scanned:** GitHub Issues, Specs, Git, Codebase, Manual

## Summary
- X items total: Y critical, Z important, W nice-to-have
- Top blockers: [items that unblock the most other work]

## By System Area

### Backend
| # | Item | Tier | Priority | Depends On | Source |
|---|------|------|----------|------------|--------|
| 1 | ... | Medium | P0 | -- | Issue #45 |
| 2 | ... | Small | P1 | #1 | TODO in config.py:142 |

### Frontend
...

### Infrastructure
...

## Dependency Graph
<text-based dependency visualization>

## Recommended Execution Order
1. [Item] -- unblocks 3 others
2. [Item] -- unblocks 2 others
...
```

### Refresh

Re-running `/prd-audit` diffs against the previous audit if one exists, highlighting what's new, resolved, or changed.

### Same three-mode fallback as `prd-generate`.

---

## Skill 3: `prd-template`

Template management via conversational UI. No subcommands required.

### Workflow

User invokes `/prd-template` and the agent responds conversationally:

> "What would you like to do?
> 1. **See templates** -- view what's available
> 2. **Customize a template** -- add/remove/reorder sections
> 3. **Create a new template** -- I'll walk you through it step by step
> 4. **Reset to defaults** -- restore the original templates"

User picks a number or describes what they want in natural language.

### Template Creation/Editing

No placeholder syntax exposed to users. Agent asks plain questions:
- "What sections should this PRD have?"
- "Should it include user stories?"
- "Do you want a risks section?"

Agent builds the template internally, shows a preview, and asks for confirmation.

### Default Templates

| Template | Sections |
|----------|----------|
| `lean.md` | Problem, Solution, Scope (in/out), Acceptance Criteria |
| `medium.md` | Lean + User Stories, Technical Requirements, Dependencies |
| `full.md` | Medium + Background, Risks, Milestones, Open Questions |
| `backlog.md` | Summary, System Area tables, Dependency Graph, Execution Order |

### Behavior

- Custom templates stored at `docs/prds/templates/` in user's workspace
- Custom templates take precedence over defaults with the same name
- `prd-generate` checks for custom templates before falling back to defaults
- Agent validates templates on create/edit — warns if critical sections are missing

### Tool Permissions

`prd-template` is the most restricted skill — only needs fs read/write. No git, web search, or GitHub CLI access.

---

## Permissions & Tier Access

| Tier | Access | Notes |
|------|--------|-------|
| Free | Chat-only mode | Scale-to-zero containers + $2 lifetime budget. PRD generation works but no file writes. Good for trying it out. |
| Starter | Full access | Always-on container, persistent EFS. All three skills, all three modes. |
| Pro | Full access | Same as Starter with more compute headroom. |
| Enterprise | Full access | Same + access to Claude Opus 4.6 for highest quality PRDs. |

### Tool Permissions Per Skill

| Skill | fs (read) | fs (write) | exec (git) | web search | GitHub CLI |
|-------|-----------|------------|------------|------------|------------|
| `prd-generate` | Yes | Yes | Yes | Yes | Yes |
| `prd-audit` | Yes | Yes | Yes | Yes | Yes |
| `prd-template` | Yes | Yes | No | No | No |

### Rate Limiting

No special limits beyond the user's existing LLM budget. `/prd-audit` warns before starting due to high token usage.

---

## Backend Changes

### `apps/backend/core/containers/config.py`

- Add `prd-agent` to `agents.list[]` in `write_openclaw_config()`
- New function `write_prd_skills()` that writes skill files + default templates to EFS
- Called during provisioning alongside existing config writes
- ~80 lines of new code

### `apps/backend/skill_templates/prd-agent/`

New directory containing the canonical skill files and templates:

```
skill_templates/prd-agent/
  skills/
    prd-generate/SKILL.md
    prd-audit/SKILL.md
    prd-template/SKILL.md
  templates/
    lean.md
    medium.md
    full.md
    backlog.md
```

### Track 1 Updates

Existing silent config patch system delivers skill updates to all users. No new infrastructure needed.

---

## Implementation Order

1. **Skill content** — write the three `SKILL.md` files and four default templates
2. **Backend config** — add agent definition and `write_prd_skills()` to `config.py`
3. **Track 1 delivery** — ensure skill files are included in config patch rollouts
4. **Testing** — provision a test container, verify agent appears, test all three skills
5. **Tier gating** — verify free tier gets chat-only, paid tiers get full access
