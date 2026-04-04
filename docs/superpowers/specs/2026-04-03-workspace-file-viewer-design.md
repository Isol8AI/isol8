# Workspace File Viewer — Design Spec

**Date:** 2026-04-03
**Status:** Approved
**Problem:** Agents write files to their EFS workspace (e.g., plans, configs, code) and reference them in chat, but users have no way to view those files. The workspace is remote (EFS) and completely invisible from the chat UI.

## Prior Art

| Solution | Access Method | Notes |
|----------|--------------|-------|
| OpenClaw macOS/CLI | Direct filesystem | Workspace is a local folder |
| Clawspace | Direct filesystem (Docker volume) | Browser-based Monaco editor, URL-as-state navigation |
| ClawControl | RPC through gateway | Remote client, gateway mediates access |
| OpenClaw gateway RPC | `agents.files.list/get/set` | Only exposes 9 hardcoded files (AGENTS.md, SOUL.md, etc.) — not arbitrary workspace files |

Isol8 is in the ClawControl position (remote user, workspace on EFS), but OpenClaw's RPC is too limited. We use REST through our own backend, which already mounts EFS and authenticates users.

## Architecture Decision: REST via Backend EFS Access

The backend (FastAPI on EC2) already has EFS mounted at `/mnt/efs/users/`. New REST endpoints read from the agent's workspace directory, scoped by authenticated user ID and validated agent ID. No dependency on the OpenClaw container being running.

**Why not RPC through the container:**
- OpenClaw only exposes 9 hardcoded files via `agents.files.*` — no arbitrary file browsing
- Requires container to be running (blocks free tier scale-to-zero users)
- No security benefit over scoped EFS reads since we control the backend

**Security model:**
- `user_id` from Clerk JWT (cannot be spoofed)
- `agent_id` validated against the user's container record in the database
- Path traversal protection: `os.path.realpath()` + verify resolved path starts with agent workspace prefix
- Symlinks that escape the workspace are rejected
- System files excluded from listing (`openclaw.json`, `.openclaw/`, `node_modules/`)

## Layout

When the file viewer opens, the `ChatLayout` grid changes:

```
Before:  grid-template-columns: 260px 1fr
After:   grid-template-columns: 260px 1fr 1fr
```

Chat compresses to the left half. File viewer takes the right half.

**File viewer panel structure:**
- **Header bar:** breadcrumb path, file metadata (size, modified), copy button, close button (X)
- **Left sub-panel:** collapsible file tree
- **Right sub-panel:** file content viewer

**Entry points:**
- Clickable file paths detected in chat messages (primary)
- Folder icon button in the chat header (manual browsing)

**Dismissal:** Close button (X) on the viewer panel restores full-width chat.

## File Path Detection in Chat

Pre-processing step on message content before ReactMarkdown rendering:
- Regex detects paths containing `/` with file extensions
- Backtick-wrapped paths where context suggests files
- Conservative matching — no false positives on package names, URLs, or code references
- Detected paths rendered as custom clickable components that open the file viewer (not `<a>` navigation)

## Backend API

New router: `routers/workspace.py`

### `GET /api/v1/workspace/{agent_id}/tree`

Lists the full directory tree for the agent's workspace.

**Auth:** Clerk JWT required. Agent ownership validated against container record.

**Response:**
```json
{
  "files": [
    { "name": "plan.md", "path": "isol8_agents/plan.md", "type": "file", "size": 2048, "modified_at": "2026-04-03T12:00:00Z" },
    { "name": "isol8_agents", "path": "isol8_agents", "type": "dir", "size": null, "modified_at": "2026-04-03T11:00:00Z" }
  ]
}
```

Flat list with paths; frontend builds the tree. Excludes: `openclaw.json`, `.openclaw/`, `node_modules/`, `__pycache__/`.

### `GET /api/v1/workspace/{agent_id}/file?path=...`

Returns content for a specific file.

**Auth:** Same as tree endpoint.

**Response:**
```json
{
  "name": "plan.md",
  "path": "isol8_agents/plan.md",
  "size": 2048,
  "modified_at": "2026-04-03T12:00:00Z",
  "content": "# Plan\n...",
  "binary": false,
  "mime_type": "text/markdown"
}
```

**File type handling:**
- Text files: `content` as UTF-8 string
- Images: base64-encoded `content` with mime type
- Binary files: `content: null`, `binary: true`
- CSVs: raw text (frontend parses)

**Path security:** `os.path.realpath()` on resolved path, verify starts with agent workspace prefix. Reject symlinks escaping workspace.

## Frontend Components

### FileViewer (new component)

**File tree (left sub-panel):**
- Fetched via `useApi().get('/workspace/{agent_id}/tree')`, cached with SWR
- Collapsible directories, folders expand/collapse on click
- Extension-based icons using lucide-react (already in project)
- Clicking a file loads content in the viewer

**File content viewer (right sub-panel) — rich preview:**

| File Type | Rendering |
|-----------|-----------|
| `.md` | Rendered markdown (reuse `ReactMarkdown` + `remarkGfm` from `MessageList`) |
| `.py`, `.js`, `.ts`, `.json`, `.yaml`, `.toml`, `.sh` | Syntax-highlighted code (reuse `CodeBlock` from `MessageList`) |
| `.csv` | Parsed into HTML table with sortable columns |
| `.png`, `.jpg`, `.gif`, `.svg`, `.webp` | Inline image preview |
| Everything else | Plain text, monospace font |

**Header bar:**
- Breadcrumb path — each segment clickable to navigate tree
- File size and last modified timestamp
- Copy button (clipboard)
- Close button (X)

**States:**
- Loading spinner while fetching
- Empty: "No files in workspace"
- Error: "Could not load file"

### ChatLayout Changes

- New state: `fileViewerOpen: boolean`, `activeFilePath: string | null`
- Grid template toggles based on `fileViewerOpen`
- Folder icon button added to header bar
- Switching agents resets the file viewer

### MessageList Changes

- `content` pre-processed before `ReactMarkdown` to detect file paths
- Detected paths wrapped in clickable components that call `onFileOpen(path)` callback
- Callback propagates up to ChatLayout to open the file viewer

## Data Flow

**Agent mentions a file:**
```
Agent says "Plan written to isol8_agents/plan.md"
  → MessageList pre-processes content, detects path
  → Renders as clickable link
  → User clicks
  → ChatLayout: fileViewerOpen=true, activeFilePath="isol8_agents/plan.md"
  → Grid: "260px 1fr" → "260px 1fr 1fr"
  → FileViewer mounts
  → GET /workspace/{agent_id}/tree → file tree renders, auto-selects file
  → GET /workspace/{agent_id}/file?path=isol8_agents/plan.md → content renders
```

**Manual browsing:**
```
User clicks folder icon in header
  → FileViewer opens, tree loaded, no file selected
  → User browses and clicks a file
  → Content loads
```

## Not in V1

- No file editing (read-only viewer)
- No real-time file change push (manual tree refresh)
- No file download
- No search within files
- No diff view
- No WebSocket notifications when agent writes files

## V2 Considerations

- File editing with Monaco editor (like Clawspace)
- WebSocket push for `file_written` events from the agent
- File download for binary files
- Search across workspace files
- Diff view for agent-modified files
