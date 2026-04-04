# Workspace File Viewer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let users view files their agents create in the EFS workspace, via a split-panel file viewer triggered from chat messages or a manual button.

**Architecture:** New REST endpoints on FastAPI read from the agent's workspace on EFS (already mounted). Frontend adds a `FileViewer` panel that splits the chat layout when opened. File paths in chat messages become clickable links via a pre-processing step on markdown content.

**Tech Stack:** FastAPI (backend REST), React + Tailwind CSS (frontend), SWR (data fetching), ReactMarkdown + Prism (file rendering), lucide-react (icons)

**Spec:** `docs/superpowers/specs/2026-04-03-workspace-file-viewer-design.md`

---

## File Structure

### Backend (new/modified)

| File | Action | Responsibility |
|------|--------|---------------|
| `apps/backend/core/containers/workspace.py` | Modify | Add `list_directory()` and `read_file_info()` methods |
| `apps/backend/routers/workspace_files.py` | Create | REST endpoints for tree listing and file reading |
| `apps/backend/main.py` | Modify | Register new router |
| `apps/backend/tests/test_workspace_files.py` | Create | Tests for new endpoints |

### Frontend (new/modified)

| File | Action | Responsibility |
|------|--------|---------------|
| `apps/frontend/src/components/chat/FileViewer.tsx` | Create | Main file viewer panel (tree + content viewer) |
| `apps/frontend/src/components/chat/FileTree.tsx` | Create | Collapsible directory tree sidebar |
| `apps/frontend/src/components/chat/FileContentViewer.tsx` | Create | Rich file content renderer (markdown, code, images, CSV) |
| `apps/frontend/src/hooks/useWorkspaceFiles.ts` | Create | SWR hooks for workspace file API |
| `apps/frontend/src/lib/filePathDetection.ts` | Create | Regex-based file path detection in message content |
| `apps/frontend/src/components/chat/MessageList.tsx` | Modify | Integrate file path detection into MarkdownContent |
| `apps/frontend/src/components/chat/ChatLayout.tsx` | Modify | Add file viewer panel, grid toggle, folder button |
| `apps/frontend/src/app/chat/page.tsx` | Modify | Add file viewer state management |

---

## Task 1: Backend — Add `list_directory()` to Workspace

**Files:**
- Modify: `apps/backend/core/containers/workspace.py`
- Test: `apps/backend/tests/test_workspace_files.py`

- [ ] **Step 1: Write the failing test**

Create `apps/backend/tests/test_workspace_files.py`:

```python
"""Tests for workspace file browsing."""

import os
import tempfile
from pathlib import Path

import pytest

from core.containers.workspace import Workspace, WorkspaceError


@pytest.fixture
def workspace(tmp_path: Path) -> Workspace:
    """Create a Workspace pointing at a temp directory."""
    return Workspace(mount_path=str(tmp_path))


@pytest.fixture
def populated_workspace(workspace: Workspace, tmp_path: Path) -> Workspace:
    """Workspace with sample agent files."""
    agent_dir = tmp_path / "user123" / "agents" / "main"
    agent_dir.mkdir(parents=True)

    (agent_dir / "AGENTS.md").write_text("# Agent config")
    (agent_dir / "plan.md").write_text("# My plan")

    sub_dir = agent_dir / "isol8_agents"
    sub_dir.mkdir()
    (sub_dir / "notes.md").write_text("# Notes")

    return workspace


class TestListDirectory:
    def test_list_agent_root(self, populated_workspace: Workspace):
        entries = populated_workspace.list_directory("user123", "agents/main")
        names = {e["name"] for e in entries}
        assert "AGENTS.md" in names
        assert "plan.md" in names
        assert "isol8_agents" in names

    def test_list_subdirectory(self, populated_workspace: Workspace):
        entries = populated_workspace.list_directory("user123", "agents/main/isol8_agents")
        assert len(entries) == 1
        assert entries[0]["name"] == "notes.md"
        assert entries[0]["type"] == "file"

    def test_entry_has_required_fields(self, populated_workspace: Workspace):
        entries = populated_workspace.list_directory("user123", "agents/main")
        for entry in entries:
            assert "name" in entry
            assert "path" in entry
            assert "type" in entry
            assert entry["type"] in ("file", "dir")
            assert "size" in entry
            assert "modified_at" in entry

    def test_dirs_have_null_size(self, populated_workspace: Workspace):
        entries = populated_workspace.list_directory("user123", "agents/main")
        dir_entry = next(e for e in entries if e["name"] == "isol8_agents")
        assert dir_entry["size"] is None
        assert dir_entry["type"] == "dir"

    def test_path_traversal_blocked(self, populated_workspace: Workspace):
        with pytest.raises(WorkspaceError, match="Path traversal"):
            populated_workspace.list_directory("user123", "../../other_user")

    def test_nonexistent_directory(self, populated_workspace: Workspace):
        with pytest.raises(WorkspaceError, match="not found"):
            populated_workspace.list_directory("user123", "agents/main/nonexistent")

    def test_excludes_system_files(self, populated_workspace: Workspace, tmp_path: Path):
        agent_dir = tmp_path / "user123" / "agents" / "main"
        (agent_dir / "openclaw.json").write_text("{}")
        (agent_dir / "node_modules").mkdir()
        (agent_dir / "node_modules" / "foo.js").write_text("x")

        entries = populated_workspace.list_directory("user123", "agents/main")
        names = {e["name"] for e in entries}
        assert "openclaw.json" not in names
        assert "node_modules" not in names
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/backend && uv run pytest tests/test_workspace_files.py -v`
Expected: FAIL — `list_directory` method does not exist.

- [ ] **Step 3: Implement `list_directory` and `read_file_info`**

