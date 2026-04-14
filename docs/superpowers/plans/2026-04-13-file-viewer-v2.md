# File Viewer V2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the empty file viewer, broken uploads, and cramped layout — replace with a full-width IDE-style split pane with two tabs (Workspace/Config) and inline editing.

**Architecture:** Backend gets 3 new endpoints (config file list, config file read, file write) and an `agent_id` param on the existing upload endpoint. Frontend layout flips to `[Chat 380px] [FileViewer 1fr]` when the viewer opens (sidebar hides). FileViewer gains tab state and FileContentViewer becomes an inline editor with save via direct EFS writes.

**Tech Stack:** Python/FastAPI (backend), React/Next.js 16 + Tailwind CSS v4 + SWR (frontend), pytest (backend tests), vitest (frontend tests)

**Spec:** `docs/superpowers/specs/2026-04-13-file-viewer-v2-design.md`

---

### Task 1: Backend — Config file list and read endpoints

**Files:**
- Modify: `apps/backend/routers/workspace_files.py`
- Modify: `apps/backend/tests/test_workspace_files.py`

The workspace_files router currently only has endpoints for `workspaces/{agent_id}/`. We need two new endpoints that serve allowlisted config files from `agents/{agent_id}/`.

- [ ] **Step 1: Write failing tests for config-files endpoint**

Add to `apps/backend/tests/test_workspace_files.py`:

```python
# At the top, add imports
from unittest.mock import MagicMock, patch, AsyncMock
from fastapi.testclient import TestClient

# Add these constants
AGENT_ID = "agent-abc-123"
ALLOWLISTED_FILES = [
    "SOUL.md", "MEMORY.md", "TOOLS.md", "IDENTITY.md",
    "USER.md", "HEARTBEAT.md", "BOOTSTRAP.md", "AGENTS.md",
]


class TestConfigFilesEndpoint:
    """Tests for GET /workspace/{agent_id}/config-files."""

    def test_returns_only_allowlisted_files(self, tmp_path):
        """Only allowlisted files that exist on disk are returned."""
        ws = _make_workspace(tmp_path)
        agent_dir = tmp_path / USER_ID / "agents" / AGENT_ID
        agent_dir.mkdir(parents=True)
        (agent_dir / "SOUL.md").write_text("I am helpful", encoding="utf-8")
        (agent_dir / "MEMORY.md").write_text("Remember this", encoding="utf-8")
        (agent_dir / "sessions").mkdir()  # should be excluded
        (agent_dir / "secret.json").write_text("{}", encoding="utf-8")  # not allowlisted

        from routers.workspace_files import _list_config_files
        result = _list_config_files(ws, USER_ID, AGENT_ID)
        names = {f["name"] for f in result}
        assert names == {"SOUL.md", "MEMORY.md"}
        assert all(f["type"] == "file" for f in result)

    def test_empty_when_no_agent_dir(self, tmp_path):
        """Returns empty list when agent dir doesn't exist."""
        ws = _make_workspace(tmp_path)
        (tmp_path / USER_ID).mkdir(parents=True)
        from routers.workspace_files import _list_config_files
        result = _list_config_files(ws, USER_ID, AGENT_ID)
        assert result == []

    def test_file_entries_have_required_fields(self, tmp_path):
        """Each entry has name, path, type, size, modified_at."""
        ws = _make_workspace(tmp_path)
        agent_dir = tmp_path / USER_ID / "agents" / AGENT_ID
        agent_dir.mkdir(parents=True)
        (agent_dir / "BOOTSTRAP.md").write_text("# Bootstrap", encoding="utf-8")
        from routers.workspace_files import _list_config_files
        result = _list_config_files(ws, USER_ID, AGENT_ID)
        assert len(result) == 1
        entry = result[0]
        assert entry["name"] == "BOOTSTRAP.md"
        assert entry["path"] == "BOOTSTRAP.md"
        assert entry["type"] == "file"
        assert isinstance(entry["size"], int)
        assert isinstance(entry["modified_at"], float)


class TestConfigFileReadEndpoint:
    """Tests for GET /workspace/{agent_id}/config-file."""

    def test_reads_allowlisted_file(self, tmp_path):
        """Can read an allowlisted config file."""
        ws = _make_workspace(tmp_path)
        agent_dir = tmp_path / USER_ID / "agents" / AGENT_ID
        agent_dir.mkdir(parents=True)
        (agent_dir / "SOUL.md").write_text("I am helpful", encoding="utf-8")
        info = ws.read_file_info(USER_ID, f"agents/{AGENT_ID}/SOUL.md")
        assert info["content"] == "I am helpful"
        assert info["binary"] is False

    def test_rejects_non_allowlisted_filename(self, tmp_path):
        """Non-allowlisted filenames are rejected."""
        from routers.workspace_files import CONFIG_ALLOWLIST
        assert "secret.json" not in CONFIG_ALLOWLIST
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd apps/backend && uv run pytest tests/test_workspace_files.py::TestConfigFilesEndpoint tests/test_workspace_files.py::TestConfigFileReadEndpoint -v`
Expected: FAIL — `_list_config_files` and `CONFIG_ALLOWLIST` don't exist yet.

