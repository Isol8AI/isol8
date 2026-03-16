# GooseTown Map & Frontend Overhaul — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the small pastoral AI Town map with a 64x48 pixel art city, and make the map fill the screen instead of sitting in a bordered rectangle.

**Architecture:** A Python script combines two existing tilesets (rpg-tileset.png + magecity.png) into one composite image and generates tile data arrays for a 64x48 city grid. The frontend layout is overhauled to be full-screen with a persistent sidebar. Backend coordinates are updated to match.

**Tech Stack:** Python 3 (Pillow), TypeScript, PixiJS, Tailwind CSS, FastAPI

---

## Context

### Current State
- Map: 48x76 tiles (rendered as 45x32 screen tiles) using `gentle-obj.png` (1440x1024px)
- Layout: `max-w-[1400px]` with 36-48px `game-frame` border, a16z/Convex branding everywhere
- Data flow: `data/gentle.js` → `convex/init.ts` → DB → `serverGame.ts` → `WorldMap` → `PixiStaticMap`

### Target State
- Map: 64x48 tiles using combined tileset (rpg-tileset.png + magecity.png = 512x768px)
- Layout: Full-screen map (left ~75%) + persistent sidebar (right ~350px), no branding
- Same data flow, new data module: `data/city.ts` replaces `data/gentle.js`

### Key Constraint
`PixiStaticMap.tsx` loads exactly ONE tileset image per map. To use both rpg-tileset.png (256 tiles) and magecity.png (128 tiles), we must combine them into a single composite image.

### Tileset Index Scheme (Combined 512x768px, 16 tiles wide × 24 tiles tall)
- **Indices 0–255:** rpg-tileset.png tiles (rows 0–15)
- **Indices 256–383:** magecity.png tiles (rows 16–23)
- Formula: `index = column + row * 16` (same as PixiStaticMap already uses)

---

## Task 1: Create the Combined Tileset Image

**Files:**
- Create: `goosetown/scripts/generate_city_map.py`
- Input: `goosetown/public/assets/rpg-tileset.png` (512x512), `goosetown/public/assets/magecity.png` (512x256)
- Output: `goosetown/public/assets/city-tileset.png` (512x768)

**Step 1: Write the tileset combiner**

```python
#!/usr/bin/env python3
"""Generate GooseTown city map data.

Combines rpg-tileset.png (512x512) and magecity.png (512x256) into a single
tileset (512x768), then generates a 64x48 tile city map as a TypeScript module.

Usage:
    cd goosetown
    python scripts/generate_city_map.py
"""

from pathlib import Path
from PIL import Image

SCRIPT_DIR = Path(__file__).parent
GOOSETOWN_DIR = SCRIPT_DIR.parent
ASSETS_DIR = GOOSETOWN_DIR / "public" / "assets"
DATA_DIR = GOOSETOWN_DIR / "data"

TILE_SIZE = 32
MAP_W = 64  # tiles
MAP_H = 48  # tiles
TILESET_COLS = 16  # tiles per row in combined tileset


def combine_tilesets() -> Image.Image:
    """Stack rpg-tileset.png on top of magecity.png → 512x768."""
    rpg = Image.open(ASSETS_DIR / "rpg-tileset.png")
    mage = Image.open(ASSETS_DIR / "magecity.png")

    assert rpg.size == (512, 512), f"Unexpected rpg-tileset size: {rpg.size}"
    assert mage.size == (512, 256), f"Unexpected magecity size: {mage.size}"

    combined = Image.new("RGBA", (512, 768))
    combined.paste(rpg, (0, 0))
    combined.paste(mage, (0, 512))
    return combined
```

**Step 2: Run the combiner to verify it works**

Run:
```bash
cd /Users/prasiddhaparthsarthy/Desktop/freebird/goosetown
pip install Pillow  # if not already installed
python scripts/generate_city_map.py --tileset-only
```

Expected: `public/assets/city-tileset.png` created, 512x768px

**Step 3: Commit**

