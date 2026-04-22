"use server";

import { auth } from "@clerk/nextjs/server";

import { apiUrl } from "@/app/admin/_lib/url";

/**
 * Server Actions for admin-driven account-level Clerk mutations.
 *
 * Each action POSTs to a backend endpoint that brokers the Clerk Backend API
 * call (suspend/unsuspend/sign-out/resend verification). The backend writes
 * the audit row before returning, so callers only need to surface the JSON
 * response back to the user.
 *
 * Conventions:
 *   - Always read the Clerk session token via `auth()` so the backend can
 *     verify the caller is a platform admin.
 *   - Always `cache: "no-store"` — admin writes must never be cached.
 *   - Return the parsed JSON body (or an inline error shape on transport
 *     failure). Confirmation UX lives in the *caller* via
 *     `<ConfirmActionDialog>`; these actions deliberately do not prompt.
 */

interface AdminActionResponse {
  ok?: boolean;
  error?: string;
  status?: number;
  [key: string]: unknown;
}

async function adminPost(path: string): Promise<AdminActionResponse> {
  const { getToken } = await auth();
  const token = await getToken();
  if (!token) {
    return { ok: false, error: "Not authenticated", status: 401 };
  }

  const base = apiUrl().replace(/\/+$/, "");
  const url = `${base}${path.startsWith("/") ? path : `/${path}`}`;

  try {
    const res = await fetch(url, {
      method: "POST",
      cache: "no-store",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
      },
    });
    let body: unknown = null;
    try {
      body = await res.json();
    } catch {
      // Non-JSON response (e.g. 204). Fall through with empty body.
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

/** Ban the Clerk user, blocking all sign-ins. */
export async function suspendAccount(userId: string): Promise<AdminActionResponse> {
  return adminPost(
    `/admin/users/${encodeURIComponent(userId)}/account/suspend`,
  );
}

/** Unban the Clerk user, restoring sign-in capability. */
export async function reactivateAccount(
  userId: string,
): Promise<AdminActionResponse> {
  return adminPost(
    `/admin/users/${encodeURIComponent(userId)}/account/reactivate`,
  );
}

/** Revoke all active Clerk sessions for the user. */
export async function forceSignout(userId: string): Promise<AdminActionResponse> {
  return adminPost(
    `/admin/users/${encodeURIComponent(userId)}/account/force-signout`,
  );
}

/** Re-send the Clerk email verification flow to the user. */
export async function resendVerification(
  userId: string,
): Promise<AdminActionResponse> {
  return adminPost(
    `/admin/users/${encodeURIComponent(userId)}/account/resend-verification`,
  );
}
