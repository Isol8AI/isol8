// src/town-gen/collision.ts — Collision rect and spawn point generation

import type { ZoneMap, PlacedBuilding, PlacedProp, CollisionRect, SpawnPoint } from './schema';

/**
 * Generate collision rectangles from zone map, buildings, and props.
 *
 * 1. Water/canal zones — greedy rect merging of adjacent blocked tiles
 * 2. Buildings — use kit collision definition offset from building origin
 * 3. Props — full footprint, base row, or skipped based on collision type
 */
export function generateCollision(
  zones: ZoneMap,
  w: number,
  h: number,
  buildings: PlacedBuilding[],
  props: PlacedProp[],
): CollisionRect[] {
  const rects: CollisionRect[] = [];

  // --- 1. Water and canal zones — greedy rect merging ---
  const visited = Array.from({ length: w }, () => new Array<boolean>(h).fill(false));

  for (let x = 0; x < w; x++) {
    for (let y = 0; y < h; y++) {
      const zone = zones[x]?.[y];
      if (visited[x][y]) continue;
      if (zone !== 'water' && zone !== 'canal') continue;

      // Extend right as far as possible with the same zone type
      let rectW = 1;
      while (
        x + rectW < w &&
        !visited[x + rectW][y] &&
        zones[x + rectW]?.[y] === zone
      ) {
        rectW++;
      }

      // Extend down: each row must have the same zone across the full width
      let rectH = 1;
      outer: while (y + rectH < h) {
        for (let dx = 0; dx < rectW; dx++) {
          if (visited[x + dx][y + rectH] || zones[x + dx]?.[y + rectH] !== zone) {
            break outer;
          }
        }
        rectH++;
      }

      // Mark all covered cells as visited
      for (let dx = 0; dx < rectW; dx++) {
        for (let dy = 0; dy < rectH; dy++) {
          visited[x + dx][y + dy] = true;
        }
      }

      rects.push({
        x,
        y,
        width: rectW,
        height: rectH,
        source: `zone:${zone}`,
      });
    }
  }

  // --- 2. Buildings ---
  for (const b of buildings) {
    rects.push({
      x: b.x + b.kit.collision.x,
      y: b.y + b.kit.collision.y,
      width: b.kit.collision.w,
      height: b.kit.collision.h,
      source: `building:${b.kit.name}`,
    });
  }

  // --- 3. Props ---
  for (const p of props) {
    if (p.def.collision === 'none') continue;

    if (p.def.collision === 'full') {
      rects.push({
        x: p.x,
        y: p.y,
        width: p.def.footprint.w,
        height: p.def.footprint.h,
        source: `prop:${p.def.name}`,
      });
    } else {
      // 'base' — only the bottom row
      rects.push({
        x: p.x,
        y: p.y + p.def.footprint.h - 1,
        width: p.def.footprint.w,
        height: 1,
        source: `prop:${p.def.name}`,
      });
    }
  }

  return rects;
}

/**
 * Generate 5 named spawn points:
 * - plaza: center of the plaza zone
 * - civic_hall: in front of the civic building's door
 * - cafe: in front of the first commercial building's door
 * - activity_center: in front of the second commercial building's door
 * - residence: in front of the first residential building's door
 */
export function generateSpawnPoints(
  zones: ZoneMap,
  w: number,
  h: number,
  buildings: PlacedBuilding[],
): SpawnPoint[] {
  const spawns: SpawnPoint[] = [];

  // --- 1. Plaza spawn — find plaza extent and use midpoint ---
  let plazaMinX = w, plazaMaxX = 0, plazaMinY = h, plazaMaxY = 0;
  let foundPlaza = false;

  for (let x = 0; x < w; x++) {
    for (let y = 0; y < h; y++) {
      if (zones[x]?.[y] === 'plaza') {
        if (!foundPlaza) foundPlaza = true;
        if (x < plazaMinX) plazaMinX = x;
        if (x > plazaMaxX) plazaMaxX = x;
        if (y < plazaMinY) plazaMinY = y;
        if (y > plazaMaxY) plazaMaxY = y;
      }
    }
  }

  if (foundPlaza) {
    spawns.push({
      name: 'plaza',
      x: Math.floor((plazaMinX + plazaMaxX) / 2),
      y: Math.floor((plazaMinY + plazaMaxY) / 2),
    });
  } else {
    // Fallback to map center
    spawns.push({ name: 'plaza', x: Math.floor(w / 2), y: Math.floor(h / 2) });
  }

  // Helper: get door-front position (1 tile below bottom of building)
  function doorFront(b: PlacedBuilding): { x: number; y: number } {
    return {
      x: b.x + b.kit.doorOffset.x,
      y: b.y + b.kit.footprint.h + 1,
    };
  }

  // --- 2. Civic hall spawn ---
  const civic = buildings.find((b) => b.kit.class === 'civic');
  if (civic) {
    const pos = doorFront(civic);
    spawns.push({ name: 'civic_hall', x: pos.x, y: pos.y });
  } else {
    spawns.push({ name: 'civic_hall', x: Math.floor(w / 2), y: Math.floor(h / 3) });
  }

  // --- 3. Cafe — first commercial building ---
  const commercial = buildings.filter((b) => b.kit.class === 'commercial');
  if (commercial.length >= 1) {
    const pos = doorFront(commercial[0]);
    spawns.push({ name: 'cafe', x: pos.x, y: pos.y });
  } else {
    spawns.push({ name: 'cafe', x: Math.floor(w / 3), y: Math.floor(h / 2) });
  }

  // --- 4. Activity center — second commercial building ---
  if (commercial.length >= 2) {
    const pos = doorFront(commercial[1]);
    spawns.push({ name: 'activity_center', x: pos.x, y: pos.y });
  } else if (commercial.length >= 1) {
    // Reuse first commercial with slight offset if only one exists
    const pos = doorFront(commercial[0]);
    spawns.push({ name: 'activity_center', x: pos.x + 2, y: pos.y });
  } else {
    spawns.push({ name: 'activity_center', x: Math.floor((2 * w) / 3), y: Math.floor(h / 2) });
  }

  // --- 5. Residence — first residential building ---
  const residential = buildings.find((b) => b.kit.class === 'residential');
  if (residential) {
    const pos = doorFront(residential);
    spawns.push({ name: 'residence', x: pos.x, y: pos.y });
  } else {
    spawns.push({ name: 'residence', x: Math.floor(w / 2), y: Math.floor((2 * h) / 3) });
  }

  return spawns;
}