Add to `apps/backend/core/containers/workspace.py`, after the existing `list_agents` method:

```python
# System files/dirs to exclude from workspace browsing
_EXCLUDED_NAMES = {
    "openclaw.json",
    ".openclaw",
    "node_modules",
    "__pycache__",
    ".mcporter",
    ".git",
}

def list_directory(self, user_id: str, path: str) -> list[dict]:
    """List files and directories at a path within a user's workspace.

    Returns a flat list of entries sorted dirs-first, then alphabetically.
    Excludes system files that users shouldn't see.

    Args:
        user_id: The user whose workspace to browse.
        path: Relative path within the user's workspace directory.

    Returns:
        List of dicts with keys: name, path, type, size, modified_at.

    Raises:
        WorkspaceError: If the path escapes the user directory,
            does not exist, or is not a directory.
    """
    resolved = self._resolve_user_file(user_id, path)
    if not resolved.exists():
        raise WorkspaceError(
            f"Directory not found: {path!r}",
            user_id=user_id,
        )
    if not resolved.is_dir():
        raise WorkspaceError(
            f"Not a directory: {path!r}",
            user_id=user_id,
        )

    entries = []
    try:
        for item in resolved.iterdir():
            if item.name in _EXCLUDED_NAMES or item.name.startswith("."):
                continue
            stat = item.stat()
            entries.append({
                "name": item.name,
                "path": str(item.relative_to(self.user_path(user_id).resolve())),
                "type": "dir" if item.is_dir() else "file",
                "size": stat.st_size if item.is_file() else None,
                "modified_at": stat.st_mtime,
            })
    except OSError as exc:
        logger.error("Failed to list %r for %s: %s", path, user_id, exc)
        raise WorkspaceError(
            f"Failed to list {path!r} for {user_id}: {exc}",
            user_id=user_id,
        ) from exc

    # Sort: dirs first, then alphabetically by name
    entries.sort(key=lambda e: (0 if e["type"] == "dir" else 1, e["name"].lower()))
    return entries

def read_file_info(self, user_id: str, path: str) -> dict:
    """Read a file's content and metadata from a user's workspace.

    For text files, returns content as a UTF-8 string.
    For images, returns base64-encoded content.
    For other binary files, returns content as None.

    Args:
        user_id: The user whose workspace to read from.
        path: Relative path within the user's workspace directory.

    Returns:
        Dict with keys: name, path, size, modified_at, content,
        binary, mime_type.

    Raises:
        WorkspaceError: If the file does not exist or the path
            escapes the user directory.
    """
    import base64
    import mimetypes

    resolved = self._resolve_user_file(user_id, path)
    if not resolved.exists():
        raise WorkspaceError(
            f"File not found: {path!r}",
            user_id=user_id,
        )
    if not resolved.is_file():
        raise WorkspaceError(
            f"Not a file: {path!r}",
            user_id=user_id,
        )

    stat = resolved.stat()
    mime_type = mimetypes.guess_type(resolved.name)[0] or "application/octet-stream"
    is_image = mime_type.startswith("image/")

    # Text file extensions
    text_extensions = {
        ".md", ".txt", ".py", ".js", ".ts", ".tsx", ".jsx",
        ".json", ".yaml", ".yml", ".toml", ".sh", ".bash",
        ".css", ".html", ".xml", ".csv", ".sql", ".rs",
        ".go", ".java", ".c", ".cpp", ".h", ".hpp",
        ".rb", ".php", ".swift", ".kt", ".r", ".lua",
        ".env", ".cfg", ".ini", ".conf", ".log",
    }
    is_text = resolved.suffix.lower() in text_extensions

    content = None
    binary = True

    try:
        if is_text:
            content = resolved.read_text(encoding="utf-8")
            binary = False
        elif is_image:
            raw = resolved.read_bytes()
            content = base64.b64encode(raw).decode("ascii")
            binary = True
    except (OSError, UnicodeDecodeError) as exc:
        logger.error("Failed to read %r for %s: %s", path, user_id, exc)
        content = None
        binary = True

    return {
        "name": resolved.name,
        "path": str(resolved.relative_to(self.user_path(user_id).resolve())),
        "size": stat.st_size,
        "modified_at": stat.st_mtime,
        "content": content,
        "binary": binary,
        "mime_type": mime_type,
    }
```

- [ ] **Step 4: Add tests for `read_file_info`**

Append to `apps/backend/tests/test_workspace_files.py`:

```python
class TestReadFileInfo:
    def test_read_text_file(self, populated_workspace: Workspace):
        info = populated_workspace.read_file_info("user123", "agents/main/plan.md")
        assert info["name"] == "plan.md"
        assert info["content"] == "# My plan"
        assert info["binary"] is False
        assert info["mime_type"] == "text/markdown"

    def test_read_image_file(self, populated_workspace: Workspace, tmp_path: Path):
        agent_dir = tmp_path / "user123" / "agents" / "main"
        # Write a minimal 1x1 PNG
        import base64
        png_bytes = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
        )
        (agent_dir / "test.png").write_bytes(png_bytes)

        info = populated_workspace.read_file_info("user123", "agents/main/test.png")
        assert info["name"] == "test.png"
        assert info["binary"] is True
        assert info["mime_type"] == "image/png"
        assert info["content"] is not None  # base64 encoded

    def test_read_binary_file(self, populated_workspace: Workspace, tmp_path: Path):
        agent_dir = tmp_path / "user123" / "agents" / "main"
        (agent_dir / "data.bin").write_bytes(b"\x00\x01\x02\x03")

        info = populated_workspace.read_file_info("user123", "agents/main/data.bin")
        assert info["binary"] is True
        assert info["content"] is None  # not served

    def test_path_traversal_blocked(self, populated_workspace: Workspace):
        with pytest.raises(WorkspaceError, match="Path traversal"):
            populated_workspace.read_file_info("user123", "../../etc/passwd")

    def test_nonexistent_file(self, populated_workspace: Workspace):
        with pytest.raises(WorkspaceError, match="not found"):
            populated_workspace.read_file_info("user123", "agents/main/nope.txt")
```

