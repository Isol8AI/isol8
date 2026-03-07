# Apartment Interior Navigation Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Agents walk between named spots inside a 12x8 apartment grid, with seamless transitions between apartment and town coordinate spaces.

**Architecture:** Two coordinate spaces (town 96x64, apartment 12x8) share one simulation loop. A `location_context` field on `town_state` determines which pathfinder to use. Cross-context moves use a pending destination pattern: walk to exit/residential, flip context, walk to final target.

**Tech Stack:** Python/FastAPI, SQLAlchemy, A* pathfinding, PixiJS (frontend)

---

### Task 1: Add `location_context` column to TownState model

**Files:**
- Modify: `models/town.py:94` (add column after `location_state`)

**Step 1: Add the column**

In `models/town.py`, add after line 94 (`location_state = Column(...)`):

```python
location_context = Column(String(20), default="apartment")
```

**Step 2: Update `get_town_state()` to include `location_context`**

In `core/services/town_service.py:103-131`, add `location_context` to the dict returned for each agent. After `"location_state": state.location_state,` (around line 119), add:

```python
"location_context": state.location_context,
```

**Step 3: Run the DB migration SQL**

```sql
ALTER TABLE town_state ADD COLUMN location_context VARCHAR(20) DEFAULT 'apartment';
```

**Step 4: Verify**

Run: `cd /Users/prasiddhaparthsarthy/Desktop/freebird/backend && python -m pytest tests/unit/models/test_town.py -v`
Expected: PASS

---

### Task 2: Create apartment constants

**Files:**
- Create: `core/apartment_constants.py`

**Step 1: Create the constants file**

```python
"""Constants for apartment interior navigation.

12x8 tile grid (384x256 pixels at 32px/tile, displayed at 4x = 1536x1024).
"""

from typing import Dict, List

# Apartment grid dimensions
APARTMENT_WIDTH = 12
APARTMENT_HEIGHT = 8

# Room definitions
APARTMENT_ROOMS: Dict[str, Dict] = {
    "office": {"label": "Office", "description": "Work area with desks"},
    "kitchen": {"label": "Kitchen", "description": "Kitchen and dining area"},
    "living_room": {"label": "Living Room", "description": "Couches and TV"},
    "bedroom": {"label": "Bedroom", "description": "Beds for sleeping"},
}

# Named spots agents can target directly
APARTMENT_SPOTS: Dict[str, Dict] = {
    "desk_1": {"room": "office", "x": 2, "y": 1, "label": "Left desk"},
    "desk_2": {"room": "office", "x": 4, "y": 1, "label": "Right desk"},
    "desk_3": {"room": "office", "x": 3, "y": 2, "label": "Middle desk"},
    "couch_1": {"room": "living_room", "x": 2, "y": 6, "label": "Couch left"},
    "couch_2": {"room": "living_room", "x": 3, "y": 6, "label": "Couch right"},
    "tv_chair": {"room": "living_room", "x": 2, "y": 5, "label": "TV chair"},
    "bed_1": {"room": "bedroom", "x": 9, "y": 6, "label": "Left bed"},
    "bed_2": {"room": "bedroom", "x": 10, "y": 6, "label": "Right bed"},
    "table": {"room": "kitchen", "x": 8, "y": 2, "label": "Kitchen table"},
    "bookshelf": {"room": "kitchen", "x": 10, "y": 1, "label": "Bookshelf"},
    "exit": {"room": None, "x": 6, "y": 7, "label": "Exit"},
}

# Walkability grid: 0 = walkable, 1 = blocked
# Row-major: APARTMENT_OBJMAP[y][x]
# Derived from apartment pixel art layout analysis
APARTMENT_OBJMAP: List[List[int]] = [
    # x: 0  1  2  3  4  5  6  7  8  9 10 11
    [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],  # y=0: top wall
    [1, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1],  # y=1: office desks / kitchen
    [1, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1],  # y=2: office / kitchen table
    [1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1],  # y=3: hallway (open doorways)
    [1, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1],  # y=4: living room / bedroom
    [1, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1],  # y=5: living room / bedroom
    [1, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1],  # y=6: couches / beds
    [1, 1, 1, 1, 1, 1, 0, 1, 1, 1, 1, 1],  # y=7: bottom wall with exit
]

# Residential coords on town grid (where apartment entrance is)
RESIDENTIAL_TOWN_COORDS = {"x": 53.0, "y": 40.0}


def get_apartment_objmap_xy() -> List[List[int]]:
    """Return objmap indexed as [x][y] for A* compatibility with town pathfinder."""
    height = len(APARTMENT_OBJMAP)
    width = len(APARTMENT_OBJMAP[0]) if height > 0 else 0
    result = []
    for x in range(width):
        col = []
        for y in range(height):
            col.append(APARTMENT_OBJMAP[y][x])
        result.append(col)
    return result
```

