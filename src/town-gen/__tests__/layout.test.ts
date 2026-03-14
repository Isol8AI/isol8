// src/town-gen/__tests__/layout.test.ts

import { generateZoneMap } from '../layout';
import { createRNG } from '../rng';
import type { Zone } from '../schema';

const W = 128;
const H = 96;

describe('generateZoneMap', () => {
  const rng = createRNG(42);
  const zones = generateZoneMap(W, H, rng);

  test('returns correct dimensions', () => {
    expect(zones.length).toBe(W);
    expect(zones[0].length).toBe(H);
  });

  test('borders are water', () => {
    for (let x = 0; x < W; x++) {
      expect(zones[x][0]).toBe('water');
      expect(zones[x][H - 1]).toBe('water');
    }
    for (let y = 0; y < H; y++) {
      expect(zones[0][y]).toBe('water');
      expect(zones[W - 1][y]).toBe('water');
    }
  });

  test('has a plaza zone', () => {
    let hasPlaza = false;
    for (let x = 0; x < W; x++) {
      for (let y = 0; y < H; y++) {
        if (zones[x][y] === 'plaza') hasPlaza = true;
      }
    }
    expect(hasPlaza).toBe(true);
  });

  test('has road zones', () => {
    let roadCount = 0;
    for (let x = 0; x < W; x++) {
      for (let y = 0; y < H; y++) {
        if (zones[x][y] === 'road') roadCount++;
      }
    }
    expect(roadCount).toBeGreaterThan(100);
  });

  test('has water canal', () => {
    // Canal runs roughly through middle third
    const midY = Math.floor(H / 2);
    let canalCount = 0;
    for (let x = 0; x < W; x++) {
      for (let y = midY - 10; y < midY + 10; y++) {
        if (zones[x][y] === 'canal') canalCount++;
      }
    }
    expect(canalCount).toBeGreaterThan(50);
  });

  test('has bridge zones crossing canal', () => {
    let hasBridge = false;
    for (let x = 0; x < W; x++) {
      for (let y = 0; y < H; y++) {
        if (zones[x][y] === 'bridge') hasBridge = true;
      }
    }
    expect(hasBridge).toBe(true);
  });

  test('deterministic — same seed same output', () => {
    const rng2 = createRNG(42);
    const zones2 = generateZoneMap(W, H, rng2);
    for (let x = 0; x < W; x++) {
      for (let y = 0; y < H; y++) {
        expect(zones2[x][y]).toBe(zones[x][y]);
      }
    }
  });
});
