import type { AuthedFetch } from '../fixtures/api';

export async function containerHealthy(
  api: AuthedFetch,
  opts: { timeoutMs?: number } = {},
): Promise<void> {
  const deadline = Date.now() + (opts.timeoutMs ?? 10 * 60_000);
  let last: string | undefined;
  while (Date.now() < deadline) {
    try {
      const data = await api.get<{ status: string; substatus?: string }>(
        '/container/status',
      );
      if (data.substatus === 'gateway_healthy') return;
      last = `${data.status}/${data.substatus}`;
      if (data.status === 'error') {
        throw new Error(`Container in error state: ${last}`);
      }
    } catch (err) {
      // 503 during ECS rolling update is normal; ignore and retry.
      if (!String(err).includes('503')) {
        console.warn('[e2e] container status err:', err);
      }
    }
    await new Promise((r) => setTimeout(r, 3000));
  }
  throw new Error(`containerHealthy: timed out, last status=${last}`);
}