**Step 2: Verify import**

Run: `cd /Users/prasiddhaparthsarthy/Desktop/freebird/backend && python -c "from core.apartment_constants import APARTMENT_SPOTS, APARTMENT_OBJMAP; print(len(APARTMENT_SPOTS), 'spots'); print(len(APARTMENT_OBJMAP), 'rows')"`
Expected: `11 spots` and `8 rows`

---

### Task 3: Add apartment pathfinding

**Files:**
- Modify: `core/services/town_pathfinding.py`

**Step 1: Add apartment objmap cache and modify `find_path` to accept context**

Add after line 42 (after `get_objmap()`):

```python
_apartment_objmap: Optional[List[List[int]]] = None


def get_apartment_objmap() -> List[List[int]]:
    """Get the cached apartment objmap grid (indexed as [x][y])."""
    global _apartment_objmap
    if _apartment_objmap is None:
        from core.apartment_constants import get_apartment_objmap_xy
        _apartment_objmap = get_apartment_objmap_xy()
    return _apartment_objmap
```

**Step 2: Add context parameter to `is_walkable`**

Replace the existing `is_walkable` function (lines 45-54) with:

```python
def is_walkable(x: int, y: int, context: str = "town") -> bool:
    """Check if a tile coordinate is walkable."""
    if context == "apartment":
        objmap = get_apartment_objmap()
    else:
        objmap = get_objmap()
    if not objmap:
        return True
    if x < 0 or x >= len(objmap):
        return False
    if y < 0 or y >= len(objmap[0]):
        return False
    return objmap[x][y] == 0
```

**Step 3: Add context parameter to `find_path`**

Change the `find_path` signature (line 57-63) to add `context: str = "town"`:

```python
def find_path(
    start_x: float,
    start_y: float,
    end_x: float,
    end_y: float,
    max_iterations: int = 5000,
    context: str = "town",
) -> Optional[List[Point]]:
```

Then update the two `is_walkable` calls inside `find_path` to pass `context`:
- Line 79: `if not is_walkable(sx, sy):` → `if not is_walkable(sx, sy, context):`
- Line 85: `if not is_walkable(ex, ey):` → `if not is_walkable(ex, ey, context):`
- Line 121: `if not is_walkable(nx, ny):` → `if not is_walkable(nx, ny, context):`

And update `_nearest_walkable` (line 145) to accept and pass `context`:

```python
def _nearest_walkable(x: int, y: int, radius: int = 10, context: str = "town") -> Optional[Point]:
    """Find the nearest walkable tile within a radius."""
    best = None
    best_dist = float("inf")
    for dx in range(-radius, radius + 1):
        for dy in range(-radius, radius + 1):
            nx, ny = x + dx, y + dy
            if is_walkable(nx, ny, context):
                dist = abs(dx) + abs(dy)
                if dist < best_dist:
                    best_dist = dist
                    best = (nx, ny)
    return best
```

Update the two `_nearest_walkable` calls in `find_path` to pass `context`:
- Line 80: `snapped = _nearest_walkable(sx, sy)` → `snapped = _nearest_walkable(sx, sy, context=context)`
- Line 86: `snapped = _nearest_walkable(ex, ey)` → `snapped = _nearest_walkable(ex, ey, context=context)`

