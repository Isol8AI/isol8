const POLL_INTERVAL_MS = 3000;

/**
 * DELETE /api/v1/debug/provision — safe to call when no container exists.
 * Treats 404 (no container) and 503 (ECS error on nonexistent service) as "not running".
 */
export async function deprovisionIfExists(apiUrl: string, authToken: string): Promise<void> {
  const res = await fetch(`${apiUrl}/debug/provision`, {
    method: 'DELETE',
    headers: { Authorization: `Bearer ${authToken}` },
  });
  if (!res.ok && res.status !== 404 && res.status !== 503) {
    throw new Error(`Unexpected deprovision response: ${res.status}`);
  }
}

/**
 * Poll GET /api/v1/container/status until status === "running".
 * Throws on status === "error" or timeout.
 */
export async function waitForRunning(
  apiUrl: string,
  authToken: string,
  timeoutMs: number,
): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const res = await fetch(`${apiUrl}/container/status`, {
      headers: { Authorization: `Bearer ${authToken}` },
    });
    if (res.ok) {
      const data = await res.json();
      if (data.status === 'running' || data.substatus === 'gateway_healthy') return;
      if (data.status === 'error') {
        throw new Error(`Container entered error state: ${data.last_error}`);
      }
    }
    await new Promise((r) => setTimeout(r, POLL_INTERVAL_MS));
  }
  throw new Error(`waitForRunning: timeout after ${timeoutMs}ms`);
}
