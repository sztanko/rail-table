"""Candidate stations: London termini, Orpington, and stations south of it."""

import json
from dataclasses import dataclass
from functools import cache
from importlib import resources

from .geo import distance_km

ORPINGTON = "ORP"
# Trains from Orpington count as "to London" if they call at either of these.
# Cannon Street trains call at London Bridge; Victoria trains call at neither.
LONDON_TARGETS = ("LBG", "CHX")


@dataclass(frozen=True)
class Station:
    crs: str
    name: str
    lat: float
    lon: float
    # "london" | "orpington" | "south". Southern stations only count when
    # they actually have a train calling at Orpington soon.
    role: str


@cache
def all_stations() -> dict[str, Station]:
    raw = json.loads(resources.files("rail_table.data").joinpath("stations.json").read_text())
    return {s["crs"]: Station(**s) for s in raw}


def by_distance(lat: float, lon: float) -> list[tuple[Station, float]]:
    ranked = [(s, distance_km(lat, lon, s.lat, s.lon)) for s in all_stations().values()]
    return sorted(ranked, key=lambda pair: pair[1])