```bash
cd /Users/prasiddhaparthsarthy/Desktop/freebird/backend
git add ../goosetown/scripts/generate_city_map.py ../goosetown/public/assets/city-tileset.png
git commit -m "feat(town): add city tileset combiner script"
```

---

## Task 2: Add City Map Generation Logic to the Script

**Files:**
- Modify: `goosetown/scripts/generate_city_map.py`

The script generates three data structures matching `gentle.js` format:
- `bgtiles`: `number[][][]` — background layers (2 layers: base terrain + detail)
- `objmap`: `number[][][]` — object/collision layer (1 layer, -1 = walkable)
- `animatedsprites`: `object[]` — empty array (no windmills in city)

**Step 1: Define tile palette constants**

Add after the combine_tilesets function:

```python
# ── Tile Palette ──────────────────────────────────────────────────────
# RPG tileset (indices 0-255, rows 0-15 of combined tileset)
# Visual identification from rpg-tileset.png grid positions:
EMPTY = -1

# Row 0-1: Grass variants
GRASS_1 = 0       # Main grass tile (top-left of rpg tileset)
GRASS_2 = 1       # Grass variant
GRASS_3 = 2       # Grass variant
GRASS_4 = 16      # Grass variant (row 1)
GRASS_5 = 17      # Grass variant

# Dirt/path tiles (row 2-3 area)
DIRT = 32
STONE_PATH = 48   # Cobblestone
STONE_PATH_2 = 49

# Water (row 4-5 area)
WATER = 64
WATER_EDGE_T = 65
WATER_EDGE_B = 81
WATER_EDGE_L = 80
WATER_EDGE_R = 66

# Trees (row 10-11 area)
TREE_TOP = 160
TREE_BOTTOM = 176
TREE_2_TOP = 161
TREE_2_BOTTOM = 177

# Flowers/bushes
FLOWER_1 = 162
FLOWER_2 = 163
BUSH = 178

# MageCity tileset (indices 256-383, rows 16-23 of combined tileset)
# Row 16 (offset 256): base tiles
CITY_GRASS = 256
CITY_STONE = 257
CITY_STONE_2 = 258

# Row 17 (offset 272): walls
WALL_H = 272
WALL_V = 273
WALL_CORNER_TL = 274
WALL_CORNER_TR = 275

# Row 18 (offset 288): more walls/edges
WALL_CORNER_BL = 288
WALL_CORNER_BR = 289

# Row 19-20 (offset 304-335): roofs
ROOF_TL = 304
ROOF_TR = 305
ROOF_BL = 320
ROOF_BR = 321
ROOF_MID = 306

# Row 21-22 (offset 336-367): building details
DOOR = 336
WINDOW = 337
BRICK = 352
BRICK_2 = 353

# Lamp/bench decorations
LAMP = 338
BENCH = 354
```

Note: These tile indices are initial estimates based on typical RPG tileset layouts. They WILL need adjustment after visual inspection of the generated map. The script includes a `--tileset-only` flag to generate just the tileset for visual verification before generating the full map.

**Step 2: Write the map generation functions**

