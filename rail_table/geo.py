"""Distances and the in/out-of-UK check."""

import json
import math
from functools import cache
from importlib import resources

EARTH_RADIUS_KM = 6371.0

# A GPS fix on a beach or pier can land just outside the coarse coastline,
# so anything this close to the outline still counts as in the UK.
COAST_TOLERANCE_KM = 8.0


def distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


@cache
def _uk_rings() -> list[list[tuple[float, float]]]:
    """Outer rings of the UK outline (Natural Earth 1:50m), as (lon, lat)."""
    geom = json.loads(resources.files("rail_table.data").joinpath("uk.json").read_text())
    return [[(x, y) for x, y in polygon[0]] for polygon in geom["coordinates"]]


def _in_ring(lon: float, lat: float, ring: list[tuple[float, float]]) -> bool:
    inside = False
    for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]):
        if (y1 > lat) != (y2 > lat) and lon < x1 + (lat - y1) * (x2 - x1) / (y2 - y1):
            inside = not inside
    return inside


def in_uk(lat: float, lon: float) -> bool:
    rings = _uk_rings()
    if any(_in_ring(lon, lat, ring) for ring in rings):
        return True
    return any(
        distance_km(lat, lon, y, x) <= COAST_TOLERANCE_KM for ring in rings for x, y in ring
    )
