"""Shared constants for the GooseTown simulation.

Extracted here to avoid circular imports between routers/town.py and
core/services/town_simulation.py.
"""

from typing import Dict

# Town locations in tile coordinates for the 64x48 town-v2 map.
# Each location has 2-4 walkable neighbours so agents can approach from any side.
TOWN_LOCATIONS: Dict[str, Dict] = {
    "plaza": {
        "x": 34.0,
        "y": 22.0,
        "label": "Plaza",
        "type": "area",
        "activities": ["walk around", "sit at the fountain", "chat with nearby agents"],
        "bounds": {"x1": 28, "y1": 18, "x2": 40, "y2": 28},
    },
    "library": {
        "x": 36.0,
        "y": 12.0,
        "label": "Library",
        "type": "point",
        "activities": ["browse shelves", "read a book", "study quietly"],
    },
    "cafe": {
        "x": 16.0,
        "y": 14.0,
        "label": "Cafe",
        "type": "point",
        "activities": ["order a drink", "sit at a table", "chat with nearby agents"],
    },
    "activity_center": {
        "x": 48.0,
        "y": 12.0,
        "label": "Activity Center",
        "type": "point",
        "activities": ["work out", "play sports", "stretch", "chat with gym-goers"],
    },
    "residence": {
        "x": 42.0,
        "y": 36.0,
        "label": "Residence",
        "type": "point",
        "activities": ["go inside your apartment"],
    },
}
