"""National Rail Darwin departure boards via the Rail Data Marketplace (LDBWS REST)."""

import asyncio
import json
import time
from pathlib import Path

import httpx

DEFAULT_BASE = "https://api1.raildata.org.uk/1010-live-departure-board-dep1_2/LDBWS/api/20220120"
CACHE_SECONDS = 30
# LDBWS caps the "with details" boards at 10 services.
NUM_ROWS = 10
TIME_WINDOW_MINUTES = 120


class DarwinError(Exception):
    pass


class Darwin:
    """Fetches departure boards, with a short in-memory cache.

    With `fixtures_dir` set, boards are read from `<CRS>-<filterCrs>.json`
    files instead of the network — for development without an API key.
    """

    def __init__(self, api_key: str | None, base: str = DEFAULT_BASE, fixtures_dir: Path | None = None):
        self._api_key = api_key
        self._base = base.rstrip("/")
        self._fixtures = fixtures_dir
        self._cache: dict[tuple[str, str], tuple[float, dict]] = {}
        self._locks: dict[tuple[str, str], asyncio.Lock] = {}
        self._http = httpx.AsyncClient(timeout=10)

    async def aclose(self) -> None:
        await self._http.aclose()

    async def departures(self, crs: str, calling_at: str) -> dict:
        """Departures from `crs` in the next two hours that call at `calling_at`."""
        key = (crs, calling_at)
        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            hit = self._cache.get(key)
            if hit and time.monotonic() - hit[0] < CACHE_SECONDS:
                return hit[1]
            board = await self._fetch(crs, calling_at)
            self._cache[key] = (time.monotonic(), board)
            return board

    async def _fetch(self, crs: str, calling_at: str) -> dict:
        if self._fixtures:
            path = self._fixtures / f"{crs}-{calling_at}.json"
            return json.loads(path.read_text()) if path.exists() else {"trainServices": []}
        if not self._api_key:
            raise DarwinError("No Rail Data Marketplace API key configured")
        try:
            resp = await self._http.get(
                f"{self._base}/GetDepBoardWithDetails/{crs}",
                params={
                    "numRows": NUM_ROWS,
                    "filterCrs": calling_at,
                    "filterType": "to",
                    "timeWindow": TIME_WINDOW_MINUTES,
                },
                headers={"x-apikey": self._api_key},
            )
            resp.raise_for_status()
        except httpx.HTTPError as e:
            raise DarwinError(f"Darwin request failed: {e}") from e
        return resp.json()