```python
def make_empty_layer(fill: int = EMPTY) -> list[list[int]]:
    """Create a MAP_W x MAP_H layer filled with a default tile."""
    return [[fill for _ in range(MAP_H)] for _ in range(MAP_W)]


def generate_base_layer() -> list[list[int]]:
    """Layer 0: grass everywhere as base."""
    layer = make_empty_layer(GRASS_1)
    # Add some grass variety
    import random
    random.seed(42)  # Deterministic
    for x in range(MAP_W):
        for y in range(MAP_H):
            r = random.random()
            if r < 0.1:
                layer[x][y] = GRASS_2
            elif r < 0.15:
                layer[x][y] = GRASS_3
            elif r < 0.2:
                layer[x][y] = GRASS_4
    return layer


def generate_detail_layer() -> list[list[int]]:
    """Layer 1: roads, paths, plazas overlaid on grass."""
    layer = make_empty_layer(EMPTY)

    # ── Main Street (vertical, x=30-33, full height) ──
    for x in range(30, 34):
        for y in range(0, MAP_H):
            layer[x][y] = STONE_PATH

    # ── Cross Street (horizontal, y=22-25, full width) ──
    for x in range(0, MAP_W):
        for y in range(22, 26):
            layer[x][y] = STONE_PATH

    # ── Town Plaza (center, 28-35 x 20-27) ──
    for x in range(28, 36):
        for y in range(20, 28):
            layer[x][y] = STONE_PATH_2

    # ── Cafe area path (10-16 x 18-24) ──
    for x in range(10, 17):
        for y in range(18, 25):
            if layer[x][y] == EMPTY:
                layer[x][y] = STONE_PATH

    # ── Library area path (48-56 x 18-24) ──
    for x in range(48, 57):
        for y in range(18, 25):
            if layer[x][y] == EMPTY:
                layer[x][y] = STONE_PATH

    # ── Park paths (44-54 x 6-14) ──
    for x in range(46, 50):
        for y in range(6, 15):
            layer[x][y] = STONE_PATH

    # ── Residential paths (6-16 x 4-12) ──
    for x in range(10, 14):
        for y in range(4, 13):
            layer[x][y] = STONE_PATH

    # ── Shop area path (8-16 x 34-40) ──
    for x in range(10, 17):
        for y in range(34, 41):
            if layer[x][y] == EMPTY:
                layer[x][y] = STONE_PATH

    # ── Workshop area path (44-54 x 34-40) ──
    for x in range(46, 53):
        for y in range(34, 41):
            if layer[x][y] == EMPTY:
                layer[x][y] = STONE_PATH

    return layer


def generate_object_layer() -> list[list[int]]:
    """Object layer: buildings (solid), trees (solid), decorations.
    -1 = walkable, anything else = collision.
    """
    layer = make_empty_layer(EMPTY)

    # ── Map border: trees along edges ──
    for x in range(MAP_W):
        for dy in range(2):
            layer[x][dy] = TREE_BOTTOM
            layer[x][MAP_H - 1 - dy] = TREE_BOTTOM
    for y in range(MAP_H):
        for dx in range(2):
            layer[dx][y] = TREE_BOTTOM
            layer[MAP_W - 1 - dx][y] = TREE_BOTTOM

    def place_building(bx: int, by: int, bw: int, bh: int):
        """Place a rectangular building (collision tiles)."""
        for x in range(bx, bx + bw):
            for y in range(by, by + bh):
                if 0 <= x < MAP_W and 0 <= y < MAP_H:
                    layer[x][y] = BRICK

    # ── Residential houses (northwest) ──
    place_building(6, 5, 4, 3)    # House 1
    place_building(6, 10, 4, 3)   # House 2
    place_building(14, 5, 4, 3)   # House 3
    place_building(14, 10, 4, 3)  # House 4
    place_building(10, 7, 3, 2)   # House 5

    # ── Cafe (west-center) ──
    place_building(8, 18, 5, 4)

    # ── Library (east-center) ──
    place_building(49, 18, 6, 4)

    # ── General Store (west-south) ──
    place_building(8, 34, 5, 4)

    # ── Workshop (southeast) ──
    place_building(47, 34, 5, 4)

    # ── Park trees and decorations (east-north) ──
    import random
    random.seed(99)
    for _ in range(12):
        tx = random.randint(42, 56)
        ty = random.randint(5, 14)
        if layer[tx][ty] == EMPTY:
            layer[tx][ty] = TREE_BOTTOM

    # ── Street trees along Main Street ──
    for y in range(4, MAP_H - 4, 6):
        if layer[28][y] == EMPTY:
            layer[28][y] = TREE_BOTTOM
        if layer[36][y] == EMPTY:
            layer[36][y] = TREE_BOTTOM

    # ── Fountain in plaza center ──
    layer[31][23] = WATER
    layer[32][23] = WATER
    layer[31][24] = WATER
    layer[32][24] = WATER

    return layer
```

