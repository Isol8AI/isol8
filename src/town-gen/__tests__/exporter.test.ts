// src/town-gen/__tests__/exporter.test.ts

import { exportTmj } from '../exporter';
import { TILESET, PROPS } from '../asset-registry';
import type {
  TmjTileLayer,
  TmjObjectLayer,
  CollisionRect,
  SpawnPoint,
  PlacedProp,
} from '../schema';

const W = 20;
const H = 15;

// Minimal terrain layers filled with GID 1 (firstgid) for all cells
function makeTerrainLayers(): Record<string, number[]> {
  const size = W * H;
  return {
    Ground_Base: new Array(size).fill(TILESET.firstgid),
    Ground_Detail: new Array(size).fill(0),
    Water_Back: new Array(size).fill(0),
    Terrain_Structures: new Array(size).fill(0),
  };
}

// Sample collisions
const sampleCollisions: CollisionRect[] = [
  { x: 1, y: 1, width: 3, height: 2, source: 'building_a' },
  { x: 5, y: 3, width: 2, height: 2, source: 'building_b' },
];

// Sample spawns
const sampleSpawns: SpawnPoint[] = [
  { name: 'player_start', x: 10, y: 7 },
  { name: 'npc_spawn_1', x: 4, y: 4 },
];

// Sample props
const benchDef = PROPS['bench'];
const treeDef = PROPS['tree'];
const lampDef = PROPS['lamp'];

const sampleProps: PlacedProp[] = [
  { def: benchDef, x: 2, y: 2 },
  { def: treeDef, x: 6, y: 3 },
  { def: lampDef, x: 8, y: 5 },
];

