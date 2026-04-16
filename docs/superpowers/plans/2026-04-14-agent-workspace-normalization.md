# Agent Workspace Normalization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Normalize every agent's workspace path to `workspaces/{agent_id}/` (including `main`), eliminating the two-directory split that broke the File Viewer v2 and created a data-corruption surface.

**Architecture:** Stop overriding the workspace in `agents.create` (custom agents inherit OpenClaw's `{defaults.workspace}/{agentId}` behavior and land at `workspaces/{id}/`). Declare `main` explicitly with `workspace: "workspaces/main"` so it joins the same scheme. Backend endpoints all read/write under `workspaces/{agent_id}/`. A shell-based manual migration moves existing prod users' files into the new layout post-deploy.

**Tech Stack:** Python/FastAPI (backend), React/Next.js 16 (frontend), pytest (backend tests), pnpm ESLint (frontend lint), POSIX shell for the migration script.

**Spec:** `docs/superpowers/specs/2026-04-14-agent-workspace-normalization-design.md`

---

## File Structure

**Modified files (code):**
- `apps/backend/core/containers/config.py` — add `workspace: "workspaces/main"` to main agent entry
- `apps/backend/core/containers/workspace.py` — extend `_EXCLUDED_NAMES` to hide OpenClaw runtime dirs (state, skills, canvas, identity)
- `apps/backend/routers/workspace_files.py` — fix `_list_config_files` to read from `workspaces/{agent_id}/`, fix `read_config_file` path, collapse `_write_file` tab branching, drop `BOOTSTRAP.md` from allowlist
- `apps/backend/routers/container_rpc.py` — no change (upload path already uses `workspaces/{agent_id}/uploads/`)
- `apps/frontend/src/components/control/panels/AgentCreateForm.tsx` — remove workspace override from `agents.create` call
- `apps/frontend/src/components/chat/FileTree.tsx` — add ghost-entry rendering for missing allowlisted files
- `apps/frontend/src/components/chat/FileViewer.tsx` — pass allowlist into FileTree for the Config tab

**Deleted files:**
- `apps/frontend/src/components/control/panels/AgentFilesTab.tsx` — superseded by the Config tab

**Modified tests:**
- `apps/backend/tests/unit/containers/test_config.py` — assert main entry has `workspace: "workspaces/main"`
- `apps/backend/tests/test_workspace_files.py` — update config-file tests to read from `workspaces/{id}/`; drop BOOTSTRAP.md references; add test that runtime dirs are excluded
- `apps/backend/tests/unit/routers/test_file_upload.py` — no change (already asserts `workspaces/{id}/uploads/`)

**New files:**
- `scripts/migrate-agent-workspace.sh` — manual migration script (runs via `aws ecs execute-command` into backend task)

---

### Task 1: Add `workspace: "workspaces/main"` to main agent config

**Files:**
- Modify: `apps/backend/core/containers/config.py:354-360`
- Modify: `apps/backend/tests/unit/containers/test_config.py`

The main agent currently inherits the default `agents.defaults.workspace = ".openclaw/workspaces"`, which causes OpenClaw to place it at the bare `workspaces/` path (no `/main` suffix). Adding a per-agent `workspace` override moves it into `workspaces/main/`, matching the custom-agent scheme.

- [ ] **Step 1: Write the failing test**

Add to `apps/backend/tests/unit/containers/test_config.py` (put it inside the same class that contains `test_agents_defaults_workspace_routes_to_efs`, around line 155):

```python
    def test_main_agent_has_explicit_workspace(self):
        """Main agent's workspace is workspaces/main so it joins the {id}/ scheme.

        Without this override, OpenClaw places the default agent at the bare
        agents.defaults.workspace path (`.openclaw/workspaces`), while custom
        agents get `{defaults.workspace}/{agentId}`. This inconsistency makes
        the file viewer unable to assume one layout per agent — which caused
        the prod bug in PR #260. The explicit override normalizes main.
        """
        config = json.loads(write_openclaw_config())
        main_entry = next(
            a for a in config["agents"]["list"] if a.get("id") == "main"
        )
        assert main_entry.get("workspace") == "workspaces/main"
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `apps/backend/`):
```
CLERK_ISSUER=https://up-moth-55.clerk.accounts.dev uv run pytest tests/unit/containers/test_config.py::TestWriteOpenclawConfig::test_main_agent_has_explicit_workspace -v
```
Expected: FAIL with `AssertionError: assert None == 'workspaces/main'`.

(If the class name differs from `TestWriteOpenclawConfig`, use whatever class the file actually uses — just pick a class that contains the other `write_openclaw_config` tests. Adjust the pytest nodeid accordingly.)

- [ ] **Step 3: Update `config.py` to declare main's workspace**

In `apps/backend/core/containers/config.py`, replace the existing main agent entry (around lines 354-360):

```python
            "list": [
                {
                    "id": "main",
                    "default": True,
                    "reasoningDefault": "stream",
                },
            ],
```

with:

```python
            "list": [
                {
                    "id": "main",
                    "default": True,
                    "reasoningDefault": "stream",
                    # Explicit override so main lands at workspaces/main/ (matching
                    # the {defaults.workspace}/{agentId} scheme custom agents get
                    # automatically). Without this, main would inherit the bare
                    # defaults.workspace path, creating a two-layout split that
                    # the file viewer cannot represent cleanly. See
                    # docs/superpowers/specs/2026-04-14-agent-workspace-normalization-design.md
                    "workspace": "workspaces/main",
                },
            ],
```

- [ ] **Step 4: Run test to verify it passes**

Run (from `apps/backend/`):
```
CLERK_ISSUER=https://up-moth-55.clerk.accounts.dev uv run pytest tests/unit/containers/test_config.py -v
```
Expected: ALL PASS (the full `test_config.py` file).

- [ ] **Step 5: Commit**

```
git add apps/backend/core/containers/config.py apps/backend/tests/unit/containers/test_config.py
git commit -m "feat(config): declare main agent workspace explicitly at workspaces/main"
```

---

### Task 2: Drop workspace override from `AgentCreateForm`

**Files:**
- Modify: `apps/frontend/src/components/control/panels/AgentCreateForm.tsx:43-49`

Custom agents pass an explicit `workspace: "agents/" + normalizedId` to `agents.create`, forcing them into `agents/{id}/`. With the default left alone, OpenClaw auto-appends `/{agentId}` to `agents.defaults.workspace`, giving us `workspaces/{id}/` — exactly what we want.

- [ ] **Step 1: Remove the workspace param from the RPC call**

In `apps/frontend/src/components/control/panels/AgentCreateForm.tsx`, replace:

```tsx
      await callRpc("agents.create", {
        name: name.trim(),
        workspace: "agents/" + normalizedId,
        // Match the main agent's default so new agents stream thinking
        // events in real time instead of batching at chat.final.
        reasoningDefault: "stream",
      });
```

with:

```tsx
      await callRpc("agents.create", {
        name: name.trim(),
        // No `workspace` override: OpenClaw appends /{agentId} to
        // agents.defaults.workspace automatically, so the agent lands at
        // workspaces/{agentId}/. Matches main's explicit workspaces/main
        // override — every agent uses the same scheme.
        reasoningDefault: "stream",
      });
```

- [ ] **Step 2: Run frontend lint on the changed file**

Run (from `apps/frontend/`):
```
pnpm eslint src/components/control/panels/AgentCreateForm.tsx
```
Expected: no errors.

- [ ] **Step 3: Commit**

```
git add apps/frontend/src/components/control/panels/AgentCreateForm.tsx
git commit -m "feat(agents): inherit OpenClaw's default workspace for new agents"
```

---

### Task 3: Extend `_EXCLUDED_NAMES` to hide OpenClaw runtime dirs

**Files:**
- Modify: `apps/backend/core/containers/workspace.py:25-33`
- Modify: `apps/backend/tests/test_workspace_files.py`

OpenClaw creates `state/`, `skills/`, `canvas/`, `identity/` inside each agent's workspace for its own runtime use. These aren't hidden (no dot prefix), so they currently appear in the Workspace tab tree. Add them to the exclusion set. Keep `memory/` visible since the user wants to eyeball QMD.

- [ ] **Step 1: Write the failing test**

Add to `apps/backend/tests/test_workspace_files.py` inside the `TestListDirectory` class (find the class that contains `test_list_agent_root` and add a sibling method):

```python
    def test_list_excludes_openclaw_runtime_dirs(self, tmp_path):
        """state/, skills/, canvas/, identity/ are excluded from listings.

        OpenClaw creates these inside each agent's workspace for its own
        runtime state. Users shouldn't see or edit them from the file viewer.
        memory/ is NOT excluded — it's user-facing via QMD.
        """
        ws = _make_workspace(tmp_path)
        root = tmp_path / USER_ID / "workspaces" / "main"
        root.mkdir(parents=True)
        (root / "SOUL.md").write_text("soul", encoding="utf-8")
        (root / "memory").mkdir()
        (root / "state").mkdir()
        (root / "skills").mkdir()
        (root / "canvas").mkdir()
        (root / "identity").mkdir()

        entries = ws.list_directory(USER_ID, "workspaces/main")
        names = {e["name"] for e in entries}
        assert "SOUL.md" in names
        assert "memory" in names  # kept — user-visible via QMD
        assert "state" not in names
        assert "skills" not in names
        assert "canvas" not in names
        assert "identity" not in names
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `apps/backend/`):
```
CLERK_ISSUER=https://up-moth-55.clerk.accounts.dev uv run pytest tests/test_workspace_files.py::TestListDirectory::test_list_excludes_openclaw_runtime_dirs -v
```
Expected: FAIL — `state`, `skills`, `canvas`, `identity` show up in the listing.