- [ ] **Step 3: Implement config file list/read endpoints**

In `apps/backend/routers/workspace_files.py`, add the allowlist constant and helper function after the existing `_collect_recursive` function:

```python
CONFIG_ALLOWLIST: set[str] = {
    "SOUL.md", "MEMORY.md", "TOOLS.md", "IDENTITY.md",
    "USER.md", "HEARTBEAT.md", "BOOTSTRAP.md", "AGENTS.md",
}


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
            results.append({
                "name": name,
                "path": name,
                "type": "file",
                "size": stat.st_size,
                "modified_at": stat.st_mtime,
            })
    return results
```

Add two new endpoint functions:

```python
@router.get("/workspace/{agent_id}/config-files")
async def list_config_files(
    agent_id: str,
    auth: AuthContext = Depends(get_current_user),
):
    """List allowlisted agent config files (SOUL.md, MEMORY.md, etc.)."""
    owner_id = resolve_owner_id(auth)
    workspace = get_workspace()
    if "/" in agent_id or "\\" in agent_id or ".." in agent_id:
        raise HTTPException(status_code=400, detail="Invalid agent_id")
    return {"files": _list_config_files(workspace, owner_id, agent_id)}


@router.get("/workspace/{agent_id}/config-file")
async def read_config_file(
    agent_id: str,
    path: str = Query(..., description="Config filename (must be allowlisted)"),
    auth: AuthContext = Depends(get_current_user),
):
    """Read a single allowlisted agent config file."""
    owner_id = resolve_owner_id(auth)
    if path not in CONFIG_ALLOWLIST:
        raise HTTPException(status_code=400, detail=f"File not in allowlist: {path}")
    if "/" in agent_id or "\\" in agent_id or ".." in agent_id:
        raise HTTPException(status_code=400, detail="Invalid agent_id")
    workspace = get_workspace()
    full_path = f"agents/{agent_id}/{path}"
    try:
        info = workspace.read_file_info(owner_id, full_path)
    except WorkspaceError as exc:
        if "not found" in str(exc).lower():
            raise HTTPException(status_code=404, detail=str(exc))
        raise HTTPException(status_code=500, detail=str(exc))
    return info
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd apps/backend && uv run pytest tests/test_workspace_files.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add apps/backend/routers/workspace_files.py apps/backend/tests/test_workspace_files.py
git commit -m "feat(api): add config-files list and read endpoints for agent personality files"
```

---

### Task 2: Backend — File write endpoint

**Files:**
- Modify: `apps/backend/routers/workspace_files.py`
- Modify: `apps/backend/tests/test_workspace_files.py`

New `PUT /workspace/{agent_id}/file` endpoint that writes to either `workspaces/` or `agents/` depending on the `tab` parameter. This powers inline editing in the file viewer.

- [ ] **Step 1: Write failing tests for write endpoint**

Add to `apps/backend/tests/test_workspace_files.py`:

```python
class TestWriteFileEndpoint:
    """Tests for the _write_workspace_file helper used by PUT endpoint."""

    def test_write_workspace_file(self, tmp_path):
        """Writing a workspace file creates it on disk."""
        ws = _make_workspace(tmp_path)
        user_root = tmp_path / USER_ID
        user_root.mkdir(parents=True)
        ws_dir = user_root / "workspaces" / AGENT_ID
        ws_dir.mkdir(parents=True)

        from routers.workspace_files import _write_file
        _write_file(ws, USER_ID, AGENT_ID, "plan.md", "# My Plan", "workspace")
        assert (ws_dir / "plan.md").read_text() == "# My Plan"

    def test_write_config_file_allowlisted(self, tmp_path):
        """Writing an allowlisted config file succeeds."""
        ws = _make_workspace(tmp_path)
        agent_dir = tmp_path / USER_ID / "agents" / AGENT_ID
        agent_dir.mkdir(parents=True)

        from routers.workspace_files import _write_file
        _write_file(ws, USER_ID, AGENT_ID, "SOUL.md", "I am kind", "config")
        assert (agent_dir / "SOUL.md").read_text() == "I am kind"

    def test_write_config_file_not_allowlisted_raises(self, tmp_path):
        """Writing a non-allowlisted config file raises ValueError."""
        ws = _make_workspace(tmp_path)
        (tmp_path / USER_ID / "agents" / AGENT_ID).mkdir(parents=True)

        from routers.workspace_files import _write_file
        with pytest.raises(ValueError, match="not in allowlist"):
            _write_file(ws, USER_ID, AGENT_ID, "secret.json", "{}", "config")

    def test_write_creates_parent_dirs(self, tmp_path):
        """Writing to a nested path creates intermediate directories."""
        ws = _make_workspace(tmp_path)
        (tmp_path / USER_ID / "workspaces" / AGENT_ID).mkdir(parents=True)

        from routers.workspace_files import _write_file
        _write_file(ws, USER_ID, AGENT_ID, "deep/nested/file.txt", "hello", "workspace")
        assert (tmp_path / USER_ID / "workspaces" / AGENT_ID / "deep" / "nested" / "file.txt").read_text() == "hello"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd apps/backend && uv run pytest tests/test_workspace_files.py::TestWriteFileEndpoint -v`
