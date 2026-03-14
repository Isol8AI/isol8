// src/town-gen/buildings.ts — Building kit stamping onto plots

import type { ZoneMap, PlacedBuilding, RNG, BuildingKit } from './schema';
import { BUILDINGS } from './asset-registry';

// Zones considered "walkable" for door adjacency checks
const WALKABLE_ZONES = new Set(['road', 'plaza', 'park', 'grass', 'bridge', 'dock', 'shore']);

// Zones that block building placement
const BLOCKED_ZONES = new Set(['water', 'canal', 'road', 'plaza', 'building', 'bridge', 'dock', 'shore']);

type PlacementClass = 'civic' | 'commercial' | 'residential';

interface Candidate {
  x: number;
  y: number;
  kit: BuildingKit;
  class: PlacementClass;
}

/** Return true if all cells of the footprint starting at (x, y) are grass or park (unoccupied). */
function footprintFits(zones: ZoneMap, x: number, y: number, w: number, h: number): boolean {
  for (let dx = 0; dx < w; dx++) {
    for (let dy = 0; dy < h; dy++) {
      const cell = zones[x + dx]?.[y + dy];
      if (cell === undefined || BLOCKED_ZONES.has(cell)) return false;
    }
  }
  return true;
}

/** Check the 1-tile gap border around the footprint is free from other buildings. */
function gapClear(zones: ZoneMap, x: number, y: number, w: number, h: number): boolean {
  for (let dx = -1; dx <= w; dx++) {
    for (let dy = -1; dy <= h; dy++) {
      if (dx >= 0 && dx < w && dy >= 0 && dy < h) continue; // skip interior
      const cell = zones[x + dx]?.[y + dy];
      if (cell === 'building') return false;
    }
  }
  return true;
}

/**
 * Check that the door tile (kit.doorOffset from building origin x,y) has a walkable
 * zone directly in front of it (south, i.e. y+1 from the door row), and that there
 * is at least 2 tiles of clearance ahead.
 */
function doorFacing(zones: ZoneMap, x: number, y: number, kit: BuildingKit): boolean {
  const doorX = x + kit.doorOffset.x;
  const doorY = y + kit.doorOffset.y;

  // Door must be at the bottom row (doorOffset.y === footprint.h - 1)
  // The tile immediately south of the door should be walkable
  const frontY = doorY + 1;
  const front1 = zones[doorX]?.[frontY];
  const front2 = zones[doorX]?.[frontY + 1];

  if (front1 === undefined || !WALKABLE_ZONES.has(front1)) return false;
  if (front2 === undefined || !WALKABLE_ZONES.has(front2)) return false;

  return true;
}

/** Determine the placement class based on adjacency. */
function classifyLocation(
  zones: ZoneMap,
  x: number,
  y: number,
  w: number,
  h: number,
): PlacementClass {
  let nearPlaza = false;
  let nearRoad = false;

  // Check a 1-tile border around the footprint
  for (let dx = -1; dx <= w; dx++) {
    for (let dy = -1; dy <= h; dy++) {
      if (dx >= 0 && dx < w && dy >= 0 && dy < h) continue;
      const cell = zones[x + dx]?.[y + dy];
      if (cell === 'plaza') nearPlaza = true;
      if (cell === 'road') nearRoad = true;
    }
  }

  if (nearPlaza) return 'civic';
  if (nearRoad) return 'commercial';
  return 'residential';
}

/**
 * Stamp a building into the zone map — marks all footprint cells as 'building'.
 */
function stampBuilding(zones: ZoneMap, placed: PlacedBuilding): void {
  const { kit, x, y } = placed;
  for (let dx = 0; dx < kit.footprint.w; dx++) {
    for (let dy = 0; dy < kit.footprint.h; dy++) {
      zones[x + dx][y + dy] = 'building';
    }
  }
}

/**
 * Find kits that match the given placement class and fit within the given w/h.
 * Falls back to smaller kits or residential if no match.
 */
function kitsForClass(cls: PlacementClass, maxW: number, maxH: number): BuildingKit[] {
  const matching = BUILDINGS.filter(
    (k) => k.class === cls && k.footprint.w <= maxW && k.footprint.h <= maxH,
  );
  if (matching.length > 0) return matching;
  // Fallback: any kit that fits regardless of class
  return BUILDINGS.filter((k) => k.footprint.w <= maxW && k.footprint.h <= maxH);
}

