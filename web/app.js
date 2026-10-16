"use strict";

const REFRESH_MS = 60_000;
// Reuse a recent fix so the board shows instantly; a fresh fix follows.
const COORDS_MAX_AGE_MS = 15 * 60_000;
const MOVED_KM = 0.3;
// Trains leaving sooner than this are shown faded: too soon to catch.
const SOON_MIN = 15;

const $ = (id) => document.getElementById(id);
const store = {
  get: (k) => { try { return JSON.parse(localStorage.getItem("rt." + k)); } catch { return null; } },
  set: (k, v) => v == null ? localStorage.removeItem("rt." + k) : localStorage.setItem("rt." + k, JSON.stringify(v)),
};

// ?station=CRS pins a station for this page only (handy as a bookmark).
const urlStation = new URLSearchParams(location.search).get("station");

let coords = null;      // {lat, lon, t} used for the board on screen
let inFlight = null;

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

// "London Charing Cross" -> "Charing Cross", but London Bridge stays whole.
const short = (name) => (name || "").replace(/London (?!Bridge)/g, "");

function km(a, b) {
  const r = Math.PI / 180;
  const x = (b.lon - a.lon) * r * Math.cos(((a.lat + b.lat) / 2) * r);
  const y = (b.lat - a.lat) * r;
  return Math.hypot(x, y) * 6371;
}

// ---- data -------------------------------------------------------------

const pinnedStation = () => urlStation || store.get("station");

async function load() {
  const station = pinnedStation();
  let query;
  if (station) query = `station=${encodeURIComponent(station)}`;
  else if (coords) query = `lat=${coords.lat.toFixed(5)}&lon=${coords.lon.toFixed(5)}`;
  else return;

  inFlight?.abort();
  const ctrl = (inFlight = new AbortController());
  $("refresh").classList.add("spin");
  try {
    const resp = await fetch(`api/board?${query}`, { signal: ctrl.signal });
    if (!resp.ok) throw new Error((await resp.json().catch(() => ({}))).detail || `HTTP ${resp.status}`);
    const board = await resp.json();
    board.fetchedAt = Date.now();
    store.set("board", board);
    render(board);
  } catch (e) {
    if (e.name === "AbortError") return;
    showNotice(`Couldn't load trains: ${e.message}`);
  } finally {
    if (inFlight === ctrl) { inFlight = null; $("refresh").classList.remove("spin"); }
  }
}

function locate() {
  if (!("geolocation" in navigator)) return noLocation("This browser can't share its location.");
  navigator.geolocation.getCurrentPosition(
    (pos) => {
      const fresh = { lat: pos.coords.latitude, lon: pos.coords.longitude, t: Date.now() };
      const moved = !coords || km(coords, fresh) > MOVED_KM;
      coords = fresh;
      store.set("coords", fresh);
      if (moved && !pinnedStation()) load();
    },
    (err) => { if (!coords) noLocation(err.code === err.PERMISSION_DENIED ? "Location access is off." : "Couldn't get your location."); },
    { enableHighAccuracy: false, maximumAge: 60_000, timeout: 15_000 },
  );
}

function noLocation(why) {
  if (pinnedStation()) return;
  showNotice(`${why} Tap the title to pick a station.`);
  $("route").textContent = "Pick a station";
}

function refresh() {
  if (!pinnedStation()) locate();
  load();
}

// ---- rendering --------------------------------------------------------

function showNotice(text, big = false) {
  const n = $("notice");
  n.textContent = text;
  n.className = big ? "notice big" : "notice";
  n.hidden = false;
}

function render(board) {
  $("notice").hidden = true;
  const list = $("services");
  const messages = $("messages");

  if (board.status === "outside_uk") {
    $("route").textContent = "Rail Table";
    $("mode").textContent = "";
    list.innerHTML = "";
    messages.hidden = true;
    showNotice("You're outside the UK 🌍", true);
    footer(board);
    return;
  }

  const { station, direction } = board;
  $("route").textContent = direction === "to_london" ? "Orpington → London" : `${short(station.name)} → Orpington`;
  $("mode").textContent = pinnedStation()
    ? "Chosen station · tap to change"
    : `Nearest${station.distanceKm != null ? ` · ${station.distanceKm} km away` : ""} · tap to change`;

  messages.innerHTML = board.messages.map((m) => `<li>${esc(m)}</li>`).join("");
  messages.hidden = !board.messages.length;

  list.innerHTML = board.services.map(row).join("");
  if (!board.services.length) showNotice("No trains in the next two hours.");
  footer(board);
}

