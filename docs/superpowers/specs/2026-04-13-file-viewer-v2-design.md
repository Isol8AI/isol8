# File Viewer V2 — Design Spec

**Date:** 2026-04-13
**Status:** Approved
**Supersedes:** 2026-04-03-workspace-file-viewer-design.md (V1)

## Problem

The V1 file viewer has three bugs:

1. **Empty workspace** — The viewer browses `workspaces/{agent_id}/` but agent personality files (SOUL.md, BOOTSTRAP.md, etc.) live in `agents/{agent_id}/`. For agents that haven't created working files yet, the viewer shows "No files in workspace" despite the agent having files.
2. **Uploads invisible** — File uploads write to `{user_root}/uploads/` which is outside the viewed directory tree. Uploaded files never appear in the viewer.
3. **No client-side file size validation** — The 10MB backend limit exists but the frontend doesn't warn users before uploading.

Additionally, the V1 layout splits chat and file viewer 50/50, which wastes horizontal space — chat is naturally narrow, files need width.

## Design

### Layout Change

When the file viewer opens, the layout transforms from the normal chat view into a split-pane IDE-style layout with a 200ms ease CSS transition.

**Normal (file viewer closed):**
```
[Sidebar 260px] [Chat 1fr                                      ]
```

**File viewer open (sidebar hidden):**
```
[Chat ~380px               ] [File Viewer 1fr                              ]
 | Connection bar           |  | Header: [Workspace] [Config] tabs         |
 | Messages (scrollable)    |  | File tree   |  File content               |
 | ...                      |  | (220px)     |  (rest)                     |
 | Chat input (bottom)      |  |             |                             |
```

Key behaviors:
- **Sidebar hides** when file viewer opens, reappears on close
- **Chat compresses** to ~380px fixed width — still fully functional (messages scroll, input works, streaming continues)
- **File viewer** gets the remaining space (majority of screen)
- **200ms ease transition** on open/close for the grid change
- **Close button** (X) in file viewer header restores normal layout

### Two Tabs: Workspace and Config

The file viewer header contains two tabs that switch the entire tree + content context.

**Workspace tab (default):**
- Browses `workspaces/{agent_id}/` on EFS — files the agent creates during conversations (plans, code, outputs, uploads)
- This is the agent's working directory
- Uploads now write here (see Upload Fix below)
- Empty state: "No files yet. Your agent will create files here as it works."

**Config tab:**
- Browses `agents/{agent_id}/` on EFS — agent personality and configuration files
- **Allowlisted files only** (not a raw directory listing):
  - `SOUL.md` — agent personality
  - `BOOTSTRAP.md` — first-run instructions
  - `MEMORY.md` — agent memory
  - `TOOLS.md` — tool configuration
  - `IDENTITY.md` — identity
  - `USER.md` — user context
  - `AGENTS.md` — sub-agent configuration
  - `HEARTBEAT.md` — heartbeat configuration
- **Excluded:** `sessions/` directory, dotfiles, any other internal OpenClaw state
- Editable inline (see Inline Editing below)
- Empty state: "No config files found. Agent config files will appear here once the agent is initialized."

**Tab behavior:**
- Clicking a file path in chat opens the Workspace tab (since agent-referenced paths are workspace paths)
- Manual open via folder icon defaults to Workspace tab
- Tab selection persists while the viewer is open but resets on close
- Switching tabs clears the selected file

### Upload Path Fix

**Current (broken):** Files upload to `{user_root}/uploads/{filename}` — invisible to file viewer.

**Fixed:** Files upload to `{user_root}/workspaces/{agent_id}/uploads/{filename}` — visible in the Workspace tab.

Changes required:

