# Marketplace Plan 6: Admin Moderation UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Ship the marketplace moderation UI inside the existing admin dashboard at `admin.isol8.co/admin/marketplace/*`. Two surfaces: a listings review queue (approve/reject) and a takedowns queue (grant/deny). Both reuse the existing admin layout, `@audit_admin_action` audit pattern, and `ConfirmActionDialog` typed-confirmation component.

**Architecture:** Pages and Server Actions inside `apps/frontend/src/app/admin/marketplace/*`, parallel to the existing `apps/frontend/src/app/admin/catalog/*`. All writes go through the Plan 2 `marketplace_admin.py` router endpoints, which audit-log every action. No new backend code in this plan; this is UI only.

**Tech Stack:** Next.js 16 App Router, React 19 Server Components + Server Actions, existing `apps/frontend` Tailwind/Clerk setup.

**Depends on:** Plan 2 (`/api/v1/admin/marketplace/*` endpoints).

---

## Context

Plan 6 is the smallest plan — the heavy moderation logic lives in Plan 2's backend. Here we just surface the queues and approve/reject/takedown buttons, gated by the existing `require_platform_admin` dependency at the API layer.

## File structure

**Create:**
- `apps/frontend/src/app/admin/marketplace/layout.tsx` — sidebar nav (Listings | Takedowns)
- `apps/frontend/src/app/admin/marketplace/listings/page.tsx` — review queue
- `apps/frontend/src/app/admin/marketplace/listings/ModerationActions.tsx` — approve/reject buttons
- `apps/frontend/src/app/admin/marketplace/takedowns/page.tsx` — takedown queue
- `apps/frontend/src/app/admin/marketplace/takedowns/TakedownActions.tsx`
- `apps/frontend/src/app/admin/_actions/marketplace.ts` — Server Actions

**Modify:**
- `apps/frontend/src/app/admin/layout.tsx` — add "Marketplace" entry in admin sidebar.

---

## Tasks

### Task 1: Server Actions

**Files:**
- Create: `apps/frontend/src/app/admin/_actions/marketplace.ts`

- [ ] **Step 1: Implement**

```typescript
"use server";

import { auth } from "@clerk/nextjs/server";

const API = process.env.NEXT_PUBLIC_API_URL ?? "https://api.isol8.co";

async function adminFetch(path: string, init: RequestInit = {}) {
  const { getToken } = await auth();
  const jwt = await getToken();
  const resp = await fetch(`${API}${path}`, {
    ...init,
    headers: {
      ...init.headers,
      Authorization: `Bearer ${jwt}`,
      "content-type": "application/json",
    },
  });
  if (!resp.ok) {
    const text = await resp.text();
    throw new Error(`admin API ${resp.status}: ${text}`);
  }
  return resp.json();
}

export async function listReviewQueue() {
  return adminFetch("/api/v1/admin/marketplace/listings");
}

export async function approveListing(listingId: string) {
  return adminFetch(`/api/v1/admin/marketplace/listings/${listingId}/approve`, {
    method: "POST",
  });
}

export async function rejectListing(listingId: string, notes: string) {
  return adminFetch(`/api/v1/admin/marketplace/listings/${listingId}/reject`, {
    method: "POST",
    body: JSON.stringify({ notes }),
  });
}

export async function listPendingTakedowns() {
  // Plan 2 expose this via a query against takedowns table; the endpoint name is
  // GET /api/v1/admin/marketplace/takedowns?status=pending. If Plan 2 hasn't
  // shipped this, the implementer should add it as a small follow-up.
  return adminFetch("/api/v1/admin/marketplace/takedowns?status=pending");
}

export async function grantTakedown(listingId: string, takedownId: string) {
  return adminFetch(`/api/v1/admin/marketplace/takedowns/${listingId}`, {
    method: "POST",
    body: JSON.stringify({ takedown_id: takedownId }),
  });
}
```

- [ ] **Step 2: Commit**

```bash
git add apps/frontend/src/app/admin/_actions/marketplace.ts
git commit -m "feat(admin-marketplace): Server Actions for moderation"
```

---

### Task 2: Moderation queue page

**Files:**
- Create: `apps/frontend/src/app/admin/marketplace/layout.tsx`
- Create: `apps/frontend/src/app/admin/marketplace/listings/page.tsx`
- Create: `apps/frontend/src/app/admin/marketplace/listings/ModerationActions.tsx`

