// src/town-gen/generator.ts — Main generation pipeline + validation

import { createRNG } from './rng';
import { generateZoneMap } from './layout';
import { fillTerrainLayers } from './terrain';
import { placeBuildings } from './buildings';
import { placeProps } from './props';
import { generateCollision, generateSpawnPoints } from './collision';
import { exportTmj } from './exporter';
import { TILESET } from './asset-registry';
import type {
  TmjMap,
  TownManifest,
  PlacedBuilding,
  SpawnPoint,
  CollisionRect,
} from './schema';

const W = 128;
const H = 96;

// -------------------------------------------------------
// A* pathfinding — used only for validation
// -------------------------------------------------------

function astar(
  startX: number,
  startY: number,
  goalX: number,
  goalY: number,
  blocked: Set<string>,
  w: number,
  h: number,
): boolean {
  if (startX === goalX && startY === goalY) return true;

  // Priority queue entries: [f, x, y]
  type Entry = [number, number, number];

  const open: Entry[] = [];
  const gScore = new Map<string, number>();
  const inOpen = new Set<string>();

  const key = (x: number, y: number) => `${x},${y}`;
  const h_dist = (x: number, y: number) => Math.abs(x - goalX) + Math.abs(y - goalY);

  const startKey = key(startX, startY);
  gScore.set(startKey, 0);
  open.push([h_dist(startX, startY), startX, startY]);
  inOpen.add(startKey);

  let iterations = 0;
  const MAX_ITER = 50000;

  const dirs: [number, number][] = [[0, 1], [0, -1], [1, 0], [-1, 0]];

  while (open.length > 0 && iterations < MAX_ITER) {
    iterations++;

    // Find min-f entry (simple linear scan — acceptable for validation)
    let minIdx = 0;
    for (let i = 1; i < open.length; i++) {
      if (open[i][0] < open[minIdx][0]) minIdx = i;
    }
    const [, cx, cy] = open[minIdx];
    open.splice(minIdx, 1);

    if (cx === goalX && cy === goalY) return true;

    const cKey = key(cx, cy);
    inOpen.delete(cKey);
    const cg = gScore.get(cKey) ?? Infinity;

    for (const [dx, dy] of dirs) {
      const nx = cx + dx;
      const ny = cy + dy;
      if (nx < 0 || nx >= w || ny < 0 || ny >= h) continue;
      const nKey = key(nx, ny);
      if (blocked.has(nKey)) continue;

      const ng = cg + 1;
      const existing = gScore.get(nKey) ?? Infinity;
      if (ng < existing) {
        gScore.set(nKey, ng);
        const f = ng + h_dist(nx, ny);
        if (!inOpen.has(nKey)) {
          open.push([f, nx, ny]);
          inOpen.add(nKey);
        }
      }
    }
  }

  return false;
}

// -------------------------------------------------------
// Spawn relocation — nudge any spawn that lands on a blocked tile
// -------------------------------------------------------

function relocateSpawns(
  spawns: SpawnPoint[],
  blocked: Set<string>,
  w: number,
  h: number,
): SpawnPoint[] {
  return spawns.map((spawn) => {
    const k = `${spawn.x},${spawn.y}`;
    if (!blocked.has(k)) return spawn;

    // BFS spiral outward until we find a non-blocked tile
    for (let radius = 1; radius < Math.max(w, h); radius++) {
      for (let dx = -radius; dx <= radius; dx++) {
        for (let dy = -radius; dy <= radius; dy++) {
          if (Math.abs(dx) !== radius && Math.abs(dy) !== radius) continue; // border only
          const nx = spawn.x + dx;
          const ny = spawn.y + dy;
          if (nx < 0 || nx >= w || ny < 0 || ny >= h) continue;
          if (!blocked.has(`${nx},${ny}`)) {
            return { name: spawn.name, x: nx, y: ny };
          }
        }
      }
    }

    return spawn; // give up, validation will catch it
  });
}

// -------------------------------------------------------
// Validation
// -------------------------------------------------------

function buildBlockedSet(collisions: CollisionRect[]): Set<string> {
  const blocked = new Set<string>();
  for (const rect of collisions) {
    for (let dx = 0; dx < rect.width; dx++) {
      for (let dy = 0; dy < rect.height; dy++) {
        blocked.add(`${rect.x + dx},${rect.y + dy}`);
      }
    }
  }
  return blocked;
}

