import type { AuthedFetch } from './api';

type DdbRowsResponse = {
  tables: Record<string, number>;
};

export class DDBReader {
  constructor(private api: AuthedFetch, private ownerId: string) {}

  async rowCounts(): Promise<Record<string, number>> {
    const r = await this.api.get<DdbRowsResponse>(
      `/debug/ddb-rows?owner_id=${encodeURIComponent(this.ownerId)}`,
    );
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