- [ ] **Step 3: Add the names to `_EXCLUDED_NAMES`**

In `apps/backend/core/containers/workspace.py`, replace:

```python
_EXCLUDED_NAMES: set[str] = {
    "openclaw.json",
    ".openclaw",
    "node_modules",
    "__pycache__",
    ".mcporter",
    ".git",
}
```

with:

```python
_EXCLUDED_NAMES: set[str] = {
    "openclaw.json",
    ".openclaw",
    "node_modules",
    "__pycache__",
    ".mcporter",
    ".git",
    # OpenClaw runtime dirs inside an agent's workspace. memory/ is NOT
    # excluded — it's the user-visible QMD memory index.
    "state",
    "skills",
    "canvas",
    "identity",
}
```

- [ ] **Step 4: Run test to verify it passes**

Run (from `apps/backend/`):
```
CLERK_ISSUER=https://up-moth-55.clerk.accounts.dev uv run pytest tests/test_workspace_files.py -v
```
Expected: ALL PASS.

- [ ] **Step 5: Commit**

```
git add apps/backend/core/containers/workspace.py apps/backend/tests/test_workspace_files.py
git commit -m "feat(workspace): hide OpenClaw runtime dirs from file tree listings"
```

---

### Task 4: Fix `_list_config_files` and `read_config_file` to read from `workspaces/{agent_id}/`

**Files:**
- Modify: `apps/backend/routers/workspace_files.py:120-142, 214-234`
- Modify: `apps/backend/tests/test_workspace_files.py`

The Config tab endpoints currently look in `agents/{agent_id}/`. With the new layout, config files live inside `workspaces/{agent_id}/` alongside workspace files. Point them at the correct directory.

- [ ] **Step 1: Write the failing test**

