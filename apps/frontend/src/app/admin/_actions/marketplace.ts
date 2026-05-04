"use server";

import { randomUUID } from "crypto";

import { auth } from "@clerk/nextjs/server";

import { apiUrl } from "@/app/admin/_lib/url";

/**
 * Server Actions for marketplace moderation (admin dashboard).
 *
 * Wraps the backend `/admin/marketplace/*` endpoints (Plan 2) so the
 * moderation UI can:
 *   - list listings pending review (`listReviewQueue`)
 *   - approve / reject listings (`approveListing`, `rejectListing`)
 *   - take a listing down (`takedownListing`) — admin-initiated, single-shot
 *   - list recent takedowns for the audit-log view (`listRecentTakedowns`)
 *
 * Style mirrors the sibling `catalog.ts` / `agent.ts` actions: each call
 * pulls the Clerk JWT server-side via `auth()`, hits `apiUrl()` (which
 * already includes the `/api/v1` segment), and returns an `ActionResult`
 * envelope so client components can render inline errors instead of
 * catching exceptions.
 *
 * The two GET endpoints (`listReviewQueue` / `listRecentTakedowns`) use
 * an unauthenticated `adminGet` wrapper — same shape, just no
 * `Idempotency-Key`. We co-locate them here per the moderation-task brief
 * even though the rest of the codebase puts read-only admin helpers in
 * `_lib/api.ts`; nothing else in this UI surface needs them, and grouping
 * keeps the moderation page imports tidy.
 *
 * Takedowns workflow note: under the Isol8-internal scope there is no
 * public DMCA filing form, so the takedown queue is structurally empty.
 * The admin initiates the takedown directly from the listing detail page;
 * the takedowns route is reframed as an audit-log view of historical
 * takedowns (`listRecentTakedowns`).
 */

interface ActionResult {
  ok: boolean;
  status: number;
  data?: unknown;
  error?: string;
}

async function adminRequest(
  method: "GET" | "POST",
  path: string,
  body?: object,
): Promise<ActionResult> {
  const { getToken } = await auth();
  const token = await getToken();
  if (!token) {
    return { ok: false, status: 401, error: "missing_token" };
  }

  const base = apiUrl().replace(/\/+$/, "");
  const url = `${base}${path.startsWith("/") ? path : `/${path}`}`;

  const headers: Record<string, string> = {
    Authorization: `Bearer ${token}`,
    "Content-Type": "application/json",
  };
  // Mutation-only: dedupe double-clicks server-side.
  if (method === "POST") {
    headers["Idempotency-Key"] = randomUUID();
  }

  try {
    const res = await fetch(url, {
      method,
      headers,
      body: method === "POST" && body ? JSON.stringify(body) : undefined,
      cache: "no-store",
    });
    const text = await res.text();
    let data: unknown = undefined;
    if (text) {
      try {
        data = JSON.parse(text);
      } catch {
        data = text;
      }
    }
    if (!res.ok) {
      return {
        ok: false,
        status: res.status,
        data,
        error:
          (data && typeof data === "object" && "detail" in data
            ? String((data as { detail?: unknown }).detail)
            : undefined) ?? `http_${res.status}`,
      };
    }
    return { ok: true, status: res.status, data };
  } catch (e) {
    return {
      ok: false,
      status: 0,
      error: e instanceof Error ? e.message : "network_error",
    };
  }
}

async function adminGet(path: string): Promise<ActionResult> {
  return adminRequest("GET", path);
}

async function adminPost(path: string, body?: object): Promise<ActionResult> {
  return adminRequest("POST", path, body);
}

/** List marketplace listings awaiting moderation review. */
export async function listReviewQueue(): Promise<ActionResult> {
  return adminGet("/admin/marketplace/listings");
}

/**
 * Approve a pending listing so it becomes visible in the marketplace.
 *
 * `version` MUST be passed through from the review row (defaults to 1 only
 * for safety on legacy callers). The backend defaults `version=1`, so a
 * v2+ moderation action without this would target the wrong row and 409.
 *
 * `prevVersion` triggers the publish_v2 atomic flip on backend (retires
 * the previous published version + publishes the new one in one
 * TransactWriteItems). Pass it for any version > 1.
 */
export async function approveListing(
  listingId: string,
  options: { version?: number; prevVersion?: number } = {},
): Promise<ActionResult> {
  const { version = 1, prevVersion } = options;
  const params = new URLSearchParams({ version: String(version) });
  if (prevVersion !== undefined) params.set("prev_version", String(prevVersion));
  return adminPost(
    `/admin/marketplace/listings/${encodeURIComponent(listingId)}/approve?${params.toString()}`,
  );
}

/**
 * Reject a pending listing. `notes` is surfaced to the publisher and recorded
 * on the moderation audit log.
 *
 * `version` MUST be passed through from the review row (see approveListing).
 */
export async function rejectListing(
  listingId: string,
  notes: string,
  options: { version?: number } = {},
): Promise<ActionResult> {
  const { version = 1 } = options;
  const params = new URLSearchParams({ version: String(version) });
  return adminPost(
    `/admin/marketplace/listings/${encodeURIComponent(listingId)}/reject?${params.toString()}`,
    { notes },
  );
}

/** Listing detail preview for moderators (file tree, content, safety scan). */
export async function getListingPreview(listingId: string): Promise<ActionResult> {
  return adminGet(
    `/admin/marketplace/listings/${encodeURIComponent(listingId)}/preview`,
  );
}

/** List recent takedowns for the audit-log view (newest first). */
export async function listRecentTakedowns(): Promise<ActionResult> {
  return adminGet("/admin/marketplace/takedowns");
}

/**
 * Admin-initiated takedown against a listing.
 *
 * Writes the takedown row + cascades license revocation + flips the
 * listing's status to `taken_down` in one shot. `reason` is the structured
 * category for routing and analytics; `basisMd` is the free-text reason
 * recorded on the audit log (and shown to anyone reviewing the takedown
 * later).
 */
export async function takedownListing(
  listingId: string,
  reason: "dmca" | "policy" | "fraud" | "seller-request",
  basisMd: string,
): Promise<ActionResult> {
  return adminPost(
    `/admin/marketplace/listings/${encodeURIComponent(listingId)}/takedown`,
    { reason, basis_md: basisMd },
  );
}

// NOTE: see catalog.ts / agent.ts — "use server" files must export ONLY
// async functions. Do NOT add `export type { ActionResult }`; Turbopack
// turns the type re-export into a runtime ReferenceError on the SSR chunk
// the first time a server action runs. If a consumer ever needs the type,
// move the interface to a non-"use server" module (e.g. `_actions/_types.ts`).