**Step 3: Write the TypeScript output function**

```python
def format_layer(layer: list[list[int]]) -> str:
    """Format a 2D tile layer as JS array literal."""
    lines = []
    lines.append("[")
    for x in range(len(layer)):
        row = ", ".join(str(t) for t in layer[x])
        lines.append(f"[ {row} ],")
    lines.append("]")
    return "\n".join(lines)


def generate_typescript(bgtiles: list, objmap: list, animated: list) -> str:
    """Generate the city.ts file content."""
    ts = '// City map generated by generate_city_map.py\n\n'
    ts += 'export const tilesetpath = "/assets/city-tileset.png"\n'
    ts += f'export const tiledim = {TILE_SIZE}\n'
    ts += f'export const screenxtiles = {MAP_W}\n'
    ts += f'export const screenytiles = {MAP_H}\n'
    ts += 'export const tilesetpxw = 512\n'
    ts += 'export const tilesetpxh = 768\n'
    ts += '\n'

    # bgtiles: array of layers
    ts += 'export const bgtiles = [\n'
    for layer in bgtiles:
        ts += format_layer(layer) + ',\n'
    ts += '];\n\n'

    # objmap: array of layers (single layer)
    ts += 'export const objmap = [\n'
    for layer in objmap:
        ts += format_layer(layer) + ',\n'
    ts += '];\n\n'

    # animatedsprites: empty for city map
    ts += 'export const animatedsprites: any[] = [];\n\n'

    ts += 'export const mapwidth = bgtiles[0].length;\n'
    ts += 'export const mapheight = bgtiles[0][0].length;\n'

    return ts


def main():
    import sys

    # Combine tilesets
    combined = combine_tilesets()
    output_path = ASSETS_DIR / "city-tileset.png"
    combined.save(output_path)
    print(f"Saved combined tileset: {output_path}")

    if "--tileset-only" in sys.argv:
        print("Tileset-only mode. Skipping map generation.")
        return

    # Generate map layers
    base = generate_base_layer()
    detail = generate_detail_layer()
    objects = generate_object_layer()

    # Write TypeScript
    ts_content = generate_typescript(
        bgtiles=[base, detail],
        objmap=[objects],
        animated=[],
    )
    ts_path = DATA_DIR / "city.ts"
    ts_path.write_text(ts_content)
    print(f"Saved city map data: {ts_path}")
    print(f"Map: {MAP_W}x{MAP_H} tiles, {MAP_W * TILE_SIZE}x{MAP_H * TILE_SIZE}px")


if __name__ == "__main__":
    main()
```

**Step 4: Run the full generator**

Run:
```bash
cd /Users/prasiddhaparthsarthy/Desktop/freebird/goosetown
python scripts/generate_city_map.py
```

Expected: `data/city.ts` created with proper exports, `public/assets/city-tileset.png` created

**Step 5: Commit**

```bash
cd /Users/prasiddhaparthsarthy/Desktop/freebird/backend
git add ../goosetown/scripts/generate_city_map.py ../goosetown/data/city.ts ../goosetown/public/assets/city-tileset.png
git commit -m "feat(town): generate 64x48 city map with combined tileset"
```

---

## Task 3: Wire City Map into Frontend Data Pipeline

**Files:**
- Modify: `goosetown/convex/init.ts:5,70-81`

**Step 1: Update the import**

In `goosetown/convex/init.ts`, change line 5:

```typescript
// OLD:
import * as map from '../data/gentle';
// NEW:
import * as map from '../data/city';
```

No other changes needed — `city.ts` exports the same names (`tilesetpath`, `tiledim`, `screenxtiles`, `screenytiles`, `tilesetpxw`, `tilesetpxh`, `bgtiles`, `objmap`, `animatedsprites`, `mapwidth`, `mapheight`) so the rest of `init.ts` lines 70-81 work unchanged.

**Step 2: Verify TypeScript compiles**

