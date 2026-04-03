const POLL_INTERVAL_MS = 3000;

/** Function that returns a fresh Clerk JWT (tokens expire after 60s). */
export type TokenGetter = () => Promise<string>;

/**
 * DELETE /api/v1/debug/provision — safe to call when no container exists.
 * Treats 401/404/503 as non-fatal (no container or expired token during cleanup).
 */
export async function deprovisionIfExists(apiUrl: string, getToken: TokenGetter): Promise<void> {
  const token = await getToken();
  const res = await fetch(`${apiUrl}/debug/provision`, {
    method: 'DELETE',
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok && res.status !== 401 && res.status !== 404 && res.status !== 503) {
    throw new Error(`Unexpected deprovision response: ${res.status}`);
  }
}

/**
 * Poll GET /api/v1/container/status until status === "running".
 * Refreshes the auth token on each poll (Clerk JWTs expire after 60s).
 */
export async function waitForRunning(
  apiUrl: string,
  getToken: TokenGetter,
  timeoutMs: number,
): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const token = await getToken();
    const res = await fetch(`${apiUrl}/container/status`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (res.ok) {
      const data = await res.json();
      if (data.status === 'running' || data.substatus === 'gateway_healthy') return;
      if (data.status === 'error') {
        throw new Error(`Container entered error state: ${data.last_error}`);
      }
    } else if (res.status !== 503) {
      throw new Error(`Unexpected poll response: ${res.status}`);
    }
    await new Promise((r) => setTimeout(r, POLL_INTERVAL_MS));
  }
  throw new Error(`waitForRunning: timeout after ${timeoutMs}ms`);
}
