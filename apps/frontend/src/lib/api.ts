import { useCallback, useMemo } from "react";
import { useAuth } from "@clerk/nextjs";

// Use environment variable for production, fallback to localhost for development
export const BACKEND_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1";

/**
 * Derive the WebSocket gateway URL from `apiUrl`.
 *
 * Hostname rewrite:
 *   api.isol8.co       → ws.isol8.co
 *   api-dev.isol8.co   → ws-dev.isol8.co
 *   api-staging.isol8.co → ws-staging.isol8.co
 *   localhost:8000     → localhost:8000   (untouched — local dev hits the same host)
 *
 * Protocol: http → ws, https → wss. Path `/api/v1` is stripped so callers get
 * the bare WebSocket origin (they append their own path, e.g. `/control-ui/`).
 *
 * An explicit `NEXT_PUBLIC_WS_URL` env var takes precedence over derivation so
 * bespoke environments (e.g. a PR preview against a non-standard gateway) can
 * override without code changes.
 */
export function deriveWebSocketUrl(apiUrl: string): string {
  if (process.env.NEXT_PUBLIC_WS_URL) {
    return process.env.NEXT_PUBLIC_WS_URL;
  }
  return apiUrl
    .replace(/^https:\/\//, "wss://")
    .replace(/^http:\/\//, "ws://")
    // Rewrite the HOSTNAME only. `\/\/` anchors us right after the scheme so a
    // path segment like `/api/v1` can't accidentally match; lookahead `(?=[-.])`
    // requires `-` or `.` after `api` so "apiary.com" wouldn't match and
    // localhost (which doesn't start with "api") is left alone.
    .replace(/\/\/api(?=[-.])/, "//ws")
    .replace(/\/api\/v1$/, "");
}

export const WS_URL = deriveWebSocketUrl(BACKEND_URL);

/**
 * Thrown by `useApi` helpers when the backend returns a non-2xx response.
 *
 * `body` is the parsed JSON response body when Content-Type is JSON, else
 * null. Callers can switch on `status` and `body` to handle structured
 * error payloads (e.g. the `blocked` field from /container/* endpoints).
 */
export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly body: unknown,
    message?: string,
  ) {
    super(message ?? `API ${status}`);
    this.name = "ApiError";
  }
}

interface UploadedFile {
  filename: string;
  path: string;
  size: number;
}

interface UploadResponse {
  uploaded: UploadedFile[];
}

interface ApiMethods {
  syncUser: () => Promise<unknown>;
  get: (endpoint: string) => Promise<unknown>;
  post: (endpoint: string, body: unknown) => Promise<unknown>;
  put: (endpoint: string, body: unknown) => Promise<unknown>;
  patch: (endpoint: string, body: unknown) => Promise<unknown>;
  del: (endpoint: string) => Promise<unknown>;
  patchConfig: (patch: Record<string, unknown>) => Promise<{ status: string; owner_id: string }>;
  uploadFiles: (files: File[], agentId: string) => Promise<UploadResponse>;
  saveWorkspaceFile: (agentId: string, path: string, content: string, tab: "workspace" | "config") => Promise<{ status: string; path: string }>;
}

export function useApi(): ApiMethods {
  const { getToken } = useAuth();

  const authenticatedFetch = useCallback(
    async function (endpoint: string, options: RequestInit = {}): Promise<unknown> {
      const token = await getToken();

      if (!token) {
        throw new Error("No authentication token available");
      }

      const headers: HeadersInit = {
        ...options.headers,
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
      };

      const response = await fetch(`${BACKEND_URL}${endpoint}`, {
        ...options,
        headers,
      });

      if (!response.ok) {
        // Preserve the parsed body on non-2xx so callers can switch on
        // structured error fields (e.g. `blocked` from /container/*
        // endpoints). Falls back to `null` on empty / non-JSON / malformed
        // bodies.
        const ct = response.headers.get("Content-Type") ?? "";
        let body: unknown = null;
        if (ct.includes("application/json")) {
          try {
            body = await response.json();
          } catch {
            // empty/malformed JSON — leave body as null
          }
        }
        const detail =
          body && typeof body === "object" && "detail" in body
            ? (body as { detail?: unknown }).detail
            : undefined;
        const message = typeof detail === "string" ? detail : undefined;
        throw new ApiError(response.status, body, message);
      }

      return response.json();
    },
    [getToken]
  );

  return useMemo(
    () => ({
      syncUser(): Promise<unknown> {
        return authenticatedFetch("/users/sync", { method: "POST" });
      },
      get(endpoint: string): Promise<unknown> {
        return authenticatedFetch(endpoint, { method: "GET" });
      },
      post(endpoint: string, body: unknown): Promise<unknown> {
        return authenticatedFetch(endpoint, {
          method: "POST",
          body: JSON.stringify(body),
        });
      },
      put(endpoint: string, body: unknown): Promise<unknown> {
        return authenticatedFetch(endpoint, {
          method: "PUT",
          body: JSON.stringify(body),
        });
      },
      patch(endpoint: string, body: unknown): Promise<unknown> {
        return authenticatedFetch(endpoint, {
          method: "PATCH",
          body: JSON.stringify(body),
        });
      },
      del(endpoint: string): Promise<unknown> {
        return authenticatedFetch(endpoint, { method: "DELETE" });
      },
      patchConfig(patch: Record<string, unknown>): Promise<{ status: string; owner_id: string }> {
        return authenticatedFetch("/config", {
          method: "PATCH",
          body: JSON.stringify({ patch }),
        }) as Promise<{ status: string; owner_id: string }>;
      },
      async uploadFiles(files: File[], agentId: string): Promise<UploadResponse> {
        const token = await getToken();
        if (!token) throw new Error("No authentication token available");

        const formData = new FormData();
        for (const file of files) {
          formData.append("files", file);
        }

        const response = await fetch(`${BACKEND_URL}/container/files?agent_id=${encodeURIComponent(agentId)}`, {
          method: "POST",
          headers: { Authorization: `Bearer ${token}` },
          body: formData,
        });

        if (!response.ok) {
          const errorData = await response.json().catch(() => ({}));
          throw new Error(errorData.detail || "Upload failed");
        }

        return response.json();
      },
      saveWorkspaceFile(
        agentId: string,
        path: string,
        content: string,
        tab: "workspace" | "config",
      ): Promise<{ status: string; path: string }> {
        return authenticatedFetch(`/container/workspace/${encodeURIComponent(agentId)}/file`, {
          method: "PUT",
          body: JSON.stringify({ path, content, tab }),
        }) as Promise<{ status: string; path: string }>;
      },
    }),
    [authenticatedFetch, getToken]
  );
}