Run:
```bash
cd /Users/prasiddhaparthsarthy/Desktop/freebird/goosetown
npx tsc --noEmit
```

Expected: No type errors

**Step 3: Commit**

```bash
cd /Users/prasiddhaparthsarthy/Desktop/freebird/backend
git add ../goosetown/convex/init.ts
git commit -m "feat(town): wire city.ts into map data pipeline"
```

---

## Task 4: Strip Branding and Overhaul App Layout

**Files:**
- Modify: `goosetown/src/App.tsx` (full rewrite)

**Step 1: Rewrite App.tsx**

Replace the entire `App.tsx` with a clean full-screen layout:

```tsx
import Game from './components/Game.tsx';
import { ToastContainer } from 'react-toastify';
import { UserButton, SignedIn, SignedOut } from '@clerk/clerk-react';
import LoginButton from './components/buttons/LoginButton.tsx';
import MusicButton from './components/buttons/MusicButton.tsx';

export default function Home() {
  return (
    <main className="relative flex h-screen w-screen overflow-hidden bg-clay-900 font-body">
      {/* Full-screen game fills everything */}
      <Game />

      {/* Floating controls — top-right overlay on the map */}
      <div className="absolute top-4 right-4 z-10 flex items-center gap-3">
        <MusicButton />
        <SignedIn>
          <UserButton afterSignOutUrl="/" />
        </SignedIn>
        <SignedOut>
          <LoginButton />
        </SignedOut>
      </div>

      <ToastContainer position="bottom-right" autoClose={2000} closeOnClick theme="dark" />
    </main>
  );
}
```

What's removed:
- `a16zImg`, `convexImg`, `starImg`, `helpImg` imports
- `ReactModal` help modal (all a16z-specific text)
- `PoweredByConvex` component
- `InteractButton`, `FreezeButton`, `Button` imports
- `game-background` CSS class usage
- `"AI Town"` title heading
- Footer with a16z/Convex links and Star button
- `game-title` heading with gradient text

What's kept:
- Clerk auth (`UserButton`, `SignedIn`, `SignedOut`, `LoginButton`)
- `MusicButton` (floating overlay)
- `ToastContainer`
- `Game` component

**Step 2: Verify no broken imports**

Run:
```bash
cd /Users/prasiddhaparthsarthy/Desktop/freebird/goosetown
npx tsc --noEmit
```

**Step 3: Commit**

```bash
cd /Users/prasiddhaparthsarthy/Desktop/freebird/backend
git add ../goosetown/src/App.tsx
git commit -m "feat(town): strip branding, full-screen layout"
```

---

## Task 5: Overhaul Game.tsx Layout

**Files:**
- Modify: `goosetown/src/components/Game.tsx:42-84`

**Step 1: Replace the layout JSX**

The current layout (lines 42-84) uses `max-w-[1400px]`, `game-frame`, and fixed grid rows. Replace with a full-screen flex layout:

```tsx
  return (
    <>
      {SHOW_DEBUG_UI && <DebugTimeManager timeManager={timeManager} width={200} height={100} />}
      <div className="flex w-full h-full">
        {/* Map area — fills remaining space */}
        <div className="relative flex-1 overflow-hidden bg-brown-900" ref={gameWrapperRef}>
          <div className="absolute inset-0">
            <Stage width={width} height={height} options={{ backgroundColor: 0x7ab5ff }}>
              <ConvexProvider client={convex}>
                <PixiGame
                  game={game}
                  worldId={worldId}
                  engineId={engineId}
                  width={width}
                  height={height}
                  historicalTime={historicalTime}
                  setSelectedElement={setSelectedElement}
                />
              </ConvexProvider>
            </Stage>
          </div>
        </div>
        {/* Sidebar — fixed width */}
        <div
          className="flex flex-col overflow-y-auto shrink-0 w-80 px-4 py-6 border-l border-clay-700 bg-clay-900 text-brown-100"
          ref={scrollViewRef}
        >
          <PlayerDetails
            worldId={worldId}
            engineId={engineId}
            game={game}
            playerId={selectedElement?.id}
            setSelectedElement={setSelectedElement}
            scrollViewRef={scrollViewRef}
          />
        </div>
      </div>
    </>
  );
```