Expected: FAIL — `_write_file` doesn't exist yet.

- [ ] **Step 3: Implement the write helper and endpoint**

Add to `apps/backend/routers/workspace_files.py`:

```python
from pydantic import BaseModel


class WriteFileRequest(BaseModel):
    path: str
    content: str
    tab: str  # "workspace" or "config"


def _write_file(
    workspace, owner_id: str, agent_id: str, path: str, content: str, tab: str
) -> str:
    """Write a file to workspace or config directory. Returns the written path."""
    if "/" in agent_id or "\\" in agent_id or ".." in agent_id:
        raise ValueError(f"Invalid agent_id: {agent_id!r}")

    if tab == "config":
        if path not in CONFIG_ALLOWLIST:
            raise ValueError(f"File not in allowlist: {path}")
        full_path = f"agents/{agent_id}/{path}"
    elif tab == "workspace":
        full_path = f"workspaces/{agent_id}/{path}"
    else:
        raise ValueError(f"Invalid tab: {tab!r}")

    workspace.write_file(owner_id, full_path, content)
    return full_path


@router.put("/workspace/{agent_id}/file")
async def write_workspace_file(
    agent_id: str,
    body: WriteFileRequest,
    auth: AuthContext = Depends(get_current_user),
):
    """Write a file to the agent's workspace or config directory."""
    owner_id = resolve_owner_id(auth)
    if "/" in agent_id or "\\" in agent_id or ".." in agent_id:
        raise HTTPException(status_code=400, detail="Invalid agent_id")
    if body.tab not in ("workspace", "config"):
        raise HTTPException(status_code=400, detail="tab must be 'workspace' or 'config'")

    workspace = get_workspace()
    try:
        written_path = _write_file(workspace, owner_id, agent_id, body.path, body.content, body.tab)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except WorkspaceError as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    logger.info("Wrote %s for user %s (tab=%s)", written_path, owner_id, body.tab)
    return {"status": "ok", "path": written_path}
```

Add the `BaseModel` import at the top of the file:

```python
from pydantic import BaseModel
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd apps/backend && uv run pytest tests/test_workspace_files.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add apps/backend/routers/workspace_files.py apps/backend/tests/test_workspace_files.py
git commit -m "feat(api): add PUT file write endpoint for inline editing"
```

---

### Task 3: Backend — Fix upload endpoint to write into agent workspace

**Files:**
- Modify: `apps/backend/routers/container_rpc.py`
- Modify: `apps/backend/tests/test_workspace_files.py` (add upload path test)

The upload endpoint currently writes to `uploads/{filename}` at the user root. Change it to write to `workspaces/{agent_id}/uploads/{filename}` so uploaded files appear in the Workspace tab.

- [ ] **Step 1: Write failing test for upload path change**

Add to `apps/backend/tests/test_workspace_files.py`:

```python
class TestUploadPath:
    """Verify upload destination path construction."""

    def test_upload_writes_to_agent_workspace(self, tmp_path):
        """Uploads should go to workspaces/{agent_id}/uploads/."""
        ws = _make_workspace(tmp_path)
        ws_dir = tmp_path / USER_ID / "workspaces" / AGENT_ID / "uploads"
        (tmp_path / USER_ID).mkdir(parents=True)

        dest_path = f"workspaces/{AGENT_ID}/uploads/test.pdf"
        ws.write_bytes(USER_ID, dest_path, b"fake pdf content")
        assert (ws_dir / "test.pdf").read_bytes() == b"fake pdf content"

    def test_agent_visible_path(self):
        """Agent-visible path should include workspaces/{agent_id}."""
        agent_id = "my-agent"
        filename = "data.csv"
        dest_path = f"workspaces/{agent_id}/uploads/{filename}"
        agent_path = f".openclaw/{dest_path}"
        assert agent_path == f".openclaw/workspaces/{agent_id}/uploads/{filename}"
```

- [ ] **Step 2: Run tests to verify they pass** (these test path construction, not the endpoint itself)

Run: `cd apps/backend && uv run pytest tests/test_workspace_files.py::TestUploadPath -v`
Expected: PASS (these validate the path scheme, the write_bytes already works)

- [ ] **Step 3: Modify upload endpoint to accept agent_id**