Add to `apps/backend/tests/test_workspace_files.py` inside `TestConfigFilesEndpoint`:

```python
    def test_reads_from_workspaces_dir_not_agents_dir(self, tmp_path):
        """Config files are expected under workspaces/{agent_id}/, not agents/{agent_id}/.

        With the workspace-normalization change, every agent (main and custom)
        stores its SOUL.md and siblings under workspaces/{agent_id}/. The old
        agents/{agent_id}/ dir now only holds OpenClaw runtime metadata.
        """
        ws = _make_workspace(tmp_path)
        # Put SOUL.md ONLY in the new location
        new_dir = tmp_path / USER_ID / "workspaces" / AGENT_ID
        new_dir.mkdir(parents=True)
        (new_dir / "SOUL.md").write_text("new layout", encoding="utf-8")

        # Also put a decoy in the OLD location — it must NOT be read
        old_dir = tmp_path / USER_ID / "agents" / AGENT_ID
        old_dir.mkdir(parents=True)
        (old_dir / "SOUL.md").write_text("DECOY", encoding="utf-8")

        from routers.workspace_files import _list_config_files

        result = _list_config_files(ws, USER_ID, AGENT_ID)
        names = {f["name"] for f in result}
        assert names == {"SOUL.md"}
        # And confirm we actually read from the new location by checking size
        assert result[0]["size"] == len(b"new layout")
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `apps/backend/`):
```
CLERK_ISSUER=https://up-moth-55.clerk.accounts.dev uv run pytest tests/test_workspace_files.py::TestConfigFilesEndpoint::test_reads_from_workspaces_dir_not_agents_dir -v
```
Expected: FAIL — `_list_config_files` currently reads from `agents/{agent_id}/` and returns the DECOY content (or finds only the decoy).

- [ ] **Step 3: Update `_list_config_files` and `read_config_file` to use the workspaces path**

In `apps/backend/routers/workspace_files.py`, replace the `_list_config_files` function:

```python
def _list_config_files(workspace, owner_id: str, agent_id: str) -> list[dict]:
    """List only allowlisted config files from agents/{agent_id}/."""
    if "/" in agent_id or "\\" in agent_id or ".." in agent_id:
        return []
    user_root = workspace.user_path(owner_id)
    agent_dir = user_root / "agents" / agent_id
    if not agent_dir.exists() or not agent_dir.is_dir():
        return []
    results = []
    for name in sorted(CONFIG_ALLOWLIST):
        fpath = agent_dir / name
        if fpath.exists() and fpath.is_file():
            stat = fpath.stat()
            results.append(
                {
                    "name": name,
                    "path": name,
                    "type": "file",
                    "size": stat.st_size,
                    "modified_at": stat.st_mtime,
                }
            )
    return results
```

with:

```python
def _list_config_files(workspace, owner_id: str, agent_id: str) -> list[dict]:
    """List only allowlisted config files from the agent's workspace.

    Config files (SOUL.md, MEMORY.md, etc.) live inside workspaces/{agent_id}/
    alongside the agent's working files. They are NOT stored in agents/{agent_id}/
    — that directory holds OpenClaw runtime metadata (sessions, models) which
    is intentionally unreachable from the file viewer.
    """
    if "/" in agent_id or "\\" in agent_id or ".." in agent_id:
        return []
    user_root = workspace.user_path(owner_id)
    agent_dir = user_root / "workspaces" / agent_id
    if not agent_dir.exists() or not agent_dir.is_dir():
        return []
    results = []
    for name in sorted(CONFIG_ALLOWLIST):
        fpath = agent_dir / name
        if fpath.exists() and fpath.is_file():
            stat = fpath.stat()
            results.append(
                {
                    "name": name,
                    "path": name,
                    "type": "file",
                    "size": stat.st_size,
                    "modified_at": stat.st_mtime,
                }
            )
    return results
```

And replace the `read_config_file` endpoint's body path construction:

Find:
```python
    workspace = get_workspace()
    full_path = f"agents/{agent_id}/{path}"
```

Replace with:
```python
    workspace = get_workspace()
    full_path = f"workspaces/{agent_id}/{path}"
```

- [ ] **Step 4: Run test to verify it passes**

Run (from `apps/backend/`):
```
CLERK_ISSUER=https://up-moth-55.clerk.accounts.dev uv run pytest tests/test_workspace_files.py::TestConfigFilesEndpoint -v
```
Expected: ALL PASS (including the new test).

- [ ] **Step 5: Commit**

```
git add apps/backend/routers/workspace_files.py apps/backend/tests/test_workspace_files.py
git commit -m "fix(api): config files read from workspaces/{id}/ not agents/{id}/"
```

---

### Task 5: Collapse `_write_file` tab branching + drop BOOTSTRAP.md from allowlist

**Files:**
- Modify: `apps/backend/routers/workspace_files.py:106-115, 243-267`
- Modify: `apps/backend/tests/test_workspace_files.py`

Both tabs now write under the same `workspaces/{agent_id}/` subtree. The `tab` parameter only matters for the allowlist gate (config tab = allowlist-only). Also drop `BOOTSTRAP.md` — OpenClaw's source at `desktop/openclaw/src/agents/workspace.ts:26-34` seeds 7 files, not 8.

- [ ] **Step 1: Write the failing test**

Add to `apps/backend/tests/test_workspace_files.py` inside `TestWriteFileEndpoint`:

```python
    def test_config_tab_writes_under_workspaces_subtree(self, tmp_path):
        """tab='config' writes into workspaces/{id}/, not agents/{id}/."""
        ws = _make_workspace(tmp_path)
        ws_dir = tmp_path / USER_ID / "workspaces" / AGENT_ID
        ws_dir.mkdir(parents=True)

        from routers.workspace_files import _write_file

        written = _write_file(ws, USER_ID, AGENT_ID, "SOUL.md", "hello", "config")
        assert written == f"workspaces/{AGENT_ID}/SOUL.md"
        assert (ws_dir / "SOUL.md").read_text() == "hello"
        # And confirm nothing was written into the old agents/{id}/ path
        assert not (tmp_path / USER_ID / "agents" / AGENT_ID / "SOUL.md").exists()

    def test_bootstrap_md_not_in_allowlist(self):
        """BOOTSTRAP.md is not a real OpenClaw-seeded file — drop it from the allowlist."""
        from routers.workspace_files import CONFIG_ALLOWLIST

        assert "BOOTSTRAP.md" not in CONFIG_ALLOWLIST
        # The 7 files OpenClaw actually seeds (per
        # desktop/openclaw/src/agents/workspace.ts):
        assert CONFIG_ALLOWLIST == {
            "SOUL.md",
            "MEMORY.md",
            "TOOLS.md",
            "IDENTITY.md",
            "USER.md",
            "HEARTBEAT.md",
            "AGENTS.md",
        }
