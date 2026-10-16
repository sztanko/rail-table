# Train Departure Board

(repo: `rail-table`) Next trains to and from **Orpington**, from whichever station you're nearest:
Charing Cross, Waterloo East, London Bridge, Orpington itself (→ London
Bridge / Charing Cross), or a station further south with trains calling at
Orpington. Delays, platforms, coaches, how full (where published) and arrival
time — on one page that opens straight to the list.

Live at **https://rail.geocube.work** — on Android, open it in Chrome and use
*Add to Home screen* to install it as an app. See [SPEC.md](SPEC.md) for the
full behaviour.

## Run locally

```sh
uv sync
cp .env.example .env            # add your RDM_API_KEY
set -a; . ./.env; set +a
.venv/bin/uvicorn rail_table.app:app --reload --port 8787
```

No key? `RAIL_FIXTURES_DIR=tests/fixtures` serves canned boards. Add
`?station=CHX` (any CRS from `/api/stations`) to the URL to skip geolocation.

```sh
.venv/bin/pytest
```

## API

`GET /api/board?lat=51.5&lon=-0.12` or `GET /api/board?station=ORP` — the
chosen station, direction, and services. `GET /api/stations` — candidates.

## Deploy (this server)

1. `bash deploy/install-service.sh` — systemd user service on 127.0.0.1:8787
   (reads `.env`).
2. `cloudflared tunnel route dns infinity rail.geocube.work` — once.
3. `sudo bash deploy/sudo-setup-rail-hosting.sh` — Caddy vhost + tunnel
   ingress, once.

Updates: pull in `~/workspace/rail-table`, then re-run step 1.

## Data

- Live departures: National Rail Darwin via the [Rail Data
  Marketplace](https://raildata.org.uk) Live Departure Board API (free,
  needs a key).
- Station coordinates: [davwheat/uk-railway-stations](https://github.com/davwheat/uk-railway-stations)
  (ODbL).
- UK outline: [Natural Earth](https://www.naturalearthdata.com) 1:50m (public domain).
