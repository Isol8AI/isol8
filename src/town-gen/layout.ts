// src/town-gen/layout.ts

import type { Zone, ZoneMap, RNG } from './schema';

/** Generate the abstract zone map for the town. */
export function generateZoneMap(w: number, h: number, rng: RNG): ZoneMap {
  // Initialize all as water
  const zones: ZoneMap = Array.from({ length: w }, () =>
    Array.from({ length: h }, () => 'water' as Zone),
  );

  // Phase 1: Island shape — fill interior with grass
  fillIsland(zones, w, h, rng);

  // Phase 2: Canal
  const canalY = fillCanal(zones, w, h);

  // Phase 3: Main roads (cross shape)
  const { hRoadY, vRoadX, plazaBounds } = fillRoads(zones, w, h, canalY);

  // Phase 4: Plaza
  fillPlaza(zones, plazaBounds);

  // Phase 5: Secondary roads
  fillSecondaryRoads(zones, w, h, rng, hRoadY, vRoadX, canalY, plazaBounds);

  // Phase 6: Bridges over canal
  fillBridges(zones, w, h, vRoadX, canalY);

  // Phase 7: Dock
  fillDock(zones, w, h, rng);

  // Phase 8: Shore (buffer between water and land)
  fillShore(zones, w, h);

  // Phase 9: Parks
  fillParks(zones, w, h, rng);

  return zones;
}

function fillIsland(zones: ZoneMap, w: number, h: number, rng: RNG): void {
  const margin = 8;
  for (let x = margin; x < w - margin; x++) {
    for (let y = margin; y < h - margin; y++) {
      // Irregular edge: vary margin by ±2 using simple noise
      const edgeDist = Math.min(x - margin, w - margin - 1 - x, y - margin, h - margin - 1 - y);
      if (edgeDist < 2) {
        // Probabilistic edge — creates irregular coastline
        if (rng.next() < 0.3) continue; // stays water
      }
      zones[x][y] = 'grass';
    }
  }
}

function fillCanal(zones: ZoneMap, w: number, h: number): number {
  // Canal runs east-west through the middle third
  const canalY = Math.floor(h * 0.45);
  const canalWidth = 4;
  const margin = 10;

  for (let x = margin; x < w - margin; x++) {
    for (let dy = 0; dy < canalWidth; dy++) {
      const y = canalY + dy;
      if (y >= 0 && y < h) {
        zones[x][y] = 'canal';
      }
    }
    // Canal walls (one tile above and below)
    if (canalY - 1 >= 0 && zones[x][canalY - 1] !== 'water') {
      zones[x][canalY - 1] = 'road'; // Will become canal edge via terrain
    }
    if (canalY + canalWidth < h && zones[x][canalY + canalWidth] !== 'water') {
      zones[x][canalY + canalWidth] = 'road';
    }
  }

  return canalY;
}

function fillRoads(
  zones: ZoneMap,
  w: number,
  h: number,
  canalY: number,
): { hRoadY: number; vRoadX: number; plazaBounds: { x1: number; y1: number; x2: number; y2: number } } {
  const vRoadX = Math.floor(w / 2); // Vertical road at center
  const hRoadY = Math.floor(canalY / 2); // Horizontal road in upper half
  const roadW = 3;

  // Vertical road (full height, skipping canal — bridges handle that)
  for (let y = 8; y < h - 8; y++) {
    if (zones[vRoadX][y] === 'canal') continue;
    for (let dx = 0; dx < roadW; dx++) {
      const x = vRoadX - 1 + dx;
      if (x >= 0 && x < w && zones[x][y] !== 'canal') {
        zones[x][y] = 'road';
      }
    }
  }

  // Horizontal road (full width, upper half)
  for (let x = 10; x < w - 10; x++) {
    for (let dy = 0; dy < roadW; dy++) {
      const y = hRoadY - 1 + dy;
      if (y >= 0 && y < h && zones[x][y] !== 'canal') {
        zones[x][y] = 'road';
      }
    }
  }

  // Plaza at intersection
  const plazaW = 12;
  const plazaH = 10;
  const plazaBounds = {
    x1: vRoadX - Math.floor(plazaW / 2),
    y1: hRoadY - Math.floor(plazaH / 2),
    x2: vRoadX + Math.ceil(plazaW / 2),
    y2: hRoadY + Math.ceil(plazaH / 2),
  };

  return { hRoadY, vRoadX, plazaBounds };
}

function fillPlaza(
  zones: ZoneMap,
  bounds: { x1: number; y1: number; x2: number; y2: number },
): void {
  for (let x = bounds.x1; x < bounds.x2; x++) {
    for (let y = bounds.y1; y < bounds.y2; y++) {
      if (zones[x]?.[y] !== undefined && zones[x][y] !== 'water' && zones[x][y] !== 'canal') {
        zones[x][y] = 'plaza';
      }
    }
  }
}

