"""A* pathfinding for Bit City agents.

Uses the objmap from city_map.json to route agents around buildings
and obstacles on the 96x64 tile grid.
"""

import heapq
import json
import logging
from pathlib import Path
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

# Type alias for a grid point
Point = Tuple[int, int]


def _load_objmap() -> List[List[int]]:
    """Load the walkability grid from city_map.json.

    Returns objmap[x][y] where 0 = walkable, -1 = blocked.
    """
    map_path = Path(__file__).parent.parent.parent / "data" / "city_map.json"
    if not map_path.exists():
        logger.warning("city_map.json not found, pathfinding disabled")
        return []
    with open(map_path) as f:
        raw = json.load(f)
    return raw["objmap"][0]


# Module-level cache
_objmap: Optional[List[List[int]]] = None
_apartment_objmap: Optional[List[List[int]]] = None


def get_objmap() -> List[List[int]]:
    """Get the cached objmap grid."""
    global _objmap
    if _objmap is None:
        _objmap = _load_objmap()
    return _objmap


def get_apartment_objmap() -> List[List[int]]:
    """Get the cached apartment objmap grid (indexed as [x][y])."""
    global _apartment_objmap
    if _apartment_objmap is None:
        from core.apartment_constants import get_apartment_objmap_xy

        _apartment_objmap = get_apartment_objmap_xy()
    return _apartment_objmap


def is_walkable(x: int, y: int, context: str = "town") -> bool:
    """Check if a tile coordinate is walkable."""
    if context == "apartment":
        objmap = get_apartment_objmap()
    else:
        objmap = get_objmap()
    if not objmap:
        return True  # No map data, allow all movement
    if x < 0 or x >= len(objmap):
        return False
    if y < 0 or y >= len(objmap[0]):
        return False
    return objmap[x][y] == 0


def find_path(
    start_x: float,
    start_y: float,
    end_x: float,
    end_y: float,
    max_iterations: int = 5000,
    context: str = "town",
) -> Optional[List[Point]]:
    """Find a path from start to end using A* on the tile grid.

    Args:
        start_x, start_y: Starting position (float tile coords)
        end_x, end_y: Target position (float tile coords)
        max_iterations: Safety limit to prevent infinite loops

    Returns:
        List of (x, y) integer tile waypoints, or None if no path found.
        The path includes the start and end points.
    """
    sx, sy = round(start_x), round(start_y)
    ex, ey = round(end_x), round(end_y)

    # If start or end is blocked, snap to nearest walkable tile
    if not is_walkable(sx, sy, context):
        snapped = _nearest_walkable(sx, sy, context=context)
        if snapped is None:
            return None
        sx, sy = snapped

    if not is_walkable(ex, ey, context):
        snapped = _nearest_walkable(ex, ey, context=context)
        if snapped is None:
            return None
        ex, ey = snapped

    if sx == ex and sy == ey:
        return [(sx, sy)]

    # A* search
    # Priority queue: (f_cost, counter, x, y)
    counter = 0
    open_set = [(0, counter, sx, sy)]
    came_from = {}
    g_score = {(sx, sy): 0}

    # 4-directional neighbors
    directions = [(0, 1), (0, -1), (1, 0), (-1, 0)]

    iterations = 0
    while open_set and iterations < max_iterations:
        iterations += 1
        f, _, cx, cy = heapq.heappop(open_set)

        if cx == ex and cy == ey:
            # Reconstruct path
            path = [(ex, ey)]
            node = (cx, cy)
            while node in came_from:
                node = came_from[node]
                path.append(node)
            path.reverse()
            return path

        for dx, dy in directions:
            nx, ny = cx + dx, cy + dy
            if not is_walkable(nx, ny, context):
                continue

            new_g = g_score[(cx, cy)] + 1
            if (nx, ny) in g_score and new_g >= g_score[(nx, ny)]:
                continue

            g_score[(nx, ny)] = new_g
            h = abs(nx - ex) + abs(ny - ey)  # Manhattan distance
            counter += 1
            heapq.heappush(open_set, (new_g + h, counter, nx, ny))
            came_from[(nx, ny)] = (cx, cy)

    logger.warning(
        "A* failed to find path from (%d,%d) to (%d,%d) after %d iterations",
        sx,
        sy,
        ex,
        ey,
        iterations,
    )
    return None


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
