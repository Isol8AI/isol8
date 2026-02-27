# GooseTown Map & Frontend Overhaul

## Problem

The current GooseTown frontend uses the default a16z AI Town map — a small pastoral scene (45x32 tiles) with windmills and a lake. It renders as a cramped rectangle on the page with an "AI Town" title bar, a16z/Convex branding, and a footer bar eating screen space. This needs to become a proper pixel art city where Isol8 agents live.

## Design Decisions

### Frontend Layout
- Map fills the left ~75% of the viewport at full height (no max-width cap, no title bar, no footer)
- Persistent sidebar on the right (~350px) with: Isol8 branding, selected agent details, agent list
- Floating controls (music, help, zoom) as small overlay buttons on the map
- Clerk auth moves to the sidebar header
- Remove all a16z/Convex branding, `game-frame` border, `game-background` wallpaper

### City Map
- **Dimensions:** 64x48 tiles at 32px = 2048x1536px world (2x current map)
- **Tilesets:** `magecity.png` (city buildings, already in assets) + `rpg-tileset.png` (terrain, trees, water, already in assets)
- **Generation:** Programmatically generate tile data arrays via Python script. Output as TypeScript module matching existing `gentle.js` format.

### City Layout (64x48 grid)
```
+----------------------------------------------------------+
|  [Residential]    [Street]    [Park]                     |
|   Houses x5        Main St     Trees, benches, fountain  |
|                      |                                    |
|  [Cafe]           [Plaza]     [Library]                  |
|   Tables,          Town        Bookshelves,              |
|   counter          Square      reading area              |
|                      |                                    |
|  [General Store]  [Street]    [Workshop]                 |
|   Shelves,         Side St     (future expansion)        |
|   goods                                                  |
+----------------------------------------------------------+
```

- Streets as stone/cobblestone paths connecting all locations
- Grass base layer everywhere, stone for paths
- Buildings as 4x3 or 5x4 tile structures with walls, roofs, doors
- Decorations: trees, flowers, lampposts, benches along streets
- All locations have walkable interiors/entrances

### Locations
| Location | Purpose | Approx Position |
|----------|---------|-----------------|
| Town Plaza | Central gathering, events | Center (32, 24) |
| Cafe | Social hangout | West-center (12, 20) |
| Library | Learning, research | East-center (52, 20) |
| General Store | Shopping, trading | West-south (12, 36) |
| Park | Relaxation, nature | East-north (48, 10) |
| Residential | Agent homes | Northwest (10, 8) |
| Workshop | Building/crafting (future) | Southeast (48, 36) |

### Backend Sync
- Update `TOWN_LOCATIONS` in `core/town_constants.py` to match new map coordinates
- Update `DEFAULT_CHARACTERS` spawn positions to be near their home locations
- No changes to simulation loop, WebSocket push, or database models

## Files Changed

### Frontend (goosetown/)
- `src/App.tsx` — Remove title bar, footer, branding. Full-screen layout.
- `src/components/Game.tsx` — Remove max-width/min-height constraints. Full h-screen map + sidebar.
- `src/components/PixiStaticMap.tsx` — Load new tileset(s), render new map data.
- `src/components/PixiViewport.tsx` — Adjust zoom bounds for 64x48 map.
- `data/city.ts` — New city map data module (replaces gentle.js references).

### Backend (backend/)
- `core/town_constants.py` — Update TOWN_LOCATIONS coordinates and spawn positions.

### New Files
- `goosetown/scripts/generate_city_map.py` — Python script to generate tile data arrays.

## What Does NOT Change
- Agent logic, simulation tick loop, decision engine
- WebSocket push, ManagementApiClient
- Database models (town_agents, town_state, etc.)
- Character sprites (f1-f8)
- Clerk authentication flow

## Success Criteria
- Open `dev.town.isol8.co` and see a full-screen pixel art city
- 5 default agents visible and walking between city locations
- Map is zoomable and pannable
- Sidebar shows agent details when clicked
- No a16z/Convex branding visible
- All existing tests still pass
