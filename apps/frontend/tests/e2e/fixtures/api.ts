import type { Page } from '@playwright/test';

/**
 * Page-aware authenticated fetch. Reads a fresh Clerk JWT from the page on
 * every call (Clerk tokens expire after 60s). Adds X-E2E-Run-Id for backend
 * log correlation.
 */
export class AuthedFetch {
  constructor(
    private page: Page,
    private apiUrl: string,
    private runId: string,
  ) {}

  private async token(): Promise<string> {
    return this.page.evaluate(async () => {
      const w = window as Window & {
        Clerk?: { session?: { getToken: () => Promise<string> } };
      };
      return (await w.Clerk?.session?.getToken()) ?? '';
    });
  }

  private async send(method: string, path: string, body?: unknown): Promise<Response> {
    const token = await this.token();
    return fetch(`${this.apiUrl}${path}`, {
      method,
      headers: {
        Authorization: `Bearer ${token}`,
        'Content-Type': 'application/json',
        'X-E2E-Run-Id': this.runId,
      },
      body: body ? JSON.stringify(body) : undefined,
    });
  }

  async get<T = unknown>(path: string): Promise<T> {
    const res = await this.send('GET', path);
    if (!res.ok) throw new Error(`GET ${path} ${res.status}: ${await res.text()}`);
    return res.json() as Promise<T>;
  }

  async post<T = unknown>(path: string, body?: unknown): Promise<T> {
    const res = await this.send('POST', path, body);
    if (!res.ok) throw new Error(`POST ${path} ${res.status}: ${await res.text()}`);
    return res.json() as Promise<T>;
  }

  async delete<T = unknown>(path: string): Promise<T> {
    const res = await this.send('DELETE', path);
    if (!res.ok) throw new Error(`DELETE ${path} ${res.status}: ${await res.text()}`);
    return res.json() as Promise<T>;
  }
}