```

- [ ] **Step 2: Run tests to verify they fail**

Run (from `apps/backend/`):
```
CLERK_ISSUER=https://up-moth-55.clerk.accounts.dev uv run pytest tests/test_workspace_files.py::TestWriteFileEndpoint -v
```
Expected: Both new tests FAIL. `_write_file` with `tab='config'` currently writes under `agents/{id}/`; `BOOTSTRAP.md` is still in the allowlist.

- [ ] **Step 3: Collapse `_write_file` branching and drop BOOTSTRAP.md**

In `apps/backend/routers/workspace_files.py`, update `CONFIG_ALLOWLIST`:

```python
CONFIG_ALLOWLIST: set[str] = {
    "SOUL.md",
    "MEMORY.md",
    "TOOLS.md",
    "IDENTITY.md",
    "USER.md",
    "HEARTBEAT.md",
    "BOOTSTRAP.md",
    "AGENTS.md",
}
```

Replace with:

```python
# The 7 config files OpenClaw seeds in every agent workspace.
# Source: desktop/openclaw/src/agents/workspace.ts:26-34. These are the only
# filenames the Config tab treats as first-class personality/config files;
# writes via tab="config" are restricted to this set.
CONFIG_ALLOWLIST: set[str] = {
    "SOUL.md",
    "MEMORY.md",
    "TOOLS.md",
    "IDENTITY.md",
    "USER.md",
    "HEARTBEAT.md",
    "AGENTS.md",
}
```

And replace `_write_file` (currently around lines 243-267):

```python
def _write_file(workspace, owner_id: str, agent_id: str, path: str, content: str, tab: str) -> str:
    """Write a file to workspace or config directory. Returns the written path."""
    encoded = content.encode("utf-8")
    if len(encoded) > MAX_WRITE_SIZE:
        raise ValueError(f"content exceeds {MAX_WRITE_SIZE // (1024 * 1024)}MB limit")

    if "/" in agent_id or "\\" in agent_id or ".." in agent_id:
        raise ValueError(f"Invalid agent_id: {agent_id!r}")

    _validate_relative_path(path)

    if tab == "config":
        if path not in CONFIG_ALLOWLIST:
            raise ValueError(f"File not in allowlist: {path}")
        subtree = f"agents/{agent_id}"
    elif tab == "workspace":
        subtree = f"workspaces/{agent_id}"
    else:
        raise ValueError(f"Invalid tab: {tab!r}")

    full_path = f"{subtree}/{path}"
    _ensure_within_subtree(workspace, owner_id, full_path, subtree)

    workspace.write_file(owner_id, full_path, content)
    return full_path
```

with:

```python
def _write_file(workspace, owner_id: str, agent_id: str, path: str, content: str, tab: str) -> str:
    """Write a file into the agent's workspace. Returns the user-root-relative path.

    Both tabs ("workspace" and "config") write under the same subtree:
    workspaces/{agent_id}/. The tab controls the allowlist gate only — the
    config tab is restricted to the 7 personality files (SOUL.md etc.), the
    workspace tab accepts arbitrary relative paths.
    """
    encoded = content.encode("utf-8")
    if len(encoded) > MAX_WRITE_SIZE:
        raise ValueError(f"content exceeds {MAX_WRITE_SIZE // (1024 * 1024)}MB limit")

    if "/" in agent_id or "\\" in agent_id or ".." in agent_id:
        raise ValueError(f"Invalid agent_id: {agent_id!r}")

    _validate_relative_path(path)

    if tab == "config":
        if path not in CONFIG_ALLOWLIST:
            raise ValueError(f"File not in allowlist: {path}")
    elif tab != "workspace":
        raise ValueError(f"Invalid tab: {tab!r}")

    subtree = f"workspaces/{agent_id}"
    full_path = f"{subtree}/{path}"
    _ensure_within_subtree(workspace, owner_id, full_path, subtree)

    workspace.write_file(owner_id, full_path, content)
    return full_path