function validate(
  spawns: SpawnPoint[],
  collisions: CollisionRect[],
  buildings: PlacedBuilding[],
): void {
  // 1. At least 5 spawn points
  if (spawns.length < 5) {
    throw new Error(`Validation failed: only ${spawns.length} spawn points (need ≥5)`);
  }

  const blocked = buildBlockedSet(collisions);

  // 2. No spawn on a blocked tile
  for (const spawn of spawns) {
    const k = `${spawn.x},${spawn.y}`;
    if (blocked.has(k)) {
      throw new Error(
        `Validation failed: spawn "${spawn.name}" at (${spawn.x},${spawn.y}) is on a blocked tile`,
      );
    }
  }

  // 3. A* connectivity between all spawn pairs
  for (let i = 0; i < spawns.length; i++) {
    for (let j = i + 1; j < spawns.length; j++) {
      const a = spawns[i];
      const b = spawns[j];
      const reachable = astar(a.x, a.y, b.x, b.y, blocked, W, H);
      if (!reachable) {
        throw new Error(
          `Validation failed: spawn "${a.name}" (${a.x},${a.y}) cannot reach "${b.name}" (${b.x},${b.y})`,
        );
      }
    }
  }

  // 4. No building footprints overlap
  for (let i = 0; i < buildings.length; i++) {
    const a = buildings[i];
    const aX2 = a.x + a.kit.footprint.w;
    const aY2 = a.y + a.kit.footprint.h;
    for (let j = i + 1; j < buildings.length; j++) {
      const b = buildings[j];
      const bX2 = b.x + b.kit.footprint.w;
      const bY2 = b.y + b.kit.footprint.h;
      const overlapsX = a.x < bX2 && aX2 > b.x;
      const overlapsY = a.y < bY2 && aY2 > b.y;
      if (overlapsX && overlapsY) {
        throw new Error(
          `Validation failed: building "${a.kit.name}" at (${a.x},${a.y}) overlaps "${b.kit.name}" at (${b.x},${b.y})`,
        );
      }
    }
  }
}

// -------------------------------------------------------
// Main pipeline
// -------------------------------------------------------

export function generateTown(seed: number): { tmj: TmjMap; manifest: TownManifest } {
  // 1. Seeded RNG
  const rng = createRNG(seed);

  // 2. Zone layout
  const zones = generateZoneMap(W, H, rng);

  // 3. Building placement
  const { buildings, updatedZones } = placeBuildings(zones, W, H, rng);

  // 4. Terrain layers
  const terrainLayers = fillTerrainLayers(updatedZones, W, H, rng);

  // 5. Props
  const props = placeProps(updatedZones, W, H, buildings, rng);

  // 6. Collision rects
  const collisions = generateCollision(updatedZones, W, H, buildings, props);

  // 7. Spawn points
  const spawns = generateSpawnPoints(updatedZones, W, H, buildings);

  // 8. Stamp buildings onto tile layers
  const buildingsBase = new Array(W * H).fill(0);
  const foregroundLow = new Array(W * H).fill(0);

  for (const b of buildings) {
    for (let row = 0; row < b.kit.footprint.h; row++) {
      for (let col = 0; col < b.kit.footprint.w; col++) {
        const gid = b.kit.tiles[row][col] + TILESET.firstgid;
        const idx = (b.y + row) * W + (b.x + col);
        if (row < b.kit.foregroundRows) {
          foregroundLow[idx] = gid;
        } else {
          buildingsBase[idx] = gid;
        }
      }
    }
  }

  const buildingLayers = {
    Buildings_Base: buildingsBase,
    Foreground_Low: foregroundLow,
  };

  // 9. Relocate any spawns that landed on blocked tiles
  const blockedForSpawns = buildBlockedSet(collisions);
  const safeSpawns = relocateSpawns(spawns, blockedForSpawns, W, H);

  // 10. Export TMJ (with relocated spawns)
  const tmj = exportTmj(W, H, terrainLayers, props, collisions, safeSpawns, buildingLayers);

  // 11. Validate
  validate(safeSpawns, collisions, buildings);

  // 12. Build manifest
  const manifest: TownManifest = {
    seed,
    width: W,
    height: H,
    tileDim: 16,
    spawns: safeSpawns,
    locations: buildings.map((b) => ({
      name: b.kit.name,
      label: b.kit.name.replace(/_/g, ' '),
      x: b.x + Math.floor(b.kit.footprint.w / 2),
      y: b.y + Math.floor(b.kit.footprint.h / 2),
    })),
  };

  return { tmj, manifest };
}
