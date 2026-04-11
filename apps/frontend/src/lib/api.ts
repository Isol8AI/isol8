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
  del: (endpoint: string) => Promise<unknown>;
  patchConfig: (patch: Record<string, unknown>) => Promise<{ status: string; owner_id: string }>;
  uploadFiles: (files: File[]) => Promise<UploadResponse>;
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
        const errorData = await response.json().catch(() => ({}));
        const error = new Error(errorData.detail || "API request failed") as Error & {
          status: number;
          detail?: string;
        };
        error.status = response.status;
        error.detail = errorData.detail;
        throw error;
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
      del(endpoint: string): Promise<unknown> {
        return authenticatedFetch(endpoint, { method: "DELETE" });
      },
      patchConfig(patch: Record<string, unknown>): Promise<{ status: string; owner_id: string }> {
        return authenticatedFetch("/config", {
          method: "PATCH",
          body: JSON.stringify({ patch }),
        }) as Promise<{ status: string; owner_id: string }>;
      },
      async uploadFiles(files: File[]): Promise<UploadResponse> {
        const token = await getToken();
        if (!token) throw new Error("No authentication token available");

        const formData = new FormData();
        for (const file of files) {
          formData.append("files", file);
        }

        const response = await fetch(`${BACKEND_URL}/container/files`, {
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
    }),
    [authenticatedFetch, getToken]
  );
}
