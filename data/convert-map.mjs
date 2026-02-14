#!/usr/bin/env node
/**
 * Converts gentle.js map data to JSON for the Python backend.
 * Run: node data/convert-map.mjs
 */
import * as map from './gentle.js';
import { writeFileSync } from 'fs';
import { dirname, join } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));

const data = {
  tilesetpath: map.tilesetpath,
  tiledim: map.tiledim,
  tilesetpxw: map.tilesetpxw,
  tilesetpxh: map.tilesetpxh,
  mapwidth: map.mapwidth,
  mapheight: map.mapheight,
  bgtiles: map.bgtiles,
  objmap: map.objmap,
  animatedsprites: map.animatedsprites,
};

const outPath = join(__dirname, '..', '..', 'backend', 'data', 'gentle_map.json');
writeFileSync(outPath, JSON.stringify(data));
console.log(`Wrote map data to ${outPath}`);
console.log(`  mapwidth=${data.mapwidth}, mapheight=${data.mapheight}`);
console.log(`  bgTiles layers=${data.bgtiles.length}`);
console.log(`  objmap rows=${data.objmap.length}`);
console.log(`  animatedsprites count=${data.animatedsprites.length}`);