- [ ] **Step 5: Run all tests to verify they pass**

Run: `cd apps/backend && uv run pytest tests/test_workspace_files.py -v`
Expected: All tests PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/backend/core/containers/workspace.py apps/backend/tests/test_workspace_files.py
git commit -m "feat: add list_directory and read_file_info to workspace module"
```

---

## Task 2: Backend — REST Endpoints for Workspace Files

**Files:**
- Create: `apps/backend/routers/workspace_files.py`
- Modify: `apps/backend/main.py`

- [ ] **Step 1: Create the router**

Create `apps/backend/routers/workspace_files.py`:

```python
"""REST endpoints for browsing agent workspace files on EFS."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query

from core.auth import AuthContext, get_current_user, resolve_owner_id
from core.containers import get_workspace
from core.containers.workspace import WorkspaceError

logger = logging.getLogger(__name__)

router = APIRouter()


def _agent_workspace_path(owner_id: str, agent_id: str) -> str:
    """Build the relative path to an agent's workspace within the user dir."""
    # Validate agent_id doesn't contain path separators
    if "/" in agent_id or "\\" in agent_id or ".." in agent_id:
        raise HTTPException(status_code=400, detail="Invalid agent_id")
    return f"agents/{agent_id}"


@router.get("/workspace/{agent_id}/tree")
async def list_workspace_tree(
    agent_id: str,
    path: str = Query("", description="Subdirectory path relative to agent workspace"),
    auth: AuthContext = Depends(get_current_user),
):
    """List files and directories in an agent's workspace.

    Returns a flat list of entries. The frontend builds the tree structure.
    """
    owner_id = resolve_owner_id(auth)
    workspace = get_workspace()

    agent_base = _agent_workspace_path(owner_id, agent_id)
    full_path = f"{agent_base}/{path}" if path else agent_base

    try:
        entries = workspace.list_directory(owner_id, full_path)
    except WorkspaceError as exc:
        if "not found" in str(exc).lower():
            raise HTTPException(status_code=404, detail=str(exc))
        if "traversal" in str(exc).lower():
            raise HTTPException(status_code=403, detail="Access denied")
        raise HTTPException(status_code=500, detail=str(exc))

    return {"files": entries}


@router.get("/workspace/{agent_id}/file")
async def read_workspace_file(
    agent_id: str,
    path: str = Query(..., description="File path relative to agent workspace"),
    auth: AuthContext = Depends(get_current_user),
):
    """Read a file's content and metadata from an agent's workspace."""
    owner_id = resolve_owner_id(auth)
    workspace = get_workspace()

    agent_base = _agent_workspace_path(owner_id, agent_id)
    full_path = f"{agent_base}/{path}"

    try:
        info = workspace.read_file_info(owner_id, full_path)
    except WorkspaceError as exc:
        if "not found" in str(exc).lower():
            raise HTTPException(status_code=404, detail=str(exc))
        if "traversal" in str(exc).lower():
            raise HTTPException(status_code=403, detail="Access denied")
        raise HTTPException(status_code=500, detail=str(exc))

    return info
```

- [ ] **Step 2: Register the router in `main.py`**

Add import and `include_router` to `apps/backend/main.py`. Find the block of router imports and add:

```python
from routers import workspace_files
```

Find the block of `app.include_router(...)` calls and add:

```python
app.include_router(workspace_files.router, prefix="/api/v1/container", tags=["container"])
```

- [ ] **Step 3: Verify the server starts**

Run: `cd apps/backend && uv run uvicorn main:app --port 8000` and verify no import errors.
Check: `curl http://localhost:8000/docs` shows the new endpoints under the "container" tag.

- [ ] **Step 4: Commit**

```bash
git add apps/backend/routers/workspace_files.py apps/backend/main.py
git commit -m "feat: add REST endpoints for workspace file browsing"
```

---

## Task 3: Frontend — Workspace Files Hook

**Files:**
- Create: `apps/frontend/src/hooks/useWorkspaceFiles.ts`

- [ ] **Step 1: Create the SWR-based hook**

Create `apps/frontend/src/hooks/useWorkspaceFiles.ts`:

```typescript
"use client";

import useSWR from "swr";
import { useApi } from "@/lib/api";
import { useCallback } from "react";

export interface FileEntry {
  name: string;
  path: string;
  type: "file" | "dir";
  size: number | null;
  modified_at: number;
}

export interface FileInfo {
  name: string;
  path: string;
  size: number;
  modified_at: number;
  content: string | null;
  binary: boolean;
  mime_type: string;
}

export function useWorkspaceTree(agentId: string | null, subPath: string = "") {
  const api = useApi();
  const key = agentId ? `/container/workspace/${agentId}/tree${subPath ? `?path=${encodeURIComponent(subPath)}` : ""}` : null;

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

export function useWorkspaceFile(agentId: string | null, filePath: string | null) {
  const api = useApi();
  const key = agentId && filePath
    ? `/container/workspace/${agentId}/file?path=${encodeURIComponent(filePath)}`
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

- [ ] **Step 2: Commit**

```bash
git add apps/frontend/src/hooks/useWorkspaceFiles.ts
git commit -m "feat: add useWorkspaceFiles hooks for file tree and content"
```

---

## Task 4: Frontend — File Path Detection

**Files:**
- Create: `apps/frontend/src/lib/filePathDetection.ts`

- [ ] **Step 1: Create the detection module**

Create `apps/frontend/src/lib/filePathDetection.ts`:

```typescript
/**
 * Detects file paths in agent message content and wraps them
 * in a custom markdown link format that the chat UI can intercept.
 *
 * Uses the custom scheme `isol8-file://` so the link renderer
 * can distinguish workspace file links from regular URLs.
 */

