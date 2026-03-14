// src/town-gen/asset-registry.ts — OGA tile ID mappings

import type { TerrainFamily, TransitionSet, BuildingKit, PropDef } from './schema';

// Combined tileset: 17 cols x 34 rows = 578 tiles
// Rows 0-18: terrain (grass/water/dirt autotiles + trees/building)
// Rows 19-23: town remix (more terrain, buildings, tower)
// Rows 24-26: original town tiles (walls, building parts)
// Rows 27-33: objects (props, items)
// localId = row * 17 + col, GID = localId + firstgid

export const TILESET = {
  name: 'oga_jrpg',
  image: 'assets/tilesets/oga-jrpg-tileset.png',
  tilewidth: 16,
  tileheight: 16,
  columns: 17,
  imagewidth: 272,
  imageheight: 544,
  tilecount: 578,
  firstgid: 1,
} as const;

// Helper: local tile ID from row, col
function t(row: number, col: number): number {
  return row * 17 + col;
}

// -------------------------------------------------------
// Terrain families — each has primary + alternates
// All IDs are LOCAL (generator adds firstgid for GID)
// -------------------------------------------------------
export const TERRAIN: Record<string, TerrainFamily> = {
  // Grass: center tiles from grass autotile block (rows 1-3, cols 1-5)
  grass: {
    primary: t(1, 1),
    alternates: [t(1, 2), t(2, 1), t(2, 2)],
    weights: [4, 2, 2, 2],
  },
  // Water: center tiles from water autotile block (rows 6-7, cols 2-5)
  water: {
    primary: t(6, 2),
    alternates: [t(6, 3), t(7, 2)],
    weights: [3, 2, 2],
  },
  // Road/dirt: center tiles from dirt autotile block (rows 11-12, cols 2-5)
  road: {
    primary: t(11, 2),
    alternates: [t(11, 3), t(12, 2)],
    weights: [3, 2, 2],
  },
  // Plaza: stone tiles from remix (row 19, cols 3-6)
  plaza: {
    primary: t(19, 3),
    alternates: [t(19, 4), t(19, 5), t(20, 3)],
    weights: [4, 2, 2, 2],
  },
  // Dock: wood plank tiles from town tiles (row 24, cols 4-5)
  dock: {
    primary: t(24, 4),
    alternates: [t(24, 5)],
    weights: [3, 2],
  },
  // Canal wall: stone wall from town remix (row 19, col 7)
  canal_wall: {
    primary: t(19, 7),
    alternates: [],
  },
  // Shore: sand/beach tiles from dirt autotile edges (row 10, cols 1-2)
  shore: {
    primary: t(10, 1),
    alternates: [t(10, 2)],
    weights: [3, 2],
  },
};

// -------------------------------------------------------
// Transition sets — edge/corner tiles for terrain pairs
// Using autotile edge tiles from the terrain sheet
// -------------------------------------------------------
export const TRANSITIONS: Record<string, TransitionSet> = {
  // Grass edges (row 0 = N, row 4 = S, col 0 = W, col 6 = E of grass block)
  grass_to_water: {
    n: t(0, 2), s: t(4, 2), e: t(2, 6), w: t(2, 0),
    ne: t(0, 6), nw: t(0, 0), se: t(4, 6), sw: t(4, 0),
    innerNE: t(3, 5), innerNW: t(3, 1), innerSE: t(1, 5), innerSW: t(1, 1),
  },
  // Water-to-shore transitions from water autotile block edges
  grass_to_road: {
    n: t(10, 2), s: t(13, 2), e: t(11, 6), w: t(11, 0),
    ne: t(10, 6), nw: t(10, 0), se: t(13, 6), sw: t(13, 0),
    innerNE: t(12, 5), innerNW: t(12, 1), innerSE: t(10, 5), innerSW: t(10, 1),
  },
  grass_to_plaza: {
    n: t(10, 3), s: t(13, 3), e: t(11, 7), w: t(11, 1),
    ne: t(10, 7), nw: t(10, 1), se: t(13, 7), sw: t(13, 1),
    innerNE: t(12, 6), innerNW: t(12, 2), innerSE: t(10, 6), innerSW: t(10, 2),
  },
  water_to_canal_wall: {
    n: t(5, 2), s: t(8, 2), e: t(6, 6), w: t(6, 0),
    ne: t(5, 6), nw: t(5, 0), se: t(8, 6), sw: t(8, 0),
    innerNE: t(7, 5), innerNW: t(7, 1), innerSE: t(5, 5), innerSW: t(5, 1),
  },
  water_to_dock: {
    n: t(5, 3), s: t(8, 3), e: t(6, 7), w: t(6, 1),
    ne: t(5, 7), nw: t(5, 1), se: t(8, 7), sw: t(8, 1),
    innerNE: t(7, 6), innerNW: t(7, 2), innerSE: t(5, 6), innerSW: t(5, 2),
  },
};

