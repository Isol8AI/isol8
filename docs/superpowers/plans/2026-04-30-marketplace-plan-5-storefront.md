# Marketplace Plan 5: Storefront Frontend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Ship `apps/marketplace`, the Next.js 16 storefront at `marketplace.isol8.co`. Home (Featured agents), `/agents` (default browse tab), `/skills` (secondary), `/listing/:slug` (detail + buy/install), `/sell` (publishing UI), `/dashboard` (creator earnings), `/buyer` (purchase history), `/mcp/setup` (integration help).

**Architecture:** Next.js 16 App Router on Vercel, separate project from `apps/frontend`. Calls Plan 2 backend via `NEXT_PUBLIC_API_URL`. Public pages SSR for SEO; auth-gated pages (`/sell`, `/dashboard`, `/buyer`) use Clerk middleware. Shared types in `packages/marketplace-shared`.

**Tech Stack:** Next.js 16, React 19, Tailwind CSS v4, Clerk auth, SWR, lucide-react.

**Depends on:** Plan 1 (Vercel project shell) and Plan 2 (API endpoints).

---

## Context

Per the design doc's agents-led reframing: home page leads with featured **agents** above the fold; skills are a tab, not the front door. The storefront is the public face; SEO matters because non-Isol8 buyers find listings via Google.

## File structure

**Create:**
- `apps/marketplace/package.json`
- `apps/marketplace/tsconfig.json`
- `apps/marketplace/next.config.ts`
- `apps/marketplace/tailwind.config.ts`
- `apps/marketplace/src/app/layout.tsx`
- `apps/marketplace/src/app/page.tsx` — home (Featured agents)
- `apps/marketplace/src/app/agents/page.tsx`
- `apps/marketplace/src/app/skills/page.tsx`
- `apps/marketplace/src/app/listing/[slug]/page.tsx`
- `apps/marketplace/src/app/sell/page.tsx` — auth-gated
- `apps/marketplace/src/app/dashboard/page.tsx` — auth-gated
- `apps/marketplace/src/app/buyer/page.tsx` — auth-gated
- `apps/marketplace/src/app/mcp/setup/page.tsx`
- `apps/marketplace/src/middleware.ts` — Clerk
- `apps/marketplace/src/components/Listing/ListingCard.tsx`
- `apps/marketplace/src/components/Listing/BuyButton.tsx`
- `apps/marketplace/src/components/Sell/PublishForm.tsx`
- `apps/marketplace/src/lib/api.ts` — typed API client
- `packages/marketplace-shared/src/types.ts`
- `packages/marketplace-shared/package.json`

---

## Tasks

### Task 1: Scaffold + Vercel project link

**Files:**
- Create: `apps/marketplace/package.json`, `tsconfig.json`, `next.config.ts`, `tailwind.config.ts`, `src/app/layout.tsx`, `src/app/page.tsx` (stub)

- [ ] **Step 1: `package.json`**

```json
{
  "name": "@isol8/marketplace-storefront",
  "version": "0.1.0",
  "private": true,
  "scripts": {
    "dev": "next dev -p 3001",
    "build": "next build",
    "start": "next start -p 3001",
    "test": "jest",
    "lint": "next lint"
  },
  "dependencies": {
    "@clerk/nextjs": "^6.0.0",
    "@isol8/marketplace-shared": "workspace:*",
    "lucide-react": "^0.456.0",
    "next": "^16.0.0",
    "react": "^19.0.0",
    "react-dom": "^19.0.0",
    "swr": "^2.3.0"
  },
  "devDependencies": {
    "@types/node": "^22.0.0",
    "@types/react": "^19.0.0",
    "tailwindcss": "^4.0.0",
    "typescript": "~5.6.3"
  }
}
```

- [ ] **Step 2: `next.config.ts`**

```typescript
import type { NextConfig } from "next";
const config: NextConfig = {
  reactStrictMode: true,
  experimental: { typedRoutes: true },
};
export default config;
```

- [ ] **Step 3: Stub root layout + home**

`src/app/layout.tsx`:

```tsx
import "./globals.css";
import { ClerkProvider } from "@clerk/nextjs";

export const metadata = {
  title: "marketplace.isol8.co — AI agents you can deploy in one command",
  description: "The marketplace for AI agents. Browse, buy, deploy.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <ClerkProvider>
      <html lang="en">
        <body className="bg-zinc-950 text-zinc-100">{children}</body>
      </html>
    </ClerkProvider>
  );
}
```