What changed:
- Removed `max-w-[1400px]` cap
- Removed `game-frame` CSS class (the 36-48px decorative border)
- Removed `min-h-[480px]`
- Changed from CSS grid to flexbox (`flex w-full h-full`)
- Map area: `flex-1` fills all available space
- Sidebar: `w-80` (320px) instead of `lg:w-96` (384px), with `border-l border-clay-700` instead of `border-brown-900`
- Changed sidebar bg from `bg-brown-800` to `bg-clay-900` for darker look
- Removed mobile-first grid-rows stacking (map + sidebar are always side-by-side)

**Step 2: Verify layout compiles**

Run:
```bash
cd /Users/prasiddhaparthsarthy/Desktop/freebird/goosetown
npx tsc --noEmit
```

**Step 3: Commit**

```bash
cd /Users/prasiddhaparthsarthy/Desktop/freebird/backend
git add ../goosetown/src/components/Game.tsx
git commit -m "feat(town): full-screen map layout with sidebar"
```

---

## Task 6: Adjust Viewport Zoom for 64x48 Map

**Files:**
- Modify: `goosetown/src/components/PixiViewport.tsx:39-44`

**Step 1: Update zoom bounds**

The current zoom formula (line 42):
```typescript
minScale: (1.04 * props.screenWidth) / (props.worldWidth / 2),
```

For the old map (48x76 tiles), `worldWidth = 1536px`, minScale showed ~half the world.
For the new map (64x48 tiles), `worldWidth = 2048px`. We want to be able to see the full map when zoomed out.

Change lines 39-44:

```typescript
      .clamp({ direction: 'all', underflow: 'center' })
      .setZoom(-10)
      .clampZoom({
        minScale: Math.max(0.5, (0.9 * props.screenWidth) / props.worldWidth),
        maxScale: 3.0,
      });
```

This ensures:
- Min zoom shows the full map width (90% of screen fills the world)
- Floor of 0.5 prevents zooming out too far on wide monitors
- Max zoom stays at 3x

**Step 2: Commit**

```bash
cd /Users/prasiddhaparthsarthy/Desktop/freebird/backend
git add ../goosetown/src/components/PixiViewport.tsx
git commit -m "feat(town): adjust viewport zoom for 64x48 city map"
```

---

## Task 7: Clean Up PixiStaticMap Animated Sprites

**Files:**
- Modify: `goosetown/src/components/PixiStaticMap.tsx:4-8,68-106`

**Step 1: Remove hardcoded animation imports**

The city map has `animatedsprites: []`. The animation imports (lines 4-8) and the animation rendering logic (lines 68-106) reference gentle map-specific spritesheets (windmill, waterfall, campfire). Since the city map has no animated sprites, these are dead code.

Remove the imports (lines 4-8):
```typescript
// DELETE these lines:
import * as campfire from '../../data/animations/campfire.json';
import * as gentlesparkle from '../../data/animations/gentlesparkle.json';
import * as gentlewaterfall from '../../data/animations/gentlewaterfall.json';
import * as gentlesplash from '../../data/animations/gentlesplash.json';
import * as windmill from '../../data/animations/windmill.json';
```

Remove the `animations` object (lines 10-23).

Remove the animated sprite rendering block (lines 68-106) — the `spritesBySheet` loop. Keep only if `map.animatedSprites.length > 0` as a guard:

```typescript
    // Animated sprites (skip if none)
    if (map.animatedSprites.length > 0) {
      console.warn('Animated sprites not yet supported for city map');
    }
```

**Step 2: Commit**

```bash
cd /Users/prasiddhaparthsarthy/Desktop/freebird/backend
git add ../goosetown/src/components/PixiStaticMap.tsx
git commit -m "feat(town): remove gentle-map animated sprite imports"
```

---

## Task 8: Update Backend Town Coordinates