function fillSecondaryRoads(
  zones: ZoneMap,
  w: number,
  h: number,
  rng: RNG,
  hRoadY: number,
  vRoadX: number,
  canalY: number,
  plazaBounds: { x1: number; y1: number; x2: number; y2: number },
): void {
  const roadW = 2;
  // Two horizontal side streets in upper half
  const sideStreetYs = [hRoadY - 12, hRoadY + 12].filter(
    (y) => y > 12 && y < canalY - 6,
  );
  for (const sy of sideStreetYs) {
    for (let x = 14; x < w - 14; x++) {
      for (let dy = 0; dy < roadW; dy++) {
        const y = sy + dy;
        if (zones[x]?.[y] && zones[x][y] === 'grass') {
          zones[x][y] = 'road';
        }
      }
    }
  }

  // Two vertical side streets in lower half (below canal)
  const lowerY = canalY + 6;
  const sideStreetXs = [vRoadX - 20, vRoadX + 20].filter(
    (x) => x > 14 && x < w - 14,
  );
  for (const sx of sideStreetXs) {
    for (let y = lowerY; y < h - 10; y++) {
      for (let dx = 0; dx < roadW; dx++) {
        const x = sx + dx;
        if (zones[x]?.[y] && zones[x][y] === 'grass') {
          zones[x][y] = 'road';
        }
      }
    }
  }
}

function fillBridges(
  zones: ZoneMap,
  w: number,
  h: number,
  vRoadX: number,
  canalY: number,
): void {
  const bridgeW = 3;
  // Bridge at main vertical road
  for (let dx = -1; dx < bridgeW - 1; dx++) {
    const x = vRoadX + dx;
    for (let y = canalY; y < canalY + 4; y++) {
      if (x >= 0 && x < w && y >= 0 && y < h) {
        zones[x][y] = 'bridge';
      }
    }
  }

  // Second bridge offset to the left
  const bridge2X = vRoadX - 25;
  if (bridge2X > 12) {
    for (let dx = 0; dx < bridgeW; dx++) {
      const x = bridge2X + dx;
      for (let y = canalY; y < canalY + 4; y++) {
        if (x >= 0 && x < w && y >= 0 && y < h) {
          zones[x][y] = 'bridge';
        }
      }
    }
  }
}

function fillDock(zones: ZoneMap, w: number, h: number, rng: RNG): void {
  // Dock along the south shore
  const dockStartX = Math.floor(w * 0.35);
  const dockEndX = Math.floor(w * 0.65);
  const dockY = h - 12;

  for (let x = dockStartX; x < dockEndX; x++) {
    for (let dy = 0; dy < 3; dy++) {
      const y = dockY + dy;
      if (y < h && (zones[x][y] === 'grass' || zones[x][y] === 'water' || zones[x][y] === 'shore')) {
        zones[x][y] = 'dock';
      }
    }
  }
}

function fillShore(zones: ZoneMap, w: number, h: number): void {
  // Shore = grass cells adjacent to water
  const toShore: [number, number][] = [];
  for (let x = 1; x < w - 1; x++) {
    for (let y = 1; y < h - 1; y++) {
      if (zones[x][y] !== 'grass') continue;
      const neighbors = [
        zones[x - 1][y], zones[x + 1][y],
        zones[x][y - 1], zones[x][y + 1],
      ];
      if (neighbors.some((n) => n === 'water' || n === 'canal')) {
        toShore.push([x, y]);
      }
    }
  }
  for (const [x, y] of toShore) {
    zones[x][y] = 'shore';
  }
}

function fillParks(zones: ZoneMap, w: number, h: number, rng: RNG): void {
  // Convert some grass patches near the plaza into park zones
  // Find grass clusters of 6x6+ and mark 1-2 as parks
  let parksPlaced = 0;
  for (let x = 16; x < w - 16 && parksPlaced < 2; x += 15) {
    for (let y = 16; y < h - 16 && parksPlaced < 2; y += 15) {
      // Check if a 6x6 area is all grass
      let allGrass = true;
      for (let dx = 0; dx < 6 && allGrass; dx++) {
        for (let dy = 0; dy < 6 && allGrass; dy++) {
          if (zones[x + dx]?.[y + dy] !== 'grass') allGrass = false;
        }
      }
      if (allGrass && rng.next() < 0.5) {
        for (let dx = 0; dx < 6; dx++) {
          for (let dy = 0; dy < 6; dy++) {
            zones[x + dx][y + dy] = 'park';
          }
        }
        parksPlaced++;
      }
    }
  }
}
