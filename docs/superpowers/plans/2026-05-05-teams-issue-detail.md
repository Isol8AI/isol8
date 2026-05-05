# Teams Issue Detail Page Implementation Plan (PR #3d)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** Replace `IssueDetailPanel.tsx`'s 40-line stub with a real IssueDetail page (header + comments thread + properties sidebar). Add a `NewIssueDialog` for creating issues from the Inbox empty-state. Closes the inbox UX loop: user creates an issue → assigns to agent → wakeup fires → issue lands in inbox → user opens detail.

**Scope correction from research:** Original 4-PR design listed #3d as "IssueDetail + ApprovalDetail + AgentRun." Upstream IssueDetail is **3,889 LOC** alone, NewIssueDialog is **1,896 LOC**. Pragmatic v1 = IssueDetail (read + comment + status mutate) + NewIssueDialog. ApprovalDetail + AgentRun detail defer to a future #3d.2 sub-project (each is reachable as a stub link from #3d). This matches the MVP-subset pattern from #3b/#3c.

**Architecture:** Backend BFF gains `comments` endpoints (the only missing surface from #3a). Frontend ports IssueDetail's chat-tab + properties-sidebar (drops activity tab, run ledger, sub-issues, plugin slots, file uploads, tree controls, documents, feedback votes, interactions — all deferred). NewIssueDialog ports as a slim `<AlertDialog>` with title/description/status/priority/project/assignee fields. Click on an inbox row → navigates to `/teams/issues/[id]` → renders the new IssueDetailPage via the existing TeamsLayout panel system.

**Tech Stack:** React 19 + Next 16 App Router + Tailwind v4 + SWR + lucide-react + shadcn primitives. No new npm deps.

**Upstream reference:** `paperclip/ui/src/pages/IssueDetail.tsx` (3,889 LOC) + `paperclip/ui/src/components/NewIssueDialog.tsx` (1,896 LOC). License attribution headers per file as in PR #3b/c.

---

## In scope (#3d v1)

**BFF additions:**
- `GET /teams/issues/{id}/comments` — list comments
- `POST /teams/issues/{id}/comments` — add comment (body only; reopen/resume/interrupt flags defer)

**Frontend port:**
- `IssueDetailPage` (~600 LOC) — header + properties sidebar + chat tab (comments thread + composer)
- `IssueHeader` — title (inline editable), identifier, status picker, priority picker, assignee picker
- `IssueProperties` — right sidebar: status, priority, assignee, project, labels (read-only chips), dates
- `IssueComments` — comment thread + composer (textarea, no markdown editor, no @mentions in v1)
- `NewIssueDialog` (~400 LOC slim) — title, description, status, priority, project, assignee_agent_id
- "New issue" button on InboxPage (top-right of InboxToolbar)

**Wiring:**
- Replace `IssueDetailPanel.tsx`'s 40-line body with `<IssueDetailPage issueId={...} />`
- InboxPage opens NewIssueDialog when user clicks "New issue"
- After issue creation: redirect to `/teams/issues/[id]` (or close dialog + invalidate inbox keys)

**Schema fix:**
- `CreateIssueBody.priority` regex currently `^(low|medium|high|urgent)$` — but upstream + our types.ts use `critical|high|medium|low` (no `urgent`). Update to match upstream exactly.

## Out of scope (deferred)

- Activity tab (separate from chat tab)
- Run ledger (`IssueRunLedger`)
- Sub-issues tree + parent issue picker
- Plugin slots (`PluginSlotMount`, `PluginSlotOutlet`)
- Tree controls (pause/resume/cancel/restore subtree)
- Documents section (`IssueDocumentsSection`)
- Feedback votes
- File / image upload + `ImageGalleryModal`
- Interactions (suggest tasks / request confirmation / etc.)
- @mentions autocomplete in comment composer
- Markdown rendering in comments (just plaintext for v1; render with `whitespace-pre-wrap`)
- Live transcripts of in-flight runs
- Continuation handoff
- ApprovalDetail page port
- AgentRun detail page port (still uses `RunDetailPanel.tsx` 28-line stub)
- Workspace pills / execution-workspace selection in NewIssueDialog
- Reviewer/approver fields in NewIssueDialog
- `assignee_user_id` (only `assignee_agent_id` in v1; agents are who actually does work)

---

## File structure

```
apps/backend/
├── core/services/paperclip_admin_client.py     # MODIFY: add list_issue_comments + add_issue_comment
├── routers/teams/issues.py                     # MODIFY: add comments routes
└── routers/teams/schemas.py                    # MODIFY: AddIssueCommentBody + fix CreateIssueBody priority

apps/backend/tests/
├── unit/services/test_paperclip_admin_client_comments.py  # NEW
└── unit/routers/teams/test_issue_comments.py              # NEW

apps/frontend/src/components/teams/
├── shared/types.ts                             # MODIFY: IssueComment type + add createIssue body type
├── shared/queryKeys.ts                         # MODIFY: nothing — issues.detail + comments already present
└── inbox/                                      # NEW directory for IssueDetail components
    └── (already exists)

apps/frontend/src/components/teams/issues/      # NEW directory
├── IssueDetailPage.tsx                         # NEW. Assembly. ~250 LOC.
├── IssueHeader.tsx                             # NEW. Title + status + priority + assignee. ~200 LOC.
├── IssueProperties.tsx                         # NEW. Right sidebar. ~180 LOC.
├── IssueComments.tsx                           # NEW. Thread + composer. ~150 LOC.
├── NewIssueDialog.tsx                          # NEW. Modal form. ~220 LOC.
└── hooks/
    ├── useIssueDetail.ts                       # NEW. SWR for issue + comments. ~80 LOC.
    └── useIssueMutations.ts                    # NEW. Update + comment + create. ~120 LOC.

apps/frontend/src/components/teams/panels/
└── IssueDetailPanel.tsx                        # MODIFY: body becomes <IssueDetailPage>

apps/frontend/src/components/teams/inbox/
└── InboxPage.tsx                               # MODIFY: add "New issue" button + dialog wiring

apps/frontend/src/__tests__/components/teams/issues/
├── IssueDetailPage.test.tsx
├── IssueHeader.test.tsx
├── IssueProperties.test.tsx
├── IssueComments.test.tsx
├── NewIssueDialog.test.tsx
└── hooks/
    ├── useIssueDetail.test.ts
    └── useIssueMutations.test.ts
```

---

## Common conventions

- 3-line MIT attribution header on every ported file (per PR #3b/c precedent).
- Test files import explicitly from vitest: `import { describe, test, expect, vi } from "vitest";` (PR #3b CI lesson).
- BFF: `/teams/issues/{id}/comments` paths follow #3a's session-cookie auth pattern via `_ctx`.
- Frontend: SWR via `useTeamsApi().read(...)`; mutations via `useTeamsApi().post()` + `useSWRConfig().mutate(...)`.
- shadcn primitives `dialog`, `dropdown-menu`, `popover`, `badge`, `checkbox`, `input`, `button`, `alert-dialog`, `textarea` exist; `tooltip` does NOT — use `title=` attr.
- Retheme rules from #3b apply: blue→amber-700/dark:amber-400, zinc→stone, KEEP semantic status colors.
- DO NOT push between tasks. Push at Task 12.

---

## Task 1: BFF — add comments admin-client methods + Pydantic schema

**Files:**
- Modify: `apps/backend/core/services/paperclip_admin_client.py` — add `list_issue_comments(issue_id, session_cookie)` and `add_issue_comment(issue_id, body, session_cookie)`. Mirror `get_issue` pattern.
- Modify: `apps/backend/routers/teams/schemas.py` — add `AddIssueCommentBody(_Strict)` with `body: str = Field(min_length=1, max_length=20000)`. Fix `CreateIssueBody.priority` and `PatchIssueBody.priority` regex from `^(low|medium|high|urgent)$` to `^(critical|high|medium|low)$`.
- Test: `apps/backend/tests/unit/services/test_paperclip_admin_client_comments.py`

- [ ] **Step 1: Read upstream comment schema**

```bash
sed -n '195,210p' /Users/prasiddhaparthsarthy/Desktop/isol8.nosync/paperclip/packages/shared/src/validators/issue.ts
```

Confirm: `body: string (min 1)`, optional `reopen`, `resume`, `interrupt` booleans. v1 only ports `body`; defer the action flags.

- [ ] **Step 2: Add the admin-client methods**

```python
async def list_issue_comments(
    self,
    *,
    issue_id: str,
    session_cookie: str,
) -> dict:
    """List comments on an issue. Maps to GET /api/issues/{id}/comments."""
    return await self._get(
        f"/api/issues/{issue_id}/comments",
        session_cookie=session_cookie,
    )


async def add_issue_comment(
    self,
    *,
    issue_id: str,
    body: dict,
    session_cookie: str,
) -> dict:
    """Add a comment. Maps to POST /api/issues/{id}/comments."""
    return await self._post(
        f"/api/issues/{issue_id}/comments",
        json=body,
        session_cookie=session_cookie,
    )
```

- [ ] **Step 3: Pydantic schemas**

```python
class AddIssueCommentBody(_Strict):
    body: str = Field(min_length=1, max_length=20000)
```

Fix priority regex on `CreateIssueBody` and `PatchIssueBody`:

```python
class CreateIssueBody(_Strict):
    title: str = Field(min_length=1, max_length=200)
    description: Optional[str] = Field(default=None, max_length=20000)
    project_id: Optional[str] = None
    assignee_agent_id: Optional[str] = None
    priority: Optional[str] = Field(default=None, pattern=r"^(critical|high|medium|low)$")
```

(Same change on PatchIssueBody.)

- [ ] **Step 4: Test the admin-client methods**

```python
import httpx
import pytest
from pytest_httpx import HTTPXMock

from core.services.paperclip_admin_client import PaperclipAdminClient


@pytest.mark.asyncio
async def test_list_issue_comments(httpx_mock: HTTPXMock):
    client = PaperclipAdminClient(base_url="https://paperclip.test")
    httpx_mock.add_response(
        method="GET",
        url="https://paperclip.test/api/issues/iss_1/comments",
        json={"comments": [{"id": "c1", "body": "Hello", "createdAt": "2026-05-05T00:00:00Z"}]},
    )
    result = await client.list_issue_comments(issue_id="iss_1", session_cookie="cookie")
    assert result == {"comments": [{"id": "c1", "body": "Hello", "createdAt": "2026-05-05T00:00:00Z"}]}


@pytest.mark.asyncio
async def test_add_issue_comment(httpx_mock: HTTPXMock):
    client = PaperclipAdminClient(base_url="https://paperclip.test")
    httpx_mock.add_response(
        method="POST",
        url="https://paperclip.test/api/issues/iss_1/comments",
        json={"id": "c2", "body": "World", "createdAt": "2026-05-05T00:01:00Z"},
    )
    result = await client.add_issue_comment(
        issue_id="iss_1",
        body={"body": "World"},
        session_cookie="cookie",
    )
    assert result["id"] == "c2"
```

(Adapt to existing test fixtures + auth-cookie helpers in this file.)

- [ ] **Step 5: Commit**

```bash
cd /Users/prasiddhaparthsarthy/Desktop/isol8.nosync/.worktrees/feat-teams-issue-detail/apps/backend && uv run pytest tests/unit/services/test_paperclip_admin_client_comments.py -v --no-cov
cd /Users/prasiddhaparthsarthy/Desktop/isol8.nosync/.worktrees/feat-teams-issue-detail
git add apps/backend/core/services/paperclip_admin_client.py apps/backend/routers/teams/schemas.py apps/backend/tests/unit/services/test_paperclip_admin_client_comments.py docs/superpowers/plans/2026-05-05-teams-issue-detail.md
git commit -m "feat(teams): admin-client list_issue_comments + add_issue_comment + priority fix"
```

---

## Task 2: BFF — comments routes + tests

**Files:**
- Modify: `apps/backend/routers/teams/issues.py` — add `GET` + `POST /issues/{issue_id}/comments`
- Test: `apps/backend/tests/unit/routers/teams/test_issue_comments.py`

- [ ] **Step 1: Add routes**

```python
from .schemas import AddIssueCommentBody, CreateIssueBody, PatchIssueBody


@router.get("/issues/{issue_id}/comments")
async def list_issue_comments(issue_id: str, ctx: TeamsContext = Depends(_ctx)):
    """List comments on an issue."""
    return await _agents._admin().list_issue_comments(
        issue_id=issue_id,
        session_cookie=ctx.session_cookie,
    )


@router.post("/issues/{issue_id}/comments")
async def add_issue_comment(
    issue_id: str,
    body: AddIssueCommentBody,
    ctx: TeamsContext = Depends(_ctx),
):
    """Add a comment to an issue."""
    return await _agents._admin().add_issue_comment(
        issue_id=issue_id,
        body=body.model_dump(exclude_none=True),
        session_cookie=ctx.session_cookie,
    )
```

- [ ] **Step 2: Tests** (mirror existing `test_issues.py` pattern with `app.dependency_overrides[_ctx]` + AsyncMock admin client).

3 tests minimum:
- `GET /teams/issues/{id}/comments` proxies with session cookie
- `POST /teams/issues/{id}/comments` accepts body, posts to admin client
- `POST` rejects missing body (422 from Pydantic)

- [ ] **Step 3: Commit**

```bash
cd /Users/prasiddhaparthsarthy/Desktop/isol8.nosync/.worktrees/feat-teams-issue-detail/apps/backend && uv run pytest tests/unit/routers/teams/test_issue_comments.py -v --no-cov
cd /Users/prasiddhaparthsarthy/Desktop/isol8.nosync/.worktrees/feat-teams-issue-detail
git add apps/backend/routers/teams/issues.py apps/backend/tests/unit/routers/teams/test_issue_comments.py
git commit -m "feat(teams): /teams/issues/{id}/comments BFF routes (GET + POST)"
```

---

## Task 3: Frontend types — IssueComment + IssueCreate

**Files:**
- Modify: `apps/frontend/src/components/teams/shared/types.ts` — add `IssueComment` interface + `IssueCreateInput` type
- Test: extend `apps/frontend/src/__tests__/components/teams/shared/types.test.ts` with compile-only assertions

- [ ] **Step 1: Add types**

```ts
export interface IssueComment {
  id: string;
  body: string;
  createdAt: string;
  authorUserId?: string | null;
  authorAgentId?: string | null;
  /** "user" | "agent" — derived for display when both ids present */
  authorKind?: "user" | "agent" | null;
}

export interface IssueCreateInput {
  title: string;
  description?: string;
  status?: IssueStatus;
  priority?: IssuePriority;
  projectId?: string;
  assigneeAgentId?: string;
}

export interface IssueUpdateInput {
  title?: string;
  description?: string;
  status?: IssueStatus;
  priority?: IssuePriority;
  projectId?: string;
  assigneeAgentId?: string;
}
```

- [ ] **Step 2: Tests** (compile-only, 2-3 assertions)

- [ ] **Step 3: Commit**

```
feat(teams): IssueComment + IssueCreateInput + IssueUpdateInput types
```

---

## Task 4: useIssueDetail hook

**Files:**
- Create: `apps/frontend/src/components/teams/issues/hooks/useIssueDetail.ts`
- Test: `apps/frontend/src/__tests__/components/teams/issues/hooks/useIssueDetail.test.ts`

- [ ] **Step 1: Implement**

```ts
import { useTeamsApi } from "@/hooks/useTeamsApi";
import { teamsQueryKeys } from "@/components/teams/shared/queryKeys";
import type { Issue, IssueComment } from "@/components/teams/shared/types";

export interface UseIssueDetailResult {
  issue: Issue | undefined;
  comments: IssueComment[];
  isLoading: boolean;
  isError: boolean;
  error: Error | null;
}

type CommentsResponse = { comments: IssueComment[] } | IssueComment[];

function normalizeComments(data: CommentsResponse | undefined): IssueComment[] {
  if (!data) return [];
  if (Array.isArray(data)) return data;
  return data.comments ?? [];
}

export function useIssueDetail(issueId: string): UseIssueDetailResult {
  const { read } = useTeamsApi();
  const issue = read<Issue>(teamsQueryKeys.issues.detail(issueId));
  const comments = read<CommentsResponse>(teamsQueryKeys.issues.comments(issueId));

  return {
    issue: issue.data,
    comments: normalizeComments(comments.data),
    isLoading: issue.isLoading || comments.isLoading,
    isError: !!(issue.error || comments.error),
    error: issue.error || comments.error || null,
  };
}
```

- [ ] **Step 2: Tests** — 5 cases: empty data, populated, isLoading, isError, normalization (envelope vs array).

- [ ] **Step 3: Commit**

```
feat(teams): useIssueDetail hook (issue + comments SWR)
```

---

## Task 5: useIssueMutations hook

**Files:**
- Create: `apps/frontend/src/components/teams/issues/hooks/useIssueMutations.ts`
- Test: `apps/frontend/src/__tests__/components/teams/issues/hooks/useIssueMutations.test.ts`

- [ ] **Step 1: Implement**

```ts
import { useCallback } from "react";
import { useSWRConfig } from "swr";
import { useTeamsApi } from "@/hooks/useTeamsApi";
import { teamsQueryKeys } from "@/components/teams/shared/queryKeys";
import type { Issue, IssueComment, IssueCreateInput, IssueUpdateInput } from "@/components/teams/shared/types";

const SWR_PREFIX = "/teams";
const swrKey = (path: string) => `${SWR_PREFIX}${path}`;

export function useIssueMutations() {
  const { post, patch } = useTeamsApi();
  const { mutate } = useSWRConfig();

  const create = useCallback(async (input: IssueCreateInput): Promise<Issue> => {
    // BFF schema accepts snake_case
    const body = {
      title: input.title,
      description: input.description,
      project_id: input.projectId,
      assignee_agent_id: input.assigneeAgentId,
      priority: input.priority,
    };
    const created = await post<Issue>("/issues", body);
    // Invalidate inbox keys (with predicate to catch all tab variants)
    mutate((key) => typeof key === "string" && key.startsWith("/teams/inbox?"));
    return created;
  }, [post, mutate]);

  const update = useCallback(async (issueId: string, input: IssueUpdateInput): Promise<Issue> => {
    const body = {
      title: input.title,
      description: input.description,
      project_id: input.projectId,
      assignee_agent_id: input.assigneeAgentId,
      priority: input.priority,
      status: input.status,
    };
    const updated = await patch<Issue>(`/issues/${issueId}`, body);
    mutate(swrKey(teamsQueryKeys.issues.detail(issueId)));
    mutate((key) => typeof key === "string" && key.startsWith("/teams/inbox?"));
    return updated;
  }, [patch, mutate]);

  const addComment = useCallback(async (issueId: string, body: string): Promise<IssueComment> => {
    const created = await post<IssueComment>(`/issues/${issueId}/comments`, { body });
    mutate(swrKey(teamsQueryKeys.issues.comments(issueId)));
    return created;
  }, [post, mutate]);

  return { create, update, addComment };
}
```

- [ ] **Step 2: Tests** — mock useTeamsApi + useSWRConfig, assert each mutation calls the right path + invalidates the right keys.

- [ ] **Step 3: Commit**

```
feat(teams): useIssueMutations hook (create + update + addComment)
```

---

## Task 6: IssueHeader component

**Files:**
- Create: `apps/frontend/src/components/teams/issues/IssueHeader.tsx`
- Test: `apps/frontend/src/__tests__/components/teams/issues/IssueHeader.test.tsx`

- [ ] **Step 1: Read upstream**

```bash
sed -n '1098,1250p' /Users/prasiddhaparthsarthy/Desktop/isol8.nosync/paperclip/ui/src/pages/IssueDetail.tsx
```

Look at the header structure: title (inline-editable on click), identifier badge, status icon button (opens picker), priority icon button (opens picker), assignee (avatar + name, opens picker).

- [ ] **Step 2: Component shape**

```tsx
import type { Issue, IssueStatus, IssuePriority } from "@/components/teams/shared/types";

export interface IssueHeaderProps {
  issue: Issue;
  onTitleSave: (title: string) => Promise<void>;
  onStatusChange: (status: IssueStatus) => Promise<void>;
  onPriorityChange: (priority: IssuePriority) => Promise<void>;
  // No assigneeChange in v1 (defer agent picker)
}
```

Renders:
- Identifier badge (e.g., "PAP-123")
- Title — editable on click (uses `<input>`-on-edit pattern). Debounced save on blur or Enter.
- Status icon — uses `<StatusIcon>` from #3b. Click opens dropdown to change.
- Priority icon — uses `<PriorityIcon>` from #3b. Click opens dropdown to change.

Apply retheme: blue→amber-700/dark:amber-400 if any literal blues remain.

- [ ] **Step 3: Tests** — 4-6 cases: title click → input mode, save on Enter, status picker fires onStatusChange, priority picker fires onPriorityChange.

- [ ] **Step 4: Commit**

```
feat(teams): port IssueHeader (title + status + priority)
```

---

## Task 7: IssueComments component

**Files:**
- Create: `apps/frontend/src/components/teams/issues/IssueComments.tsx`
- Test: `apps/frontend/src/__tests__/components/teams/issues/IssueComments.test.tsx`

- [ ] **Step 1: Component shape**

```tsx
import type { IssueComment } from "@/components/teams/shared/types";

export interface IssueCommentsProps {
  comments: IssueComment[];
  isLoading?: boolean;
  onSubmit: (body: string) => Promise<void>;
}
```

Renders:
- List of comments (each with author identity + relative time + body. Use `whitespace-pre-wrap` for newlines).
- Composer: `<Textarea>` + Submit button. Disabled when empty. Cmd/Ctrl+Enter submits. Shows pending state during submit.

Drop from upstream: @mentions, markdown rendering, image upload, interactions (suggest tasks etc.), reopen/resume/interrupt action checkboxes.

- [ ] **Step 2: Tests** — 5-6 cases: render comments, empty state, submit fires onSubmit, Cmd+Enter submits, disabled when empty, clears after submit.

- [ ] **Step 3: Commit**

```
feat(teams): port IssueComments (thread + composer)
```

---

## Task 8: IssueProperties component (right sidebar)

**Files:**
- Create: `apps/frontend/src/components/teams/issues/IssueProperties.tsx`
- Test: `apps/frontend/src/__tests__/components/teams/issues/IssueProperties.test.tsx`

- [ ] **Step 1: Read upstream**

Sidebar block of upstream IssueDetail. Renders rows of `<Property name="Status">…</Property>` style.

- [ ] **Step 2: Component shape**

```tsx
import type { Issue, CompanyAgent, IssueProject } from "@/components/teams/shared/types";

export interface IssuePropertiesProps {
  issue: Issue;
  agents: CompanyAgent[];
  projects: IssueProject[];
}
```

Renders right-sidebar with:
- Status (icon + label)
- Priority (icon + label)
- Assignee (agent identity OR "Unassigned")
- Project (chip OR "—")
- Labels (read-only chips OR "—")
- Created at (relative time)
- Updated at (relative time)

All read-only in v1. Mutations happen via header pickers (status, priority).

- [ ] **Step 3: Tests** — 4 cases: full issue renders all rows; missing optional fields render "—"; agent name lookup via agents list; relative time formatting.

- [ ] **Step 4: Commit**

```
feat(teams): port IssueProperties (right sidebar — read-only)
```

---

## Task 9: IssueDetailPage assembly

**Files:**
- Create: `apps/frontend/src/components/teams/issues/IssueDetailPage.tsx`
- Test: `apps/frontend/src/__tests__/components/teams/issues/IssueDetailPage.test.tsx`

- [ ] **Step 1: Component shape**

```tsx
"use client";

import { IssueHeader } from "./IssueHeader";
import { IssueComments } from "./IssueComments";
import { IssueProperties } from "./IssueProperties";
import { useIssueDetail } from "./hooks/useIssueDetail";
import { useIssueMutations } from "./hooks/useIssueMutations";

export interface IssueDetailPageProps {
  issueId: string;
}

export function IssueDetailPage({ issueId }: IssueDetailPageProps) {
  const { issue, comments, isLoading, isError } = useIssueDetail(issueId);
  const mutations = useIssueMutations();

  // ... loading / error states
  // ... handler functions calling mutations

  return (
    <div className="grid grid-cols-1 lg:grid-cols-[1fr_320px] gap-6 p-4 sm:p-6">
      <main className="flex flex-col gap-4 min-w-0">
        <IssueHeader issue={issue} onTitleSave={...} onStatusChange={...} onPriorityChange={...} />
        <div className="border-t pt-4">
          <h2 className="text-sm font-medium mb-3">Conversation</h2>
          <IssueComments comments={comments} onSubmit={(body) => mutations.addComment(issueId, body)} />
        </div>
      </main>
      <aside>
        <IssueProperties issue={issue} agents={[]} projects={[]} />
      </aside>
    </div>
  );
}
```

- [ ] **Step 2: Tests** — 5 cases: loading state, error state, renders header+comments+properties when data loaded, status mutation flows through useIssueMutations, comment submit flows through.

- [ ] **Step 3: Commit**

```
feat(teams): wire IssueDetailPage (header + comments + properties)
```

---

## Task 10: NewIssueDialog component

**Files:**
- Create: `apps/frontend/src/components/teams/issues/NewIssueDialog.tsx`
- Test: `apps/frontend/src/__tests__/components/teams/issues/NewIssueDialog.test.tsx`

- [ ] **Step 1: Read upstream (slim subset)**

```bash
sed -n '360,500p' /Users/prasiddhaparthsarthy/Desktop/isol8.nosync/paperclip/ui/src/components/NewIssueDialog.tsx
```

Just the form-shape header — we're NOT porting the full 1,896 LOC.

- [ ] **Step 2: Component shape**

```tsx
import { useState } from "react";
import { AlertDialog, AlertDialogContent, AlertDialogHeader, AlertDialogTitle, AlertDialogFooter, AlertDialogCancel, AlertDialogAction } from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { useIssueMutations } from "./hooks/useIssueMutations";
import type { CompanyAgent, IssueProject, IssueStatus, IssuePriority } from "@/components/teams/shared/types";

export interface NewIssueDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  agents?: CompanyAgent[];
  projects?: IssueProject[];
  /** Called with the created issue id on success. */
  onCreated?: (issueId: string) => void;
}

export function NewIssueDialog(props: NewIssueDialogProps) {
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [status, setStatus] = useState<IssueStatus>("todo");
  const [priority, setPriority] = useState<IssuePriority>("medium");
  const [projectId, setProjectId] = useState<string | undefined>();
  const [assigneeAgentId, setAssigneeAgentId] = useState<string | undefined>();
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { create } = useIssueMutations();

  const submit = async () => {
    if (!title.trim()) return;
    setSubmitting(true);
    setError(null);
    try {
      const issue = await create({ title: title.trim(), description, status, priority, projectId, assigneeAgentId });
      props.onCreated?.(issue.id);
      // reset
      setTitle(""); setDescription(""); setStatus("todo"); setPriority("medium");
      setProjectId(undefined); setAssigneeAgentId(undefined);
      props.onOpenChange(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to create issue");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <AlertDialog open={props.open} onOpenChange={props.onOpenChange}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>New issue</AlertDialogTitle>
        </AlertDialogHeader>
        <div className="flex flex-col gap-3">
          <Input
            placeholder="Issue title"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            data-autofocus
          />
          <Textarea
            placeholder="Description (optional)"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            rows={4}
          />
          {/* status / priority / project / assignee selects (use plain <select> for v1; can shadcn-ize later) */}
          {/* ... */}
          {error && <p className="text-sm text-destructive" role="alert">{error}</p>}
        </div>
        <AlertDialogFooter>
          <AlertDialogCancel>Cancel</AlertDialogCancel>
          <Button onClick={submit} disabled={!title.trim() || submitting}>
            {submitting ? "Creating..." : "Create issue"}
          </Button>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
```

(Use plain `<select>` for status/priority/project/assignee — keeps deps minimal. shadcn `select` can land later.)

- [ ] **Step 3: Tests** — 6 cases: opens, title required, submit fires create, error renders, success closes + fires onCreated, cancel doesn't fire.

- [ ] **Step 4: Commit**

```
feat(teams): port NewIssueDialog (slim title/description/status/priority/project/agent)
```

---

## Task 11: Wiring — replace IssueDetailPanel + add New issue button to InboxPage

**Files:**
- Modify: `apps/frontend/src/components/teams/panels/IssueDetailPanel.tsx` — body becomes `<IssueDetailPage>`
- Modify: `apps/frontend/src/components/teams/inbox/InboxPage.tsx` — add NewIssueDialog state + open button
- Modify: `apps/frontend/src/components/teams/inbox/InboxToolbar.tsx` — add "New issue" button next to Mark all (or as a primary action)
- Test: extend `apps/frontend/src/__tests__/components/teams/inbox/InboxPage.test.tsx` with one more case

- [ ] **Step 1: Replace IssueDetailPanel body**

```tsx
"use client";

import { IssueDetailPage } from "@/components/teams/issues/IssueDetailPage";

export interface IssueDetailPanelProps {
  issueId: string;
}

export function IssueDetailPanel({ issueId }: IssueDetailPanelProps) {
  return <IssueDetailPage issueId={issueId} />;
}
```

- [ ] **Step 2: Add "New issue" button to InboxToolbar**

In `InboxToolbar.tsx`, add a primary-styled button next to the Mark all as read button (or as a top-level action). Wire via a new prop `onNewIssue: () => void`.

- [ ] **Step 3: Wire in InboxPage**

```tsx
const [newIssueOpen, setNewIssueOpen] = useState(false);

// pass to InboxToolbar:
onNewIssue={() => setNewIssueOpen(true)}

// render the dialog at the bottom of InboxPage:
<NewIssueDialog
  open={newIssueOpen}
  onOpenChange={setNewIssueOpen}
  onCreated={(issueId) => router.push(`/teams/issues/${issueId}`)}
/>
```

- [ ] **Step 4: Tests** — assert New issue button opens dialog; dialog submit calls create + closes.

- [ ] **Step 5: Commit**

```
feat(teams): wire IssueDetailPage in IssueDetailPanel + NewIssueDialog in InboxPage
```

---

## Task 12: Final verification + roadmap update + open PR

- [ ] **Step 1: Run full frontend pnpm test**

```bash
cd apps/frontend && pnpm test 2>&1 | tail -30
```

Pre-existing failures (BotSetupWizard / MyChannelsSection / CreditsPanel) are unrelated and will fail; ignore. NO new failures introduced by this PR.

- [ ] **Step 2: Run lint + typecheck**

```bash
cd apps/frontend && pnpm lint 2>&1 | tail -10
pnpm --filter @isol8/frontend exec tsc --noEmit 2>&1 | grep -E "error" | head
```

Expected: 0 errors for our files.

- [ ] **Step 3: Run backend tests**

```bash
cd apps/backend && uv run pytest tests/unit/services/test_paperclip_admin_client_comments.py tests/unit/routers/teams/test_issue_comments.py -v --no-cov
```

- [ ] **Step 4: Update roadmap row #3**

In `docs/superpowers/specs/2026-05-04-teams-ui-parity-roadmap.md`, update row #3 status: `In progress (3a ✅, 3b ✅, 3c ✅, 3d pending)` → `Done (3a ✅, 3b ✅, 3c ✅, 3d ✅; ApprovalDetail + RunDetail deferred to #3d.2)`. Add the PR number in the PR column.

- [ ] **Step 5: Push + open PR**

```bash
git push -u origin feat/teams-issue-detail
gh pr create --title "feat(teams): port IssueDetailPage + NewIssueDialog (#3d)" --body "..."
```

PR body skeleton:

```
## Summary

Sub-project **#3d** of the [Teams UI parity roadmap](docs/superpowers/specs/2026-05-04-teams-ui-parity-roadmap.md). Replaces ``IssueDetailPanel.tsx``'s 40-line stub with a real IssueDetail page (header + comments thread + properties sidebar). Adds ``NewIssueDialog`` for creating issues from the Inbox empty-state. Closes the Inbox UX loop: user creates an issue → assigns to agent → wakeup fires → issue lands in inbox → user opens detail.

**Scope correction:** Original 4-PR design included ApprovalDetail + AgentRun in #3d. Upstream IssueDetail alone is 3,889 LOC + NewIssueDialog 1,896 LOC; pragmatic v1 = IssueDetail (read + comment + status mutate) + NewIssueDialog. ApprovalDetail + AgentRun defer to a future #3d.2 sub-project (each is reachable as a stub link from #3d). Matches the MVP-subset pattern from #3b/#3c.

## What's new

**BFF additions:**
- ``GET /teams/issues/{id}/comments``, ``POST /teams/issues/{id}/comments``
- ``CreateIssueBody`` / ``PatchIssueBody`` priority enum fixed: ``low|medium|high|urgent`` → ``critical|high|medium|low`` (matches upstream ISSUE_PRIORITIES + our types.ts)

**Frontend ports:**
- ``IssueDetailPage`` (header + comments + properties sidebar)
- ``IssueHeader`` (title editor, status/priority pickers — uses StatusIcon + PriorityIcon from #3b)
- ``IssueComments`` (thread + composer with Cmd+Enter submit)
- ``IssueProperties`` (right sidebar — read-only: status, priority, assignee, project, dates)
- ``NewIssueDialog`` (slim form: title, description, status, priority, project, assignee_agent_id)
- 2 hooks: ``useIssueDetail`` (SWR) + ``useIssueMutations`` (create/update/comment)

**Wiring:**
- ``IssueDetailPanel.tsx`` body → ``<IssueDetailPage issueId={...} />``
- ``InboxToolbar`` gains a "New issue" primary button
- ``InboxPage`` mounts NewIssueDialog; success → ``router.push(/teams/issues/<id>)``

## Out of scope (deferred to #3d.2 or later)

- ApprovalDetail page port
- AgentRun detail page port (still uses 28-line ``RunDetailPanel.tsx`` stub)
- Activity tab, Run ledger, Sub-issues, Plugin slots, Tree controls, Documents, Feedback, File uploads, Image gallery, Interactions, @mentions, Markdown rendering, Live transcripts, Continuation handoff, Workspace pills

## Test plan

- [x] Backend: 5+ tests for admin-client comments + BFF routes
- [x] Frontend: per-component + per-hook unit tests
- [x] Lint + typecheck clean
- [ ] Manual visual verification on dev (deferred — reviewer to validate)

🤖 Generated with [Claude Code](https://claude.com/claude-code)
```

- [ ] **Step 6: Watch CI**

```bash
gh pr checks <pr-number> --repo Isol8AI/isol8
```

DO NOT MERGE. Report back to the controller.

---

## Self-review checklist

- ✅ All 12 tasks have explicit file lists + step-by-step instructions + tests
- ✅ Dependencies flow correctly: BFF (T1-2) → frontend types (T3) → hooks (T4-5) → components (T6-8) → page (T9) → dialog (T10) → wiring (T11) → verification (T12)
- ✅ Per-task commits keep the PR reviewable
- ✅ Roadmap update bundled into Task 12
- ✅ Branch: `feat/teams-issue-detail` per the design
- ✅ Subagents run only their own task's tests; full suite at Task 12
- ✅ Out-of-scope list explicit at top + repeated per task where relevant
- ✅ MIT attribution required on every ported file
- ✅ Vitest explicit imports required on every test file
