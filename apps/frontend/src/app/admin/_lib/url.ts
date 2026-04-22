import "server-only";

/**
 * Resolve the backend API base URL for the admin server-side fetcher.
 *
 * Prefers `API_URL` (server-only var, never shipped to the client bundle)
 * and falls back to `NEXT_PUBLIC_API_URL` so existing dev environments that
 * only set the public var keep working. Both are expected to already include
 * the `/api/v1` path segment, matching the existing `useApi` convention
 * (see `src/lib/api.ts`).
 *
 * Exported as a function (rather than a top-level constant) so unit tests can
 * override `process.env` and re-invoke without module-level evaluation.
 */
export function apiUrl(): string {
  return (
    process.env.API_URL ||
    process.env.NEXT_PUBLIC_API_URL ||
    "http://localhost:8000/api/v1"
  );
}