**Files:**
- Modify: `backend/core/town_constants.py:11-18,21-85`
- Modify: `backend/tests/unit/services/test_town_simulation.py` (if location names change)

**Step 1: Update TOWN_LOCATIONS**

The city map places locations at these approximate tile coordinates (from the design doc):

```python
TOWN_LOCATIONS: Dict[str, Dict] = {
    "plaza":   {"x": 32.0, "y": 24.0, "label": "Town Plaza"},
    "cafe":    {"x": 12.0, "y": 20.0, "label": "Cafe"},
    "library": {"x": 52.0, "y": 20.0, "label": "Library"},
    "shop":    {"x": 12.0, "y": 36.0, "label": "General Store"},
    "park":    {"x": 48.0, "y": 10.0, "label": "Park"},
    "home":    {"x": 10.0, "y": 8.0,  "label": "Residential"},
    "workshop":{"x": 48.0, "y": 36.0, "label": "Workshop"},
}
```

**Step 2: Update DEFAULT_CHARACTERS spawn positions**

Update spawn coordinates to be near each character's home location on the new map:

```python
DEFAULT_CHARACTERS: List[Dict] = [
    {
        "name": "Lucky",
        "agent_name": "lucky",
        "character": "f1",
        "identity": (
            "Lucky is always happy and curious, and he loves cheese. He spends "
            "most of his time reading about the history of science and traveling "
            "through the galaxy on whatever ship will take him."
        ),
        "plan": "You want to hear all the gossip.",
        "spawn": {"x": 14.0, "y": 20.0},
        "home": "cafe",
    },
    {
        "name": "Bob",
        "agent_name": "bob",
        "character": "f4",
        "identity": (
            "Bob is always grumpy and he loves trees. He spends most of his time "
            "gardening by himself. When spoken to he'll respond but try and get "
            "out of the conversation as quickly as possible."
        ),
        "plan": "You want to avoid people as much as possible.",
        "spawn": {"x": 14.0, "y": 36.0},
        "home": "shop",
    },
    {
        "name": "Stella",
        "agent_name": "stella",
        "character": "f6",
        "identity": (
            "Stella can never be trusted. She tries to trick people all the time. "
            "She's incredibly charming and not afraid to use her charm."
        ),
        "plan": "You want to take advantage of others as much as possible.",
        "spawn": {"x": 12.0, "y": 8.0},
        "home": "home",
    },
    {
        "name": "Alice",
        "agent_name": "alice",
        "character": "f3",
        "identity": (
            "Alice is a famous scientist. She is smarter than everyone else and "
            "has discovered mysteries of the universe no one else can understand."
        ),
        "plan": "You want to figure out how the world works.",
        "spawn": {"x": 54.0, "y": 20.0},
        "home": "library",
    },
    {
        "name": "Pete",
        "agent_name": "pete",
        "character": "f7",
        "identity": (
            "Pete is deeply religious and sees the hand of god or of the work of "
            "the devil everywhere. He can't have a conversation without bringing "
            "up his deep faith."
        ),
        "plan": "You want to convert everyone to your religion.",
        "spawn": {"x": 34.0, "y": 24.0},
        "home": "plaza",
    },
]
```

**Step 3: Update the test if needed**

Check `tests/unit/services/test_town_simulation.py:11-16`. The test checks for these location keys:
```python
assert "home" in TOWN_LOCATIONS
assert "cafe" in TOWN_LOCATIONS
assert "plaza" in TOWN_LOCATIONS
assert "library" in TOWN_LOCATIONS
assert "park" in TOWN_LOCATIONS
assert "shop" in TOWN_LOCATIONS
```

All existing keys are preserved. The new `"workshop"` key is added but the test doesn't need to assert it (no existing test checks for it). No test changes needed.

**Step 4: Run backend tests**

Run:
```bash
cd /Users/prasiddhaparthsarthy/Desktop/freebird/backend
./run_tests.sh
```

