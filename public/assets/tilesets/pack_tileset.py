#!/usr/bin/env python3
"""
Pack individual tile/object PNGs into a single tileset PNG for Tiled.

Output:
  - town-v2-tileset.png  (512px wide, 32px grid)
  - tileset_manifest.json (tile ID -> name/category mapping)
"""

import json
import math
import os
from PIL import Image

TILE = 32
COLS = 16  # 512 / 32
SHEET_W = COLS * TILE
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def ceil_to_tile(px):
    """Round up to the next multiple of TILE."""
    return math.ceil(px / TILE) * TILE


def extract_wang_tiles(path):
    """Extract 16 individual 32x32 tiles from a 128x128 Wang tileset."""
    img = Image.open(path)
    tiles = []
    for row in range(4):
        for col in range(4):
            tile = img.crop((col * TILE, row * TILE, (col + 1) * TILE, (row + 1) * TILE))
            tiles.append(tile)
    return tiles


def main():
    os.chdir(SCRIPT_DIR)

    manifest = {}
    tile_id = 0

    # --- Phase 1: Calculate layout ---

    # Wang tilesets: each occupies 4 rows (16 tiles = 4x4, but placed in a 16-wide sheet
    # they take 1 row of 16. However the spec says Row 0, Row 4, Row 8 -- so 4 rows each
    # with the 16 tiles in the first row and rows 1-3 empty).
    # Actually re-reading: "Row 0 ... tiles 0-15" means tile IDs 0-15 which at 16 cols wide
    # is exactly 1 row. But the spec says Row 0, Row 4, Row 8 -- meaning rows 1-3 and 5-7
    # are intentionally left empty (reserved for future expansion or visual grouping).

    wang_sets = [
        ("ts_water_shore.png", "wang_water_shore", 0),   # start at row 0
        ("ts_shore_grass.png", "wang_shore_grass", 4),    # start at row 4
        ("ts_grass_road.png",  "wang_grass_road",  8),    # start at row 8
    ]

    terrain_row = 12  # Row 12 for standalone terrain tiles
    terrain_files = [f"terrain_tile_{i}.png" for i in range(6)]

    # Objects start after terrain row (row 13)
    objects_start_row = terrain_row + 1

    objects = [
        ("fountain.png",        "fountain",        96,  96),
        ("tree.png",            "tree",            64,  64),
        ("townhouse.png",       "townhouse",       96, 128),
        ("cafe.png",            "cafe",           128,  96),
        ("library.png",         "library",        160, 128),
        ("activity_center.png", "activity_center", 160, 128),
        ("apartment.png",       "apartment",      128, 160),
        ("bridge.png",          "bridge",          96,  64),
        ("bench.png",           "bench",           48,  32),
        ("lamp.png",            "lamp",            32,  64),
        ("bush.png",            "bush",            32,  32),
    ]

    # Calculate how many rows objects need
    current_col = 0
    current_row = objects_start_row
    max_row_height = 0  # in tiles
    object_placements = []

    for filename, name, w, h in objects:
        w_tiles = math.ceil(w / TILE)
        h_tiles = math.ceil(h / TILE)

        # Check if object fits in current row
        if current_col + w_tiles > COLS:
            # Move to next row block
            current_row += max_row_height
            current_col = 0
            max_row_height = 0

        object_placements.append((filename, name, current_col, current_row, w_tiles, h_tiles))
        current_col += w_tiles
        max_row_height = max(max_row_height, h_tiles)

    total_rows = current_row + max_row_height
    sheet_h = total_rows * TILE

    print(f"Tileset dimensions: {SHEET_W}x{sheet_h} ({COLS}x{total_rows} tiles)")

    # --- Phase 2: Create the image ---
    sheet = Image.new("RGBA", (SHEET_W, sheet_h), (0, 0, 0, 0))

    # Place Wang tilesets
    for filename, category, start_row in wang_sets:
        tiles = extract_wang_tiles(os.path.join(SCRIPT_DIR, filename))
        row_y = start_row * TILE
        for i, tile in enumerate(tiles):
            col = i % COLS
            x = col * TILE
            y = row_y + (i // COLS) * TILE
            sheet.paste(tile, (x, y))
            tid = start_row * COLS + i
            manifest[str(tid)] = {
                "name": f"{category}_{i}",
                "category": category,
                "source": filename,
                "index": i,
            }
        print(f"  Placed {filename} -> row {start_row}, tile IDs {start_row * COLS}-{start_row * COLS + 15}")

    # Place terrain tiles
    for i, tf in enumerate(terrain_files):
        path = os.path.join(SCRIPT_DIR, tf)
        if not os.path.exists(path):
            print(f"  WARNING: {tf} not found, skipping")
            continue
        tile = Image.open(path)
        col = i
        x = col * TILE
        y = terrain_row * TILE
        sheet.paste(tile, (x, y))
        tid = terrain_row * COLS + i
        manifest[str(tid)] = {
            "name": tf.replace(".png", ""),
            "category": "terrain",
            "source": tf,
            "index": i,
        }
    print(f"  Placed terrain tiles -> row {terrain_row}, tile IDs {terrain_row * COLS}-{terrain_row * COLS + len(terrain_files) - 1}")

    # Place objects
    for filename, name, col, row, w_tiles, h_tiles in object_placements:
        path = os.path.join(SCRIPT_DIR, filename)
        if not os.path.exists(path):
            print(f"  WARNING: {filename} not found, skipping")
            continue
        obj_img = Image.open(path)

        # Paste the object at the grid position (top-left aligned within its cell block)
        x = col * TILE
        y = row * TILE
        sheet.paste(obj_img, (x, y), obj_img)

        # Record each 32x32 cell that this object occupies
        first_tid = row * COLS + col
        cell_ids = []
        for dy in range(h_tiles):
            for dx in range(w_tiles):
                tid = (row + dy) * COLS + (col + dx)
                cell_ids.append(tid)

        manifest[str(first_tid)] = {
            "name": name,
            "category": "object",
            "source": filename,
            "width_tiles": w_tiles,
            "height_tiles": h_tiles,
            "grid_col": col,
            "grid_row": row,
            "tile_ids": cell_ids,
        }
        print(f"  Placed {filename} ({w_tiles}x{h_tiles} tiles) at col={col}, row={row}, first tile ID={first_tid}")

    # --- Phase 3: Save ---
    out_png = os.path.join(SCRIPT_DIR, "town-v2-tileset.png")
    sheet.save(out_png)
    print(f"\nSaved: {out_png}")

    out_json = os.path.join(SCRIPT_DIR, "tileset_manifest.json")
    with open(out_json, "w") as f:
        json.dump({
            "tile_size": TILE,
            "columns": COLS,
            "image_width": SHEET_W,
            "image_height": sheet_h,
            "total_rows": total_rows,
            "tiles": manifest,
        }, f, indent=2)
    print(f"Saved: {out_json}")


if __name__ == "__main__":
    main()