1. **Backend `POST /container/files`** — add required `agent_id` query parameter. Validate agent_id (no `/`, `\`, `..`). Write to `workspaces/{agent_id}/uploads/{safe_name}` instead of `uploads/{safe_name}`.
2. **Agent-visible path** — changes from `.openclaw/uploads/{filename}` to `.openclaw/workspaces/{agent_id}/uploads/{filename}`.
3. **Frontend `api.uploadFiles()`** — accept `agentId` parameter, pass as query param.
4. **Frontend `AgentChatWindow.handleSend()`** — pass current `agentId` to upload call.
5. **Chat file notice** — update the prepended message to reference the new path.

### Client-Side File Size Validation

- **10MB per-file limit** enforced in the frontend before upload
- Files exceeding 10MB are rejected at selection time (both file picker and drag-drop)
- Rejected files show a toast/inline error: `"{filename}" exceeds the 10MB file size limit`
- Valid files in the same batch still proceed
- The pending file chip already shows file size — files over 10MB get a red highlight

### Inline Editing

Both tabs support inline editing. The file content viewer doubles as an editor.

**UX:**
- When a file is selected, its content renders in a `textarea` (monospace, full height) instead of the read-only rendered view
- For text files (markdown, code, config): the textarea is immediately editable — no "edit mode" toggle needed
- An "unsaved" indicator appears in the header when content has been modified
- **Save:** Cmd/Ctrl+S saves, or a Save button in the file header. Save writes directly to EFS via a new backend endpoint.
- **Discard:** Clicking a different file or switching tabs discards unsaved changes (with a confirmation if dirty)
- Binary files and images remain read-only (no textarea)

**Write mechanism — direct EFS, no gateway RPC:**
- All saves go through the backend's new `PUT /container/workspace/{agent_id}/file` endpoint
- Backend writes to the correct EFS path (`workspaces/{agent_id}/` for Workspace tab, `agents/{agent_id}/` for Config tab)
- Backend `chown`s to 1000:1000 after write
- OpenClaw's Chokidar file watcher (`CHOKIDAR_USEPOLLING=true`) detects the change and reloads
- This replaces the `agents.files.set` gateway RPC for config file editing — direct EFS writes are more reliable (work when container is stopped, no gateway dependency)

**Config tab writes:**
- Only the 8 allowlisted files can be written (400 for anything else)
- The endpoint validates the filename against the allowlist before writing

**Deprecation of AgentFilesTab:**
- The existing `AgentFilesTab` in the control panel (`panels/AgentFilesTab.tsx`) uses `agents.files.set` RPC
- Once the file viewer editing is live, `AgentFilesTab` becomes redundant
- Remove it in a follow-up (not in this PR) to avoid scope creep

### File Path Detection Update

The existing `filePathDetection.ts` regex detects agent file paths in chat messages and wraps them in `isol8-file://` links. These paths are relative to the agent's workspace (e.g., `plan.md`, `uploads/data.csv`). No change needed — clicking detected paths opens the Workspace tab with the correct relative path.

## Backend API Changes

### Modified: `POST /api/v1/container/files`

Add `agent_id` query parameter:

```
POST /api/v1/container/files?agent_id={agent_id}
```

- `agent_id` is required (400 if missing)
- Validated: no `/`, `\`, `..` characters
- Files written to `workspaces/{agent_id}/uploads/{safe_name}`
- Agent-visible path: `.openclaw/workspaces/{agent_id}/uploads/{filename}`
- Existing 10MB/10-file limits unchanged

### Modified: `GET /api/v1/container/workspace/{agent_id}/tree`

No API change. The endpoint already browses `workspaces/{agent_id}/`. The Workspace tab uses it as-is.

### New: `GET /api/v1/container/workspace/{agent_id}/config-files`

Returns only the allowlisted config files from `agents/{agent_id}/`.

**Response:**
```json
{
  "files": [
    { "name": "SOUL.md", "path": "SOUL.md", "type": "file", "size": 1234, "modified_at": 1712000000.0 },
    { "name": "BOOTSTRAP.md", "path": "BOOTSTRAP.md", "type": "file", "size": 567, "modified_at": 1712000000.0 }
  ]
}
```

Only files that exist on disk AND are in the allowlist are returned. No directory traversal, no recursive listing.

### New: `GET /api/v1/container/workspace/{agent_id}/config-file?path=...`

Returns content for a single allowlisted config file from `agents/{agent_id}/`.

- `path` must be one of the 8 allowlisted filenames (400 otherwise)
- Uses the same `read_file_info()` method as the workspace file endpoint
- Same response format as `GET .../file`

### New: `PUT /api/v1/container/workspace/{agent_id}/file`

Writes a file to the agent's workspace or config directory.

**Request body:**
```json
{
  "path": "plan.md",
  "content": "# My Plan\n...",
  "tab": "workspace"
}
```

- `tab` is `"workspace"` or `"config"`
- When `tab=workspace`: writes to `workspaces/{agent_id}/{path}`. Path validated against traversal. Directories created as needed.
- When `tab=config`: writes to `agents/{agent_id}/{path}`. `path` must be one of the 8 allowlisted filenames (400 otherwise).
- File is `chown`ed to 1000:1000 after write (Chokidar picks up the change)
- Returns `{ "status": "ok", "path": "<written_path>" }`

## Frontend Changes

### ChatLayout.tsx

- New CSS grid states with transition:
  - Closed: `grid-template-columns: 260px 1fr` (current)
  - Open: `grid-template-columns: 0px 380px 1fr` (sidebar width → 0, overflow hidden)
- `transition: grid-template-columns 200ms ease` on the grid container
- Sidebar gets `overflow: hidden` and `opacity: 0` during transition to prevent flash

### FileViewer.tsx

- Add tab state: `activeTab: "workspace" | "config"`
- Header renders two tab buttons styled as underline tabs
- Tab switch swaps the data source:
  - Workspace: existing `useWorkspaceTree(agentId)` + `useWorkspaceFile(agentId, path)`
  - Config: new `useConfigFiles(agentId)` + `useConfigFile(agentId, path)`
- Selected file resets on tab switch

### FileContentViewer.tsx

- Text files render in an editable `textarea` (monospace) instead of read-only rendered view
- Track dirty state (content !== original)
- Header shows "unsaved" badge when dirty
- Save button + Cmd/Ctrl+S keyboard shortcut
- Save calls new `api.saveWorkspaceFile(agentId, path, content, tab)` method
- Confirmation dialog on navigate-away when dirty
- Binary/image files remain read-only

### useWorkspaceFiles.ts

Add two new hooks:

```typescript
export function useConfigFiles(agentId: string | null)
// GET /container/workspace/{agentId}/config-files

export function useConfigFile(agentId: string | null, filePath: string | null)
// GET /container/workspace/{agentId}/config-file?path={filePath}
```

### ChatInput.tsx

- On file selection (picker + drag-drop), filter out files > 10MB
- Show inline error for rejected files: `"{name}" exceeds the 10MB limit`
- Error auto-dismisses after 5 seconds or on next file selection

### api.ts

- `uploadFiles(files, agentId)` — add `agentId` param, append as query string
- `saveWorkspaceFile(agentId, path, content, tab)` — new method, `PUT /container/workspace/{agentId}/file`

### AgentChatWindow.tsx

- Pass `agentId` to `api.uploadFiles(files, agentId)` in `handleSend`

## File Changes Summary

| File | Change |
|------|--------|
| `apps/backend/routers/container_rpc.py` | Add `agent_id` param to upload endpoint, change dest path |
| `apps/backend/routers/workspace_files.py` | Add config-files, config-file, and file write endpoints |
| `apps/frontend/src/components/chat/ChatLayout.tsx` | Animated grid transition, hide sidebar |
| `apps/frontend/src/components/chat/FileViewer.tsx` | Two tabs (Workspace/Config), tab state |
| `apps/frontend/src/components/chat/FileContentViewer.tsx` | Inline editing with save, dirty state, Cmd+S |
| `apps/frontend/src/components/chat/ChatInput.tsx` | Client-side 10MB validation |
| `apps/frontend/src/hooks/useWorkspaceFiles.ts` | Add useConfigFiles, useConfigFile hooks |
| `apps/frontend/src/lib/api.ts` | Add agentId to uploadFiles |
| `apps/frontend/src/components/chat/AgentChatWindow.tsx` | Pass agentId to uploadFiles |

## Not in This Version

- Real-time file change push (manual refresh button)
- File download
- Search within files
- Drag-to-resize the chat/viewer split
- Removing AgentFilesTab from control panel (follow-up after this ships)
