// src/town-gen/__tests__/buildings.test.ts

import { placeBuildings } from '../buildings';
import { generateZoneMap } from '../layout';
import { createRNG } from '../rng';
import type { ZoneMap, PlacedBuilding } from '../schema';

const W = 128;
const H = 96;

// Zones that a door is allowed to face onto
const DOOR_WALKABLE = new Set(['road', 'plaza', 'park', 'grass', 'bridge', 'dock', 'shore']);

/** Returns true when two building footprints overlap. */
function footprintsOverlap(a: PlacedBuilding, b: PlacedBuilding): boolean {
  const aX2 = a.x + a.kit.footprint.w;
  const aY2 = a.y + a.kit.footprint.h;
  const bX2 = b.x + b.kit.footprint.w;
  const bY2 = b.y + b.kit.footprint.h;
  return a.x < bX2 && aX2 > b.x && a.y < bY2 && aY2 > b.y;
}

describe('placeBuildings', () => {
  let zones: ZoneMap;
  let buildings: PlacedBuilding[];
  let updatedZones: ZoneMap;

  beforeAll(() => {
    const rng = createRNG(42);
    zones = generateZoneMap(W, H, rng);
    const rng2 = createRNG(42);
    const result = placeBuildings(zones, W, H, rng2);
    buildings = result.buildings;
    updatedZones = result.updatedZones;
  });

  test('places at least 5 buildings', () => {
    expect(buildings.length).toBeGreaterThanOrEqual(5);
  });

  test('places exactly 1 civic building', () => {
    const civicBuildings = buildings.filter((b) => b.kit.class === 'civic');
    expect(civicBuildings).toHaveLength(1);
  });

  test('places at least 1 commercial building', () => {
    const commercial = buildings.filter((b) => b.kit.class === 'commercial');
    expect(commercial.length).toBeGreaterThanOrEqual(1);
  });

  test('no buildings overlap each other', () => {
    for (let i = 0; i < buildings.length; i++) {
      for (let j = i + 1; j < buildings.length; j++) {
        expect(footprintsOverlap(buildings[i], buildings[j])).toBe(false);
      }
    }
  });

  test('all building footprint cells are marked as building in updatedZones', () => {
    for (const b of buildings) {
      for (let dx = 0; dx < b.kit.footprint.w; dx++) {
        for (let dy = 0; dy < b.kit.footprint.h; dy++) {
          expect(updatedZones[b.x + dx][b.y + dy]).toBe('building');
        }
      }
    }
  });

  test('all building doors are adjacent to road/plaza/park/grass (walkable)', () => {
    for (const b of buildings) {
      const doorX = b.x + b.kit.doorOffset.x;
      const doorY = b.y + b.kit.doorOffset.y;
      // Door faces south — check the cell immediately below
      const frontCell = updatedZones[doorX]?.[doorY + 1];
      expect(frontCell).toBeDefined();
      expect(DOOR_WALKABLE.has(frontCell!)).toBe(true);
    }
  });

  test('original zone map is not mutated', () => {
    // The original zones should not have any 'building' cells (buildings were placed on the clone)
    let hasBuilding = false;
    for (let x = 0; x < W; x++) {
      for (let y = 0; y < H; y++) {
        if (zones[x][y] === 'building') {
          hasBuilding = true;
          break;
        }
      }
      if (hasBuilding) break;
    }
    expect(hasBuilding).toBe(false);
  });

  test('deterministic — same seed produces same placements', () => {
    const rng3 = createRNG(42);
    const zonesA = generateZoneMap(W, H, rng3);
    const rng4 = createRNG(42);
    const resultA = placeBuildings(zonesA, W, H, rng4);

    const rng5 = createRNG(42);
    const zonesB = generateZoneMap(W, H, rng5);
    const rng6 = createRNG(42);
    const resultB = placeBuildings(zonesB, W, H, rng6);

    expect(resultA.buildings.length).toBe(resultB.buildings.length);
    for (let i = 0; i < resultA.buildings.length; i++) {
      expect(resultA.buildings[i].x).toBe(resultB.buildings[i].x);
      expect(resultA.buildings[i].y).toBe(resultB.buildings[i].y);
      expect(resultA.buildings[i].kit.name).toBe(resultB.buildings[i].kit.name);
    }
  });
});
