# Agent Workspace Normalization — Design Spec

**Date:** 2026-04-14
**Status:** Approved
**Context:** Follow-up to PR #260 (File Viewer V2). PR #264 was closed without merging — it baked a workspace-path inconsistency deeper into our code and introduced a P1 data-corruption risk.

## Problem

PR #260 assumed every agent's files live at `workspaces/{agent_id}/`. The actual prod layout is inconsistent:

- `main` agent's files live at `{user_root}/workspaces/` (bare — no agent subdir)
- Custom agents' files live at `{user_root}/agents/{agent_id}/` (because our frontend passes `workspace: "agents/" + id` to `agents.create`)

As a result, the Workspace tab shows empty for main, and the Config tab shows "No config files found." Both tabs are broken in prod.

Worse: if we band-aid by routing writes to wherever each agent's files live, custom agents' viewer would be rooted at `agents/{id}/` — the same directory that holds OpenClaw's runtime `sessions/` and `agent/models.json`. A `tab="workspace"` write could corrupt runtime state, and a recursive tree listing would clutter the UI with session history.

## Root cause

OpenClaw's default behavior (verified at `/Users/prasiddhaparthsarthy/Desktop/openclaw/src/agents/agent-scope.ts:263-284`):

- If `agents.defaults.workspace` is set (we set it to `.openclaw/workspaces`), **main** lands at `{workspace}` directly; **custom agents** land at `{workspace}/{agentId}`.
- Sessions ALWAYS land at `.openclaw/agents/{agentId}/sessions/` regardless of workspace. Not controlled by the `workspace` param.

If we had done nothing, custom agents would have naturally landed at `.openclaw/workspaces/{id}/` — consistent with main's `workspaces/`. Our `AgentCreateForm.tsx` override (`workspace: "agents/" + id`) broke this for no design reason.

The fix is to stop overriding the workspace in `agents.create` and to declare main explicitly at `workspaces/main` so every agent follows the same `workspaces/{agent_id}/` scheme.

## Design

### 1. Config changes

**`apps/backend/core/containers/config.py`:**

- Keep `agents.defaults.workspace = ".openclaw/workspaces"` unchanged.
- Add `"workspace": "workspaces/main"` to the main agent entry in the `agents.list` array. Main's workspace goes from bare `workspaces/` to `workspaces/main/`, matching the custom-agent scheme.

**`apps/frontend/src/components/control/panels/AgentCreateForm.tsx`:**

- Remove the `workspace: "agents/" + normalizedId` param from the `callRpc("agents.create", …)` call. Custom agents inherit the default and land at `workspaces/{id}/` automatically.

**Net effect:** all agents live at `workspaces/{agent_id}/`. No branching in path resolution anywhere.

### 2. Backend endpoint changes

**`apps/backend/routers/workspace_files.py`:**