describe('exportTmj', () => {
  const map = exportTmj(W, H, makeTerrainLayers(), sampleProps, sampleCollisions, sampleSpawns);

  // -------------------------------------------------------
  // Top-level structure
  // -------------------------------------------------------

  test('has correct width and height', () => {
    expect(map.width).toBe(W);
    expect(map.height).toBe(H);
  });

  test('has correct tile dimensions', () => {
    expect(map.tilewidth).toBe(16);
    expect(map.tileheight).toBe(16);
  });

  test('has correct map metadata', () => {
    expect(map.orientation).toBe('orthogonal');
    expect(map.renderorder).toBe('right-down');
    expect(map.type).toBe('map');
    expect(map.version).toBe('1.10');
    expect(map.tiledversion).toBe('1.10.2');
  });

  // -------------------------------------------------------
  // Tileset
  // -------------------------------------------------------

  test('has exactly one tileset', () => {
    expect(map.tilesets).toHaveLength(1);
  });

  test('tileset has firstgid = 1', () => {
    expect(map.tilesets[0].firstgid).toBe(1);
  });

  test('tileset name matches TILESET constant', () => {
    expect(map.tilesets[0].name).toBe(TILESET.name);
  });

  test('tileset has correct image path', () => {
    expect(map.tilesets[0].image).toBe(TILESET.image);
  });

  // -------------------------------------------------------
  // Layer count and order
  // -------------------------------------------------------

  test('has exactly 17 layers', () => {
    expect(map.layers).toHaveLength(17);
  });

  const expectedLayerNames = [
    'Ground_Base',
    'Ground_Detail',
    'Water_Back',
    'Terrain_Structures',
    'Buildings_Base',
    'Props_Back',
    'Animation_Back',
    'Collision',
    'Depth_Masks',
    'Triggers',
    'Spawn_Points',
    'NPC_Paths',
    'Interaction',
    'Props_Front',
    'Foreground_Low',
    'Foreground_High',
    'Animation_Front',
  ];

  test.each(expectedLayerNames.map((name, i) => ({ name, i })))(
    'layer $i is named "$name"',
    ({ name, i }) => {
      expect(map.layers[i].name).toBe(name);
    },
  );

  // -------------------------------------------------------
  // Tile layer data sizes
  // -------------------------------------------------------

  const tileLayerIndices = [0, 1, 2, 3, 4, 5, 6, 13, 14, 15, 16];

  test.each(tileLayerIndices.map((i) => ({ i, name: expectedLayerNames[i] })))(
    'tile layer "$name" has data length W*H',
    ({ i }) => {
      const layer = map.layers[i] as TmjTileLayer;
      expect(layer.type).toBe('tilelayer');
      expect(layer.data).toHaveLength(W * H);
    },
  );

  // -------------------------------------------------------
  // Terrain data passthrough
  // -------------------------------------------------------

  test('Ground_Base data matches input terrain layer', () => {
    const layer = map.layers[0] as TmjTileLayer;
    const expected = makeTerrainLayers()['Ground_Base'];
    expect(layer.data).toEqual(expected);
  });

  test('Ground_Detail is all zeros (empty input)', () => {
    const layer = map.layers[1] as TmjTileLayer;
    expect(layer.data.every((v) => v === 0)).toBe(true);
  });

  // -------------------------------------------------------
  // Prop stamping — Props_Back
  // -------------------------------------------------------

  test('Props_Back has non-zero tiles where bench was placed', () => {
    const layer = map.layers[5] as TmjTileLayer;
    // bench is 2×1 at (2, 2) — tiles at (2,2) and (3,2)
    const idx = 2 * W + 2;
    expect(layer.data[idx]).toBeGreaterThan(0);
  });

  test('Props_Back has non-zero tiles where tree trunk was placed', () => {
    const layer = map.layers[5] as TmjTileLayer;
    // tree is 2×2 at (6,3) — lower row (trunk) at y=4
    const idx = 4 * W + 6;
    expect(layer.data[idx]).toBeGreaterThan(0);
  });

  // -------------------------------------------------------
  // Prop stamping — foreground layers
  // -------------------------------------------------------

  test('Foreground_High has non-zero tiles where tree canopy was placed', () => {
    const layer = map.layers[15] as TmjTileLayer; // Foreground_High
    // tree foregroundLayer = 'Foreground_High', foregroundTiles = top row at (6,3)
    const idx = 3 * W + 6;
    expect(layer.data[idx]).toBeGreaterThan(0);
  });

  test('Props_Front has non-zero tiles where lamp foreground was placed', () => {
    const layer = map.layers[13] as TmjTileLayer; // Props_Front
    // lamp foregroundLayer = 'Props_Front', foregroundTiles = top row at (8,5)
    const idx = 5 * W + 8;
    expect(layer.data[idx]).toBeGreaterThan(0);
  });

  // -------------------------------------------------------
  // Prop GIDs are valid
  // -------------------------------------------------------

  test('stamped prop GIDs are within tileset range', () => {
    const maxGid = TILESET.firstgid + TILESET.tilecount - 1;
    const tileLayerIdxs = [4, 5, 6, 13, 14, 15, 16];
    for (const i of tileLayerIdxs) {
      const layer = map.layers[i] as TmjTileLayer;
      for (const gid of layer.data) {
        if (gid !== 0) {
          expect(gid).toBeGreaterThanOrEqual(TILESET.firstgid);
          expect(gid).toBeLessThanOrEqual(maxGid);
        }
      }
    }
  });

  // -------------------------------------------------------
  // Object layers
  // -------------------------------------------------------

  test('Collision layer is an objectgroup', () => {
    const layer = map.layers[7];
    expect(layer.type).toBe('objectgroup');
  });

  test('Collision layer has correct number of objects', () => {
    const layer = map.layers[7] as TmjObjectLayer;
    expect(layer.objects).toHaveLength(sampleCollisions.length);
  });

  test('Collision objects use pixel coordinates (tile * 16)', () => {
    const layer = map.layers[7] as TmjObjectLayer;
    const obj = layer.objects[0];
    expect(obj.x).toBe(sampleCollisions[0].x * 16);
    expect(obj.y).toBe(sampleCollisions[0].y * 16);
    expect(obj.width).toBe(sampleCollisions[0].width * 16);
    expect(obj.height).toBe(sampleCollisions[0].height * 16);
  });

  test('Collision objects have type "collision"', () => {
    const layer = map.layers[7] as TmjObjectLayer;
    for (const obj of layer.objects) {
      expect(obj.type).toBe('collision');
    }
  });

  test('Spawn_Points layer is an objectgroup', () => {
    const layer = map.layers[10];
    expect(layer.type).toBe('objectgroup');
  });

  test('Spawn_Points layer has correct number of objects', () => {
    const layer = map.layers[10] as TmjObjectLayer;
    expect(layer.objects).toHaveLength(sampleSpawns.length);
  });

  test('Spawn_Points objects use pixel coordinates (tile * 16)', () => {
    const layer = map.layers[10] as TmjObjectLayer;
    const obj = layer.objects[0];
    expect(obj.x).toBe(sampleSpawns[0].x * 16);
    expect(obj.y).toBe(sampleSpawns[0].y * 16);
  });

  test('Spawn_Points objects have width and height of 16', () => {
    const layer = map.layers[10] as TmjObjectLayer;
    for (const obj of layer.objects) {
      expect(obj.width).toBe(16);
      expect(obj.height).toBe(16);
    }
  });

  test('Spawn_Points objects have type "spawn"', () => {
    const layer = map.layers[10] as TmjObjectLayer;
    for (const obj of layer.objects) {
      expect(obj.type).toBe('spawn');
    }
  });

  test('Spawn_Points objects preserve spawn names', () => {
    const layer = map.layers[10] as TmjObjectLayer;
    const names = layer.objects.map((o) => o.name);
    expect(names).toContain('player_start');
    expect(names).toContain('npc_spawn_1');
  });

  test('all objects have unique auto-incrementing ids', () => {
    const allObjects = map.layers
      .filter((l) => l.type === 'objectgroup')
      .flatMap((l) => (l as TmjObjectLayer).objects);
    const ids = allObjects.map((o) => o.id);
    const uniqueIds = new Set(ids);
    expect(uniqueIds.size).toBe(ids.length);
  });

  // -------------------------------------------------------
  // Reserved object layers are empty
  // -------------------------------------------------------

  test.each([
    { name: 'Depth_Masks', i: 8 },
    { name: 'Triggers', i: 9 },
    { name: 'NPC_Paths', i: 11 },
    { name: 'Interaction', i: 12 },
  ])('reserved layer "$name" is empty', ({ i }) => {
    const layer = map.layers[i] as TmjObjectLayer;
    expect(layer.type).toBe('objectgroup');
    expect(layer.objects).toHaveLength(0);
  });

  // -------------------------------------------------------
  // Placeholder tile layers are empty
  // -------------------------------------------------------

  test('Animation_Back is empty (all zeros)', () => {
    const layer = map.layers[6] as TmjTileLayer;
    expect(layer.data.every((v) => v === 0)).toBe(true);
  });

  test('Animation_Front is empty (all zeros)', () => {
    const layer = map.layers[16] as TmjTileLayer;
    expect(layer.data.every((v) => v === 0)).toBe(true);
  });

  // -------------------------------------------------------
  // Optional buildingLayers merging
  // -------------------------------------------------------

  test('buildingLayers.Buildings_Base is merged into layer 4 when provided', () => {
    const bldBase = new Array(W * H).fill(0);
    bldBase[0] = TILESET.firstgid + 5; // sentinel value
    const map2 = exportTmj(
      W, H, makeTerrainLayers(), [], [], [],
      { Buildings_Base: bldBase },
    );
    const layer = map2.layers[4] as TmjTileLayer;
    expect(layer.data[0]).toBe(TILESET.firstgid + 5);
  });

  test('buildingLayers.Foreground_Low is merged into layer 14 when provided', () => {
    const fgLow = new Array(W * H).fill(0);
    fgLow[3] = TILESET.firstgid + 10; // sentinel value
    const map2 = exportTmj(
      W, H, makeTerrainLayers(), [], [], [],
      { Foreground_Low: fgLow },
    );
    const layer = map2.layers[14] as TmjTileLayer;
    expect(layer.data[3]).toBe(TILESET.firstgid + 10);
  });

  test('without buildingLayers, Buildings_Base is all zeros', () => {
    const layer = map.layers[4] as TmjTileLayer;
    expect(layer.data.every((v) => v === 0)).toBe(true);
  });

  // -------------------------------------------------------
  // Edge case: empty props/collisions/spawns
  // -------------------------------------------------------

  test('works with no props, collisions, or spawns', () => {
    const emptyMap = exportTmj(W, H, makeTerrainLayers(), [], [], []);
    expect(emptyMap.layers).toHaveLength(17);
    const collision = emptyMap.layers[7] as TmjObjectLayer;
    expect(collision.objects).toHaveLength(0);
    const spawns = emptyMap.layers[10] as TmjObjectLayer;
    expect(spawns.objects).toHaveLength(0);
  });
});
