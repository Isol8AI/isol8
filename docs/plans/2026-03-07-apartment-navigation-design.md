# Apartment Interior Navigation Design

## Goal

Agents walk between named spots (desks, couches, beds) inside their apartment, using the same simulation loop as town movement. The apartment is a per-user 12x8 tile grid. Agents spawn in the apartment and can transition between apartment and town seamlessly.

## Architecture

Two coordinate spaces share one simulation loop:
- **Town**: 96x64 grid, shared by all agents, existing pathfinding
- **Apartment**: 12x8 grid, per-user (but identical layout), new pathfinding on same A* algorithm

A `location_context` field on `town_state` ("apartment" or "town") determines which coordinate space an agent is in and which pathfinder to use.

## Data Model

### New column on `town_state`

```
location_context = Column(String(20), default="apartment")
```

- `"apartment"` — positions are on the 12x8 apartment grid
- `"town"` — positions are on the 96x64 town grid

### Spawn state

Agents opt in with:
- `location_context = "apartment"`
- `location_state = "active"`
- `position_x/y` = bedroom spot coordinates
- `current_location = "bedroom"`

## Apartment Layout

### Grid

12x8 tiles at 32px, matching the pixel art apartment image (384x256, scaled to 1536x1024).

### Rooms and Spots

Spots are named coordinates agents can target directly. The simulation resolves a destination by checking `APARTMENT_SPOTS` and `TOWN_LOCATIONS`.

```python
APARTMENT_ROOMS = {
    "office":      {"label": "Office",      "spots": [...]},
    "kitchen":     {"label": "Kitchen",     "spots": [...]},
    "living_room": {"label": "Living Room", "spots": [...]},
    "bedroom":     {"label": "Bedroom",     "spots": [...]},
}

APARTMENT_SPOTS = {
    "desk_1":    {"room": "office",      "x": 2, "y": 1, "label": "Left desk"},
    "desk_2":    {"room": "office",      "x": 4, "y": 1, "label": "Right desk"},
    "desk_3":    {"room": "office",      "x": 3, "y": 2, "label": "Middle desk"},
    "couch_1":   {"room": "living_room", "x": 2, "y": 6, "label": "Couch left"},
    "couch_2":   {"room": "living_room", "x": 3, "y": 6, "label": "Couch right"},
    "tv_chair":  {"room": "living_room", "x": 2, "y": 5, "label": "TV chair"},
    "bed_1":     {"room": "bedroom",     "x": 9, "y": 6, "label": "Left bed"},
    "bed_2":     {"room": "bedroom",     "x": 10,"y": 6, "label": "Right bed"},
    "table":     {"room": "kitchen",     "x": 8, "y": 2, "label": "Kitchen table"},
    "bookshelf": {"room": "kitchen",     "x": 10,"y": 1, "label": "Bookshelf"},
    "exit":      {"room": None,          "x": 6, "y": 7, "label": "Exit"},
    # ... exact coords TBD from walkability analysis of apartment image
}
```

### Walkability

A 12x8 grid (0=walkable, 1=blocked) derived from the apartment pixel art. Walls and furniture are blocked; floors, hallway, and doorways are walkable. Cached at module level like the town objmap.

### Agent awareness

On WebSocket connect, the `town_event connected` payload includes available apartment spots so the agent knows where it can go:

```json
{
  "type": "town_event",
  "event": "connected",
  "apartment": {
    "spots": {
      "desk_1": {"room": "office", "label": "Left desk"},
      "desk_2": {"room": "office", "label": "Right desk"},
      "couch_1": {"room": "living_room", "label": "Couch left"},
      ...
    }
  }
}
```

## Simulation

### Tick loop changes

Same loop, branch on `location_context`:

```
for agent in active_agents:
    if agent.location_context == "apartment":
        use find_apartment_path() for movement
    else:
        use find_path() for movement (existing)
```

### Destination resolution

When agent sends `{"action": "move", "destination": "desk_1"}`:

1. Check if destination is in `APARTMENT_SPOTS` — if yes, it's an apartment destination
2. Check if destination is in `TOWN_LOCATIONS` — if yes, it's a town destination
3. Neither — reject with error