export function placeBuildings(
  zones: ZoneMap,
  w: number,
  h: number,
  rng: RNG,
): { buildings: PlacedBuilding[]; updatedZones: ZoneMap } {
  // Deep-clone the zone map so we can mutate it
  const updatedZones: ZoneMap = zones.map((col) => [...col]);

  const buildings: PlacedBuilding[] = [];

  // Gather all candidates, categorised by class
  const civicCandidates: Candidate[] = [];
  const commercialCandidates: Candidate[] = [];
  const residentialCandidates: Candidate[] = [];

  // Pick the largest civic kit for civic placement — we want to try it first
  const civicKit = BUILDINGS.find((k) => k.class === 'civic')!;

  // Scan with stride 1 for thorough coverage, but only consider cells where a
  // minimum building (3x3) could fit without going out of bounds.
  const minSize = 3;
  for (let x = 1; x < w - minSize - 1; x++) {
    for (let y = 1; y < h - minSize - 1; y++) {
      const cell = updatedZones[x]?.[y];
      if (cell !== 'grass' && cell !== 'park') continue;

      const locClass = classifyLocation(updatedZones, x, y, minSize, minSize);

      // Determine which kits to try based on class
      let kitsToTry: BuildingKit[];
      if (locClass === 'civic') {
        kitsToTry = [civicKit, ...BUILDINGS.filter((k) => k.class === 'commercial')];
      } else if (locClass === 'commercial') {
        kitsToTry = BUILDINGS.filter((k) => k.class === 'commercial');
      } else {
        kitsToTry = BUILDINGS.filter((k) => k.class === 'residential');
      }

      for (const kit of kitsToTry) {
        // Bounds check
        if (x + kit.footprint.w >= w - 1 || y + kit.footprint.h >= h - 1) continue;
        if (!footprintFits(updatedZones, x, y, kit.footprint.w, kit.footprint.h)) continue;
        if (!gapClear(updatedZones, x, y, kit.footprint.w, kit.footprint.h)) continue;
        if (!doorFacing(updatedZones, x, y, kit)) continue;

        const candidate: Candidate = { x, y, kit, class: locClass };
        if (locClass === 'civic' && kit.class === 'civic') {
          civicCandidates.push(candidate);
        } else if (locClass === 'commercial' || (locClass === 'civic' && kit.class !== 'civic')) {
          commercialCandidates.push(candidate);
        } else {
          residentialCandidates.push(candidate);
        }
        break; // only add one candidate per cell (best-fit first)
      }
    }
  }

  /** Try to place from a candidate list, returning the placed building or null. */
  function tryPlace(candidates: Candidate[]): PlacedBuilding | null {
    // Shuffle for variety
    const shuffled = [...candidates].sort(() => rng.next() - 0.5);
    for (const c of shuffled) {
      // Re-check in case a previous placement consumed this spot
      if (!footprintFits(updatedZones, c.x, c.y, c.kit.footprint.w, c.kit.footprint.h)) continue;
      if (!gapClear(updatedZones, c.x, c.y, c.kit.footprint.w, c.kit.footprint.h)) continue;
      if (!doorFacing(updatedZones, c.x, c.y, c.kit)) continue;

      const placed: PlacedBuilding = { kit: c.kit, x: c.x, y: c.y };
      stampBuilding(updatedZones, placed);
      return placed;
    }
    return null;
  }

  // 1. Place exactly 1 civic building
  const civic = tryPlace(civicCandidates);
  if (civic) buildings.push(civic);

  // 2. Place commercial buildings (aim for ~4)
  const commercialTarget = 4;
  for (let i = 0; i < commercialTarget; i++) {
    const placed = tryPlace(commercialCandidates);
    if (!placed) break;
    buildings.push(placed);
  }

  // 3. Place residential buildings (fill remaining space)
  const residentialTarget = 8;
  for (let i = 0; i < residentialTarget; i++) {
    const placed = tryPlace(residentialCandidates);
    if (!placed) break;
    buildings.push(placed);
  }

  return { buildings, updatedZones };
}
