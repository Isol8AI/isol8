import { PixiComponent } from '@pixi/react';
import * as PIXI from 'pixi.js';
import { CompositeTilemap } from '@pixi/tilemap';
import { useState, useEffect } from 'react';
import { Container } from '@pixi/react';
import {
  parseTmj,
  getLayer,
  getTileSourceRect,
  cleanGid,
  buildAnimationMap,
  type TmjMap,
} from '../lib/tmjParser';

/** Props for the PixiComponent tilemap bridge */
interface TilemapProps {
  tmjMap: TmjMap;
  layerName: string;
  tilesetTextures: PIXI.Texture[];
  tileFilter?: (gid: number) => boolean;
  tileExclude?: (gid: number) => boolean;
}

/**
 * PixiComponent bridge for CompositeTilemap.
 * Renders a single tile layer from a TMJ map.
 */
const TileLayer = PixiComponent<TilemapProps, CompositeTilemap>('TileLayer', {
  create() {
    const tilemap = new CompositeTilemap();
    // Advance tile animation counter each frame
    const onTick = () => {
      if (tilemap.tileAnim) {
        tilemap.tileAnim[0] = (tilemap.tileAnim[0] || 0) + 1;
      }
    };
    PIXI.Ticker.shared.add(onTick);
    (tilemap as any).__onTick = onTick;
    return tilemap;
  },
  willUnmount(tilemap) {
    const onTick = (tilemap as any).__onTick;
    if (onTick) {
      PIXI.Ticker.shared.remove(onTick);
    }
  },
  applyProps(tilemap, _oldProps, newProps) {
    const { tmjMap, layerName, tilesetTextures, tileFilter, tileExclude } = newProps;
    const layer = getLayer(tmjMap, layerName);
    if (!layer) return;

    tilemap.clear();

    const { width, height, tilewidth, tileheight } = tmjMap;
    const animMap = buildAnimationMap(tmjMap.tilesets);

    for (let y = 0; y < height; y++) {
      for (let x = 0; x < width; x++) {
        const index = y * width + x;
        const rawGid = layer.data[index];
        if (!rawGid) continue;

        const cleanedGid = cleanGid(rawGid);

        // Apply tile filter/exclude
        if (tileFilter && !tileFilter(cleanedGid)) continue;
        if (tileExclude && tileExclude(cleanedGid)) continue;

        const rect = getTileSourceRect(rawGid, tmjMap.tilesets);
        if (!rect) continue;

        const texture = tilesetTextures[rect.tilesetIndex];
        if (!texture) continue;

        // Check for animation
        const anim = animMap.get(cleanedGid);
        if (anim && anim.length > 1) {
          const ts = tmjMap.tilesets[rect.tilesetIndex];
          const baseLocalId = cleanedGid - ts.firstgid;
          const sequential = anim.every((f, i) => f.tileid === baseLocalId + i);

          if (sequential) {
            tilemap.tile(texture, x * tilewidth, y * tileheight, {
              u: rect.u,
              v: rect.v,
              tileWidth: tilewidth,
              tileHeight: tileheight,
              animX: tilewidth,
              animCountX: anim.length,
              animDivisor: Math.round(anim[0].duration / 16.67),
            });
          } else {
            // Non-sequential fallback: render static first frame
            tilemap.tile(texture, x * tilewidth, y * tileheight, {
              u: rect.u,
              v: rect.v,
              tileWidth: tilewidth,
              tileHeight: tileheight,
            });
          }
        } else {
          tilemap.tile(texture, x * tilewidth, y * tileheight, {
            u: rect.u,
            v: rect.v,
            tileWidth: tilewidth,
            tileHeight: tileheight,
          });
        }
      }
    }
  },
});

/** Callback with parsed map dimensions */
export interface MapDimensions {
  widthTiles: number;
  heightTiles: number;
  tileDim: number;
  widthPx: number;
  heightPx: number;
}

interface TiledMapRendererProps {
  mapUrl: string;
  tilesetUrl: string;
  onMapLoaded?: (dims: MapDimensions) => void;
  layers?: string[];
  tileFilter?: (gid: number) => boolean;
  tileExclude?: (gid: number) => boolean;
  children?: React.ReactNode;
}

// Module-level cache for parsed TMJ data
const tmjCache = new Map<string, TmjMap>();

/**
 * Multi-layer tile map renderer.
 * Loads a TMJ map file and renders specified tile layers using CompositeTilemap.
 */
export function TiledMapRenderer({
  mapUrl,
  tilesetUrl,
  onMapLoaded,
  layers: layerFilter,
  tileFilter,
  tileExclude,
  children,
}: TiledMapRendererProps) {
  const [tmjMap, setTmjMap] = useState<TmjMap | null>(null);
  const [tilesetTextures, setTilesetTextures] = useState<PIXI.Texture[]>([]);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      let map: TmjMap;

      if (tmjCache.has(mapUrl)) {
        map = tmjCache.get(mapUrl)!;
      } else {
        const resp = await fetch(mapUrl);
        const json = await resp.json();
        map = parseTmj(json);
        tmjCache.set(mapUrl, map);
      }

      if (cancelled) return;
      setTmjMap(map);

      // Load tileset textures — one per tileset entry.
      // PixiJS BaseTexture.from() internally caches by source URL,
      // so multiple TiledMapRenderer instances sharing the same tileset
      // won't create duplicate textures.
      const textures: PIXI.Texture[] = [];
      for (const _ts of map.tilesets) {
        const baseTexture = PIXI.BaseTexture.from(tilesetUrl, {
          scaleMode: PIXI.SCALE_MODES.NEAREST,
        });
        textures.push(new PIXI.Texture(baseTexture));
      }

      if (cancelled) return;
      setTilesetTextures(textures);
      setReady(true);

      onMapLoaded?.({
        widthTiles: map.width,
        heightTiles: map.height,
        tileDim: map.tilewidth,
        widthPx: map.width * map.tilewidth,
        heightPx: map.height * map.tileheight,
      });
    }

    void load();
    return () => {
      cancelled = true;
    };
  }, [mapUrl, tilesetUrl]);

  if (!ready || !tmjMap) return null;

  const visibleLayers = tmjMap.layers.filter(
    (l) => l.visible && l.name !== 'collision',
  );
  const layerNames = layerFilter ?? visibleLayers.map((l) => l.name);

  return (
    <Container>
      {layerNames.map((name) => (
        <TileLayer
          key={name}
          tmjMap={tmjMap}
          layerName={name}
          tilesetTextures={tilesetTextures}
          tileFilter={tileFilter}
          tileExclude={tileExclude}
        />
      ))}
      {children}
    </Container>
  );
}
