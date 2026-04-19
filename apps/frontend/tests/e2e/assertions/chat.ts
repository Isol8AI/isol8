import type { AuthedFetch } from '../fixtures/api';

type Session = { sessionKey?: string; usage?: { model?: string } };
type SessionsListResponse = { sessions?: Session[] };

export async function modelUsed(
  api: AuthedFetch,
  expectedModel: string,
  opts: { timeoutMs?: number } = {},
): Promise<void> {
  const deadline = Date.now() + (opts.timeoutMs ?? 30_000);
  while (Date.now() < deadline) {
    const data = await api.post<SessionsListResponse>('/container/rpc', {
      method: 'sessions.list',
      params: {},
    });
    const sessions = data.sessions ?? [];
    const used = sessions.flatMap((s) => (s.usage?.model ? [s.usage.model] : []));
    if (used.some((m) => m === expectedModel)) return;
    await new Promise((r) => setTimeout(r, 2000));
  }
  throw new Error(
    `modelUsed: expected ${expectedModel}, none of the recent sessions matched`,
  );
}