function row(s) {
  let dep;
  if (s.status === "cancelled") dep = `<div class="dep bad"><s>${esc(s.std)}</s>Cancelled</div>`;
  else if (s.status === "delayed") dep = `<div class="dep late"><s>${esc(s.std)}</s>Delayed</div>`;
  else if (s.delayMin > 0) dep = `<div class="dep late">${esc(s.expected)} (+${s.delayMin}m)</div>`;
  else dep = `<div class="dep">${esc(s.std)}</div>`;

  // Nearly everything here is Southeastern, so only name anyone else.
  const meta = s.operator && s.operator !== "Southeastern" ? [`<span class="op">${esc(s.operator)}</span>`] : [];
  if (s.coaches) meta.push(`<span>${trainIcon()} ${s.coaches}</span>`);
  if (s.loading) meta.push(loadingBadge(s.loading));
  if (s.fast) meta.push(`<span class="fast-tag">Fast</span>`);

  const arr = s.status === "cancelled" ? "" : s.arrivals.map((a) => {
    const label = `${STATION_ICONS[a.crs] || a.crs} `;
    if (a.status === "cancelled") return `${label}<span class="late">cancelled</span>`;
    const late = a.delayMin > 0 || a.status === "delayed";
    const dur = a.durationMin != null ? ` <span class="dur">${a.durationMin}m</span>` : "";
    return `${label}<span class="${late ? "late" : ""}">${esc(a.expected || a.st)}</span>${dur}`;
  }).join(" · ");

  const reason = s.cancelReason || (s.status !== "on_time" && s.delayReason);
  const cls = ["svc", s.fast && "fast", minutesUntil(s.expected || s.std) < SOON_MIN && "soon"].filter(Boolean).join(" ");
  return `<li class="${cls}">
    <div class="line">
      <div class="dest"><span class="name">${esc(short(s.destination))}</span>${s.platform ? `<span class="plat">${esc(s.platform)}</span>` : ""}</div>
      ${dep}
    </div>
    <div class="line">
      <div class="meta">${meta.join(" ")}</div>
      <div class="arr">${arr}</div>
    </div>
    ${reason ? `<div class="reason ${s.cancelReason ? "" : "delay"}">${esc(reason)}</div>` : ""}
  </li>`;
}

// Minutes from now until HH:MM (London time), negative if just gone.
function minutesUntil(hhmm) {
  if (!/^\d\d:\d\d$/.test(hhmm || "")) return Infinity;
  const [h, m] = hhmm.split(":").map(Number);
  const now = new Date().toLocaleTimeString("en-GB", { timeZone: "Europe/London", hour: "2-digit", minute: "2-digit", hour12: false });
  const [nh, nm] = now.split(":").map(Number);
  return ((h * 60 + m - (nh * 60 + nm) + 1440 + 720) % 1440) - 720;
}

function loadingBadge(l) {
  if (l.level) {
    const text = { high: "Busy", medium: "Fairly busy", low: "Quiet" }[l.level];
    return `<span class="load ${l.level}" title="${l.pct}% full">${text}</span>`;
  }
  const bg = /^#?[0-9a-f]{3,8}$/i.test(l.colour || "") ? `background:#${l.colour.replace("#", "")}` : "background:var(--rule)";
  return `<span class="load" style="${bg}">${esc(l.label)}</span>`;
}

