#!/usr/bin/env python3
"""
City Map Generator for Goosetown

Combines two tileset PNGs into one composite image and generates a 64x48 tile
city map with background, detail, and object layers.

Usage:
    cd goosetown/scripts
    python generate_city_map.py

Requires: Pillow (pip install Pillow)

Output:
    - goosetown/public/assets/city-tileset.png  (combined tileset)
    - goosetown/data/city.ts                     (map data)
"""

import os
import sys
import math
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    print("ERROR: Pillow is required. Install with: pip install Pillow")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Paths (relative to this script's location)
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent  # goosetown/

RPG_TILESET_PATH = PROJECT_DIR / "public" / "assets" / "rpg-tileset.png"
MAGE_TILESET_PATH = PROJECT_DIR / "public" / "assets" / "magecity.png"
OUTPUT_TILESET_PATH = PROJECT_DIR / "public" / "assets" / "city-tileset.png"
OUTPUT_MAP_PATH = PROJECT_DIR / "data" / "city.ts"

# ---------------------------------------------------------------------------
# Map dimensions
# ---------------------------------------------------------------------------
MAP_W = 64   # tiles wide
MAP_H = 48   # tiles tall
TILE_DIM = 32  # pixels per tile

# ---------------------------------------------------------------------------
# Tileset layout
# ---------------------------------------------------------------------------
# RPG tileset: 1600x1600 = 50 cols x 50 rows (at 32px)
RPG_COLS = 50
RPG_ROWS = 50

# Magecity tileset: 256 wide = 8 cols, height varies (we'll handle it)
MAGE_COLS = 8

# Combined tileset width matches RPG tileset (1600px = 50 tile columns)
COMBINED_COLS = RPG_COLS  # 50


def mc(mage_index: int) -> int:
    """Convert a magecity tile index to a combined-tileset tile index.

    Magecity tiles are laid out in an 8-tile-wide grid. In the combined
    tileset they sit below the RPG tileset (which is 50 rows tall), still
    at their original column positions (0-7) but in combined rows 50+.
    """
    col = mage_index % MAGE_COLS
    row = mage_index // MAGE_COLS
    return col + (RPG_ROWS + row) * COMBINED_COLS


# ---------------------------------------------------------------------------
# Tile palette  (TUNE THESE in task #12)
#
#   RPG tileset indices: col + row*50, range 0-2499
#   Magecity indices: use mc(original_index)
#
# All indices refer to the COMBINED tileset.
# ---------------------------------------------------------------------------

# --- Grass / ground (RPG tileset) ---
GRASS_A = 51    # row 1, col 1  - bright green grass (100,209,76)
GRASS_B = 52    # row 1, col 2  - bright green grass
GRASS_C = 53    # row 1, col 3  - bright green grass
GRASS_D = 54    # row 1, col 4  - bright green grass
GRASS_E = 501   # row 10, col 1 - lighter green variant (158,212,72)
GRASS_F = 502   # row 10, col 2 - lighter green
GRASS_EDGE = 50 # row 1, col 0  - grass edge (105,192,79)

GRASS_TILES = [GRASS_A, GRASS_B, GRASS_C, GRASS_D, GRASS_E, GRASS_F]

# --- Stone / path (RPG tileset rows 30-31, gray stone) ---
STONE_A = 1500  # row 30, col 0  - gray stone (125,129,136)
STONE_B = 1501  # row 30, col 1  - lighter gray (148,162,163)
STONE_C = 1503  # row 30, col 3  - gray
STONE_D = 1550  # row 31, col 0  - gray
STONE_E = 1551  # row 31, col 1  - gray

STONE_TILES = [STONE_A, STONE_B, STONE_C, STONE_D, STONE_E]

# --- Cobblestone / brown stone (RPG tileset rows 30-31, cols 10-13) ---
COBBLE_A = 1510  # row 30, col 10 - tan/brown stone (136,132,111)
COBBLE_B = 1511  # row 30, col 11 - darker brown (84,68,52)
COBBLE_C = 1560  # row 31, col 10
COBBLE_D = 1561  # row 31, col 11

# --- Water (RPG tileset, blue tiles) ---
WATER_A = 58   # row 1, col 8  - blue water (121,154,255)
WATER_B = 59   # row 1, col 9  - blue water
WATER_C = 8    # row 0, col 8  - blue water
WATER_D = 9    # row 0, col 9  - blue water

# --- Trees (RPG tileset, rows 24-26, dark green) ---
# Trees are 2x2 blocks:
#   TOP_LEFT   TOP_RIGHT
#   BOT_LEFT   BOT_RIGHT
TREE_TL = 1252  # row 25, col 2 - dark green (85,141,68)
TREE_TR = 1253  # row 25, col 3 - dark green
TREE_BL = 1302  # row 26, col 2 - darker green (61,108,67)
TREE_BR = 1303  # row 26, col 3 - darker (54,74,76)

# Single-tile tree/bush (smaller)
BUSH = 1200     # row 24, col 0 - dark green (85,141,68)

# --- Building tiles (magecity) ---
# Walls / roofs from magecity tileset
MC_GROUND   = mc(1)    # base ground
MC_WALL_L   = mc(193)  # left wall
MC_WALL_C   = mc(194)  # center wall / fill (most common ground in mage3)
MC_WALL_R   = mc(195)  # right wall
MC_ROOF_TL  = mc(72)   # roof top-left
MC_ROOF_TC  = mc(80)   # roof top-center
MC_ROOF_TR  = mc(88)   # roof top-right
MC_ROOF_ML  = mc(73)   # roof mid-left
MC_ROOF_MC  = mc(81)   # roof mid-center
MC_ROOF_MR  = mc(89)   # roof mid-right
MC_ROOF_BL  = mc(74)   # roof bottom-left
MC_ROOF_BC  = mc(82)   # roof bottom-center
MC_ROOF_BR  = mc(90)   # roof bottom-right
MC_DOOR     = mc(9)    # door/entrance
MC_WINDOW   = mc(346)  # window decoration
MC_EDGE_L   = mc(236)  # edge left
MC_EDGE_R   = mc(238)  # edge right
MC_FENCE_T  = mc(211)  # fence/decoration top
MC_FLOOR_A  = mc(0)    # interior floor
MC_FLOOR_B  = mc(227)  # floor variant

EMPTY = -1  # transparent / no tile


# ===========================================================================
# Image combining
# ===========================================================================

def combine_tilesets():
    """Stack rpg-tileset on top, magecity below, into one combined PNG."""
    print(f"Loading RPG tileset: {RPG_TILESET_PATH}")
    rpg = Image.open(RPG_TILESET_PATH).convert("RGBA")
    print(f"  Size: {rpg.size}")

    print(f"Loading Magecity tileset: {MAGE_TILESET_PATH}")
    mage = Image.open(MAGE_TILESET_PATH).convert("RGBA")
    print(f"  Size: {mage.size}")

    # Calculate combined dimensions
    combined_w = rpg.width  # 1600
    # Round magecity height up to next tile boundary
    mage_tile_rows = math.ceil(mage.height / TILE_DIM)
    mage_padded_h = mage_tile_rows * TILE_DIM
    combined_h = rpg.height + mage_padded_h

    print(f"Combined tileset: {combined_w}x{combined_h} "
          f"({combined_w // TILE_DIM} cols x {combined_h // TILE_DIM} rows)")

    combined = Image.new("RGBA", (combined_w, combined_h), (0, 0, 0, 0))
    combined.paste(rpg, (0, 0))
    combined.paste(mage, (0, rpg.height))

    os.makedirs(OUTPUT_TILESET_PATH.parent, exist_ok=True)
    combined.save(OUTPUT_TILESET_PATH)
    print(f"Saved combined tileset: {OUTPUT_TILESET_PATH}")

    return combined_w, combined_h


# ===========================================================================
# Map generation helpers
# ===========================================================================

def make_layer(default=-1):
    """Create a 64x48 layer: layer[x][y], column-major."""
    return [[default for _ in range(MAP_H)] for _ in range(MAP_W)]


def fill_rect(layer, x1, y1, x2, y2, tile):
    """Fill a rectangle (inclusive) with a single tile value."""
    for x in range(max(0, x1), min(MAP_W, x2 + 1)):
        for y in range(max(0, y1), min(MAP_H, y2 + 1)):
            layer[x][y] = tile


def fill_rect_pattern(layer, x1, y1, x2, y2, tiles):
    """Fill a rectangle with tiles cycling from a list."""
    idx = 0
    for x in range(max(0, x1), min(MAP_W, x2 + 1)):
        for y in range(max(0, y1), min(MAP_H, y2 + 1)):
            layer[x][y] = tiles[idx % len(tiles)]
            idx += 1


def fill_rect_checker(layer, x1, y1, x2, y2, tile_a, tile_b):
    """Fill a rectangle with a checkerboard pattern."""
    for x in range(max(0, x1), min(MAP_W, x2 + 1)):
        for y in range(max(0, y1), min(MAP_H, y2 + 1)):
            layer[x][y] = tile_a if (x + y) % 2 == 0 else tile_b


def place_2x2_tree(layer, x, y):
    """Place a 2x2 tree at (x, y) = top-left corner."""
    if x + 1 < MAP_W and y + 1 < MAP_H:
        layer[x][y] = TREE_TL
        layer[x + 1][y] = TREE_TR
        layer[x][y + 1] = TREE_BL
        layer[x + 1][y + 1] = TREE_BR


def place_building(obj_layer, detail_layer, x1, y1, x2, y2):
    """Place a building footprint: roof on detail, solid collision on obj."""
    w = x2 - x1 + 1
    h = y2 - y1 + 1

    # Object layer: entire building is solid
    fill_rect(obj_layer, x1, y1, x2, y2, MC_WALL_C)

    # Detail layer: roof pattern
    if w >= 3 and h >= 3:
        # Top row
        detail_layer[x1][y1] = MC_ROOF_TL
        detail_layer[x2][y1] = MC_ROOF_TR
        for x in range(x1 + 1, x2):
            detail_layer[x][y1] = MC_ROOF_TC

        # Middle rows
        for y in range(y1 + 1, y2):
            detail_layer[x1][y] = MC_ROOF_ML
            detail_layer[x2][y] = MC_ROOF_MR
            for x in range(x1 + 1, x2):
                detail_layer[x][y] = MC_ROOF_MC

        # Bottom row
        detail_layer[x1][y2] = MC_ROOF_BL
        detail_layer[x2][y2] = MC_ROOF_BR
        for x in range(x1 + 1, x2):
            detail_layer[x][y2] = MC_ROOF_BC

        # Door in bottom-center
        door_x = (x1 + x2) // 2
        detail_layer[door_x][y2] = MC_DOOR
    else:
        # Small building - just fill with wall
        fill_rect(detail_layer, x1, y1, x2, y2, MC_WALL_C)


# ===========================================================================
# Map generation
# ===========================================================================

def generate_city_map():
    """Generate the full city map (64x48) with all layers."""

    # Background layer 0: base terrain (grass)
    bg_base = make_layer(default=GRASS_A)

    # Fill with grass variants for visual interest
    for x in range(MAP_W):
        for y in range(MAP_H):
            # Use a deterministic pseudo-random pattern
            v = (x * 7 + y * 13 + x * y * 3) % len(GRASS_TILES)
            bg_base[x][y] = GRASS_TILES[v]

    # Background layer 1: detail (paths, plazas) -- mostly empty
    bg_detail = make_layer(default=EMPTY)

    # Object layer 0: collision (buildings=solid, trees=solid, -1=walkable)
    obj = make_layer(default=EMPTY)

    # ------------------------------------------------------------------
    # 1. Border: Trees along all 4 edges (2 tiles deep)
    # ------------------------------------------------------------------
    # Top border (y=0-1)
    for x in range(0, MAP_W, 2):
        for y_off in [0]:
            place_2x2_tree(obj, x, y_off)

    # Bottom border (y=46-47)
    for x in range(0, MAP_W, 2):
        place_2x2_tree(obj, x, MAP_H - 2)

    # Left border (x=0-1)
    for y in range(0, MAP_H, 2):
        place_2x2_tree(obj, 0, y)

    # Right border (x=62-63)
    for y in range(0, MAP_H, 2):
        place_2x2_tree(obj, MAP_W - 2, y)

    # ------------------------------------------------------------------
    # 2. Main Street: Vertical stone path at x=30-33, full height
    # ------------------------------------------------------------------
    fill_rect_checker(bg_detail, 30, 2, 33, MAP_H - 3, STONE_A, STONE_B)

    # ------------------------------------------------------------------
    # 3. Cross Street: Horizontal stone path at y=22-25, full width
    # ------------------------------------------------------------------
    fill_rect_checker(bg_detail, 2, 22, MAP_W - 3, 25, STONE_C, STONE_D)

    # ------------------------------------------------------------------
    # 4. Town Plaza: Stone area at center (28-35 x 20-27)
    # ------------------------------------------------------------------
    fill_rect_checker(bg_detail, 28, 20, 35, 27, STONE_B, STONE_E)

    # Plaza border accent (cobblestone ring)
    for x in range(28, 36):
        bg_detail[x][20] = COBBLE_A
        bg_detail[x][27] = COBBLE_C
    for y in range(20, 28):
        bg_detail[28][y] = COBBLE_B
        bg_detail[35][y] = COBBLE_D

    # ------------------------------------------------------------------
    # 5. Residential: 5 houses in northwest (around x=6-18, y=5-13)
    # ------------------------------------------------------------------
    # House 1: x=6-9, y=5-8
    place_building(obj, bg_detail, 6, 5, 9, 8)
    # House 2: x=11-14, y=5-8
    place_building(obj, bg_detail, 11, 5, 14, 8)
    # House 3: x=16-19, y=5-8
    place_building(obj, bg_detail, 16, 5, 19, 8)
    # House 4: x=6-9, y=10-13
    place_building(obj, bg_detail, 6, 10, 9, 13)
    # House 5: x=11-14, y=10-13
    place_building(obj, bg_detail, 11, 10, 14, 13)

    # ------------------------------------------------------------------
    # 6. Cafe: Building at west-center (x=8-12, y=18-21)
    # ------------------------------------------------------------------
    place_building(obj, bg_detail, 8, 18, 12, 21)

    # ------------------------------------------------------------------
    # 7. Library: Building at east-center (x=49-54, y=18-21)
    # ------------------------------------------------------------------
    place_building(obj, bg_detail, 49, 18, 54, 21)

    # ------------------------------------------------------------------
    # 8. General Store: Building at west-south (x=8-12, y=34-37)
    # ------------------------------------------------------------------
    place_building(obj, bg_detail, 8, 34, 12, 37)

    # ------------------------------------------------------------------
    # 9. Workshop: Building at southeast (x=47-51, y=34-37)
    # ------------------------------------------------------------------
    place_building(obj, bg_detail, 47, 34, 51, 37)

    # ------------------------------------------------------------------
    # 10. Park: Trees scattered in east-north (x=42-56, y=5-14)
    # ------------------------------------------------------------------
    park_trees = [
        (42, 5), (44, 7), (46, 5), (48, 9), (50, 6),
        (52, 5), (54, 8), (43, 11), (46, 12), (49, 11),
        (52, 13), (55, 10), (44, 9), (50, 13), (54, 5),
    ]
    for tx, ty in park_trees:
        place_2x2_tree(obj, tx, ty)

    # Also scatter some bushes in the park
    park_bushes = [
        (43, 6), (45, 8), (47, 6), (51, 7), (53, 10),
        (45, 13), (48, 12), (55, 6), (42, 10), (47, 14),
    ]
    for bx, by in park_bushes:
        if 0 <= bx < MAP_W and 0 <= by < MAP_H:
            obj[bx][by] = BUSH

    # ------------------------------------------------------------------
    # 11. Fountain: 2x2 water tiles at plaza center (31-32, 23-24)
    # ------------------------------------------------------------------
    bg_detail[31][23] = WATER_A
    bg_detail[32][23] = WATER_B
    bg_detail[31][24] = WATER_C
    bg_detail[32][24] = WATER_D
    # Fountain is also a collision object (can't walk through water)
    obj[31][23] = WATER_A
    obj[32][23] = WATER_B
    obj[31][24] = WATER_C
    obj[32][24] = WATER_D

    # ------------------------------------------------------------------
    # 12. Street trees: Along Main Street every 6 tiles
    # ------------------------------------------------------------------
    for y in range(4, MAP_H - 4, 6):
        # Skip if overlapping with cross street or plaza
        if 20 <= y <= 27:
            continue
        # Trees on left side of main street (x=28-29)
        place_2x2_tree(obj, 28, y)
        # Trees on right side of main street (x=34-35)
        place_2x2_tree(obj, 34, y)

    # ------------------------------------------------------------------
    # Assemble layers
    # ------------------------------------------------------------------
    bgtiles = [bg_base, bg_detail]   # 2 layers
    objmap = [obj]                   # 1 layer

    return bgtiles, objmap


# ===========================================================================
# TypeScript output
# ===========================================================================

def layer_to_ts(layer):
    """Convert a [x][y] layer to TypeScript array literal string.

    Output format matches gentle.js: each column is a JS array of row values.
    layer[x] is an array of MAP_H values (one per row).
    """
    lines = []
    lines.append("   [")
    for x in range(len(layer)):
        row_vals = " , ".join(str(layer[x][y]) for y in range(len(layer[x])))
        lines.append(f"[ {row_vals} , ],")
    lines.append("],")
    return "\n".join(lines)


def write_city_ts(bgtiles, objmap, tileset_w, tileset_h):
    """Write the city.ts map data file."""
    os.makedirs(OUTPUT_MAP_PATH.parent, exist_ok=True)

    with open(OUTPUT_MAP_PATH, "w") as f:
        f.write('// City map generated by generate_city_map.py\n')
        f.write('\n')
        f.write('export const tilesetpath = "/assets/city-tileset.png"\n')
        f.write(f'export const tiledim = {TILE_DIM}\n')
        f.write(f'export const screenxtiles = {MAP_W}\n')
        f.write(f'export const screenytiles = {MAP_H}\n')
        f.write(f'export const tilesetpxw = {tileset_w}\n')
        f.write(f'export const tilesetpxh = {tileset_h}\n')
        f.write('\n')

        # bgtiles: 2 layers
        f.write('export const bgtiles = [\n')
        for layer in bgtiles:
            f.write(layer_to_ts(layer))
            f.write('\n')
        f.write('];\n')
        f.write('\n')

        # objmap: 1 layer
        f.write('export const objmap = [\n')
        for layer in objmap:
            f.write(layer_to_ts(layer))
            f.write('\n')
        f.write('];\n')
        f.write('\n')

        # animatedsprites: empty
        f.write('export const animatedsprites: any[] = []\n')
        f.write('\n')

        # mapwidth / mapheight
        f.write('export const mapwidth = bgtiles[0].length   // 64\n')
        f.write('export const mapheight = bgtiles[0][0].length  // 48\n')

    print(f"Saved map data: {OUTPUT_MAP_PATH}")


# ===========================================================================
# Main
# ===========================================================================

def main():
    print("=" * 60)
    print("City Map Generator")
    print("=" * 60)
    print()

    # 1. Combine tilesets
    tileset_w, tileset_h = combine_tilesets()
    print()

    # 2. Generate map
    print("Generating 64x48 city map...")
    bgtiles, objmap = generate_city_map()
    print(f"  bgtiles: {len(bgtiles)} layers, each {len(bgtiles[0])}x{len(bgtiles[0][0])}")
    print(f"  objmap:  {len(objmap)} layers, each {len(objmap[0])}x{len(objmap[0][0])}")
    print()

    # 3. Write TypeScript output
    write_city_ts(bgtiles, objmap, tileset_w, tileset_h)
    print()

    # 4. Summary
    print("=" * 60)
    print("Done!")
    print(f"  Combined tileset: {OUTPUT_TILESET_PATH}")
    print(f"  Map data:         {OUTPUT_MAP_PATH}")
    print(f"  Tileset size:     {tileset_w}x{tileset_h} px")
    print(f"  Tileset grid:     {tileset_w // TILE_DIM}x{tileset_h // TILE_DIM} tiles")
    print(f"  Map size:         {MAP_W}x{MAP_H} tiles")
    print(f"  BG layers:        {len(bgtiles)}")
    print(f"  OBJ layers:       {len(objmap)}")
    print("=" * 60)


if __name__ == "__main__":
    main()