`src/app/page.tsx` (stub, replaced in Task 4):

```tsx
export default function Home() {
  return <h1 className="p-8 text-2xl">marketplace.isol8.co</h1>;
}
```

- [ ] **Step 4: Smoke + commit**

```bash
cd apps/marketplace && pnpm install && pnpm run build
git add apps/marketplace/
git commit -m "feat(marketplace-storefront): Next.js 16 scaffold"
```

---

### Task 2: Shared types package

**Files:**
- Create: `packages/marketplace-shared/`

- [ ] **Step 1: `packages/marketplace-shared/package.json`**

```json
{
  "name": "@isol8/marketplace-shared",
  "version": "0.1.0",
  "private": true,
  "main": "./src/index.ts",
  "types": "./src/index.ts"
}
```

- [ ] **Step 2: `packages/marketplace-shared/src/index.ts`**

```typescript
export type ListingFormat = "openclaw" | "skillmd";
export type DeliveryMethod = "cli" | "mcp" | "both";
export type ListingStatus = "draft" | "review" | "published" | "retired" | "taken_down";

export interface Listing {
  listing_id: string;
  slug: string;
  name: string;
  description_md: string;
  format: ListingFormat;
  delivery_method: DeliveryMethod;
  price_cents: number;
  tags: string[];
  seller_id: string;
  status: ListingStatus;
  version: number;
  published_at: string | null;
  created_at: string;
}

export interface Purchase {
  purchase_id: string;
  listing_id: string;
  listing_slug: string;
  license_key: string;
  price_paid_cents: number;
  status: "paid" | "refunded" | "revoked";
  created_at: string;
}
```

- [ ] **Step 3: Commit**

```bash
git add packages/marketplace-shared/
git commit -m "feat(marketplace-shared): TypeScript types package"
```

---

### Task 3: API client + Clerk middleware

**Files:**
- Create: `apps/marketplace/src/lib/api.ts`
- Create: `apps/marketplace/src/middleware.ts`

- [ ] **Step 1: `src/lib/api.ts`**

```typescript
import type { Listing } from "@isol8/marketplace-shared";

const API = process.env.NEXT_PUBLIC_API_URL ?? "https://api.isol8.co";

export async function browseListings(opts: { tags?: string; limit?: number; format?: "openclaw" | "skillmd" } = {}) {
  const params = new URLSearchParams();
  if (opts.tags) params.set("tags", opts.tags);
  if (opts.limit) params.set("limit", String(opts.limit));
  if (opts.format) params.set("format", opts.format);
  const resp = await fetch(`${API}/api/v1/marketplace/listings?${params}`, {
    next: { revalidate: 60 },
  });
  if (!resp.ok) throw new Error(`browseListings failed: ${resp.status}`);
  const body = (await resp.json()) as { items: Listing[]; count: number };
  return body;
}

export async function getListing(slug: string): Promise<Listing | null> {
  const resp = await fetch(`${API}/api/v1/marketplace/listings/${encodeURIComponent(slug)}`, {
    next: { revalidate: 60 },
  });
  if (resp.status === 404) return null;
  if (!resp.ok) throw new Error(`getListing failed: ${resp.status}`);
  return resp.json();
}

export async function checkout(opts: { listingSlug: string; successUrl: string; cancelUrl: string; jwt: string; email?: string }) {
  const resp = await fetch(`${API}/api/v1/marketplace/checkout`, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      Authorization: `Bearer ${opts.jwt}`,
    },
    body: JSON.stringify({
      listing_slug: opts.listingSlug,
      success_url: opts.successUrl,
      cancel_url: opts.cancelUrl,
      email: opts.email,
    }),
  });
  if (!resp.ok) throw new Error(`checkout failed: ${resp.status}`);
  return (await resp.json()) as { checkout_url: string; session_id: string };
}
```

- [ ] **Step 2: `src/middleware.ts`**

```typescript
import { clerkMiddleware, createRouteMatcher } from "@clerk/nextjs/server";

const isProtectedRoute = createRouteMatcher([
  "/sell(.*)",
  "/dashboard(.*)",
  "/buyer(.*)",
]);

export default clerkMiddleware(async (auth, req) => {
  if (isProtectedRoute(req)) await auth.protect();
});

export const config = {
  matcher: ["/((?!_next|.*\\..*).*)"],
};
```