// Arrival icons: London Bridge = a bridge, Charing Cross = Big Ben and the
// London Eye, Orpington = home. Drawn in currentColor so they follow the text.
const STATION_ICONS = {
  LBG: `<svg class="st-icon" viewBox="0 0 24 16" width="24" height="16" fill="currentColor" role="img" aria-label="London Bridge"><title>London Bridge</title>
    <path d="M0 4h24v1.5H0z"/>
    <path d="M0 6.5h24V15h-1.5a3 5.5 0 0 0-6 0H15a3 5.5 0 0 0-6 0H7.5a3 5.5 0 0 0-6 0H0z"/></svg>`,
  CHX: `<svg class="st-icon" viewBox="0 0 30 18" width="30" height="18" role="img" aria-label="Charing Cross"><title>Charing Cross</title>
    <path fill="currentColor" fill-rule="evenodd" d="M3.2 18v-7.5H2.2V6h.6L5 0l2.2 6h.6v4.5H6.8V18zM5 6.7a1.55 1.55 0 1 0 0 3.1a1.55 1.55 0 1 0 0-3.1z"/>
    <g fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round">
      <circle cx="20" cy="8" r="6.5"/>
      <path d="M20 1.5v13M13.5 8h13M15.4 3.4l9.2 9.2M24.6 3.4l-9.2 9.2M20 8l-3.5 9.5M20 8l3.5 9.5"/>
    </g></svg>`,
  ORP: `<svg class="st-icon" viewBox="0 0 16 16" width="16" height="16" fill="currentColor" role="img" aria-label="Orpington"><title>Orpington</title>
    <path d="M8 1 .5 8H3v7h4v-4.5h2V15h4V8h2.5z"/></svg>`,
};

function trainIcon() {
  return `<svg width="13" height="15" viewBox="0 0 13 15" fill="currentColor" aria-label="coaches" style="vertical-align:-2px"><path d="M2.5 0h8A2.5 2.5 0 0 1 13 2.5v8a2.5 2.5 0 0 1-2 2.45L12.5 15h-2l-1.5-2H4l-1.5 2h-2L2 12.95A2.5 2.5 0 0 1 0 10.5v-8A2.5 2.5 0 0 1 2.5 0zM2 3v3.5h9V3zm1.5 6a1 1 0 1 0 0 2 1 1 0 0 0 0-2zm6 0a1 1 0 1 0 0 2 1 1 0 0 0 0-2z"/></svg>`;
}

let fetchedAt = null;

function footer(board) {
  fetchedAt = board.fetchedAt || Date.now();
  tickFooter();
}

function ago(ms) {
  const s = Math.max(0, Math.round(ms / 1000));
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60);
  return m < 60 ? `${m}m ${s % 60}s ago` : `${Math.floor(m / 60)}h ${m % 60}m ago`;
}

function tickFooter() {
  if (!fetchedAt) return;
  const hhmmss = new Date(fetchedAt).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  $("updated").textContent = `Updated ${hhmmss} · ${ago(Date.now() - fetchedAt)}`;
  $("updated").classList.toggle("stale", Date.now() - fetchedAt > 2 * REFRESH_MS);
}

// ---- station picker ---------------------------------------------------

let stationList = null;

async function openPicker() {
  const box = $("picker-options");
  if (!stationList) {
    try { stationList = await (await fetch("api/stations")).json(); }
    catch { stationList = []; }
  }
  const current = store.get("station");
  const opts = [{ crs: "", name: "Nearest station (automatic)" }, ...stationList];
  box.innerHTML = opts.map((s) =>
    `<button type="button" data-crs="${esc(s.crs)}" class="${(s.crs || null) === current ? "active" : ""}">${esc(s.name)}</button>`
  ).join("");
  $("picker").showModal();
}

$("picker-options").addEventListener("click", (e) => {
  const btn = e.target.closest("button[data-crs]");
  if (!btn) return;
  store.set("station", btn.dataset.crs || null);
  $("picker").close();
  if (urlStation) location.search = "";
  else refresh();
});

// ---- startup ----------------------------------------------------------

$("station-btn").addEventListener("click", openPicker);
$("refresh").addEventListener("click", refresh);
$("messages").addEventListener("click", () => $("messages").classList.toggle("open"));
document.addEventListener("visibilitychange", () => { if (!document.hidden) refresh(); });
setInterval(() => { if (!document.hidden) load(); }, REFRESH_MS);
setInterval(tickFooter, 1000);
// Re-fade rows as their departure gets close, between refreshes.
setInterval(() => { const b = store.get("board"); if (b && !document.hidden) render(b); }, 20_000);

const cachedBoard = store.get("board");
if (cachedBoard) render(cachedBoard);
const cachedCoords = store.get("coords");
if (cachedCoords && Date.now() - cachedCoords.t < COORDS_MAX_AGE_MS) coords = cachedCoords;
refresh();

if ("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js");
