import { PixiComponent, applyDefaultProps } from '@pixi/react';
import * as PIXI from 'pixi.js';
import type { WorldMap } from '../types/town';

const BACKGROUND_URL = '/assets/town-background.png';

export const PixiStaticMap = PixiComponent('StaticMap', {
  create: (props: { map: WorldMap; [k: string]: any }) => {
    const map = props.map;
    const screenxtiles = map.bgTiles[0].length;
    const screenytiles = map.bgTiles[0][0].length;
    const mapWidthPx = screenxtiles * map.tileDim;
    const mapHeightPx = screenytiles * map.tileDim;

    const container = new PIXI.Container();

    // Render the pre-converted pixel art background as a single sprite
    const bgTexture = PIXI.BaseTexture.from(BACKGROUND_URL, {
      scaleMode: PIXI.SCALE_MODES.NEAREST,
    });
    const bgSprite = new PIXI.Sprite(new PIXI.Texture(bgTexture));
    bgSprite.width = mapWidthPx;
    bgSprite.height = mapHeightPx;
    container.addChild(bgSprite);

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
      displacementSprite.width = mapWidthPx;
      displacementSprite.height = mapHeightPx;
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

    container.interactive = true;
    container.hitArea = new PIXI.Rectangle(0, 0, mapWidthPx, mapHeightPx);

    return container;
  },

  applyProps: (instance, oldProps, newProps) => {
    applyDefaultProps(instance, oldProps, newProps);
  },
});
