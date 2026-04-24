"use server";

import { randomUUID } from "crypto";

import { auth } from "@clerk/nextjs/server";

import { apiUrl } from "@/app/admin/_lib/url";

/**
 * Server Actions for the per-user billing surface (admin dashboard).
 *
 * Each action POSTs to a backend `/admin/users/{user_id}/billing/*` route
 * with a fresh `Idempotency-Key` (CEO D1) — duplicate clicks return the
 * cached response instead of double-charging or double-cancelling.
 */

interface ActionResult {
  ok: boolean;
  status: number;
  data?: unknown;
  error?: string;
}

async function adminPost(path: string, body?: object): Promise<ActionResult> {
  const { getToken } = await auth();
  const token = await getToken();
  if (!token) {
    return { ok: false, status: 401, error: "missing_token" };
  }

  const base = apiUrl().replace(/\/+$/, "");
  const url = `${base}${path.startsWith("/") ? path : `/${path}`}`;

  try {
    const res = await fetch(url, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
        "Idempotency-Key": randomUUID(),
      },
      body: body ? JSON.stringify(body) : undefined,
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

export async function cancelSubscription(userId: string): Promise<ActionResult> {
  return adminPost(`/admin/users/${encodeURIComponent(userId)}/billing/cancel-subscription`);
}

export async function pauseSubscription(userId: string): Promise<ActionResult> {
  return adminPost(`/admin/users/${encodeURIComponent(userId)}/billing/pause-subscription`);
}

export async function issueCredit(
  userId: string,
  amountCents: number,
  reason: string,
): Promise<ActionResult> {
  return adminPost(
    `/admin/users/${encodeURIComponent(userId)}/billing/issue-credit`,
    { amount_cents: amountCents, reason },
  );
}

export async function markInvoiceResolved(
  userId: string,
  invoiceId: string,
): Promise<ActionResult> {
  return adminPost(
    `/admin/users/${encodeURIComponent(userId)}/billing/mark-invoice-resolved`,
    { invoice_id: invoiceId },
  );
}

// NOTE: see catalog.ts — "use server" files must export ONLY async functions.
// Turbopack turns `export type { ActionResult }` into a runtime ReferenceError
// at SSR chunk load. No consumer imports ActionResult today.
