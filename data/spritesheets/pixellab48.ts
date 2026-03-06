import { SpritesheetData } from './types';

// Shared spritesheet data for all PixelLab 48x48 characters.
// Layout: 6 columns (frames) x 4 rows (south/west/east/north)
// Row order: south=0 (down), west=1 (left), east=2 (right), north=3 (up)
const W = 48;
const H = 48;

function row(dir: string, rowIdx: number) {
  const y = rowIdx * H;
  const entries: Record<string, any> = {};
  for (let i = 0; i < 6; i++) {
    const key = i === 0 ? dir : `${dir}${i + 1}`;
    entries[key] = {
      frame: { x: i * W, y, w: W, h: H },
      sourceSize: { w: W, h: H },
      spriteSourceSize: { x: 0, y: 0 },
    };
  }
  return entries;
}

export const data: SpritesheetData = {
  frames: {
    ...row('down', 0),
    ...row('left', 1),
    ...row('right', 2),
    ...row('up', 3),
  },
  meta: {
    scale: '1',
  },
  animations: {
    down: ['down', 'down2', 'down3', 'down4', 'down5', 'down6'],
    left: ['left', 'left2', 'left3', 'left4', 'left5', 'left6'],
    right: ['right', 'right2', 'right3', 'right4', 'right5', 'right6'],
    up: ['up', 'up2', 'up3', 'up4', 'up5', 'up6'],
  },
};
