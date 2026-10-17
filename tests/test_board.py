from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from rail_table.board import LONDON_TZ, _expected, build_board
from rail_table.darwin import Darwin

FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 10, 15, 11, 0, tzinfo=LONDON_TZ)


@pytest.fixture
async def darwin():
    d = Darwin(api_key=None, fixtures_dir=FIXTURES)
    yield d
    await d.aclose()


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
    # Ordered by Orpington arrival: chx3 leaves before chx2 but gets there later.
    assert [s["id"] for s in board["services"]] == ["chx1", "chx2", "chx3", "chx4", "chx5"]
    assert first["delayMin"] == 8 and first["expected"] == "10:58" and first["coaches"] == 10
    assert first["arrivals"][0]["expected"] == "11:22"
    assert second["loading"] == {"level": "high", "pct": 85}
    assert fourth["status"] == "cancelled" and "train crew" in fourth["cancelReason"]
    assert fifth["loading"]["level"] == "low"


async def test_orpington_goes_to_london(darwin):
    board = await build_board(darwin, 51.375, 0.098, now=NOW)
    assert board["station"]["crs"] == "ORP"
    assert board["direction"] == "to_london"
    # orp1 appears on both the LBG and CHX boards but is listed once; it is
    # timetabled 10:58 but expected 11:06, so the on-time 11:04 goes first.
    assert [s["id"] for s in board["services"]] == ["orp2", "orp1", "orp3"]
    assert [a["crs"] for a in board["services"][1]["arrivals"]] == ["LBG", "CHX"]
    assert board["messages"] == ["Disruption between Sevenoaks & Tonbridge."]


@pytest.mark.parametrize(
    "lat, lon, outside",
    [
        (48.857, 2.352, True),  # Paris
        (52.480, -1.903, True),  # Birmingham
        (50.822, -0.137, False),  # Brighton, ~70 km
        (50.858, 0.577, False),  # Hastings, end of the line
    ],
)
async def test_outside_london(darwin, lat, lon, outside):
    board = await build_board(darwin, lat, lon, now=NOW)
    assert (board["status"] == "outside_london") is outside


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


def test_index_versions_assets(monkeypatch):
    monkeypatch.setenv("RAIL_FIXTURES_DIR", str(FIXTURES))
    from rail_table.app import app

    with TestClient(app) as client:
        resp = client.get("/")
        assert "{{v}}" not in resp.text and "app.js?v=" in resp.text
        assert client.get("/app.js").headers["cache-control"] == "no-cache"
        assert client.get("/api/board", params={"station": "ORP"}).headers["cache-control"] == "no-store"


async def test_ordered_by_arrival(darwin):
    # From Orpington: orp2 (Cannon Street) reaches LBG 11:30, orp1 reaches CHX
    # 11:30 too; the tie goes to orp2, which leaves first (11:04 vs 11:06).
    board = await build_board(darwin, station="ORP", now=NOW)
    assert [s["id"] for s in board["services"]] == ["orp2", "orp1", "orp3"]