In `apps/backend/routers/container_rpc.py`, modify the `upload_files` function signature and body. Add `Query` import at the top (it's already imported from fastapi). Change:

```python
async def upload_files(
    files: List[UploadFile] = File(..., description="Files to upload"),
    agent_id: str = Query(..., description="Target agent ID"),
    auth: AuthContext = Depends(get_current_user),
):
```

Add agent_id validation after the file count check:

```python
    if "/" in agent_id or "\\" in agent_id or ".." in agent_id:
        raise HTTPException(status_code=400, detail="Invalid agent_id")
```

Change the dest_path and agent_path lines (around line 283-287):

```python
        safe_name = _sanitize_filename(f.filename or "upload")
        dest_path = f"workspaces/{agent_id}/uploads/{safe_name}"
        workspace.write_bytes(owner_id, dest_path, data)
        agent_path = f".openclaw/{dest_path}"
```

- [ ] **Step 4: Run full backend test suite**

Run: `cd apps/backend && uv run pytest tests/ -v --timeout=30`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add apps/backend/routers/container_rpc.py apps/backend/tests/test_workspace_files.py
git commit -m "fix(api): upload files to agent workspace directory instead of user root"
```

---

### Task 4: Frontend — Add config file hooks and update API client

**Files:**
- Modify: `apps/frontend/src/hooks/useWorkspaceFiles.ts`
- Modify: `apps/frontend/src/lib/api.ts`

Add SWR hooks for config file endpoints and update the API client with `agentId` on uploads and a new `saveWorkspaceFile` method.

- [ ] **Step 1: Add config file hooks to useWorkspaceFiles.ts**

Add to the bottom of `apps/frontend/src/hooks/useWorkspaceFiles.ts`:

```typescript
export function useConfigFiles(agentId: string | null) {
  const api = useApi();
  const key = agentId ? `/container/workspace/${agentId}/config-files` : null;

  const { data, error, isLoading, mutate } = useSWR<{ files: FileEntry[] }>(
    key,
    () => api.get(key!) as Promise<{ files: FileEntry[] }>,
  );

  return {
    files: data?.files ?? [],
    error,
    isLoading,
    refresh: mutate,
  };
}

export function useConfigFile(agentId: string | null, filePath: string | null) {
  const api = useApi();
  const key = agentId && filePath
    ? `/container/workspace/${agentId}/config-file?path=${encodeURIComponent(filePath)}`
    : null;

  const { data, error, isLoading } = useSWR<FileInfo>(
    key,
    () => api.get(key!) as Promise<FileInfo>,
  );

  return {
    file: data ?? null,
    error,
    isLoading,
  };
}
```

- [ ] **Step 2: Update api.ts — add agentId to uploadFiles and add saveWorkspaceFile**

In `apps/frontend/src/lib/api.ts`, update the `UploadResponse` interface area and the `ApiMethods` interface:

Add to `ApiMethods`:
```typescript
  uploadFiles: (files: File[], agentId: string) => Promise<UploadResponse>;
  saveWorkspaceFile: (agentId: string, path: string, content: string, tab: "workspace" | "config") => Promise<{ status: string; path: string }>;
```

Update the `uploadFiles` implementation to include `agentId`:

```typescript
      async uploadFiles(files: File[], agentId: string): Promise<UploadResponse> {
        const token = await getToken();
        if (!token) throw new Error("No authentication token available");

        const formData = new FormData();
        for (const file of files) {
          formData.append("files", file);
        }

        const response = await fetch(`${BACKEND_URL}/container/files?agent_id=${encodeURIComponent(agentId)}`, {
          method: "POST",
          headers: { Authorization: `Bearer ${token}` },
          body: formData,
        });

        if (!response.ok) {
          const errorData = await response.json().catch(() => ({}));
          throw new Error(errorData.detail || "Upload failed");
        }

        return response.json();
      },
```

Add `saveWorkspaceFile` method after `uploadFiles`:

```typescript
      saveWorkspaceFile(
        agentId: string,
        path: string,
        content: string,
        tab: "workspace" | "config",
      ): Promise<{ status: string; path: string }> {
        return authenticatedFetch(`/container/workspace/${encodeURIComponent(agentId)}/file`, {
          method: "PUT",
          body: JSON.stringify({ path, content, tab }),
        }) as Promise<{ status: string; path: string }>;
      },
```

- [ ] **Step 3: Update AgentChatWindow.tsx to pass agentId to uploadFiles**

In `apps/frontend/src/components/chat/AgentChatWindow.tsx`, in the `handleSend` callback (around line 448), change:

```typescript
            const result = await api.uploadFiles(files);
```

to:

```typescript
            const result = await api.uploadFiles(files, agentId!);
```

- [ ] **Step 4: Run frontend lint and type check**

Run: `cd apps/frontend && pnpm run lint && pnpm tsc --noEmit`
Expected: No errors

- [ ] **Step 5: Commit**

```bash
git add apps/frontend/src/hooks/useWorkspaceFiles.ts apps/frontend/src/lib/api.ts apps/frontend/src/components/chat/AgentChatWindow.tsx
git commit -m "feat(frontend): add config file hooks, save API, fix upload agentId"
```

---

### Task 5: Frontend — ChatInput file size validation

**Files:**
- Modify: `apps/frontend/src/components/chat/ChatInput.tsx`

Add client-side 10MB file size limit with inline error feedback.

- [ ] **Step 1: Add file size validation to ChatInput.tsx**

Add a constant and error state at the top of the `ChatInput` component:

```typescript
const MAX_FILE_SIZE = 10 * 1024 * 1024; // 10 MB
```

Inside the component, add state for size errors:

```typescript
  const [sizeError, setSizeError] = React.useState<string | null>(null);
```

Create a filter function that separates valid and oversized files:

```typescript
  const filterOversizedFiles = (files: File[]): File[] => {
    const valid: File[] = [];
    const rejected: string[] = [];
    for (const file of files) {
      if (file.size > MAX_FILE_SIZE) {
        rejected.push(file.name);
      } else {
        valid.push(file);
      }
    }
    if (rejected.length > 0) {
      setSizeError(`${rejected.join(", ")} exceed${rejected.length === 1 ? "s" : ""} the 10MB limit`);
      setTimeout(() => setSizeError(null), 5000);
    }
    return valid;
  };
```

Update `handleFileSelect` to filter:

```typescript
  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const selected = e.target.files;
    if (!selected) return;

    const valid = filterOversizedFiles(Array.from(selected));
    const newFiles: PendingFile[] = valid.map((file) => ({
      file,
      id: crypto.randomUUID(),
    }));
    setPendingFiles((prev) => [...prev, ...newFiles].slice(0, 10));

    if (fileInputRef.current) fileInputRef.current.value = "";
  };