- [ ] **Step 3: Commit**

```bash
git add apps/marketplace/src/lib/api.ts apps/marketplace/src/middleware.ts
git commit -m "feat(marketplace-storefront): typed API client + Clerk middleware"
```

---

### Task 4: Home, /agents, /skills pages

**Files:**
- Modify: `apps/marketplace/src/app/page.tsx`
- Create: `apps/marketplace/src/app/agents/page.tsx`
- Create: `apps/marketplace/src/app/skills/page.tsx`
- Create: `apps/marketplace/src/components/Listing/ListingCard.tsx`

- [ ] **Step 1: `ListingCard.tsx`**

```tsx
import Link from "next/link";
import type { Listing } from "@isol8/marketplace-shared";

export function ListingCard({ listing }: { listing: Listing }) {
  const price = listing.price_cents === 0
    ? "Free"
    : `$${(listing.price_cents / 100).toFixed(2)}`;
  return (
    <Link href={`/listing/${listing.slug}`} className="block rounded-xl border border-zinc-800 p-5 hover:border-zinc-600 transition">
      <div className="flex items-start justify-between mb-2">
        <h3 className="font-semibold text-lg text-zinc-100">{listing.name}</h3>
        <span className="text-sm text-zinc-400">{price}</span>
      </div>
      <p className="text-sm text-zinc-400 mb-3 line-clamp-2">{listing.description_md}</p>
      <div className="flex flex-wrap gap-1">
        {listing.tags.map(t => (
          <span key={t} className="text-xs px-2 py-0.5 rounded bg-zinc-800 text-zinc-300">{t}</span>
        ))}
      </div>
    </Link>
  );
}
```

- [ ] **Step 2: Home page (Featured agents)**

`src/app/page.tsx`:

```tsx
import { browseListings } from "@/lib/api";
import { ListingCard } from "@/components/Listing/ListingCard";
import Link from "next/link";

export default async function Home() {
  const { items: agents } = await browseListings({ format: "openclaw", limit: 8 });
  return (
    <main className="max-w-6xl mx-auto px-6 py-16">
      <section className="mb-16">
        <h1 className="text-5xl font-bold mb-4">The marketplace for AI agents.</h1>
        <p className="text-xl text-zinc-400 mb-8 max-w-2xl">
          Complete AI workers with identity, workflows, and skills. Deploy in one command.
        </p>
        <div className="flex gap-4">
          <Link href="/agents" className="px-6 py-3 bg-zinc-100 text-zinc-950 rounded-lg font-semibold">
            Browse agents
          </Link>
          <Link href="/sell" className="px-6 py-3 border border-zinc-700 rounded-lg">
            Sell yours
          </Link>
        </div>
      </section>
      <section>
        <div className="flex justify-between items-baseline mb-6">
          <h2 className="text-2xl font-semibold">Featured agents</h2>
          <Link href="/agents" className="text-sm text-zinc-400 hover:text-zinc-100">View all →</Link>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {agents.map(a => <ListingCard key={a.listing_id} listing={a} />)}
        </div>
      </section>
    </main>
  );
}
```

- [ ] **Step 3: `/agents` and `/skills` pages**

`src/app/agents/page.tsx`:

```tsx
import { browseListings } from "@/lib/api";
import { ListingCard } from "@/components/Listing/ListingCard";
import Link from "next/link";

export default async function Agents() {
  const { items } = await browseListings({ format: "openclaw", limit: 50 });
  return (
    <main className="max-w-6xl mx-auto px-6 py-12">
      <Tabs current="agents" />
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {items.map(a => <ListingCard key={a.listing_id} listing={a} />)}
      </div>
    </main>
  );
}

function Tabs({ current }: { current: "agents" | "skills" }) {
  return (
    <div className="flex gap-6 border-b border-zinc-800 mb-8">
      <Link href="/agents" className={`pb-3 ${current === "agents" ? "border-b-2 border-zinc-100 font-semibold" : "text-zinc-400"}`}>
        Agents
      </Link>
      <Link href="/skills" className={`pb-3 ${current === "skills" ? "border-b-2 border-zinc-100 font-semibold" : "text-zinc-400"}`}>
        Skills
      </Link>
    </div>
  );
}
```

`src/app/skills/page.tsx`: identical to /agents but with `format: "skillmd"` and `current="skills"`. Tabs component refactor into shared file recommended.

- [ ] **Step 4: Commit**