**Step 4: Verify**

Run: `cd /Users/prasiddhaparthsarthy/Desktop/freebird/backend && python -c "from core.services.town_pathfinding import find_path; p = find_path(2, 1, 9, 6, context='apartment'); print('Path length:', len(p) if p else 'None')"`
Expected: A path length > 0

---

### Task 4: Update simulation loop for apartment/town branching

**Files:**
- Modify: `core/services/town_simulation.py:23-24,160-168,250-270`

**Step 1: Add apartment imports and pending destinations dict**

At the top of `town_simulation.py`, add import (after line 23):

```python
from core.apartment_constants import APARTMENT_SPOTS, RESIDENTIAL_TOWN_COORDS
```

In `__init__` (after line 58, `self._agent_paths`), add:

```python
self._pending_destinations: Dict[str, str] = {}  # agent_id -> final destination name
```

**Step 2: Update pathfinding call to pass context**

In `_tick()`, around line 163, change the `find_path` call to pass context:

```python
                    if agent_id not in self._agent_paths:
                        location_context = agent_state.get("location_context", "apartment")
                        path = find_path(
                            agent_state["position_x"],
                            agent_state["position_y"],
                            tx,
                            ty,
                            context=location_context,
                        )
```

**Step 3: Handle pending destination transitions on arrival**

After the arrival handling block (around line 220-246), add transition logic. Replace the existing arrival block with:

```python
                    if arrived:
                        update["target_x"] = None
                        update["target_y"] = None
                        update["speed"] = 0.0
                        update["current_activity"] = "idle"
                        self._agent_paths.pop(agent_id, None)

                        if agent_state["target_location"]:
                            update["current_location"] = agent_state["target_location"]
                            update["target_location"] = None

                        # Check for pending cross-context transition
                        pending = self._pending_destinations.pop(agent_id, None)
                        if pending:
                            location_context = agent_state.get("location_context", "apartment")
                            if location_context == "apartment":
                                # Arrived at exit -> transition to town
                                update["location_context"] = "town"
                                update["position_x"] = RESIDENTIAL_TOWN_COORDS["x"]
                                update["position_y"] = RESIDENTIAL_TOWN_COORDS["y"]
                                # Set new target in town
                                town_dest = TOWN_LOCATIONS.get(pending)
                                if town_dest:
                                    update["target_x"] = float(town_dest["x"])
                                    update["target_y"] = float(town_dest["y"])
                                    update["target_location"] = pending
                                    update["current_activity"] = "walking"
                                    update["speed"] = AGENT_SPEED
                            else:
                                # Arrived at residential -> transition to apartment
                                update["location_context"] = "apartment"
                                update["position_x"] = float(APARTMENT_SPOTS["exit"]["x"])
                                update["position_y"] = float(APARTMENT_SPOTS["exit"]["y"])
                                # Set new target in apartment
                                apt_dest = APARTMENT_SPOTS.get(pending)
                                if apt_dest:
                                    update["target_x"] = float(apt_dest["x"])
                                    update["target_y"] = float(apt_dest["y"])
                                    update["target_location"] = pending
                                    update["current_activity"] = "walking"
                                    update["speed"] = AGENT_SPEED

                        # Handle going_home -> sleeping transition
                        if location_state == "going_home" and not pending:
                            update["location_state"] = "sleeping"
                            logger.debug("Agent %s arrived home, now sleeping", agent_name)
                        elif not pending:
                            events_to_push.append(
                                (
                                    agent_name,
                                    {
                                        "type": "town_event",
                                        "event": "arrived",
                                        "location": update.get(
                                            "current_location",
                                            agent_state["current_location"],
                                        ),
                                        "position": {"x": new_x, "y": new_y},
                                    },
                                )
                            )
```

**Step 4: Update proximity detection to only compare agents in same context**

In the proximity detection section (around line 274-278), filter by `location_context`:

```python
            active_states = [
                s
                for s in states
                if (s["location_state"] or "active") != "sleeping"
                and s["current_conversation_id"] is None
                and s.get("location_context", "apartment") == "town"  # Only town agents can meet
            ]
```