// Matches paths like: path/to/file.ext or ./path/to/file.ext
// Must contain at least one slash and end with a file extension.
// Excludes URLs (http://, https://), package refs (@foo/bar), and common false positives.
const FILE_PATH_REGEX = /(?<![a-zA-Z]:\/\/|@)(?:\.\/)?(?:[a-zA-Z0-9_-]+\/)+[a-zA-Z0-9_.-]+\.[a-zA-Z0-9]{1,10}/g;

// Extensions that are almost certainly files, not package names or URLs
const FILE_EXTENSIONS = new Set([
  "md", "txt", "py", "js", "ts", "tsx", "jsx", "json", "yaml", "yml",
  "toml", "sh", "bash", "css", "html", "xml", "csv", "sql", "rs",
  "go", "java", "c", "cpp", "h", "hpp", "rb", "php", "swift", "kt",
  "r", "lua", "env", "cfg", "ini", "conf", "log", "png", "jpg",
  "jpeg", "gif", "svg", "webp", "pdf",
]);

/**
 * Pre-processes message content to convert detected file paths
 * into clickable markdown links with the isol8-file:// scheme.
 *
 * Example:
 *   "Plan written to isol8_agents/plan.md"
 *   → "Plan written to [isol8_agents/plan.md](isol8-file://isol8_agents/plan.md)"
 */
export function linkifyFilePaths(content: string): string {
  return content.replace(FILE_PATH_REGEX, (match) => {
    const ext = match.split(".").pop()?.toLowerCase();
    if (!ext || !FILE_EXTENSIONS.has(ext)) {
      return match;
    }
    // Don't double-wrap if already inside a markdown link
    // Check if the match is preceded by ]( which means it's already a link target
    return `[${match}](isol8-file://${match})`;
  });
}

/**
 * Checks if a URL uses the isol8-file:// scheme.
 */
export function isWorkspaceFileLink(href: string): boolean {
  return href.startsWith("isol8-file://");
}

/**
 * Extracts the file path from an isol8-file:// URL.
 */
export function extractFilePath(href: string): string {
  return href.replace("isol8-file://", "");
}
```

- [ ] **Step 2: Commit**

```bash
git add apps/frontend/src/lib/filePathDetection.ts
git commit -m "feat: add file path detection for chat messages"
```

---

## Task 5: Frontend — FileContentViewer Component

**Files:**
- Create: `apps/frontend/src/components/chat/FileContentViewer.tsx`

- [ ] **Step 1: Create the component**

Create `apps/frontend/src/components/chat/FileContentViewer.tsx`:

```tsx
"use client";

import * as React from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { oneDark } from "react-syntax-highlighter/dist/esm/styles/prism";
import { Copy, Loader2 } from "lucide-react";
import type { FileInfo } from "@/hooks/useWorkspaceFiles";

// Map file extensions to Prism language names
const LANGUAGE_MAP: Record<string, string> = {
  py: "python", js: "javascript", ts: "typescript", tsx: "tsx", jsx: "jsx",
  json: "json", yaml: "yaml", yml: "yaml", toml: "toml", sh: "bash",
  bash: "bash", css: "css", html: "html", xml: "xml", sql: "sql",
  rs: "rust", go: "go", java: "java", c: "c", cpp: "cpp", h: "c",
  hpp: "cpp", rb: "ruby", php: "php", swift: "swift", kt: "kotlin",
  r: "r", lua: "lua",
};