// -------------------------------------------------------
// Building kits — multi-tile footprints
// Tile IDs from right side of terrain sheet + remix
// -------------------------------------------------------
export const BUILDINGS: BuildingKit[] = [
  {
    name: 'house_small',
    class: 'residential',
    footprint: { w: 3, h: 3 },
    tiles: [
      [t(0, 8), t(0, 9), t(0, 10)],   // roof row → foreground
      [t(1, 8), t(1, 9), t(1, 10)],   // wall row
      [t(2, 8), t(2, 9), t(2, 10)],   // base row with door
    ],
    doorOffset: { x: 1, y: 2 },
    collision: { x: 0, y: 1, w: 3, h: 2 },
    foregroundRows: 1,
  },
  {
    name: 'house_medium',
    class: 'residential',
    footprint: { w: 4, h: 4 },
    tiles: [
      [t(0, 8), t(0, 9), t(0, 10), t(0, 11)],
      [t(1, 8), t(1, 9), t(1, 10), t(1, 11)],
      [t(2, 8), t(2, 9), t(2, 10), t(2, 11)],
      [t(3, 8), t(3, 9), t(3, 10), t(3, 11)],
    ],
    doorOffset: { x: 1, y: 3 },
    collision: { x: 0, y: 1, w: 4, h: 3 },
    foregroundRows: 1,
  },
  {
    name: 'shop',
    class: 'commercial',
    footprint: { w: 4, h: 3 },
    tiles: [
      [t(0, 10), t(0, 11), t(0, 12), t(0, 13)],
      [t(1, 10), t(1, 11), t(1, 12), t(1, 13)],
      [t(2, 10), t(2, 11), t(2, 12), t(2, 13)],
    ],
    doorOffset: { x: 1, y: 2 },
    collision: { x: 0, y: 1, w: 4, h: 2 },
    foregroundRows: 1,
  },
  {
    name: 'shop_wide',
    class: 'commercial',
    footprint: { w: 5, h: 3 },
    tiles: [
      [t(0, 8), t(0, 9), t(0, 10), t(0, 11), t(0, 12)],
      [t(1, 8), t(1, 9), t(1, 10), t(1, 11), t(1, 12)],
      [t(2, 8), t(2, 9), t(2, 10), t(2, 11), t(2, 12)],
    ],
    doorOffset: { x: 2, y: 2 },
    collision: { x: 0, y: 1, w: 5, h: 2 },
    foregroundRows: 1,
  },
  {
    name: 'civic',
    class: 'civic',
    footprint: { w: 6, h: 5 },
    tiles: [
      [t(0, 8), t(0, 9), t(0, 10), t(0, 11), t(0, 12), t(0, 13)],
      [t(1, 8), t(1, 9), t(1, 10), t(1, 11), t(1, 12), t(1, 13)],
      [t(2, 8), t(2, 9), t(2, 10), t(2, 11), t(2, 12), t(2, 13)],
      [t(3, 8), t(3, 9), t(3, 10), t(3, 11), t(3, 12), t(3, 13)],
      [t(3, 8), t(3, 9), t(3, 10), t(3, 11), t(3, 12), t(3, 13)],
    ],
    doorOffset: { x: 2, y: 4 },
    collision: { x: 0, y: 1, w: 6, h: 4 },
    foregroundRows: 1,
  },
  {
    name: 'inn',
    class: 'commercial',
    footprint: { w: 5, h: 4 },
    tiles: [
      [t(0, 9), t(0, 10), t(0, 11), t(0, 12), t(0, 13)],
      [t(1, 9), t(1, 10), t(1, 11), t(1, 12), t(1, 13)],
      [t(2, 9), t(2, 10), t(2, 11), t(2, 12), t(2, 13)],
      [t(3, 9), t(3, 10), t(3, 11), t(3, 12), t(3, 13)],
    ],
    doorOffset: { x: 2, y: 3 },
    collision: { x: 0, y: 1, w: 5, h: 3 },
    foregroundRows: 1,
  },
];

// -------------------------------------------------------
// Props
// -------------------------------------------------------
export const PROPS: Record<string, PropDef> = {
  fountain: {
    name: 'fountain',
    footprint: { w: 3, h: 3 },
    tiles: [
      [t(21, 1), t(21, 2), t(21, 3)],
      [t(22, 1), t(22, 2), t(22, 3)],
      [t(23, 1), t(23, 2), t(23, 3)],
    ],
    collision: 'full',
    groundLayer: 'Props_Back',
    foregroundLayer: 'Foreground_Low',
    foregroundTiles: [[t(21, 1), t(21, 2), t(21, 3)]],
  },
  tree: {
    name: 'tree',
    footprint: { w: 2, h: 2 },
    tiles: [
      [t(5, 10), t(5, 11)],  // canopy (upper)
      [t(6, 10), t(6, 11)],  // trunk (lower)
    ],
    collision: 'base',
    groundLayer: 'Props_Back',
    foregroundLayer: 'Foreground_High',
    foregroundTiles: [[t(5, 10), t(5, 11)]],
  },
  bench: {
    name: 'bench',
    footprint: { w: 2, h: 1 },
    tiles: [[t(27, 4), t(27, 5)]],
    collision: 'none',
    groundLayer: 'Props_Back',
  },
  lamp: {
    name: 'lamp',
    footprint: { w: 1, h: 2 },
    tiles: [[t(22, 7)], [t(23, 7)]],
    collision: 'base',
    groundLayer: 'Props_Back',
    foregroundLayer: 'Props_Front',
    foregroundTiles: [[t(22, 7)]],
  },
  bush: {
    name: 'bush',
    footprint: { w: 1, h: 1 },
    tiles: [[t(11, 8)]],
    collision: 'full',
    groundLayer: 'Props_Back',
  },
  sign: {
    name: 'sign',
    footprint: { w: 1, h: 2 },
    tiles: [[t(27, 3)], [t(28, 3)]],
    collision: 'none',
    groundLayer: 'Props_Back',
  },
  planter: {
    name: 'planter',
    footprint: { w: 1, h: 1 },
    tiles: [[t(12, 8)]],
    collision: 'full',
    groundLayer: 'Props_Back',
  },
};