```

Update `handleDrop` similarly:

```typescript
  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    const dropped = e.dataTransfer.files;
    if (!dropped.length) return;

    const valid = filterOversizedFiles(Array.from(dropped));
    const newFiles: PendingFile[] = valid.map((file) => ({
      file,
      id: crypto.randomUUID(),
    }));
    setPendingFiles((prev) => [...prev, ...newFiles].slice(0, 10));
  };
```

Add the error message display after the pending files list, before the input row:

```tsx
        {sizeError && (
          <div className="flex items-center gap-1.5 mb-2 px-2 py-1.5 bg-red-50 border border-red-200 rounded-lg text-xs text-red-600">
            <span>{sizeError}</span>
            <button
              type="button"
              onClick={() => setSizeError(null)}
              className="ml-auto text-red-400 hover:text-red-600"
            >
              <X className="h-3 w-3" />
            </button>
          </div>
        )}
```

- [ ] **Step 2: Run frontend lint**

Run: `cd apps/frontend && pnpm run lint`
Expected: No errors

- [ ] **Step 3: Commit**

```bash
git add apps/frontend/src/components/chat/ChatInput.tsx
git commit -m "feat(chat): add client-side 10MB file size validation"
```

---

### Task 6: Frontend — Layout transition (sidebar hides, chat compresses)

**Files:**
- Modify: `apps/frontend/src/components/chat/ChatLayout.css`
- Modify: `apps/frontend/src/components/chat/ChatLayout.tsx`

When the file viewer opens, the sidebar hides and the chat compresses to 380px. The file viewer fills the remaining space. 200ms ease transition.

- [ ] **Step 1: Update ChatLayout.css grid and transition**

Replace the existing `.app-shell` and `.app-shell.with-file-viewer` rules:

```css
.app-shell {
  display: grid;
  grid-template-columns: 260px 1fr;
  grid-template-areas: "sidebar main";
  height: 100vh;
  overflow: hidden;
  transition: grid-template-columns 200ms ease;
}
.app-shell.with-file-viewer {
  grid-template-columns: 0px 380px 1fr;
  grid-template-areas: "sidebar main viewer";
}
```

Add sidebar transition styles:

```css
.app-shell.with-file-viewer .cream-sidebar {
  overflow: hidden;
  opacity: 0;
  pointer-events: none;
  border-right: none;
  transition: opacity 150ms ease;
}
.cream-sidebar {
  /* existing styles plus: */
  transition: opacity 150ms ease;
}
```

Add the file viewer grid area:

```css
.file-viewer-panel {
  grid-area: viewer;
}
```

Update the mobile breakpoint to keep the file viewer single-column:

```css
@media (max-width: 768px) {
  .app-shell.with-file-viewer {
    grid-template-columns: 1fr;
    grid-template-areas: "viewer";
  }
  .app-shell.with-file-viewer .main-area {
    display: none;
  }
}
```

- [ ] **Step 2: Update ChatLayout.tsx grid areas**

Add `grid-area` to the sidebar div (the `cream-sidebar` element already uses the CSS class, so the grid area comes from CSS). Add `style={{ gridArea: "main" }}` to the `.main-area` div and ensure the FileViewer renders with `gridArea: "viewer"`.

In the JSX where the `main-area` div is rendered (around line 339), add:

```tsx
        <div className="main-area" style={{ gridArea: "main" }}>