function CsvTable({ content }: { content: string }) {
  const rows = content.trim().split("\n").map((row) => row.split(","));
  if (rows.length === 0) return null;

  const headers = rows[0];
  const body = rows.slice(1);

  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse border border-[#e0dbd0] text-sm">
        <thead className="bg-[#f3efe6]">
          <tr>
            {headers.map((h, i) => (
              <th key={i} className="border border-[#e0dbd0] px-3 py-2 text-left font-medium">
                {h.trim()}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {body.map((row, ri) => (
            <tr key={ri} className="even:bg-[#f3efe6]">
              {row.map((cell, ci) => (
                <td key={ci} className="border border-[#e0dbd0] px-3 py-2">
                  {cell.trim()}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

interface FileContentViewerProps {
  file: FileInfo | null;
  isLoading: boolean;
  error: Error | null;
}

export function FileContentViewer({ file, isLoading, error }: FileContentViewerProps) {
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

  if (file.binary || file.content === null) {
    return (
      <div className="flex items-center justify-center h-full text-[#8a8578] text-sm">
        Binary file — preview not available.
      </div>
    );
  }

  const ext = file.name.split(".").pop()?.toLowerCase() ?? "";

  // CSV → table
  if (ext === "csv") {
    return (
      <div className="p-4 overflow-auto h-full">
        <CsvTable content={file.content} />
      </div>
    );
  }

  // Markdown → rendered
  if (ext === "md") {
    return (
      <div className="p-6 prose prose-sm max-w-none overflow-auto h-full">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>
          {file.content}
        </ReactMarkdown>
      </div>
    );
  }

  // Code → syntax highlighted
  const language = LANGUAGE_MAP[ext];
  if (language) {
    return (
      <div className="overflow-auto h-full">
        <div className="flex items-center justify-between px-4 py-2 bg-[#f3efe6] border-b border-[#e0dbd0]">
          <span className="text-xs text-[#8a8578]">{language}</span>
          <button
            onClick={() => { navigator.clipboard.writeText(file.content!).catch(() => {}); }}
            className="text-xs text-[#8a8578] hover:text-[#1a1a1a] transition-colors flex items-center gap-1"
          >
            <Copy className="h-3 w-3" />
            Copy
          </button>
        </div>
        <SyntaxHighlighter
          style={oneDark}
          language={language}
          PreTag="div"
          customStyle={{ margin: 0, borderRadius: 0, background: "#f8f5f0" }}
        >
          {file.content}
        </SyntaxHighlighter>
      </div>
    );
  }

  // Fallback → plain text
  return (
    <div className="p-4 overflow-auto h-full">
      <pre className="text-sm font-mono whitespace-pre-wrap text-[#1a1a1a]">
        {file.content}
      </pre>
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add apps/frontend/src/components/chat/FileContentViewer.tsx
git commit -m "feat: add FileContentViewer with rich preview support"
```

---

## Task 6: Frontend — FileTree Component

**Files:**
- Create: `apps/frontend/src/components/chat/FileTree.tsx`

- [ ] **Step 1: Create the component**

Create `apps/frontend/src/components/chat/FileTree.tsx`:

```tsx
"use client";

import * as React from "react";
import {
  ChevronRight, ChevronDown, FileText, FileCode, FileImage,
  FileJson, File, FolderOpen, FolderClosed, RefreshCw,
} from "lucide-react";
import type { FileEntry } from "@/hooks/useWorkspaceFiles";

const ICON_MAP: Record<string, React.ComponentType<{ className?: string }>> = {
  md: FileText, txt: FileText, log: FileText,
  py: FileCode, js: FileCode, ts: FileCode, tsx: FileCode, jsx: FileCode,
  sh: FileCode, bash: FileCode, rs: FileCode, go: FileCode, java: FileCode,
  c: FileCode, cpp: FileCode, rb: FileCode, php: FileCode, swift: FileCode,
  json: FileJson, yaml: FileJson, yml: FileJson, toml: FileJson,
  png: FileImage, jpg: FileImage, jpeg: FileImage, gif: FileImage,
  svg: FileImage, webp: FileImage,
};

function getFileIcon(name: string): React.ComponentType<{ className?: string }> {
  const ext = name.split(".").pop()?.toLowerCase() ?? "";
  return ICON_MAP[ext] ?? File;
}

interface FileTreeNodeProps {
  entry: FileEntry;
  allEntries: FileEntry[];
  selectedPath: string | null;
  onSelect: (path: string) => void;
}

function FileTreeNode({ entry, allEntries, selectedPath, onSelect }: FileTreeNodeProps) {
  const [expanded, setExpanded] = React.useState(false);

  if (entry.type === "dir") {
    const children = allEntries.filter((e) => {
      const parentPath = entry.path + "/";
      return e.path.startsWith(parentPath) && !e.path.slice(parentPath.length).includes("/");
    });

    return (
      <div>
        <button
          onClick={() => setExpanded(!expanded)}
          className="w-full flex items-center gap-1.5 px-2 py-1 text-sm text-[#1a1a1a] hover:bg-[#e8e3d9] rounded transition-colors"
        >
          {expanded ? <ChevronDown className="h-3.5 w-3.5 text-[#8a8578] flex-shrink-0" /> : <ChevronRight className="h-3.5 w-3.5 text-[#8a8578] flex-shrink-0" />}
          {expanded ? <FolderOpen className="h-4 w-4 text-[#8a8578] flex-shrink-0" /> : <FolderClosed className="h-4 w-4 text-[#8a8578] flex-shrink-0" />}
          <span className="truncate">{entry.name}</span>
        </button>
        {expanded && (
          <div className="pl-4">
            {children.map((child) => (
              <FileTreeNode
                key={child.path}
                entry={child}
                allEntries={allEntries}
                selectedPath={selectedPath}
                onSelect={onSelect}
              />
            ))}
          </div>
        )}
      </div>
    );
  }

  const Icon = getFileIcon(entry.name);
  const isSelected = selectedPath === entry.path;

  return (
    <button
      onClick={() => onSelect(entry.path)}
      className={`w-full flex items-center gap-1.5 px-2 py-1 text-sm rounded transition-colors ${
        isSelected
          ? "bg-white text-[#1a1a1a] shadow-sm"
          : "text-[#1a1a1a] hover:bg-[#e8e3d9]"
      }`}
    >
      <span className="w-3.5 flex-shrink-0" /> {/* Indent to align with folder chevrons */}
      <Icon className="h-4 w-4 text-[#8a8578] flex-shrink-0" />
      <span className="truncate">{entry.name}</span>
    </button>
  );
}

interface FileTreeProps {
  files: FileEntry[];
  selectedPath: string | null;
  onSelect: (path: string) => void;
  onRefresh: () => void;
  isLoading: boolean;
}

export function FileTree({ files, selectedPath, onSelect, onRefresh, isLoading }: FileTreeProps) {
  // Only show root-level entries (no slash in path, or path matches a direct child)
  const rootEntries = files.filter((e) => !e.path.includes("/") ||
    e.path.split("/").length === (files[0]?.path.split("/")[0] === e.path.split("/")[0] ? e.path.split("/").length : 1)
  );

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
          <div className="text-xs text-[#8a8578] text-center py-4">No files in workspace</div>
        ) : (
          files
            .filter((e) => {
              // Show only top-level entries (entries whose path segments match the minimum depth)
              const basePath = files[0]?.path.split("/").slice(0, -1).join("/");
              const relativePath = basePath ? e.path.slice(basePath.length + 1) : e.path;
              return !relativePath.includes("/");
            })
            .map((entry) => (
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

- [ ] **Step 2: Commit**

```bash
git add apps/frontend/src/components/chat/FileTree.tsx
git commit -m "feat: add FileTree component with collapsible directories"
```

---

## Task 7: Frontend — FileViewer Panel (Main Container)

**Files:**
- Create: `apps/frontend/src/components/chat/FileViewer.tsx`

- [ ] **Step 1: Create the component**

Create `apps/frontend/src/components/chat/FileViewer.tsx`:

```tsx
"use client";

import * as React from "react";
import { X, Copy, FolderOpen } from "lucide-react";
import { FileTree } from "@/components/chat/FileTree";
import { FileContentViewer } from "@/components/chat/FileContentViewer";
import { useWorkspaceTree, useWorkspaceFile } from "@/hooks/useWorkspaceFiles";

interface FileViewerProps {
  agentId: string | null;
  initialFilePath?: string | null;
  onClose: () => void;
}

function Breadcrumbs({ path, onNavigate }: { path: string; onNavigate: (segment: string) => void }) {
  const segments = path.split("/");
  return (
    <div className="flex items-center gap-1 text-sm text-[#8a8578] min-w-0">
      {segments.map((segment, i) => (
        <React.Fragment key={i}>
          {i > 0 && <span className="text-[#cdc7ba]">/</span>}
          <button
            onClick={() => onNavigate(segments.slice(0, i + 1).join("/"))}
            className="hover:text-[#1a1a1a] transition-colors truncate"
          >
            {segment}
          </button>
        </React.Fragment>
      ))}
    </div>
  );
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatDate(timestamp: number): string {
  return new Date(timestamp * 1000).toLocaleString();
}

export function FileViewer({ agentId, initialFilePath, onClose }: FileViewerProps) {
  const [selectedPath, setSelectedPath] = React.useState<string | null>(initialFilePath ?? null);

  // Strip the "agents/{agentId}/" prefix from paths for the API
  // The tree API returns paths relative to the user root (e.g., "agents/main/plan.md")
  // but our file API expects paths relative to the agent workspace
  const relativeFilePath = React.useMemo(() => {
    if (!selectedPath) return null;
    const prefix = `agents/${agentId}/`;
    return selectedPath.startsWith(prefix) ? selectedPath.slice(prefix.length) : selectedPath;
  }, [selectedPath, agentId]);

  const { files, isLoading: treeLoading, refresh } = useWorkspaceTree(agentId);
  const { file, isLoading: fileLoading, error: fileError } = useWorkspaceFile(agentId, relativeFilePath);

  // Auto-select initial file path when it changes
  React.useEffect(() => {
    if (initialFilePath) {
      setSelectedPath(initialFilePath);
    }
  }, [initialFilePath]);

  function handleCopyContent() {
    if (file?.content) {
      navigator.clipboard.writeText(file.content).catch(() => {});
    }
  }

  return (
    <div className="file-viewer-panel">
      <style>{`
        .file-viewer-panel {
          display: flex;
          flex-direction: column;
          height: 100%;
          background: #faf7f2;
          border-left: 1px solid #e0dbd0;
        }
        .file-viewer-header {
          display: flex;
          align-items: center;
          gap: 12px;
          padding: 0 16px;
          height: 56px;
          border-bottom: 1px solid #e0dbd0;
          background: #faf7f2;
          flex-shrink: 0;
        }
        .file-viewer-body {
          display: flex;
          flex: 1;
          min-height: 0;
        }
        .file-viewer-tree {
          width: 220px;
          border-right: 1px solid #e0dbd0;
          flex-shrink: 0;
          overflow: hidden;
        }
        .file-viewer-content {
          flex: 1;
          min-width: 0;
          overflow: hidden;
        }
      `}</style>

      {/* Header */}
      <div className="file-viewer-header">
        <FolderOpen className="h-4 w-4 text-[#8a8578] flex-shrink-0" />
        {selectedPath ? (
          <>
            <Breadcrumbs
              path={relativeFilePath ?? selectedPath}
              onNavigate={() => {}}
            />
            <div className="flex-1" />
            {file && (
              <span className="text-xs text-[#8a8578] flex-shrink-0">
                {formatFileSize(file.size)} · {formatDate(file.modified_at)}
              </span>
            )}
            {file?.content && (
              <button
                onClick={handleCopyContent}
                className="text-[#8a8578] hover:text-[#1a1a1a] transition-colors flex-shrink-0"
                title="Copy file content"
              >
                <Copy className="h-4 w-4" />
              </button>
            )}
          </>
        ) : (
          <>
            <span className="text-sm text-[#8a8578]">Workspace</span>
            <div className="flex-1" />
          </>
        )}
        <button
          onClick={onClose}
          className="text-[#8a8578] hover:text-[#1a1a1a] transition-colors flex-shrink-0"
          title="Close file viewer"
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      {/* Body */}
      <div className="file-viewer-body">
        <div className="file-viewer-tree">
          <FileTree
            files={files}
            selectedPath={selectedPath}
            onSelect={setSelectedPath}
            onRefresh={() => refresh()}
            isLoading={treeLoading}
          />
        </div>
        <div className="file-viewer-content">
          <FileContentViewer
            file={file}
            isLoading={fileLoading}
            error={fileError ?? null}
          />
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add apps/frontend/src/components/chat/FileViewer.tsx
git commit -m "feat: add FileViewer panel combining tree and content viewer"
```

---

## Task 8: Frontend — Integrate FileViewer into ChatLayout

**Files:**
- Modify: `apps/frontend/src/app/chat/page.tsx`
- Modify: `apps/frontend/src/components/chat/ChatLayout.tsx`
- Modify: `apps/frontend/src/components/chat/MessageList.tsx`

- [ ] **Step 1: Add file viewer state to `page.tsx`**

In `apps/frontend/src/app/chat/page.tsx`, add state for the file viewer:

Add to imports:
```typescript
import { useCallback } from "react";
```

Add state after the existing `useState` hooks (after `activePanel`):
```typescript
const [fileViewerOpen, setFileViewerOpen] = useState(false);
const [activeFilePath, setActiveFilePath] = useState<string | null>(null);

const handleOpenFile = useCallback((path: string) => {
  setActiveFilePath(path);
  setFileViewerOpen(true);
}, []);

const handleCloseFileViewer = useCallback(() => {
  setFileViewerOpen(false);
  setActiveFilePath(null);
}, []);
```

Add new props to the `ChatLayout` component:
```tsx
<ChatLayout
  activeView={activeView}
  onViewChange={setActiveView}
  activePanel={activePanel}
  onPanelChange={setActivePanel}
  fileViewerOpen={fileViewerOpen}
  activeFilePath={activeFilePath}
  onOpenFile={handleOpenFile}
  onCloseFileViewer={handleCloseFileViewer}
>
```

Pass `onOpenFile` to `AgentChatWindow`:
```tsx
<AgentChatWindow key={selectedAgentId} agentId={selectedAgentId} onOpenFile={handleOpenFile} />
```

- [ ] **Step 2: Update `ChatLayout` props and grid**

In `apps/frontend/src/components/chat/ChatLayout.tsx`:

Add to imports:
```typescript
import { Settings, Plus, Bot, CheckCircle, CreditCard, Menu, X, FolderOpen } from "lucide-react";
import { FileViewer } from "@/components/chat/FileViewer";
```

Update the `ChatLayoutProps` interface:
```typescript
interface ChatLayoutProps {
  children: React.ReactNode;
  activeView: "chat" | "control";
  onViewChange: (view: "chat" | "control") => void;
  activePanel?: string;
  onPanelChange?: (panel: string) => void;
  fileViewerOpen?: boolean;
  activeFilePath?: string | null;
  onOpenFile?: (path: string) => void;
  onCloseFileViewer?: () => void;
}
```

Destructure the new props in the component function.

Update the `.app-shell` CSS to conditionally use a 3-column grid. Replace the existing `.app-shell` style:
```css
.app-shell {
  display: grid;
  grid-template-columns: 260px 1fr;
  height: 100vh;
  overflow: hidden;
}
.app-shell.with-file-viewer {
  grid-template-columns: 260px 1fr 1fr;
}
```

Apply the class conditionally on the div:
```tsx
<div className={`app-shell${fileViewerOpen ? " with-file-viewer" : ""}`}>
```

Add the folder button to `.main-header`, before the `<div style={{ flex: 1 }} />`:
```tsx
<button
  className="mobile-hamburger"
  onClick={() => setSidebarOpen(true)}
  aria-label="Open menu"
>
  <Menu size={22} />
</button>
{onOpenFile && (
  <button
    onClick={() => onOpenFile?.("")}
    className="flex items-center justify-center text-[#8a8578] hover:text-[#1a1a1a] transition-colors p-1"
    title="Browse workspace files"
  >
    <FolderOpen size={18} />
  </button>
)}
<div style={{ flex: 1 }} />
```

Note: when `onOpenFile` is called with `""`, this opens the file viewer without a selected file (browse mode).

Add the `FileViewer` panel after the `.main-area` div, inside `.app-shell`:
```tsx
{fileViewerOpen && (
  <FileViewer
    agentId={currentAgentId}
    initialFilePath={activeFilePath}
    onClose={() => onCloseFileViewer?.()}
  />
)}
```

Also update the mobile media query to handle the file viewer:
```css
@media (max-width: 768px) {
  .app-shell.with-file-viewer {
    grid-template-columns: 1fr;
  }
}
```

- [ ] **Step 3: Integrate file path detection into `MessageList.tsx`**

In `apps/frontend/src/components/chat/MessageList.tsx`:

Add import:
```typescript
import { linkifyFilePaths, isWorkspaceFileLink, extractFilePath } from "@/lib/filePathDetection";
```

Update `MessageListProps` to include the callback:
```typescript
interface MessageListProps {
  messages: Message[];
  isTyping?: boolean;
  onRetry?: (assistantMsgId: string) => void;
  onOpenFile?: (path: string) => void;
}
```

Update the `MarkdownContent` component to accept and use `onOpenFile`:
```typescript
const MarkdownContent = React.memo(function MarkdownContent({
  content,
  onOpenFile,
}: {
  content: string;
  onOpenFile?: (path: string) => void;
}) {
  const processedContent = React.useMemo(() => linkifyFilePaths(content), [content]);

  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      components={{
        // ... keep all existing components ...
        a: ({ href, children }) => {
          if (href && isWorkspaceFileLink(href) && onOpenFile) {
            const filePath = extractFilePath(href);
            return (
              <button
                onClick={() => onOpenFile(filePath)}
                className="text-[#06402B] hover:underline cursor-pointer bg-transparent border-none p-0 font-inherit text-inherit inline"
              >
                {children}
              </button>
            );
          }
          const isSafe = !href?.match(/^(javascript|data|vbscript):/i);
          return (
            <a href={isSafe ? href : '#'} target="_blank" rel="noopener noreferrer" className="text-[#06402B] hover:underline">
              {children}
            </a>
          );
        },
        // ... rest of components unchanged ...
      }}
    >
      {processedContent}
    </ReactMarkdown>
  );
});
```

Pass `onOpenFile` through the message rendering — find where `MarkdownContent` is used and pass the prop:
```tsx
<MarkdownContent content={msg.content} onOpenFile={onOpenFile} />
```

- [ ] **Step 4: Wire `onOpenFile` through `AgentChatWindow`**

In `apps/frontend/src/components/chat/AgentChatWindow.tsx`, add `onOpenFile` to the component props and pass it to `MessageList`:

```typescript
interface AgentChatWindowProps {
  agentId: string | null;
  onOpenFile?: (path: string) => void;
}
```

Pass to `MessageList`:
```tsx
<MessageList messages={messages} isTyping={isStreaming} onRetry={handleRetry} onOpenFile={onOpenFile} />
```

- [ ] **Step 5: Verify the build compiles**

Run: `cd apps/frontend && pnpm run build`
Expected: Build succeeds with no TypeScript errors.

- [ ] **Step 6: Commit**

```bash
git add apps/frontend/src/app/chat/page.tsx apps/frontend/src/components/chat/ChatLayout.tsx apps/frontend/src/components/chat/MessageList.tsx apps/frontend/src/components/chat/AgentChatWindow.tsx
git commit -m "feat: integrate file viewer into chat layout with file path detection"
```

---

## Task 9: Frontend — Handle FileTree Root Entries Correctly

The `useWorkspaceTree` hook returns entries with paths relative to the user's root (e.g., `agents/main/plan.md`). The `FileTree` component needs to correctly identify root-level entries by stripping the agent workspace prefix.

**Files:**
- Modify: `apps/frontend/src/components/chat/FileTree.tsx`
- Modify: `apps/frontend/src/hooks/useWorkspaceFiles.ts`

- [ ] **Step 1: Update `useWorkspaceTree` to accept a recursive flag**

In `apps/frontend/src/hooks/useWorkspaceFiles.ts`, the tree endpoint currently returns a flat list for one directory level. To build a full tree, we need to either:
- Make the backend return a recursive listing, or
- Have the frontend fetch subdirectories lazily

For v1 simplicity, update the backend `list_directory` to support a `recursive=true` query param.

Add to `apps/backend/routers/workspace_files.py` in the `list_workspace_tree` endpoint:

```python
@router.get("/workspace/{agent_id}/tree")
async def list_workspace_tree(
    agent_id: str,
    path: str = Query("", description="Subdirectory path relative to agent workspace"),
    recursive: bool = Query(False, description="List all files recursively"),
    auth: AuthContext = Depends(get_current_user),
):
```

And in the handler, if `recursive=True`, walk the directory tree:

```python
    if recursive:
        all_entries = []
        _collect_recursive(workspace, owner_id, full_path, all_entries)
        return {"files": all_entries}
    else:
        entries = workspace.list_directory(owner_id, full_path)
        return {"files": entries}
```

Add the helper function to the same file:

```python
def _collect_recursive(workspace, owner_id: str, path: str, entries: list, max_depth: int = 10):
    """Recursively collect file entries up to max_depth."""
    if max_depth <= 0:
        return
    try:
        items = workspace.list_directory(owner_id, path)
    except WorkspaceError:
        return
    for item in items:
        entries.append(item)
        if item["type"] == "dir":
            _collect_recursive(workspace, owner_id, item["path"], entries, max_depth - 1)
```

- [ ] **Step 2: Update the frontend hook to use recursive**

In `apps/frontend/src/hooks/useWorkspaceFiles.ts`, update `useWorkspaceTree`:

```typescript
export function useWorkspaceTree(agentId: string | null) {
  const api = useApi();
  const key = agentId ? `/container/workspace/${agentId}/tree?recursive=true` : null;

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
```

- [ ] **Step 3: Simplify FileTree root detection**

In `apps/frontend/src/components/chat/FileTree.tsx`, replace the root entry filtering logic. Since the recursive tree returns entries with full paths like `agents/main/plan.md`, `agents/main/subdir/file.txt`, we need to find entries at the shallowest depth:

```typescript
export function FileTree({ files, selectedPath, onSelect, onRefresh, isLoading }: FileTreeProps) {
  // Find the common prefix (e.g., "agents/main") and show only direct children
  const rootEntries = React.useMemo(() => {
    if (files.length === 0) return [];
    // Find minimum depth
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
          <div className="text-xs text-[#8a8578] text-center py-4">No files in workspace</div>
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

- [ ] **Step 4: Commit**

```bash
git add apps/backend/routers/workspace_files.py apps/frontend/src/hooks/useWorkspaceFiles.ts apps/frontend/src/components/chat/FileTree.tsx
git commit -m "feat: add recursive tree listing and fix root entry detection"
```

---

## Task 10: End-to-End Verification

**Files:** None (testing only)

- [ ] **Step 1: Run backend tests**

Run: `cd apps/backend && uv run pytest tests/test_workspace_files.py -v`
Expected: All tests pass.

- [ ] **Step 2: Run frontend build**

Run: `cd apps/frontend && pnpm run build`
Expected: Build succeeds with no errors.

- [ ] **Step 3: Run frontend lint**

Run: `cd apps/frontend && pnpm run lint`
Expected: No lint errors in new files.

- [ ] **Step 4: Manual smoke test**

1. Start backend: `cd apps/backend && uv run uvicorn main:app --reload --port 8000`
2. Start frontend: `cd apps/frontend && pnpm run dev`
3. Open `/chat`, connect to an agent
4. Send a message asking the agent to create a file (e.g., "Write a plan to plan.md")
5. Verify the file path in the response becomes a clickable link
6. Click the link — verify the file viewer panel opens on the right
7. Verify the file tree shows the workspace structure
8. Verify the file content renders correctly (markdown rendered, code highlighted)
9. Click the X button — verify the file viewer closes
10. Click the folder icon in the header — verify the file viewer opens in browse mode

- [ ] **Step 5: Final commit with any fixes**

```bash
git add -A
git commit -m "fix: address any issues found during smoke testing"
```
