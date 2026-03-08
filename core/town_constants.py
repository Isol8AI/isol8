"""Shared constants for the GooseTown simulation.

Extracted here to avoid circular imports between routers/town.py and
core/services/town_simulation.py.
"""

from typing import Dict

# Town locations in tile coordinates (verified walkable on 96x64 town map).
# Each location has 2-4 walkable neighbours so agents can approach from any side.
TOWN_LOCATIONS: Dict[str, Dict] = {
    "plaza": {
        "x": 40.0,
        "y": 25.0,
        "label": "Plaza",
        "type": "area",
        "activities": ["walk around", "sit at the fountain", "chat with nearby agents"],
        "bounds": {"x1": 32, "y1": 22, "x2": 52, "y2": 34},
    },
    "library": {
        "x": 40.0,
        "y": 13.0,
        "label": "Library",
        "type": "point",
        "activities": ["browse shelves", "read a book", "study quietly"],
    },
    "cafe": {
        "x": 10.0,
        "y": 17.0,
        "label": "Cafe",
        "type": "point",
        "activities": ["order a drink", "sit at a table", "chat with nearby agents"],
    },
    "activity_center": {
        "x": 65.0,
        "y": 10.0,
        "label": "Activity Center",
        "type": "point",
        "activities": ["work out", "play sports", "stretch", "chat with gym-goers"],
    },
    "residence": {
        "x": 69.0,
        "y": 25.0,
        "label": "Residence",
        "type": "point",
        "activities": ["go inside your apartment"],
    },
}

# Full avatar catalog with metadata for the agent selection API
AVATAR_CATALOG = [
    {"id": "c1", "name": "Lucky", "description": "A cheerful adventurer"},
    {"id": "c2", "name": "Bob", "description": "A grumpy gardener"},
    {"id": "c3", "name": "Stella", "description": "A charming trickster"},
    {"id": "c4", "name": "Alice", "description": "A brilliant scientist"},
    {"id": "c5", "name": "Pete", "description": "A devout believer"},
    {"id": "c6", "name": "Scholar", "description": "A studious bookworm"},
    {"id": "c7", "name": "Knight", "description": "A brave protector"},
    {"id": "c8", "name": "Merchant", "description": "A savvy trader"},
    {"id": "c9", "name": "Bard", "description": "A musical storyteller"},
    {"id": "c10", "name": "Ranger", "description": "A wilderness explorer"},
    {"id": "c11", "name": "Healer", "description": "A gentle caretaker"},
    {"id": "c12", "name": "Tinkerer", "description": "An inventive builder"},
]

# Available character sprites
AVAILABLE_CHARACTERS = [a["id"] for a in AVATAR_CATALOG]

# Walk speed reported to the frontend for interpolation (tiles/tick at 2s ticks)
WALK_SPEED_DISPLAY = 0.6
