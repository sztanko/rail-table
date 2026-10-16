"""HTTP app: the JSON API plus the static one-page frontend."""

import hashlib
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse
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


@app.middleware("http")
async def revalidate_static(request, call_next):
    # Cloudflare would otherwise keep app.js/style.css for hours after a deploy.
    response = await call_next(request)
    response.headers.setdefault("Cache-Control", "no-cache")
    return response


def _asset_version() -> str:
    digest = hashlib.sha256()
    for name in ("app.js", "style.css"):
        digest.update((WEB_DIR / name).read_bytes())
    return digest.hexdigest()[:10]


@app.get("/", response_class=HTMLResponse)
@app.get("/index.html", response_class=HTMLResponse)
async def index():
    # Versioned asset URLs, so a deploy can never pair new HTML with stale JS.
    return (WEB_DIR / "index.html").read_text().replace("{{v}}", _asset_version())


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