```

- [ ] **Step 4: Check for other BOOTSTRAP.md references**

Run:
```
grep -rn "BOOTSTRAP.md" apps/backend/
```

Any test assertions referencing BOOTSTRAP.md (for example `test_write_rejects_non_allowlisted_filename` or allowlist snapshots) need updating. For each reference, either remove the BOOTSTRAP.md-specific assertion or replace it with one of the 7 remaining files (e.g., `AGENTS.md`). Do NOT silently delete assertions that validate security — rewrite them against a file still in the allowlist.

Specifically check:
- `apps/backend/tests/test_workspace_files.py::TestConfigFileReadEndpoint::test_rejects_non_allowlisted_filename` — if it used BOOTSTRAP.md as an example, switch to a path outside the 7 (e.g., `"BOOTSTRAP.md"` itself is now a great test case since it USED to be allowed).
- Any fixture populating BOOTSTRAP.md — delete the file creation.

After edits, re-run:
```
grep -rn "BOOTSTRAP.md" apps/backend/
```
Expected: remaining matches are all in comments or in tests that explicitly assert BOOTSTRAP.md is now rejected — nothing asserts it is allowlisted.

- [ ] **Step 5: Run full test file**

Run (from `apps/backend/`):
```
CLERK_ISSUER=https://up-moth-55.clerk.accounts.dev uv run pytest tests/test_workspace_files.py -v
```
Expected: ALL PASS.

- [ ] **Step 6: Commit**

```
git add apps/backend/routers/workspace_files.py apps/backend/tests/test_workspace_files.py
git commit -m "fix(api): collapse write tabs to one subtree + drop BOOTSTRAP.md"
```

---

### Task 6: Delete AgentFilesTab and unmount it from AgentsPanel

**Files:**
- Delete: `apps/frontend/src/components/control/panels/AgentFilesTab.tsx`
- Modify: `apps/frontend/src/components/control/panels/AgentsPanel.tsx:16, 160-190`

The Config tab in the file viewer replaces the control-panel Files tab. Remove the import, the tab entry, and the render branch.

- [ ] **Step 1: Remove the import**

In `apps/frontend/src/components/control/panels/AgentsPanel.tsx`, delete the line (currently line 16):

```tsx
import { AgentFilesTab } from "./AgentFilesTab";
```

- [ ] **Step 2: Remove the Files tab entry from the tab list**

Find the tab definition array (around lines 159-167):

```tsx
                {(
                  [
                    { id: "overview", icon: Bot, label: "Overview" },
                    { id: "files", icon: FileText, label: "Files" },
                    { id: "tools", icon: Wrench, label: "Tools" },
                    ...(channelsEnabled
                      ? [{ id: "channels", icon: MessageSquare, label: "Channels" } as const]
                      : []),
                  ] as const
                ).map((tab) => (
```

Remove the `{ id: "files", icon: FileText, label: "Files" },` line:

```tsx
                {(
                  [
                    { id: "overview", icon: Bot, label: "Overview" },
                    { id: "tools", icon: Wrench, label: "Tools" },
                    ...(channelsEnabled
                      ? [{ id: "channels", icon: MessageSquare, label: "Channels" } as const]
                      : []),
                  ] as const
                ).map((tab) => (
```

- [ ] **Step 3: Remove the render branch**

Find the render block (around lines 188-190):

```tsx
              {activeTab === "files" && (
                <AgentFilesTab agentId={selected.id} />
              )}
```

Delete those three lines entirely.

- [ ] **Step 4: Clean up unused imports**

If `FileText` from `lucide-react` is no longer used anywhere else in `AgentsPanel.tsx`, remove it from the `lucide-react` import. Check the file with:

```
grep -n "FileText" apps/frontend/src/components/control/panels/AgentsPanel.tsx
```

If no other usage remains, remove `FileText` from the `lucide-react` import list.

- [ ] **Step 5: Delete `AgentFilesTab.tsx`**

```
rm apps/frontend/src/components/control/panels/AgentFilesTab.tsx
```

- [ ] **Step 6: Verify nothing else imports AgentFilesTab**

Run:
```
grep -rn "AgentFilesTab" apps/frontend/src
```
Expected: no matches.

- [ ] **Step 7: Run lint**

Run (from `apps/frontend/`):
```
pnpm eslint src/components/control/panels/AgentsPanel.tsx
```
Expected: no errors.

- [ ] **Step 8: Verify types still compile**

Run (from `apps/frontend/`):
```
pnpm tsc --noEmit 2>&1 | grep -E "AgentsPanel\.tsx|AgentFilesTab"
```
Expected: no output (no TypeScript errors in those files).

- [ ] **Step 9: Commit**

```
git add apps/frontend/src/components/control/panels/AgentFilesTab.tsx apps/frontend/src/components/control/panels/AgentsPanel.tsx
git commit -m "refactor(control): remove AgentFilesTab, superseded by file-viewer Config tab"
```

(`git add` on a deleted file records the deletion; no `git rm` needed, but you can use `git rm` if preferred.)

---

### Task 7: Surface allowlist ghost entries in the Config tab

**Files:**
- Modify: `apps/frontend/src/components/chat/FileTree.tsx`
- Modify: `apps/frontend/src/components/chat/FileViewer.tsx`

When the Config tab's list comes back missing one of the 7 allowlisted files, show a faded "missing" entry with a warning icon. Clicking it still fires `onSelect(name)` — the editor opens a blank buffer that the user can save to create the file.

- [ ] **Step 1: Extend `FileTreeProps` with an optional `allowlist` prop**

In `apps/frontend/src/components/chat/FileTree.tsx`, update the props interface and imports.

Replace the lucide-react import at the top:

```tsx
import {
  ChevronRight, ChevronDown, FileText, FileCode, FileImage,
  FileJson, File, FolderOpen, FolderClosed, RefreshCw,
} from "lucide-react";
```

with:

```tsx
import {
  ChevronRight, ChevronDown, FileText, FileCode, FileImage,
  FileJson, File, FileWarning, FolderOpen, FolderClosed, RefreshCw,
} from "lucide-react";
```

Replace the `FileTreeProps` interface:

```tsx
interface FileTreeProps {
  files: FileEntry[];
  selectedPath: string | null;
  onSelect: (path: string) => void;
  onRefresh: () => void;
  isLoading: boolean;
  emptyMessage?: string;
}
```

with:

```tsx
interface FileTreeProps {
  files: FileEntry[];
  selectedPath: string | null;
  onSelect: (path: string) => void;
  onRefresh: () => void;
  isLoading: boolean;
  emptyMessage?: string;
  /**
   * Optional allowlist of filenames that SHOULD be visible as entries in this
   * tree even if they don't exist on disk. Used by the Config tab to render
   * "missing" ghost entries the user can click to create the file. When set,
   * the tree also filters `files` down to only names in the allowlist.
   */
  allowlist?: string[];
}
```

- [ ] **Step 2: Update the `FileTree` component body to compute ghost + filtered entries**

Replace the `FileTree` function (currently around lines 96-135):

```tsx
export function FileTree({ files, selectedPath, onSelect, onRefresh, isLoading, emptyMessage }: FileTreeProps) {
  const rootEntries = React.useMemo(() => {
    if (files.length === 0) return [];
    const depths = files.map((f) => f.path.split("/").length);
    const minDepth = Math.min(...depths);
    return files.filter((f) => f.path.split("/").length === minDepth);
  }, [files]);

  return (
    <div className="h-full flex flex-col">
      <div className="flex items-center justify-between px-3 py-2 border-b border-[#e0dbd0]">
        <span className="text-xs font-medium text-[#8a8578] uppercase tracking-wide">Files</span>
        <button
          onClick={onRefresh}
          className="text-[#8a8578] hover:text-[#1a1a1a] transition-colors"
          title="Refresh file tree"
        >
          <RefreshCw className={`h-3.5 w-3.5 ${isLoading ? "animate-spin" : ""}`} />
        </button>
      </div>
      <div className="flex-1 overflow-y-auto p-2">
        {files.length === 0 && !isLoading ? (
          <div className="text-xs text-[#8a8578] text-center py-4 px-3">
            {emptyMessage ?? "No files in workspace"}
          </div>
        ) : (
          rootEntries.map((entry) => (
            <FileTreeNode
              key={entry.path}
              entry={entry}
              allEntries={files}
              selectedPath={selectedPath}
              onSelect={onSelect}
            />
          ))
        )}
      </div>
    </div>
  );
}
```

with:

```tsx
export function FileTree({
  files,
  selectedPath,
  onSelect,
  onRefresh,
  isLoading,
  emptyMessage,
  allowlist,
}: FileTreeProps) {
  // When an allowlist is provided, we're in "curated" mode (Config tab):
  //   - filter `files` down to only names in the allowlist
  //   - synthesize ghost entries for allowlisted names that aren't present
  // Without an allowlist we render every entry as-is (Workspace tab).
  const displayEntries = React.useMemo<FileEntry[]>(() => {
    if (!allowlist) {
      return files;
    }
    const allowed = new Set(allowlist);
    const presentByName = new Map(
      files.filter((f) => allowed.has(f.name)).map((f) => [f.name, f]),
    );
    return allowlist.map(
      (name) =>
        presentByName.get(name) ?? {
          name,
          path: name,
          type: "file" as const,
          size: null,
          modified_at: 0,
          missing: true,
        },
    );
  }, [files, allowlist]);

  const rootEntries = React.useMemo(() => {
    if (allowlist) {
      // In curated mode, every entry is a root entry — no tree nesting.
      return displayEntries;
    }
    if (displayEntries.length === 0) return [];
    const depths = displayEntries.map((f) => f.path.split("/").length);
    const minDepth = Math.min(...depths);
    return displayEntries.filter((f) => f.path.split("/").length === minDepth);
  }, [displayEntries, allowlist]);

  return (
    <div className="h-full flex flex-col">
      <div className="flex items-center justify-between px-3 py-2 border-b border-[#e0dbd0]">
        <span className="text-xs font-medium text-[#8a8578] uppercase tracking-wide">Files</span>
        <button
          onClick={onRefresh}
          className="text-[#8a8578] hover:text-[#1a1a1a] transition-colors"
          title="Refresh file tree"
        >
          <RefreshCw className={`h-3.5 w-3.5 ${isLoading ? "animate-spin" : ""}`} />
        </button>
      </div>
      <div className="flex-1 overflow-y-auto p-2">
        {rootEntries.length === 0 && !isLoading ? (
          <div className="text-xs text-[#8a8578] text-center py-4 px-3">
            {emptyMessage ?? "No files in workspace"}
          </div>
        ) : (
          rootEntries.map((entry) => (
            <FileTreeNode
              key={entry.path}
              entry={entry}
              allEntries={displayEntries}
              selectedPath={selectedPath}
              onSelect={onSelect}
            />
          ))
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Render missing entries with a faded + warning-icon style**

Still in `apps/frontend/src/components/chat/FileTree.tsx`, update the file-branch of `FileTreeNode` (starting around the current `const isSelected = selectedPath === entry.path;`). Replace that block with:

```tsx
  const isSelected = selectedPath === entry.path;
  const isMissing = Boolean((entry as FileEntry & { missing?: boolean }).missing);

  return (
    <button
      onClick={() => onSelect(entry.path)}
      className={`w-full flex items-center gap-1.5 px-2 py-1 text-sm rounded transition-colors ${
        isSelected
          ? "bg-white text-[#1a1a1a] shadow-sm"
          : isMissing
            ? "text-[#8a8578] hover:bg-[#e8e3d9]"
            : "text-[#1a1a1a] hover:bg-[#e8e3d9]"
      }`}
      title={isMissing ? "Click to create this file" : undefined}
    >
      <span className="w-3.5 flex-shrink-0" />
      {isMissing ? (
        <FileWarning className="h-4 w-4 text-[#8a8578] flex-shrink-0" />
      ) : (
        renderFileIcon(entry.name, "h-4 w-4 text-[#8a8578] flex-shrink-0")
      )}
      <span className={`truncate ${isMissing ? "italic" : ""}`}>{entry.name}</span>
    </button>
  );
```

- [ ] **Step 4: Extend `FileEntry` type to permit the `missing` flag**

In `apps/frontend/src/hooks/useWorkspaceFiles.ts`, find the `FileEntry` interface. It currently looks like:

```ts
export interface FileEntry {
  name: string;
  path: string;
  type: "file" | "dir";
  size: number | null;
  modified_at: number;
}
```

Extend it:

```ts
export interface FileEntry {
  name: string;
  path: string;
  type: "file" | "dir";
  size: number | null;
  modified_at: number;
  /**
   * Present only on frontend-synthesized "ghost" entries — allowlisted config
   * files that don't exist on disk yet. Backend responses never set this.
   */
  missing?: boolean;
}
```

- [ ] **Step 5: Pass `allowlist` from `FileViewer` to `FileTree` when the Config tab is active**

In `apps/frontend/src/components/chat/FileViewer.tsx`, add a module-scope constant that mirrors the backend allowlist and pass it to `FileTree` in the config branch.

Find the existing module-scope area (top of file, after imports):

Add:

```tsx
const CONFIG_ALLOWLIST = [
  "SOUL.md",
  "MEMORY.md",
  "TOOLS.md",
  "IDENTITY.md",
  "USER.md",
  "HEARTBEAT.md",
  "AGENTS.md",
];
```

Then find the `<FileTree>` render. Depending on the current implementation, it will look something like:

```tsx
<FileTree
  files={files}
  selectedPath={selectedPath}
  onSelect={handleSelectFile}
  onRefresh={handleRefresh}
  isLoading={isLoadingTree}
  emptyMessage={tab === "config" ? "No config files for this agent yet" : undefined}
/>
```

Pass an `allowlist` prop in the config branch (and only in the config branch):

```tsx
<FileTree
  files={files}
  selectedPath={selectedPath}
  onSelect={handleSelectFile}
  onRefresh={handleRefresh}
  isLoading={isLoadingTree}
  emptyMessage={tab === "config" ? "No config files for this agent yet" : undefined}
  allowlist={tab === "config" ? CONFIG_ALLOWLIST : undefined}
/>
```

(The existing `tab` variable and `<FileTree>` props may be named slightly differently — adapt to whatever the current file uses.)

- [ ] **Step 6: Handle ghost click → open blank editor buffer**

The `onSelect` callback receives just the filename for a missing entry. Confirm by reading the existing `onSelect` handler flow in `FileViewer.tsx` — it should already call a getter that hits the config-file endpoint. When the backend returns 404 for a missing file, the editor should default to an empty buffer rather than an error.

If the editor currently shows "Could not load file" on 404, add a fallback that shows an empty buffer with the given name. Inspect the `FileContentViewer` component (or equivalent) — the data fetcher should distinguish "file not yet created" from "error". Implementation will vary by the current code; the goal is that clicking a ghost entry opens an editor with empty content, the user can type and save, and the save hits `PUT /workspace/{agent_id}/file` with `tab="config"`.

If this requires more than a small change, capture it as a separate follow-up commit in this task rather than over-engineering it here. The ghost rendering alone is a significant UX improvement; the "click-to-create" flow can ship in a later iteration.

- [ ] **Step 7: Run lint on the changed files**

Run (from `apps/frontend/`):
```
pnpm eslint src/components/chat/FileTree.tsx src/components/chat/FileViewer.tsx src/hooks/useWorkspaceFiles.ts
```
Expected: no errors.

- [ ] **Step 8: Commit**

```
git add apps/frontend/src/components/chat/FileTree.tsx apps/frontend/src/components/chat/FileViewer.tsx apps/frontend/src/hooks/useWorkspaceFiles.ts
git commit -m "feat(viewer): show ghost entries for missing allowlisted files"
```

---

### Task 8: Manual migration script

**Files:**
- Create: `scripts/migrate-agent-workspace.sh`

A POSIX shell script that, given a user's EFS directory path, moves the main agent's workspace files from bare `workspaces/` into `workspaces/main/`. Runs as dry-run by default; `--apply` actually performs moves. Invoked per-user via `aws ecs execute-command` into the backend task.

- [ ] **Step 1: Create the script**

Create `scripts/migrate-agent-workspace.sh` with:

```sh
#!/bin/sh
# Migrate one EFS user directory from the pre-normalization layout
# (main agent's files at workspaces/*) to the normalized layout
# (main agent's files at workspaces/main/*).
#
# Usage:
#   migrate-agent-workspace.sh /mnt/efs/users/<user_id>            # dry run
#   migrate-agent-workspace.sh --apply /mnt/efs/users/<user_id>    # execute
#
# Run inside the backend ECS task:
#   aws ecs execute-command --cluster <cluster> --task <task_id> \
#     --container backend --interactive \
#     --command "/bin/sh /app/scripts/migrate-agent-workspace.sh /mnt/efs/users/<uid>"
#
# The user's OpenClaw service should be stopped (desired count = 0) before
# running with --apply, to avoid races with a running agent writing into
# workspaces/ while we're moving files.

set -eu

APPLY=0
if [ "${1:-}" = "--apply" ]; then
  APPLY=1
  shift
fi

USER_DIR="${1:-}"
if [ -z "$USER_DIR" ]; then
  echo "usage: $0 [--apply] /mnt/efs/users/<user_id>" >&2
  exit 2
fi

if [ ! -d "$USER_DIR" ]; then
  echo "error: $USER_DIR is not a directory" >&2
  exit 2
fi

WS="$USER_DIR/workspaces"
MAIN="$WS/main"

echo "== migrate-agent-workspace =="
echo "  user_dir: $USER_DIR"
echo "  apply:    $APPLY"
echo

if [ ! -d "$WS" ]; then
  echo "  workspaces/ doesn't exist — nothing to migrate"
  exit 0
fi

# Items to move from workspaces/ into workspaces/main/.
# Explicit lists prevent accidentally touching custom-agent subdirs that
# already exist at workspaces/{id}/ (these inherit the default and are
# already correctly placed).
CONFIG_FILES="SOUL.md MEMORY.md TOOLS.md IDENTITY.md USER.md HEARTBEAT.md AGENTS.md"
WORKING_DIRS="memory state skills canvas identity uploads"
HIDDEN_DIRS=".openclaw .clawhub"

mkdir_main() {
  if [ -d "$MAIN" ]; then
    return 0
  fi
  if [ "$APPLY" -eq 1 ]; then
    mkdir -p "$MAIN"
    echo "  mkdir: $MAIN"
  else
    echo "  would mkdir: $MAIN"
  fi
}

move_item() {
  src="$1"
  dst="$2"
  if [ ! -e "$src" ] && [ ! -L "$src" ]; then
    return 0
  fi
  if [ -e "$dst" ]; then
    echo "  SKIP (exists): $dst"
    return 0
  fi
  if [ "$APPLY" -eq 1 ]; then
    mv "$src" "$dst"
    echo "  moved: $src -> $dst"
  else
    echo "  would move: $src -> $dst"
  fi
}

echo "== preview changes =="
mkdir_main
for f in $CONFIG_FILES; do
  move_item "$WS/$f" "$MAIN/$f"
done
for d in $WORKING_DIRS; do
  move_item "$WS/$d" "$MAIN/$d"
done
for d in $HIDDEN_DIRS; do
  move_item "$WS/$d" "$MAIN/$d"
done

echo
if [ "$APPLY" -eq 0 ]; then
  echo "dry run complete. Re-run with --apply to perform moves."
else
  echo "migration complete."
  echo
  echo "Remaining in $WS/ (should be only custom-agent subdirs + main/):"
  ls -la "$WS/"
fi
```

- [ ] **Step 2: Make it executable**

```
chmod +x scripts/migrate-agent-workspace.sh
```

- [ ] **Step 3: Hand-verify the dry-run output against a local fixture**

Create a temporary fake user dir and run the script in dry-run mode to sanity-check the preview output:

```
TMPDIR=$(mktemp -d)
mkdir -p "$TMPDIR/workspaces"
echo "soul" > "$TMPDIR/workspaces/SOUL.md"
mkdir -p "$TMPDIR/workspaces/memory"
mkdir -p "$TMPDIR/workspaces/state"
sh scripts/migrate-agent-workspace.sh "$TMPDIR"
```

Expected output includes lines like:
```
  would mkdir: .../workspaces/main
  would move: .../workspaces/SOUL.md -> .../workspaces/main/SOUL.md
  would move: .../workspaces/memory -> .../workspaces/main/memory
  would move: .../workspaces/state -> .../workspaces/main/state
```

Then run with `--apply`:
```
sh scripts/migrate-agent-workspace.sh --apply "$TMPDIR"
```

Confirm the files actually moved:
```
ls -la "$TMPDIR/workspaces/main/"
```

Expected: SOUL.md, memory/, state/ all inside workspaces/main/.

Clean up:
```
rm -rf "$TMPDIR"
```

- [ ] **Step 4: Commit**

```
git add scripts/migrate-agent-workspace.sh
git commit -m "chore(migration): add script to normalize main agent workspace on EFS"
```

---

### Task 9: Integration verification and documentation

**Files:**
- No new files — verification task.

- [ ] **Step 1: Run the full backend test suite**

Run (from `apps/backend/`):
```
CLERK_ISSUER=https://up-moth-55.clerk.accounts.dev uv run pytest tests/
```
Expected: all tests pass. If anything fails, the fix goes in the task that owns that code; don't silence failures here.

- [ ] **Step 2: Run frontend lint**

Run (from `apps/frontend/`):
```
pnpm run lint
```
Expected: no errors.

- [ ] **Step 3: Run frontend typecheck**

Run (from `apps/frontend/`):
```
pnpm tsc --noEmit
```
Expected: no errors.

- [ ] **Step 4: Grep for stale references**

Run:
```
grep -rn 'workspace: "agents/' apps/frontend/src
grep -rn 'agents/{agent_id}/SOUL.md\|agents/{agent_id}/MEMORY.md' apps/backend
grep -rn "AgentFilesTab" apps/frontend/src
```
Expected: no matches in source files (matches in the design doc, plan doc, or generated code are OK — inspect and confirm they're documentation).

- [ ] **Step 5: Produce a manual verification checklist in the PR body**

Don't run these — they require prod deploy + migration. Put them in the PR description under a "Post-deploy verification" heading:

- [ ] Deploy backend + frontend.
- [ ] For each of the 3 prod users, stop their OpenClaw service, run `migrate-agent-workspace.sh --apply /mnt/efs/users/{user_id}`, run `PATCH /debug/provision` (or equivalent) to rewrite `openclaw.json`, restart the service.
- [ ] Sign in as a user with a main agent. Open the file viewer. Config tab lists the 7 allowlisted files; `BOOTSTRAP.md` is NOT listed. Missing files (if any) appear as italicized ghost entries.
- [ ] Edit SOUL.md, save, refresh — change persists.
- [ ] Workspace tab excludes `state/`, `skills/`, `canvas/`, `identity/`; includes `memory/`.
- [ ] Create a new custom agent. `ls /mnt/efs/users/{user_id}/workspaces/{new_id}/` on the backend shows the seed files.
- [ ] Old Files tab in the control panel Agent detail view is gone.

- [ ] **Step 6: Push and open the PR**

```
git push -u origin feat/agent-workspace-normalization
gh pr create --title "feat: normalize agent workspaces to workspaces/{id}/" --body-file <(printf '<PR body here>')
```

For the PR body, reference the spec path and include the Post-deploy verification checklist from Step 5.