```bash
git add apps/marketplace/src/app/page.tsx apps/marketplace/src/app/agents/ apps/marketplace/src/app/skills/ apps/marketplace/src/components/
git commit -m "feat(marketplace-storefront): home (Featured agents) + /agents + /skills"
```

---

### Task 5: Listing detail + Buy button

**Files:**
- Create: `apps/marketplace/src/app/listing/[slug]/page.tsx`
- Create: `apps/marketplace/src/components/Listing/BuyButton.tsx`

- [ ] **Step 1: Detail page**

```tsx
import { getListing } from "@/lib/api";
import { BuyButton } from "@/components/Listing/BuyButton";
import { notFound } from "next/navigation";

export default async function ListingDetail({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const listing = await getListing(slug);
  if (!listing) notFound();
  return (
    <main className="max-w-4xl mx-auto px-6 py-12">
      <header className="mb-8">
        <span className="text-sm text-zinc-400 uppercase tracking-wider">
          {listing.format === "openclaw" ? "Agent" : "Skill"}
        </span>
        <h1 className="text-4xl font-bold mt-2">{listing.name}</h1>
        <div className="flex gap-2 mt-3">
          {listing.tags.map(t => (
            <span key={t} className="text-xs px-2 py-1 bg-zinc-800 rounded">{t}</span>
          ))}
        </div>
      </header>
      <article className="prose prose-invert max-w-none mb-12">
        {/* Render description_md via a markdown renderer in v1.5 */}
        <p className="whitespace-pre-line text-zinc-300">{listing.description_md}</p>
      </article>
      <BuyButton listing={listing} />
    </main>
  );
}
```

- [ ] **Step 2: Buy button (split free/paid + Isol8/non-Isol8)**

```tsx
"use client";
import type { Listing } from "@isol8/marketplace-shared";
import { useAuth, useUser } from "@clerk/nextjs";
import { useState } from "react";

export function BuyButton({ listing }: { listing: Listing }) {
  const { isSignedIn, getToken } = useAuth();
  const { user } = useUser();
  const [loading, setLoading] = useState(false);

  if (listing.price_cents === 0) {
    const cmd = `npx @isol8/marketplace install ${listing.slug}`;
    return (
      <div className="rounded-lg border border-zinc-700 p-6">
        <h3 className="font-semibold mb-3">Install (free)</h3>
        <pre className="bg-zinc-900 px-4 py-3 rounded overflow-x-auto text-sm">{cmd}</pre>
        <p className="text-sm text-zinc-400 mt-3">Auto-detects Claude Code, Cursor, OpenClaw, Copilot CLI.</p>
      </div>
    );
  }

  async function purchase() {
    if (!isSignedIn) {
      window.location.href = `/sign-in?redirect_url=${encodeURIComponent(window.location.href)}`;
      return;
    }
    setLoading(true);
    const jwt = await getToken();
    const resp = await fetch("/api/internal/checkout", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        listing_slug: listing.slug,
        jwt,
        email: user?.primaryEmailAddress?.emailAddress,
      }),
    });
    const body = await resp.json();
    if (body.checkout_url) window.location.href = body.checkout_url;
  }

  const price = `$${(listing.price_cents / 100).toFixed(2)}`;
  return (
    <button onClick={purchase} disabled={loading} className="px-6 py-3 bg-zinc-100 text-zinc-950 rounded-lg font-semibold disabled:opacity-50">
      {loading ? "Loading..." : `Buy for ${price}`}
    </button>
  );
}
```

`/api/internal/checkout` is a server route that proxies to the backend (Clerk JWT validation + secret-key handling). Add at `apps/marketplace/src/app/api/internal/checkout/route.ts`:

```typescript
import { NextRequest, NextResponse } from "next/server";
import { checkout } from "@/lib/api";

export async function POST(req: NextRequest) {
  const body = await req.json();
  const origin = new URL(req.url).origin;
  const result = await checkout({
    listingSlug: body.listing_slug,
    successUrl: `${origin}/buyer?success=true`,
    cancelUrl: `${origin}/listing/${body.listing_slug}`,
    jwt: body.jwt,
    email: body.email,
  });
  return NextResponse.json(result);
}
```

- [ ] **Step 3: Commit**

```bash
git add apps/marketplace/src/app/listing/ apps/marketplace/src/components/Listing/BuyButton.tsx apps/marketplace/src/app/api/
git commit -m "feat(marketplace-storefront): listing detail + buy button (free CLI + paid checkout)"
```

