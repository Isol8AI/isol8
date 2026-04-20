import type { AuthedFetch } from './api';

type DdbRowsResponse = {
  tables: Record<string, number>;
};

export class DDBReader {
  /**
   * For personal flows pass `userId` undefined — backend will treat
   * `owner_id` as both. For org flows pass `ownerId = orgId` AND
   * `userId = clerkUserId` so user-scoped tables (users, ws-connections)
   * are queried with the right key.
   */
  constructor(
    private api: AuthedFetch,
    private ownerId: string,
    private userId?: string,
  ) {}

  async rowCounts(): Promise<Record<string, number>> {
    const params = new URLSearchParams({ owner_id: this.ownerId });
    if (this.userId && this.userId !== this.ownerId) {
      params.set('user_id', this.userId);
    }
    const r = await this.api.get<DdbRowsResponse>(`/debug/ddb-rows?${params}`);
    return r.tables;
  }

  async assertEmpty(): Promise<void> {
    const counts = await this.rowCounts();
    const nonZero = Object.entries(counts).filter(([, n]) => n > 0);
    if (nonZero.length > 0) {
      throw new Error(`DDB cleanup leak: ${JSON.stringify(Object.fromEntries(nonZero))}`);
    }
  }
}
