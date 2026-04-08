import { useCallback, useMemo } from "react";
import { useAuth } from "@clerk/nextjs";

// Use environment variable for production, fallback to localhost for development
export const BACKEND_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1";

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
