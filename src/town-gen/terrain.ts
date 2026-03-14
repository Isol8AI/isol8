// src/town-gen/terrain.ts — Ground tile placement with transitions and streak limiting

import type { ZoneMap, RNG, Zone } from './schema';
import { TERRAIN, TRANSITIONS, TILESET } from './asset-registry';

export interface TerrainLayers {
  Ground_Base: number[];       // w*h flat array, row-major (y*w+x)
  Ground_Detail: number[];     // transition tiles
  Water_Back: number[];        // water positions for animation
  Terrain_Structures: number[]; // canal walls, bridge bases
}

// Map zone types to terrain family keys
function zoneToTerrainKey(zone: Zone): string {
  switch (zone) {
    case 'water':    return 'water';
    case 'shore':    return 'shore';
    case 'grass':    return 'grass';
    case 'road':     return 'road';
    case 'plaza':    return 'plaza';
    case 'canal':    return 'water';
    case 'dock':     return 'dock';
    case 'park':     return 'grass';
    case 'building': return 'grass';
    case 'bridge':   return 'road';
    default:         return 'grass';
  }
}

// Pick a weighted-random tile from a terrain family (local ID)
function pickTile(terrainKey: string, rng: RNG): number {
  const family = TERRAIN[terrainKey];
  if (!family) return TERRAIN['grass'].primary;
  const allIds = [family.primary, ...family.alternates];
  return rng.weightedPick(allIds, family.weights);
}

// Pick a tile that is different from `exclude` (still valid for the family)
function pickDifferentTile(terrainKey: string, excludeLocalId: number, rng: RNG): number {
  const family = TERRAIN[terrainKey];
  if (!family) return TERRAIN['grass'].primary;
  const allIds = [family.primary, ...family.alternates];
  if (allIds.length <= 1) return allIds[0]; // only one tile, can't differ

  // Build list of candidates that are NOT the excluded tile
  const candidates = allIds.filter((id) => id !== excludeLocalId);
  if (candidates.length === 0) return allIds[0]; // can't differ — single-variant

  // Pick from the non-excluded candidates using uniform random (no weights,
  // since we must guarantee a different tile)
  return candidates[rng.nextInt(candidates.length)];
}

// Determine which direction a neighbor is relative to center cell (dx, dy)
type Dir = 'n' | 's' | 'e' | 'w' | 'ne' | 'nw' | 'se' | 'sw';

function getDir(dx: number, dy: number): Dir | null {
  if (dx === 0 && dy === -1) return 'n';
  if (dx === 0 && dy === 1)  return 's';
  if (dx === 1 && dy === 0)  return 'e';
  if (dx === -1 && dy === 0) return 'w';
  if (dx === 1 && dy === -1) return 'ne';
  if (dx === -1 && dy === -1) return 'nw';
  if (dx === 1 && dy === 1)  return 'se';
  if (dx === -1 && dy === 1) return 'sw';
  return null;
}

// Look up a transition tile between two terrain keys
// Returns local tile ID or 0 if no transition found
function getTransitionTile(fromKey: string, toKey: string, dir: Dir): number {
  // Try direct key
  const directKey = `${fromKey}_to_${toKey}`;
  if (TRANSITIONS[directKey]) {
    return TRANSITIONS[directKey][dir];
  }
  // Try reverse (swap inner/outer directions)
  const reverseKey = `${toKey}_to_${fromKey}`;
  if (TRANSITIONS[reverseKey]) {
    // Flip the direction for the reversed lookup
    const flippedDir = flipDir(dir);
    return TRANSITIONS[reverseKey][flippedDir];
  }
  return 0;
}

function flipDir(dir: Dir): Dir {
  switch (dir) {
    case 'n': return 's';
    case 's': return 'n';
    case 'e': return 'w';
    case 'w': return 'e';
    case 'ne': return 'sw';
    case 'sw': return 'ne';
    case 'nw': return 'se';
    case 'se': return 'nw';
  }
}