```

The FileViewer component already has the `file-viewer-panel` CSS class which gets `grid-area: viewer`.

- [ ] **Step 3: Test visually**

Run: `cd apps/frontend && pnpm run dev`
Open http://localhost:3000/chat, click the folder icon. Verify:
- Sidebar slides away (opacity 0, width 0)
- Chat compresses to ~380px on the left
- File viewer fills the right
- Closing reverses the animation

- [ ] **Step 4: Commit**

```bash
git add apps/frontend/src/components/chat/ChatLayout.css apps/frontend/src/components/chat/ChatLayout.tsx
git commit -m "feat(layout): animate sidebar hide + chat compress when file viewer opens"
```

---

### Task 7: Frontend — FileViewer tabs (Workspace / Config)

**Files:**
- Modify: `apps/frontend/src/components/chat/FileViewer.tsx`
- Modify: `apps/frontend/src/components/chat/FileTree.tsx`

Add tab state to FileViewer. The header shows two underline tabs. Switching tabs swaps the data source and resets the selected file. Update FileTree empty states per tab.

- [ ] **Step 1: Add tab state and tab UI to FileViewer.tsx**

Replace the full `FileViewer` component in `apps/frontend/src/components/chat/FileViewer.tsx`:

```typescript
import { useWorkspaceTree, useWorkspaceFile, useConfigFiles, useConfigFile } from "@/hooks/useWorkspaceFiles";

type ViewerTab = "workspace" | "config";

