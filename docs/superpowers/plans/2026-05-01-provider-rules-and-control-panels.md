# Provider rules + LLM/Credits panels Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Block ChatGPT OAuth provider for organization users (UI + backend), hide the Credits control-panel tab from non-Bedrock users, and redesign the LLM Provider and Credits panels to match the warm-palette card aesthetic used elsewhere in the app.

**Architecture:** Three small slices that ship together as one PR off `feat/provider-rules-and-control-panels`. (A) `ProviderPicker` filters out the `chatgpt_oauth` card when `isOrg`, and `POST /billing/trial-checkout` + `POST /oauth/chatgpt/start` return 403 when the JWT carries `org_id`. (B) `ControlSidebar` reads `provider_choice` via SWR'd `GET /users/me` and hides the `credits` nav item unless the user is on `bedrock_claude`; `ControlPanelRouter` mirrors the gate as defense-in-depth. (C) `LLMPanel` becomes a hero-card layout with the right provider mark + status chip, and `CreditsPanel` becomes a dense card layout aligned with `UsagePanel`. No new dependencies; all utilities (`AuthContext.is_org_context`, `OpenAIIcon`/`AnthropicIcon`, `useCredits`, `useChatGPTOAuth`, shadcn `Checkbox`/`Input`) already exist.

**Tech Stack:** FastAPI + DynamoDB backend (pytest/`async_client`/`AsyncMock`), Next.js 16 + React 19 frontend (vitest + React Testing Library + SWR + Clerk + Tailwind), Turborepo monorepo (pnpm/uv).

**Spec:** `docs/superpowers/specs/2026-05-01-provider-rules-and-control-panels-design.md`

---

## File map

| File | Status | Purpose |
|---|---|---|
| `apps/backend/routers/billing.py` | modify (line ~272 region) | Add `chatgpt_oauth + is_org_context → 403` check at top of `create_trial_checkout` |
| `apps/backend/routers/oauth.py` | modify (function `start`, ~line 41) | Add `is_org_context → 403` check at top of `start` |
| `apps/backend/tests/unit/routers/test_billing.py` | modify | Add 4 new test cases under the trial-checkout class |
| `apps/backend/tests/unit/routers/test_oauth.py` | modify | Add 2 new test cases for `/start` |
| `apps/frontend/src/components/chat/ProvisioningStepper.tsx` | modify (lines 840–979) | Filter `chatgpt_oauth` card, switch header copy "Three"↔"Two", switch grid `md:grid-cols-3`↔`md:grid-cols-2 max-w-3xl mx-auto` |
| `apps/frontend/src/components/chat/__tests__/ProviderPicker.test.tsx` | create | Unit tests for the ProviderPicker filter |
| `apps/frontend/src/components/control/ControlSidebar.tsx` | modify | Add SWR fetch of `/users/me`, gate `credits` item via `BEDROCK_ONLY_PANELS` |
| `apps/frontend/src/components/control/__tests__/ControlSidebar.test.tsx` | create | Unit tests for the sidebar gate |
| `apps/frontend/src/components/control/ControlPanelRouter.tsx` | modify | Active-panel fallback: `panel === "credits" && provider_choice !== "bedrock_claude"` → render OverviewPanel |
| `apps/frontend/src/components/control/__tests__/ControlPanelRouter.test.tsx` | create | Unit tests for the router fallback |
| `apps/frontend/src/components/control/panels/LLMPanel.tsx` | rewrite | Hero + summary card layout per provider; drop the stale `/users/me` comment |
| `apps/frontend/src/components/control/panels/__tests__/LLMPanel.test.tsx` | create | Unit tests for each provider state of the redesigned panel |
| `apps/frontend/src/components/control/panels/CreditsPanel.tsx` | rewrite | Balance + Add credits + Auto-reload card layout; drop `pendingTopUpSecret` debug paragraph |
| `apps/frontend/src/components/control/panels/__tests__/CreditsPanel.test.tsx` | create | Unit tests for balance, quick-pick, auto-reload toggle |

**Working directory for all commands:** `/Users/prasiddhaparthsarthy/Desktop/isol8.nosync/.worktrees/provider-rules`. Branch: `feat/provider-rules-and-control-panels`. Do NOT push without explicit user approval (per the `feedback_no_push_without_approval` memory).

---

## Section A — Block ChatGPT OAuth for org workspaces

### Task 1: Backend — reject `chatgpt_oauth` in `POST /billing/trial-checkout` for org context