- [ ] **Step 1: Layout with sub-nav**

```tsx
import Link from "next/link";

export default function MarketplaceAdminLayout({ children }: { children: React.ReactNode }) {
  return (
    <div>
      <nav className="flex gap-6 border-b border-zinc-800 mb-6">
        <Link href="/admin/marketplace/listings" className="pb-3 text-sm">Review queue</Link>
        <Link href="/admin/marketplace/takedowns" className="pb-3 text-sm">Takedowns</Link>
      </nav>
      {children}
    </div>
  );
}
```

- [ ] **Step 2: Listings review page**

```tsx
import { listReviewQueue } from "@/app/admin/_actions/marketplace";
import { ModerationActions } from "./ModerationActions";

export const dynamic = "force-dynamic";

export default async function ListingsReview() {
  const { items } = await listReviewQueue();
  if (items.length === 0) {
    return <p className="text-zinc-400">No listings awaiting review.</p>;
  }
  return (
    <div className="space-y-3">
      {items.map((listing: any) => (
        <div key={listing.listing_id} className="rounded-lg border border-zinc-800 p-5 flex justify-between items-start">
          <div>
            <h3 className="font-semibold">{listing.name}</h3>
            <p className="text-sm text-zinc-400 mt-1">
              <code>{listing.slug}</code> · {listing.format} · ${(listing.price_cents / 100).toFixed(2)}
            </p>
            <p className="text-sm mt-2">{listing.description_md.slice(0, 200)}…</p>
            <p className="text-xs text-zinc-500 mt-2">seller: {listing.seller_id}</p>
          </div>
          <ModerationActions listingId={listing.listing_id} />
        </div>
      ))}
    </div>
  );
}
```

- [ ] **Step 3: ModerationActions client component (uses ConfirmActionDialog)**

```tsx
"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { approveListing, rejectListing } from "@/app/admin/_actions/marketplace";
import { ConfirmActionDialog } from "@/components/ui/ConfirmActionDialog";

export function ModerationActions({ listingId }: { listingId: string }) {
  const router = useRouter();
  const [dialog, setDialog] = useState<"approve" | "reject" | null>(null);
  const [notes, setNotes] = useState("");

  async function onConfirm() {
    if (dialog === "approve") {
      await approveListing(listingId);
    } else if (dialog === "reject") {
      await rejectListing(listingId, notes);
    }
    setDialog(null);
    setNotes("");
    router.refresh();
  }

  return (
    <div className="flex gap-2">
      <button onClick={() => setDialog("approve")} className="px-3 py-1 rounded bg-green-700/30 text-green-300 text-sm">
        Approve
      </button>
      <button onClick={() => setDialog("reject")} className="px-3 py-1 rounded bg-red-700/30 text-red-300 text-sm">
        Reject
      </button>
      {dialog === "approve" && (
        <ConfirmActionDialog
          title="Approve listing"
          confirmText="approve"
          onConfirm={onConfirm}
          onCancel={() => setDialog(null)}
        >
          Listing will become publicly visible at marketplace.isol8.co. Type 'approve' to confirm.
        </ConfirmActionDialog>
      )}
      {dialog === "reject" && (
        <ConfirmActionDialog
          title="Reject listing"
          confirmText="reject"
          onConfirm={onConfirm}
          onCancel={() => setDialog(null)}
        >
          <textarea
            className="w-full mt-3 bg-zinc-900 px-3 py-2 rounded"
            rows={4}
            placeholder="Notes for the seller (visible in their dashboard)"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            required
          />
          <p className="text-sm text-zinc-400 mt-2">Listing returns to draft. Type 'reject' to confirm.</p>
        </ConfirmActionDialog>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Commit**

```bash
git add apps/frontend/src/app/admin/marketplace/
git commit -m "feat(admin-marketplace): listings review queue with approve/reject"
```

---

### Task 3: Takedowns queue page

**Files:**
- Create: `apps/frontend/src/app/admin/marketplace/takedowns/page.tsx`
- Create: `apps/frontend/src/app/admin/marketplace/takedowns/TakedownActions.tsx`

- [ ] **Step 1: Page**

```tsx
import { listPendingTakedowns } from "@/app/admin/_actions/marketplace";
import { TakedownActions } from "./TakedownActions";