- Remove the `_agent_workspace_dir` helper if the closed PR's commits sneaked in. Not needed.
- `_agent_workspace_path(owner_id, agent_id)` returns `f"workspaces/{agent_id}"` (its original behavior from PR #260).
- `_list_config_files(workspace, owner_id, agent_id)` reads allowlisted files from `workspaces/{agent_id}/`.
- `read_config_file` uses `f"workspaces/{agent_id}/{path}"`.
- `_write_file` for both tabs composes `full_path = f"workspaces/{agent_id}/{path}"`. Config tab still gates on the allowlist.
- `_strip_agent_prefix` strips `workspaces/{agent_id}/`.
- `_ensure_within_subtree` symlink guard: subtree is `workspaces/{agent_id}/`.
- `CONFIG_ALLOWLIST`: drop `BOOTSTRAP.md`. Final set — `{SOUL.md, MEMORY.md, TOOLS.md, IDENTITY.md, USER.md, HEARTBEAT.md, AGENTS.md}` (7 files). This matches what OpenClaw's `src/agents/workspace.ts:26-34` actually seeds.

**`apps/backend/core/containers/workspace.py`:**

- `_EXCLUDED_NAMES`: add `state`, `skills`, `canvas`, `identity`. Keep `memory` visible (user wants to eyeball QMD). Do not add `sessions` or `agent` — those stay in `agents/{id}/` and never touch the viewer's path.
- Do not remove `openclaw.json`, `.openclaw`, `node_modules`, `__pycache__`, `.mcporter`, `.git` — those stay excluded.

**`apps/backend/routers/container_rpc.py`:**

- `upload_files` dest path: `f"workspaces/{agent_id}/uploads/{safe_name}"`. Unconditional — no helper.

**Session files stay at `agents/{id}/sessions/`** and are unreachable from any viewer endpoint. The P1 corruption and P2 tree-pollution concerns from PR #264 both become structurally impossible.

### 3. Frontend changes

**`apps/frontend/src/components/chat/FileViewer.tsx`:**

- No structural changes. Tabs and panels stay as-is.

**`apps/frontend/src/components/chat/FileTree.tsx`:**

- When `activeTab === "config"`: for each name in the 7-file allowlist that isn't present in the tree's `files` array, render a "missing" ghost entry (faded, with a `FileWarning` icon). Clicking a missing entry creates a blank editor buffer for that name so the user can save content and create the file. This matches the old `AgentFilesTab` UX.
- On the Workspace tab, no ghost entries — tree shows only what's on disk.
- The tab context needs to be threaded into `FileTree` (currently it doesn't know which tab it's rendering for). Either pass `activeTab` as a prop, or pass a precomputed `allowlist?: string[]` — the latter is cleaner and keeps `FileTree` tab-agnostic.

**`apps/frontend/src/components/control/panels/AgentFilesTab.tsx`:** Delete.

**Remove AgentFilesTab from its mounting site:**

- Check `apps/frontend/src/components/control/panels/AgentsPanel.tsx` and `ControlPanelRouter.tsx`. Remove any import, route, or tab entry that references `AgentFilesTab`. If a tab/section becomes empty, collapse or remove it.

**`apps/frontend/src/components/control/panels/agents-types.ts`:** Keep — the file viewer's ghost-entry rendering reuses `AgentFileEntry`.

### 4. Manual migration (ECS exec, post-deploy)

After the code is merged and the backend rolls out, migrate the 3 existing prod users via `aws ecs execute-command`. No in-app migration logic — the backend change is compatible with either layout once the viewer points at `workspaces/{id}/`, but existing main files at `workspaces/*` (bare) need to move.

For each user directory at `/mnt/efs/users/{user_id}/`:

1. **Stop the user's OpenClaw ECS service** (scale to 0 desired tasks). Prevents races while we move files.
2. **Create `workspaces/main/` if it doesn't exist.**
3. **Move main's bare-root content into `workspaces/main/`:**
   - `SOUL.md`, `AGENTS.md`, `HEARTBEAT.md`, `IDENTITY.md`, `TOOLS.md`, `USER.md`, `MEMORY.md` (if present)
   - `memory/`, `state/`, `skills/`, `canvas/`, `identity/`
   - `.openclaw/` (hidden OpenClaw state file)
   - `.clawhub/` (hidden clawhub state)
   - Any `uploads/` directory at `workspaces/` root
4. **Do not touch:**
   - Any existing `workspaces/{custom_id}/` directories (shouldn't exist yet, but defensive)
   - `agents/*` — leave entirely alone. OpenClaw still owns `agents/{id}/sessions/` and `agents/{id}/agent/models.json` for every agent including main.
   - Top-level user files: `openclaw.json`, `.mcporter/`, `devices/`, `credentials/`, `cron/`, `delivery-queue/`, `logs/`, `exec-approvals.json`, `qmd/`, `qqbot/`, `tasks/`, etc.
5. **For each custom agent** currently at `agents/{id}/` with user-workspace files (SOUL.md etc.):
   - Create `workspaces/{id}/`.
   - Move user-workspace content only (NOT `sessions/`, NOT `agent/`).
   - In practice, prod custom agents today (`ember`) have no user-workspace files yet, so step 5 is a no-op for existing prod users. Script still handles it for safety.
6. **Rewrite `openclaw.json`** — backend reprovision call will regenerate with the new `workspace: "workspaces/main"` declaration. Easier to trigger a config patch (`PATCH /debug/provision`) than to hand-edit.
7. **Bring the user's ECS service back up** (scale to 1). OpenClaw re-reads the patched `openclaw.json` and now points main at `workspaces/main/`.
8. **Verify:** `ls /mnt/efs/users/{user_id}/workspaces/main/` shows SOUL.md etc.; chat with the agent; open the file viewer and confirm files render.

A shell script will be produced in the implementation plan. It runs dry-run by default; add `--apply` to execute moves. The script is invoked via `aws ecs execute-command` into the backend task.

### 5. Testing

**Backend — `apps/backend/tests/test_workspace_files.py`:**

- Rebase existing tests against the single-layout model (`workspaces/{agent_id}/`). Drop branching that assumed `agents/{id}/` for custom agents.
- Keep all coverage areas: tree, read, write, config list, config read, symlink escape, traversal, content size cap, allowlist rejection, round-trip list→read.
- Add a test: `list_directory` in `workspaces/{agent_id}/` excludes `state`, `skills`, `canvas`, `identity`, but keeps `memory`.
- Remove any test that referenced `BOOTSTRAP.md` in the allowlist.

**Backend — `apps/backend/tests/unit/containers/test_config.py`:**

- Update the main agent list-entry assertion to include `workspace: "workspaces/main"`.

**Backend — `apps/backend/tests/unit/routers/test_file_upload.py`:**

- Update existing tests so upload destinations are asserted at `workspaces/{agent_id}/uploads/` for every agent (including main — main is no longer special).

**Frontend:**

- No new unit test infrastructure for `FileViewer` / `FileTree` in this PR (no existing coverage to rebase from; belongs in a follow-up with proper test scaffolding).
- Post-deploy manual checklist (see below).

**Post-deploy / post-migration verification:**

- Open the file viewer for the main agent. Config tab lists the 7 allowlisted files. Missing ones render as ghost entries.
- Click SOUL.md, edit, save. Refresh the viewer. Change persists.
- Workspace tab shows `memory/` but not `state/`, `skills/`, `canvas/`, `identity/`. Sessions are not visible anywhere.
- Create a new custom agent in the UI. Confirm on the backend: `ls /mnt/efs/users/{user_id}/workspaces/{new_agent_id}/` exists with the 7 seed files.
- Upload a file via the chat input. Appears in Workspace tab under `uploads/`.
- `AgentFilesTab` is gone from the control panel — no broken imports, no blank tab, no dead route.

## Not in this version

- Automatic / lazy migration. Manual ECS-exec migration only.
- New unit tests for the file viewer frontend components (deferred).
- Any change to OpenClaw itself — we only change our overrides.
- Preserving the `AgentFilesTab` grid-of-chips UI as a "simple editor" mode; Config tab's tree view replaces it wholesale.

## Risks + rollback

- **Config patch during migration:** If the backend rolls out before we run the manual migration, the viewer will be broken for existing users (it will look in `workspaces/main/` which doesn't exist yet). Sequence matters: deploy code → migrate users → verify.
- **Service stop during migration:** Each user's OpenClaw container is stopped briefly during the move. Mitigation: only 3 prod users, each migration is small, whole thing should take under a minute per user. Users receive a brief "agent offline" state; they can retry in 30s.
- **Rollback:** If something breaks, the code change is reversible (restore the `workspace: "agents/" + id` override in AgentCreateForm and drop the `workspace: "workspaces/main"` line in config.py). The migration is reversible too — moved files can be moved back. No destructive DB changes, no schema migrations, no external state to undo.
