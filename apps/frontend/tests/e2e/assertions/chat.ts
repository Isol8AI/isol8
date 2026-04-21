import { AuthedFetchError, type AuthedFetch } from '../fixtures/api';

type Session = { sessionKey?: string; usage?: { model?: string } };
type SessionsListResponse = { sessions?: Session[] };

export async function modelUsed(
  api: AuthedFetch,
  expectedModel: string,
  opts: { timeoutMs?: number } = {},
): Promise<void> {
  // 3-minute budget — after a free→starter upgrade, the gateway RPC path
  // briefly returns 502 "Gateway RPC call failed" while the OpenClaw
  // container reconfigures (model swap + config watcher reload). That
  // window can exceed the AuthedFetch internal retry (5 × 2s = 10s), so
  // we wrap the whole poll in a longer budget and explicitly swallow
  // transient 5xx to keep trying. PR #343 e2e-dev artifact (run
  // 24725288866, 2026-04-21) hit this — 502 on modelUsed ~12s after
  // Step 4 completed.
  const deadline = Date.now() + (opts.timeoutMs ?? 5 * 60_000);
  let lastSeen: string[] = [];
  while (Date.now() < deadline) {
    try {
      const data = await api.post<SessionsListResponse>('/container/rpc', {
        method: 'sessions.list',
        params: {},
      });
      const sessions = data.sessions ?? [];
      const used = sessions.flatMap((s) => (s.usage?.model ? [s.usage.model] : []));
      lastSeen = used;
      // Tolerate provider prefix — the backend config stores
      // "amazon-bedrock/qwen.qwen3-vl-235b-a22b" while some session
      // usage records strip the "amazon-bedrock/" prefix
      // (bedrock_pricing.py uses the bare id; apps/backend/core/config.py
      // uses the prefixed form). Match either (PR #345 e2e-dev artifact
      // run 24729067287, 2026-04-21: modelUsed never matched the bare-id
      // expected value).
      const suffix = expectedModel.replace(/^.*\//, '');
      if (used.some((m) => m === expectedModel || m === suffix || m.endsWith(`/${suffix}`))) {
        return;
      }
    } catch (err) {
      // Swallow transient 5xx — the gateway is temporarily disconnected
      // from the reconfiguring container. Let any other error propagate
      // so real bugs surface fast.
      if (!(err instanceof AuthedFetchError) || err.status < 500 || err.status >= 600) {
        throw err;
      }
    }
    await new Promise((r) => setTimeout(r, 2000));
  }
  throw new Error(
    `modelUsed: expected ${expectedModel}, never observed within 5 min. ` +
      `Last seen models across sessions: [${lastSeen.join(', ')}]`,
  );
}
