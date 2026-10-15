"""Turns a location into the list of trains worth showing."""

import asyncio
import html
import re
from datetime import datetime
from zoneinfo import ZoneInfo

from .darwin import Darwin
from .geo import in_uk
from .stations import LONDON_TARGETS, ORPINGTON, Station, all_stations, by_distance

LONDON_TZ = ZoneInfo("Europe/London")
# How many southern stations to try (nearest first) before giving up on them.
MAX_SOUTHERN_TRIES = 4


async def build_board(
    darwin: Darwin,
    lat: float | None = None,
    lon: float | None = None,
    station: str | None = None,
    now: datetime | None = None,
) -> dict:
    now = now or datetime.now(LONDON_TZ)
    distance = None

    if station:
        chosen = all_stations()[station]
        boards = await _boards_for(darwin, chosen)
    else:
        if not in_uk(lat, lon):
            return {"status": "outside_uk"}
        chosen, distance, boards = await _nearest_with_service(darwin, lat, lon)

    targets = LONDON_TARGETS if chosen.crs == ORPINGTON else (ORPINGTON,)
    services = _merge_services(boards, targets, now)
    return {
        "status": "ok",
        "station": {"crs": chosen.crs, "name": chosen.name, "distanceKm": distance},
        "direction": "to_london" if chosen.crs == ORPINGTON else "to_orpington",
        "services": services,
        "messages": _messages(boards),
        "generatedAt": now.isoformat(timespec="seconds"),
    }


async def _boards_for(darwin: Darwin, station: Station) -> list[dict]:
    if station.crs == ORPINGTON:
        return list(await asyncio.gather(*(darwin.departures(ORPINGTON, t) for t in LONDON_TARGETS)))
    return [await darwin.departures(station.crs, ORPINGTON)]


async def _nearest_with_service(darwin: Darwin, lat: float, lon: float):
    southern_tries = 0
    for station, distance in by_distance(lat, lon):
        if station.role != "south":
            return station, round(distance, 1), await _boards_for(darwin, station)
        if southern_tries >= MAX_SOUTHERN_TRIES:
            continue
        southern_tries += 1
        boards = await _boards_for(darwin, station)
        if any(b.get("trainServices") for b in boards):
            return station, round(distance, 1), boards
    raise AssertionError("candidate list always contains London and Orpington")


def _merge_services(boards: list[dict], targets: tuple[str, ...], now: datetime) -> list[dict]:
    seen: dict[str, dict] = {}
    for board in boards:
        for svc in board.get("trainServices") or []:
            sid = svc.get("serviceID") or f"{svc.get('std')}-{len(seen)}"
            if sid in seen:
                continue
            parsed = _service(svc, targets)
            if parsed:
                seen[sid] = parsed
    now_min = now.hour * 60 + now.minute
    # Trains a little past their scheduled time (i.e. running late) sort first.
    return sorted(seen.values(), key=lambda s: (_minutes(s["std"]) - now_min + 720) % 1440)


def _service(svc: dict, targets: tuple[str, ...]) -> dict | None:
    arrivals = _arrivals(svc, targets)
    if not arrivals:
        return None
    std = svc.get("std")
    cancelled = bool(svc.get("isCancelled")) or svc.get("etd") == "Cancelled"
    expected, delay, status = _expected(std, svc.get("etd"), cancelled)
    formation = svc.get("formation") or {}
    coaches = svc.get("length") or len(formation.get("coaches") or []) or None
    return {
        "id": svc.get("serviceID"),
        "std": std,
        "expected": expected,
        "delayMin": delay,
        "status": status,
        "cancelReason": svc.get("cancelReason") if cancelled else None,
        "delayReason": svc.get("delayReason"),
        "platform": svc.get("platform"),
        "destination": " & ".join(d.get("locationName", "") for d in svc.get("destination") or []),
        "operator": svc.get("operator"),
        "coaches": coaches,
        "loading": _loading(formation),
        "arrivals": arrivals,
    }


def _arrivals(svc: dict, targets: tuple[str, ...]) -> list[dict]:
    found = {}
    for portion in svc.get("subsequentCallingPoints") or []:
        for cp in portion.get("callingPoint") or []:
            crs = cp.get("crs")
            if crs in targets and crs not in found:
                cancelled = bool(cp.get("isCancelled")) or cp.get("et") == "Cancelled"
                expected, delay, status = _expected(cp.get("st"), cp.get("at") or cp.get("et"), cancelled)
                found[crs] = {
                    "crs": crs,
                    "name": cp.get("locationName"),
                    "st": cp.get("st"),
                    "expected": expected,
                    "delayMin": delay,
                    "status": status,
                }
    return [found[t] for t in targets if t in found]


def _expected(scheduled: str | None, estimate: str | None, cancelled: bool):
    """(expected time, delay in minutes, status) from Darwin's st/et strings.

    Darwin estimates are "On time", "HH:MM", "Delayed", "Cancelled" or absent.
    """
    if cancelled:
        return None, None, "cancelled"
    if estimate == "On time":
        return scheduled, 0, "on_time"
    if estimate and re.fullmatch(r"\d\d:\d\d", estimate) and scheduled:
        delay = (_minutes(estimate) - _minutes(scheduled)) % 1440
        if delay > 720:
            delay -= 1440
        return estimate, delay, "late" if delay > 0 else "on_time"
    if estimate == "Delayed":
        return None, None, "delayed"
    return scheduled, None, "unknown"


def _minutes(hhmm: str | None) -> int:
    if not hhmm or not re.fullmatch(r"\d\d:\d\d", hhmm):
        return 0
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def _loading(formation: dict) -> dict | None:
    """How full the train is, from per-coach loading or the loading category."""
    per_coach = [c["loading"] for c in formation.get("coaches") or [] if c.get("loadingSpecified")]
    if per_coach:
        pct = round(sum(per_coach) / len(per_coach))
        level = "low" if pct < 40 else "medium" if pct < 75 else "high"
        return {"level": level, "pct": pct}
    category = formation.get("loadingCategory")
    if category and (category.get("Value") or category.get("code")):
        return {
            "level": None,
            "label": category.get("Value") or category.get("code"),
            "colour": category.get("colour"),
        }
    return None


def _messages(boards: list[dict]) -> list[str]:
    out = []
    for board in boards:
        for msg in board.get("nrccMessages") or []:
            text = html.unescape(re.sub(r"<[^>]+>", "", msg.get("Value") or "")).strip()
            if text and text not in out:
                out.append(text)
    return out
