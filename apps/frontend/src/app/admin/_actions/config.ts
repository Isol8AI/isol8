"use server";

import { auth } from "@clerk/nextjs/server";

import { apiUrl } from "@/app/admin/_lib/url";

/**
 * Server Action: PATCH a per-user OpenClaw config (Track 1 silent update).
 *
 * Forwards to `PATCH /api/v1/admin/users/{id}/config` with `{patch: dict}`
 * body. The backend deep-merges the patch into `openclaw.json` on EFS and
 * notifies the user's container via the file-watcher pipeline. The audit row
 * (`container.config.patch`) is written before the response returns.
 *
 * The caller is responsible for diff-confirmation UX (`<ConfirmActionDialog>`)
 * — this action just makes the call.
 */

interface ConfigPatchResponse {
  ok?: boolean;
  error?: string;
  status?: number;
  [key: string]: unknown;
}

export async function patchConfig(
  userId: string,
  patch: Record<string, unknown>,
): Promise<ConfigPatchResponse> {
  const { getToken } = await auth();
  const token = await getToken();
  if (!token) {
    return { ok: false, error: "Not authenticated", status: 401 };
  }

  const base = apiUrl().replace(/\/+$/, "");
  const url = `${base}/admin/users/${encodeURIComponent(userId)}/config`;

  try {
    const res = await fetch(url, {
      method: "PATCH",
      cache: "no-store",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ patch }),
    });
    let body: unknown = null;
    try {
      body = await res.json();
    } catch {
      // Non-JSON response. Fall through with empty body.
    }
    if (!res.ok) {
      return {
        ok: false,
        status: res.status,
        error:
          (body && typeof body === "object" && "error" in body
            ? String((body as { error: unknown }).error)
            : null) ?? `Request failed with status ${res.status}`,
        ...(body && typeof body === "object" ? body : {}),
      };
    }
    return {
      ok: true,
      status: res.status,
      ...(body && typeof body === "object" ? body : {}),
    };
  } catch (err) {
    return {
      ok: false,
      error: err instanceof Error ? err.message : "Network error",
    };
  }
}