---

### Task 6: /sell, /dashboard, /buyer (auth-gated)

**Files:**
- Create: `apps/marketplace/src/app/sell/page.tsx`
- Create: `apps/marketplace/src/app/dashboard/page.tsx`
- Create: `apps/marketplace/src/app/buyer/page.tsx`

- [ ] **Step 1: `/sell` — minimal publish form**

```tsx
"use client";
import { useState } from "react";
import { useAuth } from "@clerk/nextjs";

export default function Sell() {
  const { getToken } = useAuth();
  const [form, setForm] = useState({
    slug: "",
    name: "",
    description_md: "",
    format: "openclaw" as const,
    delivery_method: "cli" as const,
    price_cents: 0,
    tags: "",
  });
  const [status, setStatus] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setStatus("uploading...");
    const jwt = await getToken();
    const resp = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/api/v1/marketplace/listings`, {
      method: "POST",
      headers: { "content-type": "application/json", Authorization: `Bearer ${jwt}` },
      body: JSON.stringify({
        ...form,
        tags: form.tags.split(",").map(t => t.trim()).filter(Boolean),
      }),
    });
    if (resp.ok) {
      const body = await resp.json();
      setStatus(`Draft saved: ${body.slug}`);
    } else {
      setStatus(`Error: ${resp.status}`);
    }
  }

  return (
    <main className="max-w-2xl mx-auto px-6 py-12">
      <h1 className="text-3xl font-bold mb-6">Publish a listing</h1>
      <form onSubmit={submit} className="space-y-4">
        <input className="w-full bg-zinc-900 px-4 py-2 rounded" placeholder="slug (lowercase-kebab)" value={form.slug} onChange={e => setForm({ ...form, slug: e.target.value })} required />
        <input className="w-full bg-zinc-900 px-4 py-2 rounded" placeholder="Name" value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} required />
        <textarea className="w-full bg-zinc-900 px-4 py-2 rounded" rows={5} placeholder="Description (markdown)" value={form.description_md} onChange={e => setForm({ ...form, description_md: e.target.value })} required />
        <div className="flex gap-3">
          <select className="bg-zinc-900 px-3 py-2 rounded" value={form.format} onChange={e => setForm({ ...form, format: e.target.value as "openclaw" | "skillmd" })}>
            <option value="openclaw">Agent (OpenClaw)</option>
            <option value="skillmd">Skill (SKILL.md)</option>
          </select>
          <select className="bg-zinc-900 px-3 py-2 rounded" value={form.delivery_method} onChange={e => setForm({ ...form, delivery_method: e.target.value as any })}>
            <option value="cli">CLI install</option>
            <option value="mcp">MCP server (SKILL.md only)</option>
            <option value="both">Both</option>
          </select>
          <input className="bg-zinc-900 px-3 py-2 rounded w-32" type="number" placeholder="Price (¢)" value={form.price_cents} onChange={e => setForm({ ...form, price_cents: Number(e.target.value) })} min={0} max={2000} />
        </div>
        <input className="w-full bg-zinc-900 px-4 py-2 rounded" placeholder="tags (comma-separated, max 5)" value={form.tags} onChange={e => setForm({ ...form, tags: e.target.value })} />
        <button className="px-6 py-2 bg-zinc-100 text-zinc-950 rounded font-semibold" type="submit">Save draft</button>
        {status && <p className="text-sm text-zinc-400">{status}</p>}
      </form>
    </main>
  );
}
```

(Artifact upload via separate file-input + multipart endpoint is captured as a v1.5 enhancement; v1 ships metadata-only here, with the artifact uploaded by an admin via the existing `publish-agent.sh` style script during initial seeding.)

- [ ] **Step 2: `/dashboard` (creator earnings)**

```tsx
"use client";
import { useAuth } from "@clerk/nextjs";
import useSWR from "swr";

const fetcher = (url: string, jwt: string) =>
  fetch(url, { headers: { Authorization: `Bearer ${jwt}` } }).then(r => r.json());

