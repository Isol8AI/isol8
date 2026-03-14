// src/town-gen/props.ts — Prop placement with spatial rules

import type { ZoneMap, PlacedProp, PlacedBuilding, RNG, PropDef } from './schema';
import { PROPS } from './asset-registry';

// Zones that block prop placement
const BLOCKED_FOR_PROPS = new Set(['water', 'canal', 'building']);

/**
 * Place all props onto the zone map and return the placed prop list.
 *
 * Order of placement:
 *   1. Fountain (plaza center, once)
 *   2. Trees     (parks + grass, step 4)
 *   3. Lamps     (road edges, step 6-8)
 *   4. Benches   (plaza/park, step 8)
 *   5. Bushes    (building front edges)
 *   6. Signs     (adjacent to commercial doors)
 *   7. Planters  (building front corners)
 */
export function placeProps(
  zones: ZoneMap,
  w: number,
  h: number,
  buildings: PlacedBuilding[],
  rng: RNG,
): PlacedProp[] {
  const props: PlacedProp[] = [];

  // Track occupied cells — start by marking every building footprint cell
  const occupied = new Set<string>();
  for (const b of buildings) {
    for (let dx = 0; dx < b.kit.footprint.w; dx++) {
      for (let dy = 0; dy < b.kit.footprint.h; dy++) {
        occupied.add(`${b.x + dx},${b.y + dy}`);
      }
    }
  }

  // -------------------------------------------------------
  // Helpers
  // -------------------------------------------------------

  function key(x: number, y: number): string {
    return `${x},${y}`;
  }

  function inBounds(x: number, y: number): boolean {
    return x >= 0 && x < w && y >= 0 && y < h;
  }

  function canPlace(def: PropDef, x: number, y: number): boolean {
    for (let dx = 0; dx < def.footprint.w; dx++) {
      for (let dy = 0; dy < def.footprint.h; dy++) {
        const cx = x + dx;
        const cy = y + dy;
        if (!inBounds(cx, cy)) return false;
        if (occupied.has(key(cx, cy))) return false;
        const zone = zones[cx][cy];
        if (BLOCKED_FOR_PROPS.has(zone)) return false;
      }
    }
    return true;
  }

  function place(def: PropDef, x: number, y: number): void {
    props.push({ def, x, y });
    for (let dx = 0; dx < def.footprint.w; dx++) {
      for (let dy = 0; dy < def.footprint.h; dy++) {
        occupied.add(key(x + dx, y + dy));
      }
    }
  }

  // -------------------------------------------------------
  // 1. Fountain — place at plaza center (3x3)
  // -------------------------------------------------------
  (function placeFountain() {
    const def = PROPS.fountain;
    // Find plaza bounds
    let minX = w, maxX = 0, minY = h, maxY = 0;
    let hasPlaza = false;
    for (let x = 0; x < w; x++) {
      for (let y = 0; y < h; y++) {
        if (zones[x][y] === 'plaza') {
          if (x < minX) minX = x;
          if (x > maxX) maxX = x;
          if (y < minY) minY = y;
          if (y > maxY) maxY = y;
          hasPlaza = true;
        }
      }
    }
    if (!hasPlaza) return;

    // Center the 3x3 fountain in the plaza
    const cx = Math.floor((minX + maxX) / 2) - Math.floor(def.footprint.w / 2);
    const cy = Math.floor((minY + maxY) / 2) - Math.floor(def.footprint.h / 2);
    if (canPlace(def, cx, cy)) {
      place(def, cx, cy);
    }
  })();

  // -------------------------------------------------------
  // 2. Trees — parks and grass, minimum 4 tiles apart, step 4+rng(3)
  // -------------------------------------------------------
  (function placeTrees() {
    const def = PROPS.tree;
    let x = 1;
    while (x < w - def.footprint.w - 1) {
      let y = 1;
      while (y < h - def.footprint.h - 1) {
        const zone = zones[x]?.[y];
        if ((zone === 'park' || zone === 'grass') && rng.next() < 0.30) {
          if (canPlace(def, x, y)) {
            place(def, x, y);
            // Skip ahead to enforce minimum 4-tile gap
            y += 4;
            x += 1; // minor x offset to avoid column lines
            continue;
          }
        }
        y += 4 + rng.nextInt(3);
      }
      x += 4 + rng.nextInt(3);
    }
  })();

  // -------------------------------------------------------
  // 3. Lamps — along main roads, every 6-8 tiles
  //    Scan x with step 6+rng(3), find a road tile in that column,
  //    place lamp 1 tile above.
  // -------------------------------------------------------
  (function placeLamps() {
    const def = PROPS.lamp;
    let x = 2;
    while (x < w - 2) {
      // Find a road tile in this column
      for (let y = 2; y < h - def.footprint.h - 1; y++) {
        if (zones[x]?.[y] === 'road') {
          // Place lamp 1 tile above the road tile
          const lampY = y - 1;
          if (lampY >= 1 && canPlace(def, x, lampY)) {
            place(def, x, lampY);
          }
          break; // one lamp per x position
        }
      }
      x += 6 + rng.nextInt(3);
    }
  })();

  // -------------------------------------------------------
  // 4. Benches — near plazas and parks, step 8+rng(4), 40% probability
  // -------------------------------------------------------
  (function placeBenches() {
    const def = PROPS.bench;
    let x = 2;
    while (x < w - def.footprint.w - 1) {
      let y = 2;
      while (y < h - def.footprint.h - 1) {
        const zone = zones[x]?.[y];
        if ((zone === 'plaza' || zone === 'park') && rng.next() < 0.40) {
          if (canPlace(def, x, y)) {
            place(def, x, y);
          }
        }
        y += 8 + rng.nextInt(4);
      }
      x += 8 + rng.nextInt(4);
    }
  })();

  // -------------------------------------------------------
  // 5. Bushes — along building edges (1 tile above building front row)
  //    30% probability per building front tile
  // -------------------------------------------------------
  (function placeBushes() {
    const def = PROPS.bush;
    for (const b of buildings) {
      // Front row = bottom row of building footprint (y + footprint.h - 1)
      const frontY = b.y + b.kit.footprint.h - 1;
      // Place bushes at y - 1 (one tile above the bottom building row = in front)
      const bushY = frontY - 1;
      for (let dx = 0; dx < b.kit.footprint.w; dx++) {
        const bx = b.x + dx;
        if (rng.next() < 0.30 && canPlace(def, bx, bushY)) {
          place(def, bx, bushY);
        }
      }
    }
  })();

  // -------------------------------------------------------
  // 6. Signs — adjacent to shop doors (1 tile right of door)
  //    Only for commercial buildings
  // -------------------------------------------------------
  (function placeSigns() {
    const def = PROPS.sign;
    for (const b of buildings) {
      if (b.kit.class !== 'commercial') continue;
      const doorX = b.x + b.kit.doorOffset.x;
      const doorY = b.y + b.kit.doorOffset.y;
      // Place sign 1 tile to the right of the door
      const signX = doorX + 1;
      const signY = doorY - 1; // sign is 1x2, align bottom with door row
      if (canPlace(def, signX, signY)) {
        place(def, signX, signY);
      }
    }
  })();

  // -------------------------------------------------------
  // 7. Planters — at building front corners, 40% probability
  //    Front = bottom row of footprint; corners = leftmost and rightmost x
  // -------------------------------------------------------
  (function placePlanters() {
    const def = PROPS.planter;
    for (const b of buildings) {
      const frontY = b.y + b.kit.footprint.h; // one tile below building (in front)
      const leftX = b.x;
      const rightX = b.x + b.kit.footprint.w - 1;

      if (rng.next() < 0.40 && canPlace(def, leftX, frontY)) {
        place(def, leftX, frontY);
      }
      if (rng.next() < 0.40 && canPlace(def, rightX, frontY)) {
        place(def, rightX, frontY);
      }
    }
  })();

  return props;
}
