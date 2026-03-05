import { PixiComponent, applyDefaultProps } from '@pixi/react';
import * as PIXI from 'pixi.js';
import { WorldMap } from '../../convex/aiTown/worldMap';

export const PixiStaticMap = PixiComponent('StaticMap', {
  create: (props: { map: WorldMap; [k: string]: any }) => {
    const map = props.map;
    const numxtiles = Math.floor(map.tileSetDimX / map.tileDim);
    const numytiles = Math.floor(map.tileSetDimY / map.tileDim);
    const bt = PIXI.BaseTexture.from(map.tileSetUrl, {
      scaleMode: PIXI.SCALE_MODES.NEAREST,
    });

    const tiles: PIXI.Texture[] = [];
    for (let x = 0; x < numxtiles; x++) {
      for (let y = 0; y < numytiles; y++) {
        tiles[x + y * numxtiles] = new PIXI.Texture(
          bt,
          new PIXI.Rectangle(x * map.tileDim, y * map.tileDim, map.tileDim, map.tileDim),
        );
      }
    }
    const screenxtiles = map.bgTiles[0].length;
    const screenytiles = map.bgTiles[0][0].length;

    const container = new PIXI.Container();
    const allLayers = [...map.bgTiles, ...map.objectTiles];

    // blit bg & object layers of map onto canvas
    for (let i = 0; i < screenxtiles * screenytiles; i++) {
      const x = i % screenxtiles;
      const y = Math.floor(i / screenxtiles);
      const xPx = x * map.tileDim;
      const yPx = y * map.tileDim;

      // Add all layers of backgrounds.
      for (const layer of allLayers) {
        const tileIndex = layer[x][y];
        // Some layers may not have tiles at this location.
        if (tileIndex === -1) continue;
        const ctile = new PIXI.Sprite(tiles[tileIndex]);
        ctile.x = xPx;
        ctile.y = yPx;
        container.addChild(ctile);
      }
    }

    // Subtle water shimmer effect using displacement filter
    const noiseCanvas = document.createElement('canvas');
    noiseCanvas.width = 128;
    noiseCanvas.height = 128;
    const ctx = noiseCanvas.getContext('2d');
    if (ctx) {
      for (let nx = 0; nx < 128; nx++) {
        for (let ny = 0; ny < 128; ny++) {
          const v = Math.floor(Math.random() * 12 + 122);
          ctx.fillStyle = `rgb(${v},${v},${v})`;
          ctx.fillRect(nx, ny, 1, 1);
        }
      }
      const displacementTexture = PIXI.Texture.from(noiseCanvas);
      const displacementSprite = new PIXI.Sprite(displacementTexture);
      displacementSprite.texture.baseTexture.wrapMode = PIXI.WRAP_MODES.REPEAT;
      displacementSprite.width = screenxtiles * map.tileDim;
      displacementSprite.height = screenytiles * map.tileDim;
      container.addChild(displacementSprite);
      const displacementFilter = new PIXI.DisplacementFilter(displacementSprite, 1.5);
      container.filters = [displacementFilter];
      PIXI.Ticker.shared.add(() => {
        displacementSprite.x += 0.3;
        displacementSprite.y += 0.15;
      });
    }

    container.x = 0;
    container.y = 0;

    // Set the hit area manually to ensure `pointerdown` events are delivered to this container.
    container.interactive = true;
    container.hitArea = new PIXI.Rectangle(
      0,
      0,
      screenxtiles * map.tileDim,
      screenytiles * map.tileDim,
    );

    return container;
  },

  applyProps: (instance, oldProps, newProps) => {
    applyDefaultProps(instance, oldProps, newProps);
  },
});
