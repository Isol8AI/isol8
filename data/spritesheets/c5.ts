import { SpritesheetData } from './types';

export const data: SpritesheetData = {
  frames: {
    down: {
      frame: { x: 384, y: 0, w: 32, h: 40 },
      sourceSize: { w: 32, h: 40 },
      spriteSourceSize: { x: 0, y: 0 },
    },
    down2: {
      frame: { x: 416, y: 0, w: 32, h: 40 },
      sourceSize: { w: 32, h: 40 },
      spriteSourceSize: { x: 0, y: 0 },
    },
    down3: {
      frame: { x: 448, y: 0, w: 32, h: 40 },
      sourceSize: { w: 32, h: 40 },
      spriteSourceSize: { x: 0, y: 0 },
    },
    left: {
      frame: { x: 384, y: 40, w: 32, h: 40 },
      sourceSize: { w: 32, h: 40 },
      spriteSourceSize: { x: 0, y: 0 },
    },
    left2: {
      frame: { x: 416, y: 40, w: 32, h: 40 },
      sourceSize: { w: 32, h: 40 },
      spriteSourceSize: { x: 0, y: 0 },
    },
    left3: {
      frame: { x: 448, y: 40, w: 32, h: 40 },
      sourceSize: { w: 32, h: 40 },
      spriteSourceSize: { x: 0, y: 0 },
    },
    right: {
      frame: { x: 384, y: 80, w: 32, h: 40 },
      sourceSize: { w: 32, h: 40 },
      spriteSourceSize: { x: 0, y: 0 },
    },
    right2: {
      frame: { x: 416, y: 80, w: 32, h: 40 },
      sourceSize: { w: 32, h: 40 },
      spriteSourceSize: { x: 0, y: 0 },
    },
    right3: {
      frame: { x: 448, y: 80, w: 32, h: 40 },
      sourceSize: { w: 32, h: 40 },
      spriteSourceSize: { x: 0, y: 0 },
    },
    up: {
      frame: { x: 384, y: 120, w: 32, h: 40 },
      sourceSize: { w: 32, h: 40 },
      spriteSourceSize: { x: 0, y: 0 },
    },
    up2: {
      frame: { x: 416, y: 120, w: 32, h: 40 },
      sourceSize: { w: 32, h: 40 },
      spriteSourceSize: { x: 0, y: 0 },
    },
    up3: {
      frame: { x: 448, y: 120, w: 32, h: 40 },
      sourceSize: { w: 32, h: 40 },
      spriteSourceSize: { x: 0, y: 0 },
    },
  },
  meta: {
    scale: '1',
  },
  animations: {
    down: ['down', 'down2', 'down3'],
    left: ['left', 'left2', 'left3'],
    right: ['right', 'right2', 'right3'],
    up: ['up', 'up2', 'up3'],
  },
};
