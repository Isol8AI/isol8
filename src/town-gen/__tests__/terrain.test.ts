// src/town-gen/__tests__/terrain.test.ts

import { fillTerrainLayers } from '../terrain';
import { generateZoneMap } from '../layout';
import { createRNG } from '../rng';
import { TILESET, TERRAIN } from '../asset-registry';

const W = 128;
const H = 96;

describe('fillTerrainLayers', () => {
  const rng = createRNG(42);
  const zones = generateZoneMap(W, H, rng);
  const rng2 = createRNG(42); // fresh rng for terrain pass
  const layers = fillTerrainLayers(zones, W, H, rng2);

  test('Ground_Base has correct size (W*H)', () => {
    expect(layers.Ground_Base.length).toBe(W * H);
  });

  test('Ground_Detail has correct size (W*H)', () => {
    expect(layers.Ground_Detail.length).toBe(W * H);
  });

  test('Water_Back has correct size (W*H)', () => {
    expect(layers.Water_Back.length).toBe(W * H);
  });

  test('Terrain_Structures has correct size (W*H)', () => {
    expect(layers.Terrain_Structures.length).toBe(W * H);
  });

  test('Ground_Base has non-zero GIDs for all cells', () => {
    // Every cell should have a tile
    const zeros = layers.Ground_Base.filter((g) => g === 0);
    expect(zeros.length).toBe(0);
  });

  test('Water zones get non-zero GIDs in Ground_Base', () => {
    let waterFound = false;
    for (let x = 0; x < W; x++) {
      for (let y = 0; y < H; y++) {
        const zone = zones[x][y];
        if (zone === 'water' || zone === 'canal') {
          const gid = layers.Ground_Base[y * W + x];
          expect(gid).toBeGreaterThan(0);
          waterFound = true;
        }
      }
    }
    expect(waterFound).toBe(true);
  });

  test('Water_Back has non-zero values only for water/canal zones', () => {
    for (let x = 0; x < W; x++) {
      for (let y = 0; y < H; y++) {
        const zone = zones[x][y];
        const waterBackGid = layers.Water_Back[y * W + x];
        if (zone === 'water' || zone === 'canal') {
          expect(waterBackGid).toBeGreaterThan(0);
        } else {
          expect(waterBackGid).toBe(0);
        }
      }
    }
  });

  test('GIDs in Ground_Base are >= firstgid', () => {
    for (const gid of layers.Ground_Base) {
      expect(gid).toBeGreaterThanOrEqual(TILESET.firstgid);
    }
  });

  test('GIDs in Ground_Base are within tileset range', () => {
    const maxGid = TILESET.firstgid + TILESET.tilecount - 1;
    for (const gid of layers.Ground_Base) {
      expect(gid).toBeLessThanOrEqual(maxGid);
    }
  });

  test('No horizontal streak greater than 3', () => {
    for (let y = 0; y < H; y++) {
      let streakGid = -1;
      let streakLen = 0;
      for (let x = 0; x < W; x++) {
        const gid = layers.Ground_Base[y * W + x];
        if (gid === streakGid) {
          streakLen++;
          expect(streakLen).toBeLessThanOrEqual(3);
        } else {
          streakGid = gid;
          streakLen = 1;
        }
      }
    }
  });

  test('No vertical streak greater than 3', () => {
    for (let x = 0; x < W; x++) {
      let streakGid = -1;
      let streakLen = 0;
      for (let y = 0; y < H; y++) {
        const gid = layers.Ground_Base[y * W + x];
        if (gid === streakGid) {
          streakLen++;
          expect(streakLen).toBeLessThanOrEqual(3);
        } else {
          streakGid = gid;
          streakLen = 1;
        }
      }
    }
  });

  test('Bridge zones get structures layer tiles', () => {
    let bridgeFound = false;
    for (let x = 0; x < W; x++) {
      for (let y = 0; y < H; y++) {
        if (zones[x][y] === 'bridge') {
          const structGid = layers.Terrain_Structures[y * W + x];
          expect(structGid).toBeGreaterThan(0);
          bridgeFound = true;
        }
      }
    }
    expect(bridgeFound).toBe(true);
  });

  test('Non-bridge cells adjacent to canal get canal_wall structures', () => {
    const canalWallGid = TERRAIN['canal_wall'].primary + TILESET.firstgid;
    let wallFound = false;

    for (let x = 0; x < W; x++) {
      for (let y = 0; y < H; y++) {
        const zone = zones[x][y];
        // Skip canal itself and bridge zones (bridges get road tile, not canal wall)
        if (zone === 'canal' || zone === 'bridge') continue;

        const cardinalNeighbors: [number, number][] = [[0, -1], [0, 1], [1, 0], [-1, 0]];
        const adjacentToCanal = cardinalNeighbors.some(([dx, dy]) => {
          const nx = x + dx;
          const ny = y + dy;
          if (nx < 0 || nx >= W || ny < 0 || ny >= H) return false;
          return zones[nx][ny] === 'canal';
        });

        if (adjacentToCanal) {
          expect(layers.Terrain_Structures[y * W + x]).toBe(canalWallGid);
          wallFound = true;
        }
      }
    }
    expect(wallFound).toBe(true);
  });

  test('Deterministic — same seed produces same output', () => {
    const rng3 = createRNG(42);
    const zones3 = generateZoneMap(W, H, rng3);
    const rng4 = createRNG(42);
    const layers2 = fillTerrainLayers(zones3, W, H, rng4);

    expect(layers2.Ground_Base).toEqual(layers.Ground_Base);
    expect(layers2.Ground_Detail).toEqual(layers.Ground_Detail);
    expect(layers2.Water_Back).toEqual(layers.Water_Back);
    expect(layers2.Terrain_Structures).toEqual(layers.Terrain_Structures);
  });
});