**Files:**
- Modify: `apps/backend/routers/billing.py` (function `create_trial_checkout`, lines ~260–325)
- Test: `apps/backend/tests/unit/routers/test_billing.py` (existing `TestTrialCheckout`-style class — find the trial-checkout test class by `grep -n "trial-checkout\|create_trial_checkout" apps/backend/tests/unit/routers/test_billing.py`; if no class exists, create new tests at the bottom of the file matching the file's existing module-level pattern)

- [ ] **Step 1: Read the existing trial-checkout test class to mirror its fixture pattern**

```bash
grep -n "trial-checkout\|trial_checkout\|TrialCheckout\|provider_choice" apps/backend/tests/unit/routers/test_billing.py | head
```

This will show the existing trial-checkout test class (likely named `TestTrialCheckout` or similar) and how it stubs `auth`, `billing_repo`, and `stripe`. Mirror its fixtures and decorators in the new tests below.

- [ ] **Step 2: Add the four failing tests**

In `apps/backend/tests/unit/routers/test_billing.py`, add the following four tests. Place them inside the existing trial-checkout test class if there is one; otherwise add them as module-level `@pytest.mark.asyncio` functions matching the file's other patterns. Reuse whatever `async_client` / billing-account / stripe-mock fixtures the surrounding tests already use (the file already has them — do not invent new ones).

```python
@pytest.mark.asyncio
async def test_trial_checkout_rejects_chatgpt_oauth_for_org(async_client, override_auth_org):
    """Org-context user calling trial-checkout with provider_choice=chatgpt_oauth gets 403."""
    # override_auth_org is the existing fixture that swaps get_current_user to
    # return AuthContext(user_id="u_x", org_id="org_x"). If the file uses a
    # different override pattern (e.g. monkeypatching app.dependency_overrides),
    # follow that pattern instead.
    resp = await async_client.post(
        "/api/v1/billing/trial-checkout",
        json={"provider_choice": "chatgpt_oauth"},
    )
    assert resp.status_code == 403
    assert "organization workspaces" in resp.json()["detail"].lower() or \
           "organization" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_trial_checkout_allows_byo_key_for_org(async_client, override_auth_org, ...existing_stripe_mocks):
    """Org-context user can still pick byo_key — the gate is chatgpt_oauth-only."""
    # Reuse whatever Stripe mock/billing-repo fixture chain the existing
    # `test_trial_checkout_creates_session` (or equivalent) test uses so the
    # call reaches Stripe and returns a checkout_url.
    resp = await async_client.post(
        "/api/v1/billing/trial-checkout",
        json={"provider_choice": "byo_key"},
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_trial_checkout_allows_bedrock_claude_for_org(async_client, override_auth_org, ...existing_stripe_mocks):
    """Org-context user can still pick bedrock_claude."""
    resp = await async_client.post(
        "/api/v1/billing/trial-checkout",
        json={"provider_choice": "bedrock_claude"},
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_trial_checkout_allows_chatgpt_oauth_for_personal(async_client, override_auth_personal, ...existing_stripe_mocks):
    """Personal user (no org_id) can still pick chatgpt_oauth — only orgs are blocked."""
    resp = await async_client.post(
        "/api/v1/billing/trial-checkout",
        json={"provider_choice": "chatgpt_oauth"},
    )
    assert resp.status_code == 200
```

If the existing tests don't expose `override_auth_org` / `override_auth_personal` fixtures, define them in the same file (or in `apps/backend/tests/conftest.py` if cleaner) as:

```python
import pytest
from core.auth import AuthContext, get_current_user

@pytest.fixture
def override_auth_personal(app):
    def _stub() -> AuthContext:
        return AuthContext(user_id="u_x", org_id=None, email="u_x@example.com")
    app.dependency_overrides[get_current_user] = _stub
    yield
    app.dependency_overrides.pop(get_current_user, None)

@pytest.fixture
def override_auth_org(app):
    def _stub() -> AuthContext:
        return AuthContext(user_id="u_x", org_id="org_x", email="u_x@example.com")
    app.dependency_overrides[get_current_user] = _stub
    yield
    app.dependency_overrides.pop(get_current_user, None)
```

(Inspect `core/auth.py` for the exact `AuthContext` dataclass signature — it may take more or fewer kwargs than shown.)

- [ ] **Step 3: Run the four new tests to verify they fail**

```bash
cd apps/backend && uv run pytest tests/unit/routers/test_billing.py -k "rejects_chatgpt_oauth_for_org or allows_byo_key_for_org or allows_bedrock_claude_for_org or allows_chatgpt_oauth_for_personal" -v
```

**Expected:** `test_trial_checkout_rejects_chatgpt_oauth_for_org` FAILS (returns 200 instead of 403). The other three should PASS or fail for unrelated mock-wiring reasons. If they fail with mock errors, fix the fixtures until they pass — those tests are baseline regression coverage, not the change under test.

- [ ] **Step 4: Add the org-block check in the router**

In `apps/backend/routers/billing.py`, find the `create_trial_checkout` function (around line 260). The function already has a 400-on-unknown-provider check at line ~270:

```python
if body.provider_choice not in ("chatgpt_oauth", "byo_key", "bedrock_claude"):
    raise HTTPException(status_code=400, detail="unknown provider_choice")
```

Immediately after that block, **before** the `if auth.is_org_context: require_org_admin(auth)` block at line ~276, add:

```python
# Org-context users cannot pick ChatGPT OAuth — see
# memory/project_chatgpt_oauth_personal_only.md (decision 2026-04-30:
# OpenAI Plus terms forbid reselling; orgs route inference through Bedrock
# or BYOK only). Frontend ProviderPicker hides the card too, but a savvy
# user could call this endpoint directly without server-side enforcement.
if body.provider_choice == "chatgpt_oauth" and auth.is_org_context:
    raise HTTPException(
        status_code=403,
        detail=(
            "ChatGPT OAuth is not available for organization workspaces. "
            "Use Bring-Your-Own-Key or Powered by Claude instead."
        ),
    )
```

- [ ] **Step 5: Run the targeted tests to verify all four pass**

```bash
cd apps/backend && uv run pytest tests/unit/routers/test_billing.py -k "rejects_chatgpt_oauth_for_org or allows_byo_key_for_org or allows_bedrock_claude_for_org or allows_chatgpt_oauth_for_personal" -v
```

**Expected:** All four PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/backend/routers/billing.py apps/backend/tests/unit/routers/test_billing.py apps/backend/tests/conftest.py
git commit -m "feat(billing): block chatgpt_oauth for org workspaces in trial-checkout

Org-context users get 403 when calling POST /billing/trial-checkout with
provider_choice=chatgpt_oauth. byo_key and bedrock_claude continue to work
for orgs; personal users still get chatgpt_oauth as before.

Enforces the 2026-04-30 decision in memory/project_chatgpt_oauth_personal_only.md
(OpenAI Plus terms forbid reselling Plus access).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

(If `apps/backend/tests/conftest.py` was not modified — i.e., you defined the override fixtures in the test file itself — drop it from the `git add` line.)

---

### Task 2: Backend — reject `POST /oauth/chatgpt/start` in org context

**Files:**
- Modify: `apps/backend/routers/oauth.py` (function `start`, around line 41)
- Test: `apps/backend/tests/unit/routers/test_oauth.py`

- [ ] **Step 1: Add two failing tests**

In `apps/backend/tests/unit/routers/test_oauth.py`, append:

```python
@pytest.mark.asyncio
async def test_start_rejects_org_context(async_client, override_auth_org):
    """Org-context user calling /oauth/chatgpt/start gets 403 before any device-code request."""
    # Even with the device-code service mocked to succeed, the router must
    # short-circuit before calling it — assert the mock was NOT awaited.
    fake_resp = DeviceCodeResponse(
        user_code="TEST-1234",
        verification_uri="https://chatgpt.com/codex",
        expires_in=900,
        interval=5,
    )
    with patch(
        "routers.oauth.request_device_code",
        new=AsyncMock(return_value=fake_resp),
    ) as mock_request:
        resp = await async_client.post("/api/v1/oauth/chatgpt/start")
    assert resp.status_code == 403
    assert "organization" in resp.json()["detail"].lower()
    mock_request.assert_not_awaited()


@pytest.mark.asyncio
async def test_start_allows_personal_context(async_client, override_auth_personal):
    """Personal user (no org_id) still reaches the device-code request."""
    fake_resp = DeviceCodeResponse(
        user_code="TEST-1234",
        verification_uri="https://chatgpt.com/codex",
        expires_in=900,
        interval=5,
    )
    with patch(
        "routers.oauth.request_device_code",
        new=AsyncMock(return_value=fake_resp),
    ):
        resp = await async_client.post("/api/v1/oauth/chatgpt/start")
    assert resp.status_code == 200
```

The `override_auth_personal` and `override_auth_org` fixtures from Task 1 should be reusable — if they live in the test file itself rather than `conftest.py`, copy them to this file or move them to `conftest.py` (cleaner) so both Task 1 and Task 2 share them.

- [ ] **Step 2: Run the two new tests to verify they fail**

```bash
cd apps/backend && uv run pytest tests/unit/routers/test_oauth.py -k "rejects_org_context or allows_personal_context" -v
```

**Expected:** `test_start_rejects_org_context` FAILS (returns 200, not 403). `test_start_allows_personal_context` PASSES (the existing logic already accepts personal callers).

- [ ] **Step 3: Add the org-block check in the router**

In `apps/backend/routers/oauth.py`, the `start` function is around line 41:

```python
async def start(ctx: AuthContext = Depends(get_current_user)):
    ...
```

Inside the function, before the existing try/except that wraps the device-code request, add:

```python
async def start(ctx: AuthContext = Depends(get_current_user)):
    # Org-context users cannot use ChatGPT OAuth — see
    # memory/project_chatgpt_oauth_personal_only.md. Belt-and-suspenders to
    # the trial-checkout block: a future "reconnect" flow that calls this
    # endpoint outside trial-checkout still won't bypass the rule.
    if ctx.is_org_context:
        raise HTTPException(
            status_code=403,
            detail="ChatGPT OAuth is not available for organization workspaces.",
        )
    # ... existing body unchanged
```

(Confirm `HTTPException` is already imported at the top of the file — line 14 of the snippet I read showed `from fastapi import APIRouter, Depends, HTTPException`, so it is.)

- [ ] **Step 4: Run the two tests to verify they pass**

```bash
cd apps/backend && uv run pytest tests/unit/routers/test_oauth.py -k "rejects_org_context or allows_personal_context" -v
```

**Expected:** Both PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/backend/routers/oauth.py apps/backend/tests/unit/routers/test_oauth.py
git commit -m "feat(oauth): reject /oauth/chatgpt/start in org context

Returns 403 before requesting a device code when the JWT carries org_id.
Belt-and-suspenders to the trial-checkout block from the previous commit:
prevents a future reconnect/re-link flow from bypassing the rule.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Frontend — filter `chatgpt_oauth` card from `ProviderPicker` for orgs

**Files:**
- Modify: `apps/frontend/src/components/chat/ProvisioningStepper.tsx` (function `ProviderPicker`, lines 840–979)
- Test: `apps/frontend/src/components/chat/__tests__/ProviderPicker.test.tsx` (new file)

- [ ] **Step 1: Create the failing test file**

Create `apps/frontend/src/components/chat/__tests__/ProviderPicker.test.tsx`:

```tsx
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import React from "react";

// The ProviderPicker is currently defined as a non-exported function inside
// ProvisioningStepper.tsx. To test it directly we'll export it from that
// file (see Step 3 of this task) and import it here. If you'd rather not
// add a named export, render the parent ProvisioningStepper and assert
// the same behavior — the test names below stay the same.
import { ProviderPicker } from "../ProvisioningStepper";

// useApi is invoked inside the component on Pick — stub it.
vi.mock("@/lib/api", () => ({
  useApi: () => ({
    post: vi.fn(),
    get: vi.fn(),
  }),
}));

describe("ProviderPicker", () => {
  it("renders all three provider cards for personal users", () => {
    render(<ProviderPicker isOrg={false} />);
    expect(screen.getByText("Sign in with ChatGPT")).toBeInTheDocument();
    expect(screen.getByText("Bring your own API key")).toBeInTheDocument();
    expect(screen.getByText("Powered by Claude")).toBeInTheDocument();
  });

  it("hides the ChatGPT OAuth card for org users", () => {
    render(<ProviderPicker isOrg={true} orgName="Acme" />);
    expect(screen.queryByText("Sign in with ChatGPT")).not.toBeInTheDocument();
    expect(screen.getByText("Bring your own API key")).toBeInTheDocument();
    expect(screen.getByText("Powered by Claude")).toBeInTheDocument();
  });

  it('uses "Three ways" headline for personal users', () => {
    render(<ProviderPicker isOrg={false} />);
    expect(screen.getByRole("heading", { level: 2 })).toHaveTextContent(
      "One price. Three ways to power it.",
    );
  });

  it('uses "Two ways" headline for org users', () => {
    render(<ProviderPicker isOrg={true} orgName="Acme" />);
    expect(screen.getByRole("heading", { level: 2 })).toHaveTextContent(
      "One price. Two ways to power it.",
    );
  });

  it("uses 2-col centered grid for org users and 3-col grid otherwise", () => {
    const { container: orgContainer } = render(
      <ProviderPicker isOrg={true} orgName="Acme" />,
    );
    expect(orgContainer.querySelector(".md\\:grid-cols-2")).toBeInTheDocument();
    expect(orgContainer.querySelector(".max-w-3xl")).toBeInTheDocument();

    const { container: personalContainer } = render(<ProviderPicker isOrg={false} />);
    expect(personalContainer.querySelector(".md\\:grid-cols-3")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd apps/frontend && pnpm test --run src/components/chat/__tests__/ProviderPicker.test.tsx
```

**Expected:** Either ALL tests fail with `ProviderPicker is not exported` (Step 3 fixes that) OR if you chose to render `ProvisioningStepper` instead, the org-specific tests fail because the filter doesn't exist yet.

- [ ] **Step 3: Edit `ProvisioningStepper.tsx`**

Open `apps/frontend/src/components/chat/ProvisioningStepper.tsx`. Two edits inside the `ProviderPicker` function (currently runs lines 840–979).

(a) Change the function declaration from local to exported so the test can import it:

```tsx
// before — line 840
function ProviderPicker({ isOrg, orgName }: { isOrg: boolean; orgName?: string }) {

// after
export function ProviderPicker({ isOrg, orgName }: { isOrg: boolean; orgName?: string }) {
```

(b) After the existing `cards` array literal (ends ~line 915), derive the visible subset:

```tsx
const cards: Card[] = [
  // ... existing three card literals stay as-is
];

// NEW
const visibleCards = isOrg
  ? cards.filter((c) => c.id !== "chatgpt_oauth")
  : cards;
```

(c) The h2 currently reads `"One price. Three ways to power it."`. Replace it (around line 925):

```tsx
<h2 className="text-2xl font-semibold tracking-tight text-[#1a1a1a] font-lora">
  One price. {isOrg ? "Two" : "Three"} ways to power it.
</h2>
```

(d) The grid wrapper currently reads:

```tsx
<div className="grid grid-cols-1 md:grid-cols-3 gap-4">
```

Replace with:

```tsx
<div
  className={
    "grid grid-cols-1 gap-4 " +
    (isOrg ? "md:grid-cols-2 max-w-3xl mx-auto" : "md:grid-cols-3")
  }
>
```

(e) Inside the grid, change `cards.map(...)` to `visibleCards.map(...)`.

No other change to ProviderPicker — the rest of the body, the `handlePick` callback, and the card-rendering JSX stay identical.

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd apps/frontend && pnpm test --run src/components/chat/__tests__/ProviderPicker.test.tsx
```

**Expected:** All five tests PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/frontend/src/components/chat/ProvisioningStepper.tsx \
        apps/frontend/src/components/chat/__tests__/ProviderPicker.test.tsx
git commit -m "feat(onboarding): hide ChatGPT OAuth card from ProviderPicker for orgs

When the onboarding wizard is rendered in org context (isOrg=true), the
ChatGPT OAuth card is filtered out, the headline switches to 'Two ways
to power it', and the grid centers two cards in a max-w-3xl container
instead of leaving an empty third column. Mirrors the backend 403s
shipped in the previous commits.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Section B — Hide Credits sidebar item for non-Bedrock users

### Task 4: `ControlSidebar` gates the `credits` nav item by `provider_choice`

**Files:**
- Modify: `apps/frontend/src/components/control/ControlSidebar.tsx`
- Test: `apps/frontend/src/components/control/__tests__/ControlSidebar.test.tsx` (new file)

- [ ] **Step 1: Create the failing test file**

Create `apps/frontend/src/components/control/__tests__/ControlSidebar.test.tsx`:

```tsx
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import React from "react";
import { ControlSidebar } from "../ControlSidebar";

// SWR mock: each test seeds a different /users/me response.
const mockSWRData = vi.fn();
vi.mock("swr", () => ({
  default: () => ({ data: mockSWRData(), error: null, isLoading: false, mutate: vi.fn() }),
}));

vi.mock("@/lib/api", () => ({
  useApi: () => ({
    get: vi.fn(),
    post: vi.fn(),
  }),
}));

vi.mock("@clerk/nextjs", () => ({
  useOrganization: () => ({ membership: null }),
}));

describe("ControlSidebar", () => {
  beforeEach(() => {
    mockSWRData.mockReset();
  });

  it("shows the Credits item for bedrock_claude users", () => {
    mockSWRData.mockReturnValue({ provider_choice: "bedrock_claude" });
    render(<ControlSidebar activePanel="overview" />);
    expect(screen.getByText("Credits")).toBeInTheDocument();
  });

  it("hides the Credits item for byo_key users", () => {
    mockSWRData.mockReturnValue({ provider_choice: "byo_key" });
    render(<ControlSidebar activePanel="overview" />);
    expect(screen.queryByText("Credits")).not.toBeInTheDocument();
  });

  it("hides the Credits item for chatgpt_oauth users", () => {
    mockSWRData.mockReturnValue({ provider_choice: "chatgpt_oauth" });
    render(<ControlSidebar activePanel="overview" />);
    expect(screen.queryByText("Credits")).not.toBeInTheDocument();
  });

  it("shows the Credits item while /users/me is still loading (undefined)", () => {
    mockSWRData.mockReturnValue(undefined);
    render(<ControlSidebar activePanel="overview" />);
    // Loading state: render the item rather than flash it on resolve.
    expect(screen.getByText("Credits")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd apps/frontend && pnpm test --run src/components/control/__tests__/ControlSidebar.test.tsx
```

**Expected:** Tests for `byo_key` and `chatgpt_oauth` FAIL (Credits is still in the DOM).

- [ ] **Step 3: Edit `ControlSidebar.tsx`**

Replace the contents of `apps/frontend/src/components/control/ControlSidebar.tsx` with:

```tsx
"use client";

import {
  LayoutDashboard,
  Bot,
  Sparkles,
  MessageSquare,
  Clock,
  BarChart3,
  Plug,
  Wallet,
} from "lucide-react";
import { useOrganization } from "@clerk/nextjs";
import useSWR from "swr";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { useApi } from "@/lib/api";
import { cn } from "@/lib/utils";

interface ControlSidebarProps {
  activePanel?: string;
  onPanelChange?: (panel: string) => void;
}

type UserMeResponse = {
  user_id?: string;
  provider_choice?: "chatgpt_oauth" | "byo_key" | "bedrock_claude" | null;
  byo_provider?: "openai" | "anthropic" | null;
};

const NAV_ITEMS = [
  { key: "overview", label: "Overview", icon: LayoutDashboard },
  { key: "agents", label: "Agents", icon: Bot },
  { key: "skills", label: "Skills", icon: Sparkles },
  { key: "sessions", label: "Sessions", icon: MessageSquare },
  { key: "cron", label: "Cron Jobs", icon: Clock },
  { key: "usage", label: "Usage", icon: BarChart3 },
  { key: "llm", label: "LLM Provider", icon: Plug },
  { key: "credits", label: "Credits", icon: Wallet },
];

// Panels hidden from non-admin org members
const ADMIN_ONLY_PANELS = new Set(["usage"]);

// Panels that only apply when the user is on the Bedrock-provided plan.
// byo_key + chatgpt_oauth users manage billing directly with their provider.
const BEDROCK_ONLY_PANELS = new Set(["credits"]);

export function ControlSidebar({ activePanel, onPanelChange }: ControlSidebarProps) {
  const api = useApi();
  const { membership } = useOrganization();
  const isOrgAdmin = !membership || membership.role === "org:admin";

  const { data: me } = useSWR<UserMeResponse>(
    "/users/me",
    () => api.get("/users/me") as Promise<UserMeResponse>,
  );
  // While loading, treat the user as Bedrock-eligible so the Credits item
  // doesn't flash on resolve. Once provider_choice resolves to a non-Bedrock
  // value, the item disappears.
  const isBedrockUser = me === undefined || me.provider_choice === "bedrock_claude";

  return (
    <ScrollArea className="flex-1 px-3 py-2">
      <div className="space-y-1">
        {NAV_ITEMS.map(({ key, label, icon: Icon }) => {
          if (ADMIN_ONLY_PANELS.has(key) && !isOrgAdmin) return null;
          if (BEDROCK_ONLY_PANELS.has(key) && !isBedrockUser) return null;
          return (
            <Button
              key={key}
              variant="ghost"
              className={cn(
                "w-full justify-start gap-2 font-normal transition-all h-auto py-1.5",
                activePanel === key
                  ? "bg-white text-[#1a1a1a] shadow-sm"
                  : "text-[#8a8578] hover:text-[#1a1a1a] hover:bg-white/60",
              )}
              onClick={() => onPanelChange?.(key)}
            >
              <Icon className="h-4 w-4 flex-shrink-0 opacity-70" />
              <span className="truncate">{label}</span>
            </Button>
          );
        })}
      </div>
    </ScrollArea>
  );
}
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd apps/frontend && pnpm test --run src/components/control/__tests__/ControlSidebar.test.tsx
```

**Expected:** All four tests PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/frontend/src/components/control/ControlSidebar.tsx \
        apps/frontend/src/components/control/__tests__/ControlSidebar.test.tsx
git commit -m "feat(control): hide Credits sidebar item from non-Bedrock users

byo_key and chatgpt_oauth users manage their billing on the provider's
own site — there's no Isol8 credit ledger to expose for them. Sidebar
keeps the Credits item visible while /users/me is loading so the layout
doesn't shift on resolve.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: `ControlPanelRouter` falls back to Overview when `panel === "credits"` and user isn't Bedrock

**Files:**
- Modify: `apps/frontend/src/components/control/ControlPanelRouter.tsx`
- Test: `apps/frontend/src/components/control/__tests__/ControlPanelRouter.test.tsx` (new file)

This is defense-in-depth. The sidebar is the primary gate; this guard catches a user who was on the Credits panel when their `provider_choice` flipped (rare, but the URL/state can still drive `panel === "credits"`).

- [ ] **Step 1: Create the failing test file**

Create `apps/frontend/src/components/control/__tests__/ControlPanelRouter.test.tsx`:

```tsx
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import React from "react";
import { ControlPanelRouter } from "../ControlPanelRouter";

const mockSWRData = vi.fn();
vi.mock("swr", () => ({
  default: () => ({ data: mockSWRData(), error: null, isLoading: false, mutate: vi.fn() }),
}));

vi.mock("@/lib/api", () => ({
  useApi: () => ({ get: vi.fn(), post: vi.fn() }),
}));

// Stub OverviewPanel and CreditsPanel so we can assert which one mounts
// without dragging their full deps into the test sandbox.
vi.mock("../panels/OverviewPanel", () => ({
  OverviewPanel: () => <div data-testid="overview-panel" />,
}));
vi.mock("../panels/CreditsPanel", () => ({
  CreditsPanel: () => <div data-testid="credits-panel" />,
}));
// All other panels can stub-render too — they shouldn't mount in these
// tests but the import graph evaluates the module.
vi.mock("../panels/InstancesPanel", () => ({ InstancesPanel: () => null }));
vi.mock("../panels/SessionsPanel", () => ({ SessionsPanel: () => null }));
vi.mock("../panels/UsagePanel", () => ({ UsagePanel: () => null }));
vi.mock("../panels/CronPanel", () => ({ CronPanel: () => null }));
vi.mock("../panels/AgentsPanel", () => ({ AgentsPanel: () => null }));
vi.mock("../panels/SkillsPanel", () => ({ SkillsPanel: () => null }));
vi.mock("../panels/NodesPanel", () => ({ NodesPanel: () => null }));
vi.mock("../panels/ConfigPanel", () => ({ ConfigPanel: () => null }));
vi.mock("../panels/DebugPanel", () => ({ DebugPanel: () => null }));
vi.mock("../panels/LogsPanel", () => ({ LogsPanel: () => null }));
vi.mock("../panels/LLMPanel", () => ({ LLMPanel: () => null }));

describe("ControlPanelRouter", () => {
  beforeEach(() => {
    mockSWRData.mockReset();
  });

  it("renders CreditsPanel when panel='credits' and user is bedrock_claude", () => {
    mockSWRData.mockReturnValue({ provider_choice: "bedrock_claude" });
    render(<ControlPanelRouter panel="credits" />);
    expect(screen.getByTestId("credits-panel")).toBeInTheDocument();
  });

  it("falls back to OverviewPanel when panel='credits' and user is byo_key", () => {
    mockSWRData.mockReturnValue({ provider_choice: "byo_key" });
    render(<ControlPanelRouter panel="credits" />);
    expect(screen.getByTestId("overview-panel")).toBeInTheDocument();
    expect(screen.queryByTestId("credits-panel")).not.toBeInTheDocument();
  });

  it("falls back to OverviewPanel when panel='credits' and user is chatgpt_oauth", () => {
    mockSWRData.mockReturnValue({ provider_choice: "chatgpt_oauth" });
    render(<ControlPanelRouter panel="credits" />);
    expect(screen.getByTestId("overview-panel")).toBeInTheDocument();
  });

  it("renders CreditsPanel while /users/me is still loading", () => {
    mockSWRData.mockReturnValue(undefined);
    render(<ControlPanelRouter panel="credits" />);
    expect(screen.getByTestId("credits-panel")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd apps/frontend && pnpm test --run src/components/control/__tests__/ControlPanelRouter.test.tsx
```

**Expected:** The two "falls back to OverviewPanel" tests FAIL (CreditsPanel still renders).

- [ ] **Step 3: Edit `ControlPanelRouter.tsx`**

Replace the contents of `apps/frontend/src/components/control/ControlPanelRouter.tsx` with:

```tsx
"use client";

import useSWR from "swr";
import { useApi } from "@/lib/api";
import { OverviewPanel } from "./panels/OverviewPanel";
import { InstancesPanel } from "./panels/InstancesPanel";
import { SessionsPanel } from "./panels/SessionsPanel";
import { UsagePanel } from "./panels/UsagePanel";
import { CronPanel } from "./panels/CronPanel";
import { AgentsPanel } from "./panels/AgentsPanel";
import { SkillsPanel } from "./panels/SkillsPanel";
import { NodesPanel } from "./panels/NodesPanel";
import { ConfigPanel } from "./panels/ConfigPanel";
import { DebugPanel } from "./panels/DebugPanel";
import { LogsPanel } from "./panels/LogsPanel";
import { LLMPanel } from "./panels/LLMPanel";
import { CreditsPanel } from "./panels/CreditsPanel";


interface ControlPanelRouterProps {
  panel: string;
}

type UserMeResponse = {
  provider_choice?: "chatgpt_oauth" | "byo_key" | "bedrock_claude" | null;
};

const PANELS: Record<string, React.ComponentType> = {
  overview: OverviewPanel,
  instances: InstancesPanel,
  sessions: SessionsPanel,
  usage: UsagePanel,
  cron: CronPanel,
  agents: AgentsPanel,
  skills: SkillsPanel,
  nodes: NodesPanel,
  config: ConfigPanel,
  debug: DebugPanel,
  logs: LogsPanel,
  llm: LLMPanel,
  credits: CreditsPanel,
};

export function ControlPanelRouter({ panel }: ControlPanelRouterProps) {
  const api = useApi();
  const { data: me } = useSWR<UserMeResponse>(
    "/users/me",
    () => api.get("/users/me") as Promise<UserMeResponse>,
  );

  // Defense-in-depth: the sidebar already hides the Credits item for
  // non-Bedrock users, but if the parent's panel state still reads
  // "credits" (URL param, stale prop), fall back to the overview rather
  // than render a panel the user isn't supposed to see.
  let resolvedPanel = panel;
  if (resolvedPanel === "credits" && me !== undefined && me.provider_choice !== "bedrock_claude") {
    resolvedPanel = "overview";
  }

  const Panel = PANELS[resolvedPanel] || PANELS.overview;
  return <Panel />;
}
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd apps/frontend && pnpm test --run src/components/control/__tests__/ControlPanelRouter.test.tsx
```

**Expected:** All four tests PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/frontend/src/components/control/ControlPanelRouter.tsx \
        apps/frontend/src/components/control/__tests__/ControlPanelRouter.test.tsx
git commit -m "feat(control): fall back to overview when Credits is shown to non-Bedrock

Defense-in-depth alongside the sidebar gate: if the parent's panel state
still drives panel='credits' for a user who flipped to byo_key or
chatgpt_oauth, render OverviewPanel instead of letting CreditsPanel mount.
Loading state preserves CreditsPanel to avoid layout flash.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Section C — Redesign LLM Provider and Credits panels

### Task 6: Rewrite `LLMPanel.tsx` with hero + summary card layout

**Files:**
- Rewrite: `apps/frontend/src/components/control/panels/LLMPanel.tsx`
- Test: `apps/frontend/src/components/control/panels/__tests__/LLMPanel.test.tsx` (new file)

- [ ] **Step 1: Create the failing test file**

Create `apps/frontend/src/components/control/panels/__tests__/LLMPanel.test.tsx`:

```tsx
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import React from "react";
import { LLMPanel } from "../LLMPanel";

const mockSWRData = vi.fn();
const mockMutate = vi.fn();
vi.mock("swr", () => ({
  default: () => ({ data: mockSWRData(), error: null, isLoading: false, mutate: mockMutate }),
}));

const mockApiPut = vi.fn();
vi.mock("@/lib/api", () => ({
  useApi: () => ({
    get: vi.fn(),
    post: vi.fn(),
    put: mockApiPut,
  }),
}));

const mockDisconnect = vi.fn();
vi.mock("@/hooks/useChatGPTOAuth", () => ({
  useChatGPTOAuth: () => ({ disconnect: mockDisconnect }),
}));

describe("LLMPanel", () => {
  beforeEach(() => {
    mockSWRData.mockReset();
    mockMutate.mockReset();
    mockApiPut.mockReset();
    mockDisconnect.mockReset();
  });

  it("renders the ChatGPT hero + Connected status + Disconnect button for chatgpt_oauth", () => {
    mockSWRData.mockReturnValue({ provider_choice: "chatgpt_oauth" });
    render(<LLMPanel />);
    expect(screen.getByText("Sign in with ChatGPT")).toBeInTheDocument();
    expect(screen.getByText("Connected")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /disconnect/i })).toBeInTheDocument();
  });

  it("calls disconnect and revalidates SWR when Disconnect is clicked", async () => {
    mockSWRData.mockReturnValue({ provider_choice: "chatgpt_oauth" });
    mockDisconnect.mockResolvedValueOnce(undefined);
    render(<LLMPanel />);
    fireEvent.click(screen.getByRole("button", { name: /disconnect/i }));
    await waitFor(() => expect(mockDisconnect).toHaveBeenCalledTimes(1));
    expect(mockMutate).toHaveBeenCalled();
  });

  it("renders the OpenAI hero + Replace key form for byo_key + openai", () => {
    mockSWRData.mockReturnValue({ provider_choice: "byo_key", byo_provider: "openai" });
    render(<LLMPanel />);
    expect(screen.getByText("Bring your own OpenAI key")).toBeInTheDocument();
    expect(screen.getByPlaceholderText(/sk-proj-/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /save/i })).toBeInTheDocument();
  });

  it("renders the Anthropic hero for byo_key + anthropic", () => {
    mockSWRData.mockReturnValue({ provider_choice: "byo_key", byo_provider: "anthropic" });
    render(<LLMPanel />);
    expect(screen.getByText("Bring your own Anthropic key")).toBeInTheDocument();
    expect(screen.getByPlaceholderText(/sk-ant-/)).toBeInTheDocument();
  });

  it("renders the Bedrock hero + Manage credits button for bedrock_claude", () => {
    mockSWRData.mockReturnValue({ provider_choice: "bedrock_claude" });
    render(<LLMPanel />);
    expect(screen.getByText("Powered by Claude")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /manage credits/i })).toBeInTheDocument();
  });

  it("renders the empty-state when provider_choice is null", () => {
    mockSWRData.mockReturnValue({ provider_choice: null });
    render(<LLMPanel />);
    expect(screen.getByText(/haven't picked a provider/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /re-onboard/i })).toBeInTheDocument();
  });

  it("surfaces a save error from PUT /settings/keys/{provider}", async () => {
    mockSWRData.mockReturnValue({ provider_choice: "byo_key", byo_provider: "openai" });
    mockApiPut.mockRejectedValueOnce(new Error("Invalid key"));
    render(<LLMPanel />);
    const input = screen.getByPlaceholderText(/sk-proj-/);
    fireEvent.change(input, { target: { value: "sk-proj-bad" } });
    fireEvent.click(screen.getByRole("button", { name: /save/i }));
    await waitFor(() => expect(screen.getByText("Invalid key")).toBeInTheDocument());
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd apps/frontend && pnpm test --run src/components/control/panels/__tests__/LLMPanel.test.tsx
```

**Expected:** Most tests fail because the new copy ("Bring your own OpenAI key", "Manage credits", "Connected" status chip, etc.) doesn't exist in the current panel.

- [ ] **Step 3: Rewrite `LLMPanel.tsx`**

Replace the contents of `apps/frontend/src/components/control/panels/LLMPanel.tsx` with:

```tsx
"use client";

import { useState } from "react";
import Link from "next/link";
import useSWR from "swr";
import { useApi } from "@/lib/api";
import { useChatGPTOAuth } from "@/hooks/useChatGPTOAuth";
import { OpenAIIcon, AnthropicIcon } from "@/components/chat/ProviderIcons";
import { Input } from "@/components/ui/input";

type ProviderChoice = "chatgpt_oauth" | "byo_key" | "bedrock_claude";
type ByoProvider = "openai" | "anthropic";

type UserData = {
  provider_choice?: ProviderChoice | null;
  byo_provider?: ByoProvider | null;
};

const HERO_TILE = "h-12 w-12 rounded-lg bg-[#f3efe6] flex items-center justify-center flex-shrink-0";
const ACTION_CARD = "rounded-lg border border-[#e0dbd0] bg-white p-4 space-y-3";
const EYEBROW = "text-[10px] uppercase tracking-wider text-[#8a8578]/60";

function StatusChip({ label }: { label: string }) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full bg-[#06402B]/10 text-[#06402B] px-2 py-0.5 text-xs font-medium">
      <span className="h-1.5 w-1.5 rounded-full bg-[#06402B]" />
      {label}
    </span>
  );
}

function HeroCard({
  icon,
  title,
  subtitle,
  status,
}: {
  icon: React.ReactNode;
  title: string;
  subtitle: string;
  status: string;
}) {
  return (
    <div className="rounded-xl border border-[#e0dbd0] bg-white p-6 flex items-center gap-4">
      <div className={HERO_TILE}>{icon}</div>
      <div className="flex-1 min-w-0">
        <h3 className="font-medium text-[#1a1a1a]">{title}</h3>
        <p className="text-sm text-[#8a8578] truncate">{subtitle}</p>
      </div>
      <StatusChip label={status} />
    </div>
  );
}

function ChatGPTOAuthBlock({ onDisconnected }: { onDisconnected: () => void }) {
  const { disconnect } = useChatGPTOAuth();
  const [busy, setBusy] = useState(false);

  const handleDisconnect = async () => {
    setBusy(true);
    try {
      await disconnect();
      onDisconnected();
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <HeroCard
        icon={<OpenAIIcon size={32} />}
        title="Sign in with ChatGPT"
        subtitle="Inference via your ChatGPT account"
        status="Connected"
      />
      <div className={ACTION_CARD}>
        <span className={EYEBROW}>Account</span>
        <p className="text-sm text-[#1a1a1a]">Connected via OAuth</p>
        <button
          onClick={handleDisconnect}
          disabled={busy}
          className="rounded-md border border-[#e0dbd0] text-[#1a1a1a] hover:bg-[#f3efe6] px-3 py-1.5 text-sm disabled:opacity-50"
        >
          {busy ? "Disconnecting…" : "Disconnect"}
        </button>
      </div>
    </>
  );
}

function ByoKeyBlock({
  byoProvider,
  onReplaced,
}: {
  byoProvider: ByoProvider;
  onReplaced: () => void;
}) {
  const isOpenAI = byoProvider === "openai";
  const title = isOpenAI ? "Bring your own OpenAI key" : "Bring your own Anthropic key";
  const icon = isOpenAI ? <OpenAIIcon size={32} /> : <AnthropicIcon size={32} />;

  return (
    <>
      <HeroCard
        icon={icon}
        title={title}
        subtitle="Your key, your billing"
        status="Active"
      />
      <div className={ACTION_CARD}>
        <span className={EYEBROW}>API key</span>
        <p className="text-xs text-[#8a8578]">
          Stored encrypted in AWS Secrets Manager. Paste a new key to rotate.
        </p>
        <ReplaceKeyForm currentProvider={byoProvider} onReplaced={onReplaced} />
      </div>
    </>
  );
}

function BedrockBlock({ onManageCredits }: { onManageCredits: () => void }) {
  return (
    <>
      <HeroCard
        icon={<AnthropicIcon size={32} />}
        title="Powered by Claude"
        subtitle="Anthropic Claude via AWS Bedrock"
        status="Active"
      />
      <div className={ACTION_CARD}>
        <span className={EYEBROW}>Billing</span>
        <p className="text-sm text-[#1a1a1a]">
          Manage your Claude credits and auto-reload settings.
        </p>
        <button
          onClick={onManageCredits}
          className="rounded-full bg-[#06402B] hover:bg-[#0a5c3e] text-white px-4 py-2 text-sm"
        >
          Manage credits →
        </button>
      </div>
    </>
  );
}

function EmptyStateCard() {
  return (
    <div className={ACTION_CARD}>
      <p className="text-sm text-[#1a1a1a]">You haven&apos;t picked a provider yet.</p>
      <Link
        href="/onboarding"
        className="inline-flex rounded-full bg-[#06402B] hover:bg-[#0a5c3e] text-white px-4 py-2 text-sm"
      >
        Re-onboard →
      </Link>
    </div>
  );
}

interface LLMPanelProps {
  onPanelChange?: (panel: string) => void;
}

export function LLMPanel({ onPanelChange }: LLMPanelProps) {
  const api = useApi();
  const { data: user, mutate } = useSWR<UserData | null>(
    "/users/me",
    (p: string) => api.get(p) as Promise<UserData | null>,
  );

  if (!user) return <div className="p-6 text-sm">Loading…</div>;

  const handleManageCredits = () => {
    if (onPanelChange) onPanelChange("credits");
    else if (typeof window !== "undefined") window.location.href = "/chat?panel=credits";
  };

  return (
    <div className="p-6 space-y-6">
      <h2 className="text-lg font-semibold">LLM Provider</h2>

      {user.provider_choice === "chatgpt_oauth" && (
        <ChatGPTOAuthBlock onDisconnected={() => mutate()} />
      )}

      {user.provider_choice === "byo_key" && user.byo_provider && (
        <ByoKeyBlock byoProvider={user.byo_provider} onReplaced={() => mutate()} />
      )}

      {user.provider_choice === "bedrock_claude" && (
        <BedrockBlock onManageCredits={handleManageCredits} />
      )}

      {!user.provider_choice && <EmptyStateCard />}
    </div>
  );
}

function ReplaceKeyForm({
  currentProvider,
  onReplaced,
}: {
  currentProvider: ByoProvider;
  onReplaced: () => void;
}) {
  const api = useApi();
  const [apiKey, setApiKey] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await api.put(`/settings/keys/${currentProvider}`, { api_key: apiKey });
      setApiKey("");
      onReplaced();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't save key");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="flex flex-col gap-2">
      <form onSubmit={submit} className="flex gap-2">
        <Input
          type="password"
          value={apiKey}
          onChange={(e) => setApiKey(e.target.value)}
          placeholder={currentProvider === "openai" ? "sk-proj-…" : "sk-ant-…"}
          className="flex-1 font-mono text-sm"
        />
        <button
          type="submit"
          disabled={submitting || !apiKey}
          className="rounded-full bg-[#06402B] hover:bg-[#0a5c3e] text-white px-4 py-2 text-sm disabled:opacity-50"
        >
          Save
        </button>
      </form>
      {error && <p className="text-sm text-red-600">{error}</p>}
    </div>
  );
}
```

Note: this rewrite drops the stale module-level comment about `/users/me` not existing — the endpoint exists (`apps/backend/routers/users.py:80–105` returns the right shape).

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd apps/frontend && pnpm test --run src/components/control/panels/__tests__/LLMPanel.test.tsx
```

**Expected:** All seven tests PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/frontend/src/components/control/panels/LLMPanel.tsx \
        apps/frontend/src/components/control/panels/__tests__/LLMPanel.test.tsx
git commit -m "feat(control): redesign LLM Provider panel — hero + summary card

Switches LLMPanel from raw text + tiny button to a hero card (provider
mark + title + status chip) plus a per-provider action card. Each
provider gets the right brand mark from ProviderIcons (OpenAI for
ChatGPT and BYO-OpenAI, Anthropic for BYO-Anthropic and Bedrock). The
ReplaceKeyForm now uses the shadcn Input and matches the warm-palette
button style; the Codex P2 error-surfacing fix is preserved. Empty
state links to /onboarding. Stale '/users/me does not exist' comment
deleted — endpoint has been live since Plan 3 of the trial cutover.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: Rewrite `CreditsPanel.tsx` with dense, UsagePanel-aligned layout

**Files:**
- Rewrite: `apps/frontend/src/components/control/panels/CreditsPanel.tsx`
- Test: `apps/frontend/src/components/control/panels/__tests__/CreditsPanel.test.tsx` (new file)

- [ ] **Step 1: Inspect `useCredits` hook signature so the test mocks the right shape**

```bash
grep -n "export\|return\|balance\|startTopUp\|setAutoReload\|refresh" apps/frontend/src/hooks/useCredits.ts
```

Confirm the return shape (likely `{ balance, startTopUp, setAutoReload, refresh }` per the spec). If the hook uses different field names, adjust the test mock and the panel component to match.

- [ ] **Step 2: Create the failing test file**

Create `apps/frontend/src/components/control/panels/__tests__/CreditsPanel.test.tsx`:

```tsx
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import React from "react";
import { CreditsPanel } from "../CreditsPanel";

const mockBalance = vi.fn();
const mockStartTopUp = vi.fn();
const mockSetAutoReload = vi.fn();
const mockRefresh = vi.fn();
vi.mock("@/hooks/useCredits", () => ({
  useCredits: () => ({
    balance: mockBalance(),
    startTopUp: mockStartTopUp,
    setAutoReload: mockSetAutoReload,
    refresh: mockRefresh,
  }),
}));

describe("CreditsPanel", () => {
  beforeEach(() => {
    mockBalance.mockReset();
    mockStartTopUp.mockReset();
    mockSetAutoReload.mockReset();
    mockRefresh.mockReset();
  });

  it("renders the BALANCE eyebrow + dollar balance from the hook", () => {
    mockBalance.mockReturnValue({ balance_dollars: "12.50", balance_microcents: 12_500_000 });
    render(<CreditsPanel />);
    expect(screen.getByText("BALANCE")).toBeInTheDocument();
    expect(screen.getByText("$12.50")).toBeInTheDocument();
  });

  it("shows $0.00 placeholder when balance is null", () => {
    mockBalance.mockReturnValue(null);
    render(<CreditsPanel />);
    expect(screen.getByText("$0.00")).toBeInTheDocument();
  });

  it("toggles the active style on quick-pick buttons", () => {
    mockBalance.mockReturnValue({ balance_dollars: "0.00", balance_microcents: 0 });
    render(<CreditsPanel />);
    const fiftyButton = screen.getByRole("button", { name: /\$50/ });
    fireEvent.click(fiftyButton);
    expect(fiftyButton.className).toContain("border-[#06402B]");
  });

  it("calls startTopUp with the selected amount when Add is clicked", async () => {
    mockBalance.mockReturnValue({ balance_dollars: "0.00", balance_microcents: 0 });
    mockStartTopUp.mockResolvedValueOnce({ client_secret: "pi_xxx" });
    render(<CreditsPanel />);
    fireEvent.click(screen.getByRole("button", { name: /\$50/ }));
    fireEvent.click(screen.getByRole("button", { name: /add \$50/i }));
    await waitFor(() => expect(mockStartTopUp).toHaveBeenCalledWith(5000));
  });

  it("reveals threshold + amount inputs when Auto-reload is enabled", () => {
    mockBalance.mockReturnValue({ balance_dollars: "0.00", balance_microcents: 0 });
    render(<CreditsPanel />);
    expect(screen.queryByText(/when balance drops below/i)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("checkbox"));
    expect(screen.getByText(/when balance drops below/i)).toBeInTheDocument();
    expect(screen.getByText(/charge me/i)).toBeInTheDocument();
  });

  it("calls setAutoReload with the right payload when Save is clicked", async () => {
    mockBalance.mockReturnValue({ balance_dollars: "0.00", balance_microcents: 0 });
    mockSetAutoReload.mockResolvedValueOnce(undefined);
    render(<CreditsPanel />);
    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.click(screen.getByRole("button", { name: /^save$/i }));
    await waitFor(() =>
      expect(mockSetAutoReload).toHaveBeenCalledWith({
        enabled: true,
        threshold_cents: 500,
        amount_cents: 2000,
      }),
    );
  });

  it("calls refresh when the refresh icon is clicked", () => {
    mockBalance.mockReturnValue({ balance_dollars: "0.00", balance_microcents: 0 });
    render(<CreditsPanel />);
    fireEvent.click(screen.getByRole("button", { name: /refresh/i }));
    expect(mockRefresh).toHaveBeenCalled();
  });
});
```

- [ ] **Step 3: Run the test to verify it fails**

```bash
cd apps/frontend && pnpm test --run src/components/control/panels/__tests__/CreditsPanel.test.tsx
```

**Expected:** Most tests fail because the new copy ("BALANCE" eyebrow, refresh button, "$50" quick-pick button) doesn't exist in the current panel.

- [ ] **Step 4: Rewrite `CreditsPanel.tsx`**

Replace the contents of `apps/frontend/src/components/control/panels/CreditsPanel.tsx` with:

```tsx
"use client";

import { useState } from "react";
import { Wallet, RefreshCw } from "lucide-react";
import { useCredits } from "@/hooks/useCredits";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";

const CARD = "rounded-lg border border-[#e0dbd0] bg-white p-4 space-y-3";
const EYEBROW = "text-[10px] uppercase tracking-wider text-[#8a8578]/60";

const QUICK_PICKS_CENTS = [1000, 2000, 5000, 10000];

export function CreditsPanel() {
  const { balance, startTopUp, setAutoReload, refresh } = useCredits();
  const [topUpAmount, setTopUpAmount] = useState(2000);
  const [autoEnabled, setAutoEnabled] = useState(false);
  const [thresholdCents, setThresholdCents] = useState(500);
  const [reloadCents, setReloadCents] = useState(2000);

  const handleTopUp = async () => {
    await startTopUp(topUpAmount);
    refresh();
  };

  const handleAutoReloadSave = async () => {
    await setAutoReload({
      enabled: autoEnabled,
      threshold_cents: autoEnabled ? thresholdCents : undefined,
      amount_cents: autoEnabled ? reloadCents : undefined,
    });
  };

  const balanceDisplay = balance ? `$${balance.balance_dollars}` : "$0.00";

  return (
    <div className="p-6 space-y-6">
      <h2 className="text-lg font-semibold">Claude credits</h2>

      <div className={CARD}>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Wallet className="h-3.5 w-3.5 text-[#8a8578]" />
            <span className={EYEBROW}>BALANCE</span>
          </div>
          <button
            type="button"
            onClick={() => refresh()}
            aria-label="Refresh"
            className="text-[#8a8578] hover:text-[#1a1a1a]"
          >
            <RefreshCw className="h-3.5 w-3.5" />
          </button>
        </div>
        <div className="text-3xl font-semibold font-mono text-[#1a1a1a]">{balanceDisplay}</div>
      </div>

      <div className={CARD}>
        <span className={EYEBROW}>ADD CREDITS</span>
        <div className="flex flex-wrap gap-2">
          {QUICK_PICKS_CENTS.map((c) => {
            const active = topUpAmount === c;
            return (
              <button
                key={c}
                onClick={() => setTopUpAmount(c)}
                className={
                  "rounded-md border px-3 py-1.5 text-sm transition-colors " +
                  (active
                    ? "border-[#06402B] bg-[#06402B]/5 text-[#06402B]"
                    : "border-[#e0dbd0] text-[#1a1a1a] hover:bg-[#f3efe6]")
                }
              >
                ${c / 100}
              </button>
            );
          })}
        </div>
        <button
          onClick={handleTopUp}
          className="rounded-full bg-[#06402B] hover:bg-[#0a5c3e] text-white px-4 py-2 text-sm"
        >
          Add ${topUpAmount / 100}
        </button>
      </div>

      <div className={CARD}>
        <span className={EYEBROW}>AUTO-RELOAD</span>
        <label className="flex items-center gap-2 text-sm cursor-pointer">
          <Checkbox
            checked={autoEnabled}
            onCheckedChange={(v) => setAutoEnabled(v === true)}
          />
          Automatically top up when balance is low
        </label>
        {autoEnabled && (
          <div className="space-y-3 pt-1">
            <div className="space-y-1">
              <label className={EYEBROW}>When balance drops below</label>
              <div className="flex items-center gap-1">
                <span className="text-sm text-[#8a8578]">$</span>
                <Input
                  type="number"
                  min={5}
                  step={5}
                  value={thresholdCents / 100}
                  onChange={(e) =>
                    setThresholdCents(Math.round(Number(e.target.value) * 100))
                  }
                  className="w-24"
                />
              </div>
            </div>
            <div className="space-y-1">
              <label className={EYEBROW}>Charge me</label>
              <div className="flex items-center gap-1">
                <span className="text-sm text-[#8a8578]">$</span>
                <Input
                  type="number"
                  min={5}
                  step={5}
                  value={reloadCents / 100}
                  onChange={(e) =>
                    setReloadCents(Math.round(Number(e.target.value) * 100))
                  }
                  className="w-24"
                />
              </div>
            </div>
          </div>
        )}
        <button
          onClick={handleAutoReloadSave}
          className="rounded-md bg-secondary px-4 py-2 text-sm hover:bg-secondary/90"
        >
          Save
        </button>
      </div>
    </div>
  );
}
```

This drops the previous `pendingTopUpSecret` debug paragraph (the TODO marker noting the missing in-panel Stripe Elements flow). The `useCredits` hook stays unchanged; redesign is purely presentational.

- [ ] **Step 5: Run the test to verify it passes**

```bash
cd apps/frontend && pnpm test --run src/components/control/panels/__tests__/CreditsPanel.test.tsx
```

**Expected:** All seven tests PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/frontend/src/components/control/panels/CreditsPanel.tsx \
        apps/frontend/src/components/control/panels/__tests__/CreditsPanel.test.tsx
git commit -m "feat(control): redesign Credits panel — dense card layout

Switches CreditsPanel from raw inputs + plain text to three cards
(Balance / Add credits / Auto-reload) styled to match UsagePanel's
warm palette, eyebrow labels, and shadcn primitives. Quick-pick
buttons get the green accent on active. Auto-reload uses shadcn
Checkbox + Input instead of raw HTML controls. The pendingTopUpSecret
debug paragraph is removed — Stripe Elements wiring stays a follow-up,
but the dev string shouldn't ship.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Section D — Final verification

### Task 8: Full verification + manual smoke

- [ ] **Step 1: Backend full test suite**

```bash
cd apps/backend && uv run pytest tests/ -v
```

**Expected:** All tests PASS. If anything fails outside the files we edited (`routers/billing.py`, `routers/oauth.py`, their tests, possibly `conftest.py`), investigate per the CLAUDE.md rule "If tests are not passing, your change is likely the culprit."

- [ ] **Step 2: Frontend lint + type check + unit tests + build**

```bash
cd apps/frontend && pnpm lint && pnpm test --run && pnpm build
```

**Expected:** Lint clean, all unit tests PASS, build succeeds.

- [ ] **Step 3: Manual smoke (per spec section E)**

Per CLAUDE.md's UI-test rule, exercise the change in a browser before declaring victory. From repo root:

```bash
turbo run dev
```

Then walk through the seven scenarios in the spec's Section E (`docs/superpowers/specs/2026-05-01-provider-rules-and-control-panels-design.md`), recorded here verbatim for convenience:

1. Sign in as a personal account → `/chat` → ProvisioningStepper provider step → confirm all three cards.
2. Sign out, sign up as an org account, create an org → `/chat` → confirm only two cards (no ChatGPT), header reads "Two ways", grid is centered 2-up.
3. With the dev server running and an org-context Clerk token in hand, curl `POST /api/v1/billing/trial-checkout` directly with `provider_choice=chatgpt_oauth` → expect `403`. Same with `POST /api/v1/oauth/chatgpt/start` → `403`.
4. Provision through to ProvisioningStepper, pick `byo_key` → after onboarding, open the control panel sidebar → confirm Credits item is hidden.
5. Same with `bedrock_claude` → confirm Credits item is visible, the redesigned panel renders, balance card + add credits card + auto-reload card are styled per spec.
6. Same with `chatgpt_oauth` → confirm Credits item hidden, LLM Provider panel shows the hero with a Connected status chip, Disconnect button works.
7. On the LLM Provider panel for `byo_key`, confirm Replace key form save success and save failure both work (the Codex P2 fix is preserved — submit a bad key and confirm the error appears under the form, then submit a good key and confirm the form clears).

If any scenario fails, fix the underlying issue, add a regression test, and re-run from Step 1.

- [ ] **Step 4: Final summary commit (if any test fixes accrued)**

If Steps 1–3 surfaced fixes, commit them with a clear message like `fix(control): <thing> caught during full verification`. Otherwise no commit needed.

- [ ] **Step 5: Hand off to user**

Do NOT push. Tell the user the branch is verified locally, summarize the commits, and ask whether to:

- Push `feat/provider-rules-and-control-panels` and open a PR against `main`, or
- Wait for them to review locally first.

(Per `memory/feedback_no_push_without_approval`.)

---

## Self-Review

**1. Spec coverage:**

| Spec section | Tasks |
|---|---|
| A.1 Frontend ProviderPicker filter | Task 3 |
| A.2 Backend trial-checkout 403 | Task 1 |
| A.3 Backend oauth/chatgpt/start 403 | Task 2 |
| B Sidebar gate | Task 4 |
| B Active-panel safety | Task 5 |
| C LLMPanel redesign + stale-comment cleanup | Task 6 |
| D CreditsPanel redesign + pendingTopUpSecret cleanup | Task 7 |
| E Backend tests (4 trial-checkout + 2 oauth) | Tasks 1, 2 |
| E Frontend tests (ProviderPicker + Sidebar + Router + LLM + Credits) | Tasks 3, 4, 5, 6, 7 |
| E Manual smoke (7 scenarios) | Task 8 step 3 |
| F Implementation order + commits | Task ordering matches spec's three logical commits — Section A = tasks 1+2+3, Section B = tasks 4+5, Section C = tasks 6+7 |
| G Risks: pre-existing chatgpt_oauth org subscription | Mentioned in Task 1 commit message context; spec calls out reviewer comms which Task 8 step 5 forwards to PR description |

**2. Placeholder scan:** No `TBD`/`TODO`/`implement later`/"add appropriate" left in the plan. Each step has runnable commands and complete code.

**3. Type consistency:**
- `ProviderChoice` literal `"chatgpt_oauth" | "byo_key" | "bedrock_claude"` is used identically in `LLMPanel`, `ControlSidebar`, `ControlPanelRouter`, and the backend `TrialCheckoutRequest`.
- `ByoProvider` literal `"openai" | "anthropic"` matches between `LLMPanel` and the existing `ReplaceKeyForm`.
- `useCredits` shape (`balance`, `startTopUp`, `setAutoReload`, `refresh`) is used identically in `CreditsPanel` and the test mock — Step 1 of Task 7 has a verification grep so the implementer notices any drift.
- `AuthContext.is_org_context` is used in both backend tasks (1, 2).

**4. Ambiguity check:**
- "Find the existing trial-checkout test class" in Task 1 Step 1 is a real fork — the implementer's first action is the grep, and the result drives whether they edit a class or add module-level functions. Spelled out in the step.
- Hero icon for `bedrock_claude` is `<AnthropicIcon size={32} />` (not the underspecified "AWS+Anthropic lockup" of an earlier draft). Matches the spec.
- Empty state link target for LLMPanel is `/onboarding` (the existing route stays). Matches the spec.