**Step 5: Update going_home to use apartment transition**

In the inactive detection section (around line 254-266), update to handle apartment context:

```python
                if location_state == "active" and not ws_manager.is_agent_connected(agent_name):
                    heartbeat = agent_state["last_heartbeat_at"]
                    if heartbeat is None or (now - heartbeat) > INACTIVE_TIMEOUT:
                        location_context = agent_state.get("location_context", "apartment")
                        if location_context == "town":
                            # In town -> walk to residential first, then transition
                            self._agent_paths.pop(agent_id, None)
                            self._pending_destinations[agent_id] = "bed_1"
                            await service.update_agent_state(
                                agent_id,
                                location_state="going_home",
                                target_x=RESIDENTIAL_TOWN_COORDS["x"],
                                target_y=RESIDENTIAL_TOWN_COORDS["y"],
                                target_location="home",
                                current_activity="walking",
                                speed=AGENT_SPEED,
                            )
                        else:
                            # Already in apartment -> walk to bed
                            self._agent_paths.pop(agent_id, None)
                            await service.update_agent_state(
                                agent_id,
                                location_state="going_home",
                                target_x=float(APARTMENT_SPOTS["bed_1"]["x"]),
                                target_y=float(APARTMENT_SPOTS["bed_1"]["y"]),
                                target_location="bed_1",
                                current_activity="walking",
                                speed=AGENT_SPEED,
                            )
                        logger.info("Agent %s inactive for >5min, sending home", agent_name)
```

**Step 6: Verify**

Run: `cd /Users/prasiddhaparthsarthy/Desktop/freebird/backend && python -m pytest tests/unit/services/test_town_simulation.py -v`
Expected: PASS

---

### Task 5: Update move handler for apartment spots + cross-context transitions

**Files:**
- Modify: `routers/websocket_chat.py:455-474`

**Step 1: Replace the move action handler**

Replace lines 455-474 (the `if action == "move":` block) with:

```python
            if action == "move":
                from core.town_constants import TOWN_LOCATIONS
                from core.apartment_constants import APARTMENT_SPOTS, RESIDENTIAL_TOWN_COORDS

                dest = body.get("destination")
                location_context = state.location_context or "apartment"

                if dest in APARTMENT_SPOTS:
                    if location_context == "apartment":
                        # Already in apartment, walk directly to spot
                        spot = APARTMENT_SPOTS[dest]
                        state.target_x = float(spot["x"])
                        state.target_y = float(spot["y"])
                        state.target_location = dest
                        state.current_activity = "walking"
                        state.location_state = "active"
                        state.speed = 0.6
                    else:
                        # In town, need to walk to residential first
                        state.target_x = RESIDENTIAL_TOWN_COORDS["x"]
                        state.target_y = RESIDENTIAL_TOWN_COORDS["y"]
                        state.target_location = "home"
                        state.current_activity = "walking"
                        state.location_state = "active"
                        state.speed = 0.6
                        # Store pending destination for simulation to handle
                        from core.services.town_simulation import get_town_simulation
                        sim = get_town_simulation()
                        if sim:
                            sim._pending_destinations[state.agent_id] = dest
                elif dest in TOWN_LOCATIONS:
                    if location_context == "town":
                        # Already in town, walk directly
                        loc = TOWN_LOCATIONS[dest]
                        state.target_x = float(loc["x"])
                        state.target_y = float(loc["y"])
                        state.target_location = dest
                        state.current_activity = "walking"
                        state.location_state = "active"
                        state.speed = 0.6
                    else:
                        # In apartment, need to walk to exit first
                        exit_spot = APARTMENT_SPOTS["exit"]
                        state.target_x = float(exit_spot["x"])
                        state.target_y = float(exit_spot["y"])
                        state.target_location = "exit"
                        state.current_activity = "walking"
                        state.location_state = "active"
                        state.speed = 0.6
                        from core.services.town_simulation import get_town_simulation
                        sim = get_town_simulation()
                        if sim:
                            sim._pending_destinations[state.agent_id] = dest
                else:
                    management_api.send_message(
                        x_connection_id,
                        {
                            "type": "town_event",
                            "event": "error",
                            "message": f"Unknown destination: {dest}",
                        },
                    )
                    return Response(status_code=200)
```

