from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from rail_table.board import LONDON_TZ, _expected, build_board
from rail_table.darwin import Darwin
from rail_table.geo import in_uk

FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 10, 15, 11, 0, tzinfo=LONDON_TZ)


@pytest.fixture
async def darwin():
    d = Darwin(api_key=None, fixtures_dir=FIXTURES)
    yield d
    await d.aclose()


@pytest.mark.parametrize(
    "lat, lon, expected",
    [
        (51.508, -0.128, True),  # Trafalgar Square
        (55.953, -3.188, True),  # Edinburgh
        (54.597, -5.930, True),  # Belfast
        (51.389, 1.386, True),  # Margate seafront
        (48.857, 2.352, False),  # Paris
        (53.349, -6.260, False),  # Dublin
        (50.951, 1.858, False),  # Calais
    ],
)
def test_in_uk(lat, lon, expected):
    assert in_uk(lat, lon) is expected


@pytest.mark.parametrize(
    "st, et, cancelled, result",
    [
        ("10:50", "On time", False, ("10:50", 0, "on_time")),
        ("10:50", "10:58", False, ("10:58", 8, "late")),
        ("23:58", "00:04", False, ("00:04", 6, "late")),
        ("10:50", "10:49", False, ("10:49", -1, "on_time")),
        ("10:50", "Delayed", False, (None, None, "delayed")),
        ("10:50", "Cancelled", True, (None, None, "cancelled")),
        ("10:50", None, False, ("10:50", None, "unknown")),
    ],
)
def test_expected(st, et, cancelled, result):
    assert _expected(st, et, cancelled) == result


@pytest.mark.parametrize(
    "lat, lon, crs",
    [
        (51.508, -0.128, "CHX"),  # Trafalgar Square
        (51.5035, -0.107, "WAE"),  # The Cut
        (51.5055, -0.091, "LBG"),  # Borough Market
        (51.270, 0.190, "SEV"),  # Sevenoaks town
        (51.296, 0.171, "SEV"),  # Dunton Green: no Orpington trains in fixtures, falls through
    ],
)
async def test_nearest_station_towards_orpington(darwin, lat, lon, crs):
    board = await build_board(darwin, lat, lon, now=NOW)
    assert board["station"]["crs"] == crs
    assert board["direction"] == "to_orpington"
    assert board["services"]
    assert all(s["arrivals"][0]["crs"] == "ORP" for s in board["services"])


async def test_charing_cross_board(darwin):
    board = await build_board(darwin, 51.508, -0.128, now=NOW)
    first, second, third, fourth, fifth = board["services"]
    # Ordered by scheduled departure.
    assert [s["std"] for s in board["services"]] == ["10:50", "11:07", "11:08", "11:20", "11:37"]
    assert first["delayMin"] == 8 and first["expected"] == "10:58" and first["coaches"] == 10
    assert first["arrivals"][0]["expected"] == "11:22"
    assert third["loading"] == {"level": "high", "pct": 85}
    assert fourth["status"] == "cancelled" and "train crew" in fourth["cancelReason"]
    assert fifth["loading"]["level"] == "low"


async def test_orpington_goes_to_london(darwin):
    board = await build_board(darwin, 51.375, 0.098, now=NOW)
    assert board["station"]["crs"] == "ORP"
    assert board["direction"] == "to_london"
    # orp1 appears on both the LBG and CHX boards but is listed once.
    assert [s["id"] for s in board["services"]] == ["orp1", "orp2", "orp3"]
    assert [a["crs"] for a in board["services"][0]["arrivals"]] == ["LBG", "CHX"]
    assert board["messages"] == ["Disruption between Sevenoaks & Tonbridge."]


async def test_outside_uk(darwin):
    assert await build_board(darwin, 48.857, 2.352, now=NOW) == {"status": "outside_uk"}


async def test_station_override(darwin):
    board = await build_board(darwin, station="LBG", now=NOW)
    assert board["station"] == {"crs": "LBG", "name": "London Bridge", "distanceKm": None}


def test_api(monkeypatch):
    monkeypatch.setenv("RAIL_FIXTURES_DIR", str(FIXTURES))
    from rail_table.app import app

    with TestClient(app) as client:
        assert client.get("/api/board", params={"lat": 51.508, "lon": -0.128}).json()["station"]["crs"] == "CHX"
        assert client.get("/api/board", params={"station": "xyz"}).status_code == 400
        assert client.get("/api/board").status_code == 400
        assert client.get("/").status_code == 200


async def test_fast_trains(darwin):
    lbg = {s["id"]: s for s in (await build_board(darwin, station="LBG", now=NOW))["services"]}
    assert lbg["chx1"]["fast"] is True  # non-stop to Orpington
    assert lbg["cst1"]["fast"] is False  # stops at Hither Green, 24 min
    orp = {s["id"]: s for s in (await build_board(darwin, station="ORP", now=NOW))["services"]}
    assert orp["orp1"]["fast"] is True  # 17 min to London Bridge


async def test_durations(darwin):
    orp = {s["id"]: s for s in (await build_board(darwin, station="ORP", now=NOW))["services"]}
    # Leaves 11:06 (8 late), reaches LBG 11:23 and CHX 11:30.
    assert [(a["crs"], a["durationMin"]) for a in orp["orp1"]["arrivals"]] == [("LBG", 17), ("CHX", 24)]
    chx = {s["id"]: s for s in (await build_board(darwin, station="CHX", now=NOW))["services"]}
    assert chx["chx4"]["arrivals"][0]["durationMin"] is None  # cancelled