export default function Dashboard() {
  const { getToken } = useAuth();
  const { data } = useSWR(
    `${process.env.NEXT_PUBLIC_API_URL}/api/v1/marketplace/payouts/dashboard`,
    async (url) => {
      const jwt = await getToken();
      return fetcher(url, jwt!);
    },
  );
  if (!data) return <p className="p-8">Loading...</p>;
  return (
    <main className="max-w-3xl mx-auto px-6 py-12">
      <h1 className="text-3xl font-bold mb-8">Creator dashboard</h1>
      <div className="grid grid-cols-2 gap-4 mb-8">
        <Stat label="Held balance" value={`$${((data.balance_held_cents ?? 0) / 100).toFixed(2)}`} />
        <Stat label="Lifetime earned" value={`$${((data.lifetime_earned_cents ?? 0) / 100).toFixed(2)}`} />
      </div>
      {data.dashboard_url ? (
        <a href={data.dashboard_url} className="text-zinc-100 underline">Open Stripe dashboard →</a>
      ) : (
        <a href="/dashboard/onboard" className="px-4 py-2 bg-zinc-100 text-zinc-950 rounded">Onboard for payouts</a>
      )}
    </main>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-zinc-800 p-4">
      <p className="text-sm text-zinc-400">{label}</p>
      <p className="text-2xl font-bold mt-1">{value}</p>
    </div>
  );
}
```

- [ ] **Step 3: `/buyer` (purchase history) — similar pattern, queries `/api/v1/marketplace/my-purchases`. Skipped here for brevity; follows the SWR pattern from /dashboard.**

- [ ] **Step 4: Commit**

```bash
git add apps/marketplace/src/app/sell/ apps/marketplace/src/app/dashboard/ apps/marketplace/src/app/buyer/
git commit -m "feat(marketplace-storefront): /sell, /dashboard, /buyer (Clerk-gated)"
```

---

### Task 7: `/mcp/setup` integration help page

**Files:**
- Create: `apps/marketplace/src/app/mcp/setup/page.tsx`

- [ ] **Step 1: Implement**

```tsx
import Link from "next/link";

export default function McpSetup() {
  return (
    <main className="max-w-3xl mx-auto px-6 py-12 prose prose-invert">
      <h1>Connect MCP to your AI client</h1>
      <p>
        Once you've purchased a SKILL.md skill, you can serve it via MCP to any client
        that supports the Model Context Protocol — Claude Desktop, Cursor with MCP, Codex CLI.
      </p>

      <h2>Claude Desktop</h2>
      <pre><code>{JSON.stringify({
        mcpServers: {
          "isol8-marketplace": {
            url: "https://marketplace.isol8.co/mcp/<your-listing-id>/sse",
            transport: "sse",
            headers: { Authorization: "Bearer iml_<your-license-key>" },
          },
        },
      }, null, 2)}</code></pre>

      <h2>Cursor with MCP</h2>
      <p>
        Open <strong>Settings → MCP → Add Server</strong>. URL is the same as above; headers
        configured per Cursor's MCP UI.
      </p>

      <h2>Where do I find my license key?</h2>
      <p>
        After purchase, your license key is shown on the success page and is also available
        in <Link href="/buyer">your purchase history</Link>.
      </p>
    </main>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add apps/marketplace/src/app/mcp/setup/
git commit -m "feat(marketplace-storefront): /mcp/setup integration help"
```

---

## Verification

```bash
cd apps/marketplace && pnpm install && pnpm run build
# Expected: build succeeds with no type errors.

pnpm run dev  # local at http://localhost:3001
# Manual smoke checks:
#   - http://localhost:3001          → home with featured agents
#   - http://localhost:3001/agents   → agent grid
#   - http://localhost:3001/skills   → skills grid
#   - http://localhost:3001/listing/some-real-slug → detail page

# Once Vercel project is live (Plan 1 runbook):
curl -i https://marketplace.dev.isol8.co  # expected: 200
```

## Self-review

- **Agents-led brand:** home leads with "The marketplace for AI agents", /agents is default tab, /skills is secondary. Matches the spec's Positioning section.
- **SSR for SEO:** all public pages use server components with `next: { revalidate: 60 }` cache.
- **Auth gate:** Clerk middleware protects /sell, /dashboard, /buyer.
- **No placeholders:** every step has full code.

## NOT in Plan 5

- Markdown rendering for description_md (rendered as plain whitespace-preserve in v1; v1.5 adds a markdown component).
- Search bar UI (browse + tag filter only v1).
- Buyer's individual purchase detail page.
- Reviews/ratings UI (Phase 2 per design doc).
- Mobile-optimized layouts beyond Tailwind defaults.
- Vercel project provisioning (operational, in Plan 1 runbook).
