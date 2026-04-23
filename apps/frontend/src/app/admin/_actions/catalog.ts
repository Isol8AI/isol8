"use server";

import { randomUUID } from "crypto";

import { auth } from "@clerk/nextjs/server";

import { apiUrl } from "@/app/admin/_lib/url";

/**
 * Server Actions for the shared agent catalog (admin dashboard).
 *
 * `publishAgent` adds a new version under a slug (or creates the slug on
 * first publish); `unpublishSlug` retires a slug so newcomers don't see the
 * template but the manifest history stays queryable for rollback + audit.
 *
 * Each action POSTs with a fresh `Idempotency-Key` so double-clicks
 * short-circuit on the backend. The Clerk JWT is fetched server-side via
 * `auth()`; never exposed to the client. Shape + error semantics mirror the
 * sibling `container.ts` / `agent.ts` actions so CatalogRowActions can treat
 * all admin server actions uniformly.
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

/**
 * Publish an agent to the shared catalog. Optional `slug` / `description`
 * overrides let the caller rename the template or edit its blurb at publish
 * time; omitted fields default to the agent's current metadata on the
 * backend.
 */
export async function publishAgent(
  agentId: string,
  slug?: string,
  description?: string,
): Promise<ActionResult> {
  const body: Record<string, string> = { agent_id: agentId };
  if (slug) body.slug = slug;
  if (description) body.description = description;
  return adminPost("/admin/catalog/publish", body);
}

/** Retire a catalog slug. History remains queryable; newcomers no longer see it. */
export async function unpublishSlug(slug: string): Promise<ActionResult> {
  return adminPost(`/admin/catalog/${encodeURIComponent(slug)}/unpublish`);
}

export type { ActionResult };