export function fillTerrainLayers(zones: ZoneMap, w: number, h: number, rng: RNG): TerrainLayers {
  const size = w * h;
  const Ground_Base: number[] = new Array(size).fill(0);
  const Ground_Detail: number[] = new Array(size).fill(0);
  const Water_Back: number[] = new Array(size).fill(0);
  const Terrain_Structures: number[] = new Array(size).fill(0);

  // Helper: index into flat array
  const idx = (x: number, y: number) => y * w + x;

  // Helper: get zone safely
  const getZone = (x: number, y: number): Zone => {
    if (x < 0 || x >= w || y < 0 || y >= h) return 'water';
    return zones[x][y];
  };

  // -----------------------------------------------------------------------
  // Pass 1: Ground_Base — fill with weighted random tiles
  // Single pass (row-major) enforcing BOTH horizontal and vertical streaks ≤3.
  // At each cell (x,y), if the proposed GID would extend either the horizontal
  // run (checking x-3, x-2, x-1) or the vertical run (checking y-3, y-2, y-1)
  // to length 4, we pick a different tile from the same terrain family.
  // -----------------------------------------------------------------------
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      const zone = getZone(x, y);
      const terrainKey = zoneToTerrainKey(zone);
      let localId = pickTile(terrainKey, rng);
      let gid = localId + TILESET.firstgid;

      // Helper: check whether `candidateGid` would form a horizontal run of 4
      const wouldHStreak = (candidateGid: number): boolean =>
        x >= 3 &&
        Ground_Base[idx(x - 1, y)] === candidateGid &&
        Ground_Base[idx(x - 2, y)] === candidateGid &&
        Ground_Base[idx(x - 3, y)] === candidateGid;

      // Helper: check whether `candidateGid` would form a vertical run of 4
      const wouldVStreak = (candidateGid: number): boolean =>
        y >= 3 &&
        Ground_Base[idx(x, y - 1)] === candidateGid &&
        Ground_Base[idx(x, y - 2)] === candidateGid &&
        Ground_Base[idx(x, y - 3)] === candidateGid;

      if (wouldHStreak(gid) || wouldVStreak(gid)) {
        // Build list of GIDs from this family that break BOTH constraints
        const family = TERRAIN[terrainKey];
        const allIds = family ? [family.primary, ...family.alternates] : [localId];
        // Filter to tiles that do NOT create either kind of streak
        const safe = allIds.filter((lid) => {
          const candidateGid = lid + TILESET.firstgid;
          return !wouldHStreak(candidateGid) && !wouldVStreak(candidateGid);
        });

        if (safe.length > 0) {
          // Pick randomly from safe candidates, consuming RNG to stay deterministic
          const picked = safe[rng.nextInt(safe.length)];
          gid = picked + TILESET.firstgid;
        } else {
          // All tiles in the family would create a streak (single-variant family).
          // Pick any different one from the family to minimise the streak,
          // preferring to break the horizontal constraint first.
          const altLocalId = pickDifferentTile(terrainKey, localId, rng);
          gid = altLocalId + TILESET.firstgid;
        }
      }

      Ground_Base[idx(x, y)] = gid;
    }
  }

  // -----------------------------------------------------------------------
  // Pass 2: Ground_Detail — transition edge/corner tiles between zones
  // -----------------------------------------------------------------------
  const neighbors8: [number, number][] = [
    [0, -1], [0, 1], [1, 0], [-1, 0],
    [1, -1], [-1, -1], [1, 1], [-1, 1],
  ];

  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      const zone = getZone(x, y);
      const terrainKey = zoneToTerrainKey(zone);
      let transitionGid = 0;

      for (const [dx, dy] of neighbors8) {
        const nx = x + dx;
        const ny = y + dy;
        const neighborZone = getZone(nx, ny);
        const neighborKey = zoneToTerrainKey(neighborZone);

        if (neighborKey === terrainKey) continue; // same terrain, no transition needed

        const dir = getDir(dx, dy);
        if (!dir) continue;

        const localId = getTransitionTile(terrainKey, neighborKey, dir);
        if (localId > 0) {
          transitionGid = localId + TILESET.firstgid;
          break; // Use the first matching transition found
        }
      }

      Ground_Detail[idx(x, y)] = transitionGid;
    }
  }

  // -----------------------------------------------------------------------
  // Pass 3: Terrain_Structures — bridges and canal walls
  // -----------------------------------------------------------------------
  const canalWallLocalId = TERRAIN['canal_wall'].primary;

  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      const zone = getZone(x, y);

      if (zone === 'bridge') {
        // Bridge zones: road tile on structures layer
        const roadFamily = TERRAIN['road'];
        Terrain_Structures[idx(x, y)] = roadFamily.primary + TILESET.firstgid;
      } else if (zone !== 'canal') {
        // Check if adjacent to canal
        const cardinalNeighbors: [number, number][] = [[0, -1], [0, 1], [1, 0], [-1, 0]];
        for (const [dx, dy] of cardinalNeighbors) {
          const neighborZone = getZone(x + dx, y + dy);
          if (neighborZone === 'canal') {
            Terrain_Structures[idx(x, y)] = canalWallLocalId + TILESET.firstgid;
            break;
          }
        }
      }
    }
  }

  // -----------------------------------------------------------------------
  // Water_Back — copy water tile positions for zones 'water' or 'canal'
  // -----------------------------------------------------------------------
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      const zone = getZone(x, y);
      if (zone === 'water' || zone === 'canal') {
        Water_Back[idx(x, y)] = Ground_Base[idx(x, y)];
      }
    }
  }

  return { Ground_Base, Ground_Detail, Water_Back, Terrain_Structures };
}
