"""Shared constants for the GooseTown simulation.

Extracted here to avoid circular imports between routers/town.py and
core/services/town_simulation.py.
"""

from typing import Dict

# Town locations in tile coordinates (verified walkable on 96x64 town map).
# Each location has 2-4 walkable neighbours so agents can approach from any side.
TOWN_LOCATIONS: Dict[str, Dict] = {
    "plaza": {"x": 49.0, "y": 33.0, "label": "Town Plaza"},
    "cafe": {"x": 32.0, "y": 34.0, "label": "Cafe"},
    "library": {"x": 38.0, "y": 21.0, "label": "Library"},
    "town_hall": {"x": 62.0, "y": 28.0, "label": "Town Hall"},
    "apartment": {"x": 37.0, "y": 41.0, "label": "Apartment"},
    "barn": {"x": 60.0, "y": 36.0, "label": "Barn"},
    "shop": {"x": 47.0, "y": 48.0, "label": "Shop"},
    "home": {"x": 53.0, "y": 40.0, "label": "Residential"},
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
