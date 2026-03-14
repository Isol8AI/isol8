// src/town-gen/schema.ts — Type definitions for the OGA town generator

// --- Tilemap structure (Tiled-compatible) ---

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
}

export interface TmjTileLayer {
  name: string;
  type: 'tilelayer';
  width: number;
  height: number;
  data: number[];
  visible: boolean;
  opacity: number;
  x: number;
  y: number;
}

export interface TmjObject {
  id: number;
  name: string;
  type: string;
  x: number;
  y: number;
  width: number;
  height: number;
  properties?: { name: string; type: string; value: unknown }[];
}

export interface TmjObjectLayer {
  name: string;
  type: 'objectgroup';
  objects: TmjObject[];
  visible: boolean;
  opacity: number;
  x: number;
  y: number;
}

export type TmjLayer = TmjTileLayer | TmjObjectLayer;

export interface TmjMap {
  width: number;
  height: number;
  tilewidth: number;
  tileheight: number;
  orientation: 'orthogonal';
  renderorder: 'right-down';
  tilesets: TmjTileset[];
  layers: TmjLayer[];
  type: 'map';
  version: '1.10';
  tiledversion: string;
}

// --- Generator internal types ---

export type Zone =
  | 'water'
  | 'shore'
  | 'grass'
  | 'road'
  | 'plaza'
  | 'canal'
  | 'dock'
  | 'park'
  | 'building'
  | 'bridge';

export type ZoneMap = Zone[][];

export interface TerrainFamily {
  primary: number;
  alternates: number[];
  weights?: number[];
}

export interface TransitionSet {
  n: number; s: number; e: number; w: number;
  ne: number; nw: number; se: number; sw: number;
  innerNE: number; innerNW: number; innerSE: number; innerSW: number;
}

export interface BuildingKit {
  name: string;
  class: 'residential' | 'commercial' | 'civic';
  footprint: { w: number; h: number };
  tiles: number[][];
  doorOffset: { x: number; y: number };
  collision: { x: number; y: number; w: number; h: number };
  foregroundRows: number;
}

export interface PropDef {
  name: string;
  footprint: { w: number; h: number };
  tiles: number[][];
  collision: 'none' | 'base' | 'full';
  groundLayer: string;
  foregroundLayer?: string;
  foregroundTiles?: number[][];
}

export interface PlacedBuilding {
  kit: BuildingKit;
  x: number;
  y: number;
}

export interface PlacedProp {
  def: PropDef;
  x: number;
  y: number;
}

export interface CollisionRect {
  x: number;
  y: number;
  width: number;
  height: number;
  source: string;
}

export interface SpawnPoint {
  name: string;
  x: number;
  y: number;
}

export interface TownManifest {
  seed: number;
  width: number;
  height: number;
  tileDim: number;
  spawns: SpawnPoint[];
  locations: { name: string; label: string; x: number; y: number }[];
}

export interface TownData {
  zoneMap: ZoneMap;
  buildings: PlacedBuilding[];
  props: PlacedProp[];
  collisions: CollisionRect[];
  spawns: SpawnPoint[];
  manifest: TownManifest;
}

// --- Seeded PRNG ---

export interface RNG {
  next(): number;
  nextInt(max: number): number;
  pick<T>(arr: T[]): T;
  weightedPick(ids: number[], weights?: number[]): number;
}