export const dynamic = "force-dynamic";

export default async function TakedownsQueue() {
  const { items } = await listPendingTakedowns();
  if (items.length === 0) return <p className="text-zinc-400">No pending takedowns.</p>;
  return (
    <div className="space-y-3">
      {items.map((t: any) => (
        <div key={t.takedown_id} className="rounded-lg border border-zinc-800 p-5">
          <div className="flex justify-between items-start mb-3">
            <div>
              <p className="font-semibold">listing: {t.listing_id}</p>
              <p className="text-sm text-zinc-400">reason: {t.reason}</p>
              <p className="text-sm text-zinc-400">filed by: {t.filed_by_name} ({t.filed_by_email})</p>
            </div>
            <TakedownActions listingId={t.listing_id} takedownId={t.takedown_id} />
          </div>
          <p className="text-sm whitespace-pre-line bg-zinc-900 p-3 rounded">{t.basis_md}</p>
        </div>
      ))}
    </div>
  );
}
```

- [ ] **Step 2: TakedownActions client component**

```tsx
"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { grantTakedown } from "@/app/admin/_actions/marketplace";
import { ConfirmActionDialog } from "@/components/ui/ConfirmActionDialog";

export function TakedownActions({ listingId, takedownId }: { listingId: string; takedownId: string }) {
  const router = useRouter();
  const [open, setOpen] = useState(false);

  async function confirmGrant() {
    await grantTakedown(listingId, takedownId);
    setOpen(false);
    router.refresh();
  }

  return (
    <>
      <button onClick={() => setOpen(true)} className="px-3 py-1 rounded bg-red-700/30 text-red-300 text-sm">
        Grant takedown
      </button>
      {open && (
        <ConfirmActionDialog
          title="Grant takedown"
          confirmText="takedown"
          onConfirm={confirmGrant}
          onCancel={() => setOpen(false)}
        >
          <p className="text-sm">
            Will: revoke ALL license keys for this listing, queue refunds for purchases in
            the last 30 days, hide listing from browse, email all affected buyers.
          </p>
          <p className="text-sm mt-2">Type 'takedown' to confirm. This action is audited.</p>
        </ConfirmActionDialog>
      )}
    </>
  );
}
```

- [ ] **Step 3: Commit**

```bash
git add apps/frontend/src/app/admin/marketplace/takedowns/
git commit -m "feat(admin-marketplace): takedowns queue with confirm + cascade revocation"
```

---

### Task 4: Wire into admin sidebar

**Files:**
- Modify: `apps/frontend/src/app/admin/layout.tsx` (existing)

- [ ] **Step 1: Add marketplace entry**

Locate the sidebar/nav section in the existing admin layout. Add (matching the existing style):

```tsx
<Link href="/admin/marketplace/listings" className={navLinkClass}>
  Marketplace
</Link>
```

- [ ] **Step 2: Smoke + commit**

```bash
cd apps/frontend && pnpm run build
# Expected: build succeeds; both new pages compile.
git add apps/frontend/src/app/admin/layout.tsx
git commit -m "feat(admin-marketplace): add Marketplace entry to admin sidebar"
```

---

## Verification

```bash
cd apps/frontend && pnpm run build
# Expected: clean build, no type errors, /admin/marketplace/* routes registered.

# Local smoke (against backend dev):
NEXT_PUBLIC_API_URL=https://api-dev.isol8.co pnpm run dev
# Sign in as a platform admin, navigate to /admin/marketplace/listings.
# Expected: queue renders. Approve a test listing — listing transitions to published.
# Audit log entry appears in isol8-{env}-admin-actions table with action="marketplace.approve".
```

## Self-review

- All admin actions go through Plan 2's audit-decorated endpoints. UI does not bypass audit.
- ConfirmActionDialog reused for typed-confirmation per existing pattern.
- No new backend code; UI-only.
- Two surfaces (listings, takedowns) match the design doc's admin surface.

## NOT in Plan 6

- Admin search/filter on the queue (v1.5).
- Bulk approve.
- Restore taken-down listings (must republish per design doc).
- Counter-notice handling (Phase 2 per spec).
- Admin-side seller messaging UI (use email for v1).
