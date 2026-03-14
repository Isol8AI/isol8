// src/town-gen/index.ts — CLI entry point for town generation

import { writeFileSync } from 'fs';
import { fileURLToPath } from 'url';
import { dirname, resolve } from 'path';
import { generateTown } from './generator';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

// Parse seed from CLI arg (default 42)
const seedArg = process.argv[2];
const seed = seedArg !== undefined ? parseInt(seedArg, 10) : 42;

if (isNaN(seed)) {
  console.error(`Invalid seed: "${seedArg}"`);
  process.exit(1);
}

console.log(`Generating town with seed ${seed}…`);

const { tmj, manifest } = generateTown(seed);

// Output paths relative to goosetown root
// __dirname = goosetown/src/town-gen; goosetown root is two levels up
const root = resolve(__dirname, '../..');

const tmjPath = resolve(root, 'public/assets/town-center.tmj');
const manifestPath = resolve(root, 'public/assets/town-gen-manifest.json');
const backendTmjPath = resolve(root, '../backend/data/town-center.tmj');

writeFileSync(tmjPath, JSON.stringify(tmj, null, 2));
console.log(`Written: ${tmjPath}`);

writeFileSync(manifestPath, JSON.stringify(manifest, null, 2));
console.log(`Written: ${manifestPath}`);

writeFileSync(backendTmjPath, JSON.stringify(tmj, null, 2));
console.log(`Written: ${backendTmjPath}`);

console.log(`Done. ${manifest.locations.length} buildings, ${manifest.spawns.length} spawns.`);