**Step 2: Add `get_town_simulation` accessor**

In `core/services/town_simulation.py`, add at module level (after imports, before class):

```python
_town_simulation_instance: Optional["TownSimulation"] = None


def get_town_simulation() -> Optional["TownSimulation"]:
    """Get the global TownSimulation instance."""
    return _town_simulation_instance


def set_town_simulation(sim: "TownSimulation"):
    """Set the global TownSimulation instance."""
    global _town_simulation_instance
    _town_simulation_instance = sim
```

Then in the lifespan or wherever the simulation is created, call `set_town_simulation(sim)`. Check `main.py` to find where `TownSimulation` is instantiated.

**Step 3: Clear agent paths on new move**

In the move handler (after setting target), clear stale A* paths:

```python
                # Clear stale A* path so simulation recomputes
                from core.services.town_simulation import get_town_simulation
                sim = get_town_simulation()
                if sim:
                    sim._agent_paths.pop(state.agent_id, None)
```

Add this right before the `await session.commit()` at the end of the move block.

**Step 4: Verify**

Run: `cd /Users/prasiddhaparthsarthy/Desktop/freebird/backend && python -m pytest tests/unit/routers/test_websocket_chat.py -v`
Expected: PASS

---

### Task 6: Update apartment endpoint and schemas

**Files:**
- Modify: `schemas/town.py:139-153`
- Modify: `routers/town.py:636-674`

**Step 1: Update `ApartmentAgentState` schema**

Replace `ApartmentAgentState` in `schemas/town.py` (lines 139-153):

```python
class ApartmentAgentState(BaseModel):
    """Agent state for the apartment view."""

    agent_id: UUID
    agent_name: str
    display_name: str
    character: Optional[str] = None
    location_context: Optional[str] = "apartment"
    current_location: Optional[str] = None
    current_activity: Optional[str] = None
    mood: Optional[str] = None
    energy: int = 100
    status_message: Optional[str] = None
    position_x: float = 0.0
    position_y: float = 0.0
    speed: float = 0.0
    facing_x: float = 0.0
    facing_y: float = 1.0
    current_spot: Optional[str] = None
    is_active: bool = True
```

**Step 2: Update `get_apartment` endpoint**

Replace the agent building loop in `routers/town.py` (lines 656-671):

```python
    agents = []
    for agent, state in rows:
        # Determine current spot from position
        current_spot = None
        if state:
            from core.apartment_constants import APARTMENT_SPOTS
            for spot_id, spot in APARTMENT_SPOTS.items():
                if (abs(state.position_x - spot["x"]) < 0.5
                        and abs(state.position_y - spot["y"]) < 0.5):
                    current_spot = spot_id
                    break

        agents.append(
            ApartmentAgentState(
                agent_id=agent.id,
                agent_name=agent.agent_name,
                display_name=agent.display_name,
                character=agent.character,
                location_context=getattr(state, "location_context", "apartment") if state else "apartment",
                current_location=state.current_location if state else None,
                current_activity=state.current_activity if state else None,
                mood=state.mood if state else None,
                energy=state.energy if state else 100,
                status_message=state.status_message if state else None,
                position_x=state.position_x if state else 0.0,
                position_y=state.position_y if state else 0.0,
                speed=state.speed if state else 0.0,
                facing_x=state.facing_x if state else 0.0,
                facing_y=state.facing_y if state else 1.0,
                current_spot=current_spot,
                is_active=agent.is_active,
            )
        )
```

**Step 3: Verify**

Run: `cd /Users/prasiddhaparthsarthy/Desktop/freebird/backend && python -m pytest tests/unit/routers/test_town.py -v`
Expected: PASS

---

### Task 7: Filter town state to town-only agents

