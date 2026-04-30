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
 *   - list pending takedown requests (`listPendingTakedowns`)
 *   - grant a takedown against a listing (`grantTakedown`)
 *
 * Style mirrors the sibling `catalog.ts` / `agent.ts` actions: each call
 * pulls the Clerk JWT server-side via `auth()`, hits `apiUrl()` (which
 * already includes the `/api/v1` segment), and returns an `ActionResult`
 * envelope so client components can render inline errors instead of
 * catching exceptions.
 *
 * The two GET endpoints (`listReviewQueue` / `listPendingTakedowns`) use
 * an unauthenticated `adminGet` wrapper — same shape, just no
 * `Idempotency-Key`. We co-locate them here per the moderation-task brief
 * even though the rest of the codebase puts read-only admin helpers in
 * `_lib/api.ts`; nothing else in this UI surface needs them, and grouping
 * keeps the moderation page imports tidy.
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

/** Approve a pending listing so it becomes visible in the marketplace. */
export async function approveListing(listingId: string): Promise<ActionResult> {
  return adminPost(
    `/admin/marketplace/listings/${encodeURIComponent(listingId)}/approve`,
  );
}

/**
 * Reject a pending listing. `notes` is surfaced to the publisher and recorded
 * on the moderation audit log.
 */
export async function rejectListing(
  listingId: string,
  notes: string,
): Promise<ActionResult> {
  return adminPost(
    `/admin/marketplace/listings/${encodeURIComponent(listingId)}/reject`,
    { notes },
  );
}

/** List takedown requests awaiting admin action. */
export async function listPendingTakedowns(): Promise<ActionResult> {
  return adminGet("/admin/marketplace/takedowns?status=pending");
}

/** Grant a takedown request against the given listing. */
export async function grantTakedown(
  listingId: string,
  takedownId: string,
): Promise<ActionResult> {
  return adminPost(
    `/admin/marketplace/takedowns/${encodeURIComponent(listingId)}`,
    { takedown_id: takedownId },
  );
}

// NOTE: see catalog.ts / agent.ts — "use server" files must export ONLY
// async functions. Do NOT add `export type { ActionResult }`; Turbopack
// turns the type re-export into a runtime ReferenceError on the SSR chunk
// the first time a server action runs. If a consumer ever needs the type,
// move the interface to a non-"use server" module (e.g. `_actions/_types.ts`).
