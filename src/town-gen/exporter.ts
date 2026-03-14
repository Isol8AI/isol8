// src/town-gen/exporter.ts — Serialize town data to Tiled-compatible TMJ JSON

import type {
  TmjMap,
  TmjTileLayer,
  TmjObjectLayer,
  TmjLayer,
  CollisionRect,
  SpawnPoint,
  PlacedProp,
} from './schema';
import { TILESET } from './asset-registry';

// -------------------------------------------------------
// Helpers
// -------------------------------------------------------

function makeTileLayer(name: string, w: number, h: number, data?: number[]): TmjTileLayer {
  return {
    name,
    type: 'tilelayer',
    width: w,
    height: h,
    data: data ?? new Array(w * h).fill(0),
    visible: true,
    opacity: 1,
    x: 0,
    y: 0,
  };
}

function makeObjectLayer(name: string, objects: TmjObjectLayer['objects'] = []): TmjObjectLayer {
  return {
    name,
    type: 'objectgroup',
    objects,
    visible: true,
    opacity: 1,
    x: 0,
    y: 0,
  };
}

/**
 * Stamp a prop's tiles into a flat tile array (in-place).
 * tileRows is the 2-D grid of local tile IDs.
 * GID = localId + TILESET.firstgid (0 local IDs are skipped).
 */
function stampTiles(
  target: number[],
  tileRows: number[][],
  propX: number,
  propY: number,
  mapW: number,
  mapH: number,
): void {
  for (let row = 0; row < tileRows.length; row++) {
    for (let col = 0; col < tileRows[row].length; col++) {
      const localId = tileRows[row][col];
      if (localId === 0) continue;
      const tx = propX + col;
      const ty = propY + row;
      if (tx < 0 || tx >= mapW || ty < 0 || ty >= mapH) continue;
      target[ty * mapW + tx] = localId + TILESET.firstgid;
    }
  }
}

// -------------------------------------------------------
// Main export function
// -------------------------------------------------------

export function exportTmj(
  w: number,
  h: number,
  terrainLayers: Record<string, number[]>,
  props: PlacedProp[],
  collisions: CollisionRect[],
  spawns: SpawnPoint[],
  buildingLayers?: Record<string, number[]>,
): TmjMap {
  // --- Tile layer data arrays ---

  // Ground layers come directly from terrain
  const groundBase = (terrainLayers['Ground_Base'] ?? new Array(w * h).fill(0)).slice();
  const groundDetail = (terrainLayers['Ground_Detail'] ?? new Array(w * h).fill(0)).slice();
  const waterBack = (terrainLayers['Water_Back'] ?? new Array(w * h).fill(0)).slice();
  const terrainStructures = (terrainLayers['Terrain_Structures'] ?? new Array(w * h).fill(0)).slice();

  // Building layers — start from buildingLayers if provided, else empty
  const buildingsBase = (buildingLayers?.['Buildings_Base'] ?? new Array(w * h).fill(0)).slice();

  // Prop layers — filled by stamping
  const propsBack: number[] = new Array(w * h).fill(0);
  const propsFront: number[] = new Array(w * h).fill(0);
  const foregroundLow: number[] = (buildingLayers?.['Foreground_Low'] ?? new Array(w * h).fill(0)).slice();
  const foregroundHigh: number[] = new Array(w * h).fill(0);

  // Stamp each prop onto its declared layers
  for (const prop of props) {
    const { def, x, y } = prop;

    // Ground / back layer
    if (def.groundLayer === 'Props_Back') {
      stampTiles(propsBack, def.tiles, x, y, w, h);
    } else if (def.groundLayer === 'Props_Front') {
      stampTiles(propsFront, def.tiles, x, y, w, h);
    }

    // Foreground layer (if any)
    if (def.foregroundLayer && def.foregroundTiles) {
      if (def.foregroundLayer === 'Props_Front') {
        stampTiles(propsFront, def.foregroundTiles, x, y, w, h);
      } else if (def.foregroundLayer === 'Foreground_Low') {
        stampTiles(foregroundLow, def.foregroundTiles, x, y, w, h);
      } else if (def.foregroundLayer === 'Foreground_High') {
        stampTiles(foregroundHigh, def.foregroundTiles, x, y, w, h);
      }
    }
  }

  // --- Object layers ---

  let nextId = 1;

  // Collision objects (tile coords * 16 → pixel coords)
  const collisionObjects = collisions.map((c) => ({
    id: nextId++,
    name: c.source,
    type: 'collision',
    x: c.x * 16,
    y: c.y * 16,
    width: c.width * 16,
    height: c.height * 16,
  }));

  // Spawn point objects
  const spawnObjects = spawns.map((s) => ({
    id: nextId++,
    name: s.name,
    type: 'spawn',
    x: s.x * 16,
    y: s.y * 16,
    width: 16,
    height: 16,
  }));

  // --- Assemble 17 layers in required order ---

  const layers: TmjLayer[] = [
    /* 1 */ makeTileLayer('Ground_Base', w, h, groundBase),
    /* 2 */ makeTileLayer('Ground_Detail', w, h, groundDetail),
    /* 3 */ makeTileLayer('Water_Back', w, h, waterBack),
    /* 4 */ makeTileLayer('Terrain_Structures', w, h, terrainStructures),
    /* 5 */ makeTileLayer('Buildings_Base', w, h, buildingsBase),
    /* 6 */ makeTileLayer('Props_Back', w, h, propsBack),
    /* 7 */ makeTileLayer('Animation_Back', w, h),               // empty placeholder
    /* 8 */ makeObjectLayer('Collision', collisionObjects),
    /* 9 */ makeObjectLayer('Depth_Masks'),                      // reserved
    /* 10 */ makeObjectLayer('Triggers'),                        // reserved
    /* 11 */ makeObjectLayer('Spawn_Points', spawnObjects),
    /* 12 */ makeObjectLayer('NPC_Paths'),                       // reserved
    /* 13 */ makeObjectLayer('Interaction'),                     // reserved
    /* 14 */ makeTileLayer('Props_Front', w, h, propsFront),
    /* 15 */ makeTileLayer('Foreground_Low', w, h, foregroundLow),
    /* 16 */ makeTileLayer('Foreground_High', w, h, foregroundHigh),
    /* 17 */ makeTileLayer('Animation_Front', w, h),             // empty placeholder
  ];

  // --- Build TMJ map ---

  return {
    width: w,
    height: h,
    tilewidth: 16,
    tileheight: 16,
    orientation: 'orthogonal',
    renderorder: 'right-down',
    type: 'map',
    version: '1.10',
    tiledversion: '1.10.2',
    tilesets: [
      {
        firstgid: TILESET.firstgid,
        name: TILESET.name,
        tilewidth: TILESET.tilewidth,
        tileheight: TILESET.tileheight,
        tilecount: TILESET.tilecount,
        columns: TILESET.columns,
        image: TILESET.image,
        imagewidth: TILESET.imagewidth,
        imageheight: TILESET.imageheight,
      },
    ],
    layers,
  };
}