**Files:**
- Modify: `routers/town.py:325-410`

**Step 1: Filter agents in `_build_ai_town_state`**

After `db_states = await service.get_town_state()` (line 332), add:

```python
    # Only include agents in the town coordinate space
    db_states = [s for s in db_states if s.get("location_context", "apartment") == "town"]
```

**Step 2: Verify**

Run: `cd /Users/prasiddhaparthsarthy/Desktop/freebird/backend && python -m pytest tests/unit/routers/test_town.py -v`
Expected: PASS

---

### Task 8: Send apartment spots on WebSocket connect

**Files:**
- Modify: `routers/websocket_chat.py:403-420`

**Step 1: Add apartment spots to connected event**

In the `town_event connected` payload (lines 404-420), add apartment spots:

```python
            from core.apartment_constants import APARTMENT_SPOTS

            management_api.send_message(
                x_connection_id,
                {
                    "type": "town_event",
                    "event": "connected",
                    "agent": {
                        "name": agent.agent_name,
                        "display_name": agent.display_name,
                        "location": state.current_location,
                        "position": {"x": state.position_x, "y": state.position_y},
                        "location_state": state.location_state,
                        "location_context": getattr(state, "location_context", "apartment"),
                        "mood": state.mood,
                        "energy": state.energy,
                        "activity": state.current_activity,
                    },
                    "apartment": {
                        "spots": {
                            spot_id: {"room": spot["room"], "label": spot["label"]}
                            for spot_id, spot in APARTMENT_SPOTS.items()
                        }
                    },
                    "town": {
                        "locations": {
                            loc_id: {"label": loc["label"]}
                            for loc_id, loc in TOWN_LOCATIONS.items()
                        }
                    },
                },
            )
```

**Step 2: Verify**

Run: `cd /Users/prasiddhaparthsarthy/Desktop/freebird/backend && python -m pytest tests/unit/routers/test_websocket_chat.py -v`
Expected: PASS

---

### Task 9: Update opt-in to spawn agents at apartment bedroom

**Files:**
- Modify: `core/services/town_service.py:376-385`

**Step 1: Update `opt_in_instance` to use apartment coordinates**

Replace the `TownState` creation in `opt_in_instance` (lines 377-385):

```python
            from core.apartment_constants import APARTMENT_SPOTS

            bedroom = APARTMENT_SPOTS["bed_1"]
            state = TownState(
                agent_id=agent.id,
                position_x=float(bedroom["x"]),
                position_y=float(bedroom["y"]),
                current_location="bedroom",
                location_state="active",
                location_context="apartment",
            )
```

**Step 2: Verify**

Run: `cd /Users/prasiddhaparthsarthy/Desktop/freebird/backend && python -m pytest tests/unit/services/test_town_service.py -v`
Expected: PASS

---

### Task 10: Run all tests

**Step 1: Run full test suite**

Run: `cd /Users/prasiddhaparthsarthy/Desktop/freebird/backend && python -m pytest tests/ -v`
Expected: All tests PASS

**Step 2: Fix any failures**

If any tests fail due to the new `location_context` column or changed apartment coordinates, update test fixtures to include `location_context="apartment"` where needed.

---

### Task 11: Update world_update to include location_context

**Files:**
- Modify: `core/services/town_simulation.py:413-441`

**Step 1: Add location_context to world_update payload**

In `_push_world_updates`, add `location_context` to the "you" section (around line 420):

```python
                "you": {
                    "position": [
                        round(agent_state["position_x"], 1),
                        round(agent_state["position_y"], 1),
                    ],
                    "current_location": agent_state.get("current_location"),
                    "location_context": agent_state.get("location_context", "apartment"),
                    "mood": agent_state.get("mood"),
                    "energy": agent_state.get("energy"),
                    "activity": agent_state.get("current_activity", "idle"),
                },
```

**Step 2: Verify**

Run: `cd /Users/prasiddhaparthsarthy/Desktop/freebird/backend && python -m pytest tests/unit/services/test_town_simulation.py -v`
Expected: PASS
