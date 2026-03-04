"""Shared constants for the GooseTown simulation.

Extracted here to avoid circular imports between routers/town.py and
core/services/town_simulation.py.
"""

from typing import Dict, List

# Town locations in tile coordinates (verified walkable on Dreamyland map).
# Each location has 4+ walkable neighbours so agents can approach from any side.
TOWN_LOCATIONS: Dict[str, Dict] = {
    "plaza": {"x": 30.0, "y": 22.0, "label": "Town Plaza"},
    "cafe": {"x": 7.0, "y": 18.0, "label": "Cafe"},
    "library": {"x": 55.0, "y": 16.0, "label": "Library"},
    "park": {"x": 26.0, "y": 5.0, "label": "Park"},
    "apartment": {"x": 7.0, "y": 11.0, "label": "Apartment"},
    "barn": {"x": 42.0, "y": 11.0, "label": "Barn"},
    "shop": {"x": 49.0, "y": 18.0, "label": "Shop"},
    "home": {"x": 28.0, "y": 32.0, "label": "Residential"},
}

# Default characters for the town (same data used by both simulation and router)
DEFAULT_CHARACTERS: List[Dict] = [
    {
        "name": "Lucky",
        "agent_name": "lucky",
        "character": "c1",
        "identity": (
            "Lucky is always happy and curious, and he loves cheese. He spends "
            "most of his time reading about the history of science and traveling "
            "through the galaxy on whatever ship will take him."
        ),
        "plan": "You want to hear all the gossip.",
        "spawn": {"x": 7.0, "y": 16.0},
        "home": "cafe",
    },
    {
        "name": "Bob",
        "agent_name": "bob",
        "character": "c2",
        "identity": (
            "Bob is always grumpy and he loves trees. He spends most of his time "
            "gardening by himself. When spoken to he'll respond but try and get "
            "out of the conversation as quickly as possible."
        ),
        "plan": "You want to avoid people as much as possible.",
        "spawn": {"x": 28.0, "y": 32.0},
        "home": "home",
    },
    {
        "name": "Stella",
        "agent_name": "stella",
        "character": "c3",
        "identity": (
            "Stella can never be trusted. She tries to trick people all the time. "
            "She's incredibly charming and not afraid to use her charm."
        ),
        "plan": "You want to take advantage of others as much as possible.",
        "spawn": {"x": 7.0, "y": 11.0},
        "home": "apartment",
    },
    {
        "name": "Alice",
        "agent_name": "alice",
        "character": "c4",
        "identity": (
            "Alice is a famous scientist. She is smarter than everyone else and "
            "has discovered mysteries of the universe no one else can understand."
        ),
        "plan": "You want to figure out how the world works.",
        "spawn": {"x": 55.0, "y": 16.0},
        "home": "library",
    },
    {
        "name": "Pete",
        "agent_name": "pete",
        "character": "c5",
        "identity": (
            "Pete is deeply religious and sees the hand of god or of the work of "
            "the devil everywhere. He can't have a conversation without bringing "
            "up his deep faith."
        ),
        "plan": "You want to convert everyone to your religion.",
        "spawn": {"x": 30.0, "y": 22.0},
        "home": "plaza",
    },
]

# Default spawn positions (derived from DEFAULT_CHARACTERS for backward compat)
DEFAULT_SPAWN_POSITIONS = [c["spawn"] for c in DEFAULT_CHARACTERS]

# Available character sprites (c1-c5 in data/characters.ts)
AVAILABLE_CHARACTERS = ["c1", "c2", "c3", "c4", "c5"]

# Characters already assigned to default AI agents
AGENT_CHARACTERS = {c["character"] for c in DEFAULT_CHARACTERS}

# System user ID for default seeded agents
SYSTEM_USER_ID = "system"

# Walk speed reported to the frontend for interpolation (tiles/tick at 2s ticks)
WALK_SPEED_DISPLAY = 0.6