export function FileViewer({ agentId, initialFilePath, onClose }: FileViewerProps) {
  const [activeTab, setActiveTab] = React.useState<ViewerTab>("workspace");
  const [selectedPath, setSelectedPath] = React.useState<string | null>(initialFilePath ?? null);

  const relativeFilePath = React.useMemo(() => {
    if (!selectedPath) return null;
    const prefix = `agents/${agentId}/`;
    return selectedPath.startsWith(prefix) ? selectedPath.slice(prefix.length) : selectedPath;
  }, [selectedPath, agentId]);

  // Workspace tab data
  const { files: wsFiles, isLoading: wsTreeLoading, refresh: wsRefresh } = useWorkspaceTree(agentId);
  const { file: wsFile, isLoading: wsFileLoading, error: wsFileError } = useWorkspaceFile(
    activeTab === "workspace" ? agentId : null,
    activeTab === "workspace" ? relativeFilePath : null,
  );

  // Config tab data
  const { files: cfgFiles, isLoading: cfgTreeLoading, refresh: cfgRefresh } = useConfigFiles(agentId);
  const { file: cfgFile, isLoading: cfgFileLoading, error: cfgFileError } = useConfigFile(
    activeTab === "config" ? agentId : null,
    activeTab === "config" ? relativeFilePath : null,
  );

  const files = activeTab === "workspace" ? wsFiles : cfgFiles;
  const treeLoading = activeTab === "workspace" ? wsTreeLoading : cfgTreeLoading;
  const refresh = activeTab === "workspace" ? wsRefresh : cfgRefresh;
  const file = activeTab === "workspace" ? wsFile : cfgFile;
  const fileLoading = activeTab === "workspace" ? wsFileLoading : cfgFileLoading;
  const fileError = activeTab === "workspace" ? wsFileError : cfgFileError;

  React.useEffect(() => {
    if (initialFilePath) {
      setSelectedPath(initialFilePath);
      setActiveTab("workspace"); // file path clicks are always workspace
    }
  }, [initialFilePath]);

  function handleTabChange(tab: ViewerTab) {
    setActiveTab(tab);
    setSelectedPath(null); // reset selection on tab switch
  }

  function handleCopyContent() {
    if (file?.content) {
      navigator.clipboard.writeText(file.content).catch(() => {});
    }
  }

  return (
    <div className="file-viewer-panel">
      {/* ... existing <style> block unchanged ... */}

      <div className="file-viewer-header">
        {/* Tabs */}
        <div className="flex items-center gap-1">
          <button
            onClick={() => handleTabChange("workspace")}
            className={`px-3 py-1 text-sm rounded-md transition-colors ${
              activeTab === "workspace"
                ? "bg-white text-[#1a1a1a] shadow-sm font-medium"
                : "text-[#8a8578] hover:text-[#1a1a1a]"
            }`}
          >
            Workspace
          </button>
          <button
            onClick={() => handleTabChange("config")}
            className={`px-3 py-1 text-sm rounded-md transition-colors ${
              activeTab === "config"
                ? "bg-white text-[#1a1a1a] shadow-sm font-medium"
                : "text-[#8a8578] hover:text-[#1a1a1a]"
            }`}
          >
            Config
          </button>
        </div>

        <div className="flex-1" />

        {/* File metadata + actions when a file is selected */}
        {selectedPath && file && (
          <>
            <Breadcrumbs path={relativeFilePath ?? selectedPath} onNavigate={() => {}} />
            <span className="text-xs text-[#8a8578] flex-shrink-0 ml-2">
              {formatFileSize(file.size)} · {formatDate(file.modified_at)}
            </span>
            {file.content && (
              <button onClick={handleCopyContent} className="text-[#8a8578] hover:text-[#1a1a1a] transition-colors flex-shrink-0 ml-2" title="Copy file content">
                <Copy className="h-4 w-4" />
              </button>
            )}
          </>
        )}

        <button onClick={onClose} className="text-[#8a8578] hover:text-[#1a1a1a] transition-colors flex-shrink-0 ml-2" title="Close file viewer">
          <X className="h-4 w-4" />
        </button>
      </div>

      <div className="file-viewer-body">
        <div className="file-viewer-tree">
          <FileTree
            files={files}
            selectedPath={selectedPath}
            onSelect={setSelectedPath}
            onRefresh={() => refresh()}
            isLoading={treeLoading}
            emptyMessage={
              activeTab === "workspace"
                ? "No files yet. Your agent will create files here as it works."
                : "No config files found."
            }
          />
        </div>
        <div className="file-viewer-content">
          <FileContentViewer file={file} isLoading={fileLoading} error={fileError ?? null} />
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Update FileTree to accept emptyMessage prop**

In `apps/frontend/src/components/chat/FileTree.tsx`, add `emptyMessage` to the props interface:

```typescript
interface FileTreeProps {
  files: FileEntry[];
  selectedPath: string | null;
  onSelect: (path: string) => void;
  onRefresh: () => void;
  isLoading: boolean;
  emptyMessage?: string;
}

export function FileTree({ files, selectedPath, onSelect, onRefresh, isLoading, emptyMessage }: FileTreeProps) {
```

Update the empty state in the render:

```tsx
        {files.length === 0 && !isLoading ? (
          <div className="text-xs text-[#8a8578] text-center py-4 px-3">
            {emptyMessage ?? "No files in workspace"}
          </div>
        ) : (
```

- [ ] **Step 3: Test visually**

Run: `cd apps/frontend && pnpm run dev`
Open the file viewer, verify:
- Two tabs appear in the header
- Workspace tab shows workspace files (or empty state)
- Config tab shows SOUL.md, MEMORY.md, etc. (or empty state)
- Switching tabs resets the file selection

- [ ] **Step 4: Commit**

```bash
git add apps/frontend/src/components/chat/FileViewer.tsx apps/frontend/src/components/chat/FileTree.tsx
git commit -m "feat(viewer): add Workspace and Config tabs to file viewer"
```

---

### Task 8: Frontend — Inline editing in FileContentViewer

**Files:**
- Modify: `apps/frontend/src/components/chat/FileContentViewer.tsx`
- Modify: `apps/frontend/src/components/chat/FileViewer.tsx`

Replace the read-only file content viewer with an editable textarea for text files. Add dirty tracking, save button, Cmd+S shortcut, and unsaved confirmation.

- [ ] **Step 1: Rewrite FileContentViewer.tsx for inline editing**

Replace the full content of `apps/frontend/src/components/chat/FileContentViewer.tsx`:

```typescript
"use client";

import * as React from "react";
import { Loader2, Save } from "lucide-react";
import type { FileInfo } from "@/hooks/useWorkspaceFiles";

interface FileContentViewerProps {
  file: FileInfo | null;
  isLoading: boolean;
  error: Error | null;
  onSave?: (content: string) => Promise<void>;
}

export function FileContentViewer({ file, isLoading, error, onSave }: FileContentViewerProps) {
  const [editContent, setEditContent] = React.useState("");
  const [originalContent, setOriginalContent] = React.useState("");
  const [saving, setSaving] = React.useState(false);
  const [saveError, setSaveError] = React.useState<string | null>(null);
  const textareaRef = React.useRef<HTMLTextAreaElement>(null);

  const dirty = editContent !== originalContent;

  // Sync editor content when a new file loads
  React.useEffect(() => {
    if (file?.content != null && !file.binary) {
      setEditContent(file.content);
      setOriginalContent(file.content);
      setSaveError(null);
    }
  }, [file?.path, file?.content, file?.binary]);

  // Cmd/Ctrl+S save shortcut
  const handleSaveRef = React.useRef(handleSave);
  handleSaveRef.current = handleSave;

  React.useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key === "s") {
        e.preventDefault();
        handleSaveRef.current();
      }
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, []);

  async function handleSave() {
    if (!onSave || !dirty) return;
    setSaving(true);
    setSaveError(null);
    try {
      await onSave(editContent);
      setOriginalContent(editContent);
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : "Save failed");
    } finally {
      setSaving(false);
    }
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-full text-[#8a8578]">
        <Loader2 className="h-5 w-5 animate-spin mr-2" />
        Loading file...
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center justify-center h-full text-red-500 text-sm">
        Could not load file.
      </div>
    );
  }

  if (!file) {
    return (
      <div className="flex items-center justify-center h-full text-[#8a8578] text-sm">
        Select a file to view its contents.
      </div>
    );
  }

  // Image preview (read-only)
  if (file.binary && file.mime_type.startsWith("image/") && file.content) {
    return (
      <div className="p-4 flex items-center justify-center">
        <img
          src={`data:${file.mime_type};base64,${file.content}`}
          alt={file.name}
          className="max-w-full max-h-[80vh] object-contain rounded border border-[#e0dbd0]"
        />
      </div>
    );
  }

  // Binary file (read-only)
  if (file.binary || file.content === null) {
    return (
      <div className="flex items-center justify-center h-full text-[#8a8578] text-sm">
        Binary file — preview not available.
      </div>
    );
  }

  // Editable text file
  return (
    <div className="flex flex-col h-full">
      {/* Editor toolbar */}
      <div className="flex items-center justify-between px-3 py-1.5 bg-[#f3efe6] border-b border-[#e0dbd0] flex-shrink-0">
        <span className="text-xs text-[#8a8578]">{file.name}</span>
        <div className="flex items-center gap-2">
          {dirty && <span className="text-[10px] text-amber-500 font-medium">unsaved</span>}
          {saveError && <span className="text-[10px] text-red-500">{saveError}</span>}
          <button
            onClick={handleSave}
            disabled={!dirty || saving}
            className="flex items-center gap-1 px-2 py-1 text-xs rounded bg-[#06402B] text-white hover:bg-[#0a5c3e] disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            {saving ? <Loader2 className="h-3 w-3 animate-spin" /> : <Save className="h-3 w-3" />}
            Save
          </button>
        </div>
      </div>

      {/* Editor area */}
      <textarea
        ref={textareaRef}
        value={editContent}
        onChange={(e) => setEditContent(e.target.value)}
        className="flex-1 w-full p-4 text-sm font-mono bg-white text-[#1a1a1a] resize-none focus:outline-none"
        spellCheck={false}
      />
    </div>
  );
}
```

- [ ] **Step 2: Wire onSave callback from FileViewer.tsx**

In `apps/frontend/src/components/chat/FileViewer.tsx`, import `useApi`:

```typescript
import { useApi } from "@/lib/api";
```

Inside the `FileViewer` component, add the API hook and save handler:

```typescript
  const api = useApi();

  const handleSave = React.useCallback(async (content: string) => {
    if (!agentId || !relativeFilePath) return;
    await api.saveWorkspaceFile(agentId, relativeFilePath, content, activeTab);
    // Refresh the tree to pick up size/date changes
    refresh();
  }, [agentId, relativeFilePath, activeTab, api, refresh]);
```

Pass `onSave` to `FileContentViewer`:

```tsx
          <FileContentViewer
            file={file}
            isLoading={fileLoading}
            error={fileError ?? null}
            onSave={selectedPath ? handleSave : undefined}
          />
```

- [ ] **Step 3: Test visually**

Run: `cd apps/frontend && pnpm run dev`
Open the file viewer, select a text file (e.g., SOUL.md in Config tab). Verify:
- Content appears in an editable textarea
- Editing shows "unsaved" badge
- Save button + Cmd+S both work
- After save, "unsaved" disappears
- Binary/image files remain read-only

- [ ] **Step 4: Commit**

```bash
git add apps/frontend/src/components/chat/FileContentViewer.tsx apps/frontend/src/components/chat/FileViewer.tsx
git commit -m "feat(viewer): inline editing with save for text files"
```

---

### Task 9: Integration test and final verification

**Files:**
- No new files — this is a verification task

- [ ] **Step 1: Run full backend test suite**

Run: `cd apps/backend && uv run pytest tests/ -v --timeout=30`
Expected: ALL PASS

- [ ] **Step 2: Run frontend lint and type check**

Run: `cd apps/frontend && pnpm run lint && pnpm tsc --noEmit`
Expected: No errors

- [ ] **Step 3: Run frontend unit tests**

Run: `cd apps/frontend && pnpm test`
Expected: ALL PASS

- [ ] **Step 4: Manual E2E verification**

Run: `cd apps/frontend && pnpm run dev`

Test the following scenarios:
1. **Config tab**: Open file viewer → Config tab shows SOUL.md, BOOTSTRAP.md, etc. → Click SOUL.md → Content is editable → Edit and save → Refresh shows saved content
2. **Workspace tab**: Workspace tab shows agent working files (or empty state if no files yet)
3. **Upload**: Attach a file (< 10MB) to chat → Send → File appears in Workspace tab under `uploads/`
4. **File size rejection**: Try to attach a file > 10MB → See error message → File is not added to pending list
5. **Layout animation**: Open file viewer → Sidebar slides away, chat compresses left → Close → Sidebar returns, chat expands
6. **Cmd+S**: Edit a file → Press Cmd+S → File saves without clicking button

- [ ] **Step 5: Final commit if any fixes needed**

```bash
git add -A
git commit -m "fix: address integration test feedback"
```
