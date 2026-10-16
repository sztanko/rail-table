# Train Departure Board (rail-table) — spec

A one-page web app that, opened on a phone, immediately shows the next trains
that matter for getting to or from **Orpington**, from whichever relevant
station you are nearest to.

## Behaviour

1. The page asks the browser for the current location.
2. **Outside the UK** → show "You're outside the UK" and nothing else.
3. Otherwise pick the **nearest candidate station** (straight-line distance):
   - London: **Charing Cross (CHX)**, **Waterloo East (WAE)**, **London Bridge (LBG)**
   - **Orpington (ORP)**
   - Stations south of Orpington on lines whose trains call at Orpington
     (Chelsfield, Knockholt, Dunton Green, Sevenoaks, Tonbridge, the Tunbridge
     Wells/Hastings line, …).
   - A southern station only counts if it actually has a train calling at
     Orpington in the next 2 hours; otherwise fall through to the next nearest.
4. **At Orpington** → list trains to London that call at **London Bridge or
   Charing Cross** (Cannon Street trains count, via London Bridge).
   **No Victoria trains.** Arrival time shown is at LBG/CHX.
5. **Anywhere else** → list only trains that **call at Orpington**, with the
   Orpington arrival time.
6. The chosen station can be overridden with a tap (kept until cleared).

## Per train

- Scheduled departure, and expected time / delay (`+8m`), or **Cancelled**
  (with reason when given)
- Platform
- Destination and operator
- Number of coaches
- How full (Darwin loading category or average coach loading — only where the
  operator publishes it)
- Arrival time at Orpington (or at LBG/CHX when departing Orpington),
  expected if known

Plus: station name, "updated HH:MM", auto-refresh every ~60 s while visible,
pull/tap to refresh. Dark theme, compact, readable at a glance (see the
"On Rails" screenshot this was modelled on).

## Data

- **National Rail Darwin**, via the free **Rail Data Marketplace** "Live
  Departure Board" product (LDBWS REST/JSON, `x-apikey` header):
  `GET https://api1.raildata.org.uk/1010-live-departure-board-dep1_2/LDBWS/api/20220120/GetDepBoardWithDetails/{crs}?filterCrs=…&filterType=to&timeWindow=120`
- UK outline: Natural Earth (public domain), simplified, for the
  in/out-of-UK check.
- Station coordinates: static list in the repo.

Free sources only.

## Architecture

The data needs a secret API key and isn't callable cross-origin from a
browser, so there is a small backend:

- **Backend**: Python (FastAPI) — `GET /api/board?lat=&lon=[&station=]`
  does the UK check, station choice, Darwin calls (cached ~30 s), filtering,
  and returns a compact JSON. Also serves the frontend.
- **Frontend**: static HTML/CSS/vanilla JS, installable as a PWA (home-screen
  icon on the Pixel 5, opens straight to the list).
- **Hosting**: `https://rail.geocube.work` on this server — systemd user
  service on loopback, Caddy vhost on `:8080`, Cloudflare Tunnel ingress.
  Public (no auth) for now.

## Not in scope (for now)

- A true Android home-screen widget (needs a native app; could later read the
  same `/api/board` JSON).
- Victoria trains; other stations between London and Orpington.