Expected: All tests pass (the coordinate values don't matter to tests, only the keys and types)

**Step 5: Commit**

```bash
cd /Users/prasiddhaparthsarthy/Desktop/freebird/backend
git add core/town_constants.py
git commit -m "feat(town): update locations and spawns for 64x48 city map"
```

---

## Task 9: Visual Verification and Tile Index Tuning

**Files:**
- Possibly modify: `goosetown/scripts/generate_city_map.py` (tile index adjustments)
- Possibly modify: `goosetown/data/city.ts` (regenerated)

This task is iterative. The tile indices in Task 2 are educated guesses. We need to visually verify and tune them.

**Step 1: Start the dev server**

Run:
```bash
cd /Users/prasiddhaparthsarthy/Desktop/freebird
./start_dev.sh
```

**Step 2: Open in browser and take screenshot**

Use Playwright to navigate to `localhost:5173` (or whatever port Vite uses) and screenshot the map.

**Step 3: Inspect the tileset**

Open `goosetown/public/assets/city-tileset.png` in an image viewer. Each tile is 32x32px. Count tiles left-to-right, top-to-bottom to find the correct indices for:
- Grass (should be the most common tile)
- Stone/cobblestone path
- Building walls/roofs
- Trees
- Water
- Decorations

**Step 4: Update tile palette constants in the script**

Adjust the tile index constants in `generate_city_map.py` to match the actual tileset content. Regenerate:

```bash
cd /Users/prasiddhaparthsarthy/Desktop/freebird/goosetown
python scripts/generate_city_map.py
```

**Step 5: Iterate until the map looks correct**

Reload the browser and verify:
- Green grass base layer visible
- Stone paths connecting locations
- Building rectangles visible at correct positions
- Trees along borders and in park
- No visual artifacts or wrong tiles

**Step 6: Run all tests**

```bash
cd /Users/prasiddhaparthsarthy/Desktop/freebird/backend
./run_tests.sh
```

**Step 7: Final commit**

```bash
cd /Users/prasiddhaparthsarthy/Desktop/freebird/backend
git add -A
git commit -m "feat(town): tune city map tile indices after visual verification"
```

---

## Task 10: Push and Deploy

**Step 1: Push to main**

```bash
cd /Users/prasiddhaparthsarthy/Desktop/freebird/backend
git push origin main
```

**Step 2: Monitor CI/CD**

```bash
gh run list --repo Isol8AI/backend --limit 1
gh run watch <run-id> --repo Isol8AI/backend --exit-status
```

**Step 3: Verify on dev.town.isol8.co**

Use Playwright to:
1. Navigate to `dev.town.isol8.co`
2. Screenshot the full page
3. Verify: full-screen map, no branding, sidebar visible, agents walking
4. Check console for errors

---

## Summary of All Files Changed

| File | Action | Description |
|------|--------|-------------|
| `goosetown/scripts/generate_city_map.py` | Create | Python script: combines tilesets, generates tile arrays |
| `goosetown/public/assets/city-tileset.png` | Create | Combined tileset (512x768px) |
| `goosetown/data/city.ts` | Create | Generated city map data module |
| `goosetown/convex/init.ts` | Modify | Import city.ts instead of gentle.js |
| `goosetown/src/App.tsx` | Modify | Strip branding, full-screen layout |
| `goosetown/src/components/Game.tsx` | Modify | Remove constraints, flex layout |
| `goosetown/src/components/PixiViewport.tsx` | Modify | Adjust zoom for 64x48 |
| `goosetown/src/components/PixiStaticMap.tsx` | Modify | Remove gentle-specific animation imports |
| `backend/core/town_constants.py` | Modify | Update coordinates for new map |

## What Does NOT Change
- Agent logic, simulation tick loop, decision engine
- WebSocket push, ManagementApiClient
- Database models (town_agents, town_state, etc.)
- Character sprites (f1-f8)
- Clerk authentication flow
- `worldMap.ts` type definitions
- `serverGame.ts` hook
- `PixiGame.tsx` component (already generic)
- `Player.tsx` component
