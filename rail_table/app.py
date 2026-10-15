"""HTTP app: the JSON API plus the static one-page frontend."""

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .board import build_board
from .darwin import DEFAULT_BASE, Darwin, DarwinError
from .stations import all_stations

WEB_DIR = Path(__file__).resolve().parent.parent / "web"


@asynccontextmanager
async def lifespan(app: FastAPI):
    fixtures = os.environ.get("RAIL_FIXTURES_DIR")
    app.state.darwin = Darwin(
        api_key=os.environ.get("RDM_API_KEY"),
        base=os.environ.get("RDM_BASE", DEFAULT_BASE),
        fixtures_dir=Path(fixtures) if fixtures else None,
    )
    yield
    await app.state.darwin.aclose()


app = FastAPI(title="rail-table", lifespan=lifespan, docs_url=None, redoc_url=None)


@app.get("/api/board")
async def board(
    lat: float | None = Query(None, ge=-90, le=90),
    lon: float | None = Query(None, ge=-180, le=180),
    station: str | None = None,
):
    if station is not None:
        station = station.upper()
        if station not in all_stations():
            raise HTTPException(400, f"Unknown station {station}")
    elif lat is None or lon is None:
        raise HTTPException(400, "Give lat and lon, or station")
    try:
        result = await build_board(app.state.darwin, lat, lon, station)
    except DarwinError as e:
        raise HTTPException(502, str(e)) from e
    return JSONResponse(result, headers={"Cache-Control": "no-store"})


@app.get("/api/stations")
async def stations():
    return [{"crs": s.crs, "name": s.name, "role": s.role} for s in all_stations().values()]


app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
