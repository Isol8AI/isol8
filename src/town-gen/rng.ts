// src/town-gen/rng.ts — Mulberry32 seeded PRNG

import type { RNG } from './schema';

export function createRNG(seed: number): RNG {
  let s = seed | 0;

  function next(): number {
    s |= 0;
    s = (s + 0x6d2b79f5) | 0;
    let t = Math.imul(s ^ (s >>> 15), 1 | s);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  }

  return {
    next,
    nextInt(max: number) {
      return Math.floor(next() * max);
    },
    pick<T>(arr: T[]): T {
      return arr[Math.floor(next() * arr.length)];
    },
    weightedPick(ids: number[], weights?: number[]): number {
      if (!weights || weights.length === 0) {
        return ids[Math.floor(next() * ids.length)];
      }
      const total = weights.reduce((a, b) => a + b, 0);
      let r = next() * total;
      for (let i = 0; i < ids.length; i++) {
        r -= weights[i];
        if (r <= 0) return ids[i];
      }
      return ids[ids.length - 1];
    },
  };
}
