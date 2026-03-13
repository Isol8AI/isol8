/** Parsed tile layer from TMJ */
export interface TmjTileLayer {
  name: string;
  data: number[];
  width: number;
  height: number;
  visible: boolean;
}

/** Tile animation frame from TMJ tileset */
export interface TmjTileAnimFrame {
  tileid: number;
  duration: number;
}

/** Per-tile data from TMJ tileset */
export interface TmjTileData {
  id: number;
  animation?: TmjTileAnimFrame[];
  properties?: Array<{ name: string; type: string; value: unknown }>;
}

/** Tileset reference from TMJ */
export interface TmjTileset {
  firstgid: number;
  name: string;
  tilewidth: number;
  tileheight: number;
  tilecount: number;
  columns: number;
  image: string;
  imagewidth: number;
  imageheight: number;
  tiles?: TmjTileData[];
}

/** Parsed TMJ map */
export interface TmjMap {
  width: number;
  height: number;
  tilewidth: number;
  tileheight: number;
  layers: TmjTileLayer[];
  tilesets: TmjTileset[];
}

/** GID bit mask to strip flip/rotation flags */
const GID_MASK = 0x1fffffff;

/** Strip flip/rotation bits from a GID to get the actual tile ID */
export function cleanGid(rawGid: number): number {
  return rawGid & GID_MASK;
}

/**
 * Parse a TMJ (Tiled JSON) file into typed structures.
 * Filters to tile layers only (ignores object/image layers).
 * NOTE: Requires embedded tilesets. External tileset references (with `source` field) are skipped.
 */
export function parseTmj(json: unknown): TmjMap {
  const raw = json as Record<string, unknown>;
  const width = raw.width as number;
  const height = raw.height as number;
  const tilewidth = raw.tilewidth as number;
  const tileheight = raw.tileheight as number;

  const rawLayers = raw.layers as Record<string, unknown>[];
  const layers: TmjTileLayer[] = rawLayers
    .filter((l) => l.type === 'tilelayer')
    .map((l) => ({
      name: l.name as string,
      data: l.data as number[],
      width: l.width as number,
      height: l.height as number,
      visible: l.visible !== false,
    }));

  const rawTilesets = raw.tilesets as Record<string, unknown>[];
  const tilesets: TmjTileset[] = rawTilesets
    .filter((ts) => !ts.source)
    .map((ts) => ({
      firstgid: ts.firstgid as number,
      name: (ts.name as string) ?? '',
      tilewidth: (ts.tilewidth as number) ?? 32,
      tileheight: (ts.tileheight as number) ?? 32,
      tilecount: (ts.tilecount as number) ?? 0,
      columns: (ts.columns as number) ?? 1,
      image: (ts.image as string) ?? '',
      imagewidth: (ts.imagewidth as number) ?? 0,
      imageheight: (ts.imageheight as number) ?? 0,
      tiles: (ts.tiles as TmjTileData[]) ?? undefined,
    }));

  return { width, height, tilewidth, tileheight, layers, tilesets };
}

/**
 * Get the layer with the given name from a parsed TMJ map.
 */
export function getLayer(map: TmjMap, name: string): TmjTileLayer | undefined {
  return map.layers.find((l) => l.name === name);
}

/**
 * For a given GID, find which tileset it belongs to and compute
 * the source rectangle (u, v) in the tileset image.
 * Returns null for GID 0 (empty tile).
 */
export function getTileSourceRect(
  gid: number,
  tilesets: TmjTileset[],
): { tilesetIndex: number; u: number; v: number } | null {
  const cleanedGid = cleanGid(gid);
  if (cleanedGid === 0) return null;

  // Find the tileset this GID belongs to (highest firstgid <= cleanedGid)
  let tilesetIndex = 0;
  for (let i = tilesets.length - 1; i >= 0; i--) {
    if (tilesets[i].firstgid <= cleanedGid) {
      tilesetIndex = i;
      break;
    }
  }

  const tileset = tilesets[tilesetIndex];
  const localId = cleanedGid - tileset.firstgid;
  const col = localId % tileset.columns;
  const row = Math.floor(localId / tileset.columns);
  const u = col * tileset.tilewidth;
  const v = row * tileset.tileheight;

  return { tilesetIndex, u, v };
}

/**
 * Build a map of GID -> animation frames from all tilesets.
 * Call once per map load, not per tile.
 */
export function buildAnimationMap(
  tilesets: TmjTileset[],
): Map<number, TmjTileAnimFrame[]> {
  const animations = new Map<number, TmjTileAnimFrame[]>();
  for (const ts of tilesets) {
    if (!ts.tiles) continue;
    for (const tile of ts.tiles) {
      if (tile.animation && tile.animation.length > 0) {
        const globalId = ts.firstgid + tile.id;
        animations.set(globalId, tile.animation);
      }
    }
  }
  return animations;
}

/**
 * Water tile GIDs (from town-tileset, firstgid=1).
 * Populated after identifying water tiles during collision audit.
 * These tiles get the displacement filter.
 */
export const WATER_TILE_GIDS: Set<number> = new Set([
  // To be populated during Task 12
]);

export function isWaterTile(gid: number): boolean {
  return WATER_TILE_GIDS.has(cleanGid(gid));
}