### Transition: Apartment to Town

Agent sends `{"action": "move", "destination": "cafe"}` while in apartment:

1. Simulation sets intermediate target: pathfind to `exit` spot (6, 7) on apartment grid
2. Store the final town destination (e.g. "cafe") in a pending field
3. On arrival at exit:
   - Set `location_context = "town"`
   - Set position to residential town coords (53, 40)
   - Set `target_x/y` to cafe's town coords
   - Clear pending destination
4. Agent disappears from apartment view, appears on town map at residential, walks to cafe

### Transition: Town to Apartment

Agent sends `{"action": "move", "destination": "bed_1"}` while in town:

1. Simulation sets intermediate target: pathfind to residential coords (53, 40) on town grid
2. Store the final apartment destination (e.g. "bed_1") in a pending field
3. On arrival at residential:
   - Set `location_context = "apartment"`
   - Set position to exit tile (6, 7)
   - Set `target_x/y` to bed_1's apartment coords
   - Clear pending destination
4. Agent disappears from town map, appears in apartment view at exit, walks to bed

### Going home / sleeping

`going_home` state walks agent to residential on town grid, transitions to apartment, walks to bedroom spot, then sets `location_state = "sleeping"`.

### Pending destination storage

Add `pending_destination` to the in-memory simulation state (not DB — it's transient, only lives during a multi-step move). Stored in a dict on the simulation instance: `self._pending_destinations: dict[UUID, str] = {}`.

## API Changes

### `GET /town/state`

Filter: only include agents where `location_context = "town"`. No change to response shape.

### `GET /town/apartment`

Returns all of the current user's agents regardless of location_context:

```json
{
  "agents": [
    {
      "agent_name": "peeps",
      "display_name": "Peeps",
      "character": "c12",
      "location_context": "apartment",
      "position": {"x": 9, "y": 6},
      "speed": 0.6,
      "facing": {"dx": 1, "dy": 0},
      "current_spot": "bed_1",
      "current_activity": "sleeping"
    },
    {
      "agent_name": "claude-test",
      "display_name": "Claude",
      "character": "c6",
      "location_context": "town",
      "position": {"x": 47, "y": 48},
      "speed": 0.6,
      "facing": {"dx": 0, "dy": 1},
      "current_spot": null,
      "current_activity": "walking"
    }
  ]
}
```

## Frontend Changes

### Apartment page (`/ai-town/apartment`)

- Replace static image with PixiJS canvas
- Use `apartment.png` as background sprite (same as town uses `town-background.png`)
- Render user's agents (where `location_context = "apartment"`) walking on 12x8 grid
- Reuse `Player` component, lerp interpolation, `PixiViewport`
- Poll `GET /town/apartment` for agent positions

### Sidebar

- Lists all user's agents from `/town/apartment` response
- Each agent shows name, location, activity
- Clicking an agent:
  - If `location_context = "apartment"` — navigate to apartment view, highlight agent
  - If `location_context = "town"` — navigate to town view, pan to agent

### Town map

- `GET /town/state` already filters to town-only agents (backend change)
- No frontend filtering needed

## Pathfinding

### New: `find_apartment_path()`

Same A* algorithm as `find_path()` but operates on the 12x8 apartment objmap instead of the 96x64 town objmap. Implemented as a parameter or wrapper:

```python
def find_path(start_x, start_y, end_x, end_y, context="town"):
    if context == "apartment":
        objmap = get_apartment_objmap()
    else:
        objmap = get_objmap()
    # ... same A* logic
```

### Apartment objmap

12x8 grid derived from pixel art analysis. Cached at module level. Stored in `data/apartment_map.json` or hardcoded in `apartment_constants.py`.

## DB Migration

Single column addition — no schema migration tool, just add the column with a default:

```sql
ALTER TABLE town_state ADD COLUMN location_context VARCHAR(20) DEFAULT 'apartment';
```

Existing agents get `"apartment"` which is correct (they should be in their apartment until they connect and decide to go somewhere).
