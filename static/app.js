"use strict";

const METERS_TO_FEET = 3.28084;
const MPS_TO_KNOTS = 1.94384;
const state = { aircraft: [], filtered: [], filter: "all", query: "", maxAltitude: 60000, selected: null };
const $ = (selector) => document.querySelector(selector);

let globe;
let toastTimer;
let serviceStatus = { requiresRefreshKey: false };
let detailTouchStartY = null;

function altitudeMeters(aircraft) {
  return aircraft.geoAltitude ?? aircraft.baroAltitude ?? 0;
}

function altitudeFeet(aircraft) {
  return altitudeMeters(aircraft) * METERS_TO_FEET;
}

function altitudeColor(aircraft) {
  if (aircraft.onGround) return "#728895";
  const feet = altitudeFeet(aircraft);
  if (feet < 10000) return "#43f1c4";
  if (feet < 30000) return "#56e8ff";
  if (feet < 45000) return "#ffc75a";
  return "#ff738a";
}

function pointAltitude(aircraft) {
  if (aircraft.onGround) return 0.002;
  return Math.min(0.035, 0.006 + altitudeFeet(aircraft) / 1_800_000);
}

function initializeGlobe() {
  globe = Globe({ animateIn: true, waitForGlobeReady: true })($("#globe"))
    .globeImageUrl("/vendor/earth-night.jpg")
    .backgroundColor("rgba(0,0,0,0)")
    .showAtmosphere(true)
    .atmosphereColor("#3bcbe6")
    .atmosphereAltitude(0.18)
    .pointLat("latitude")
    .pointLng("longitude")
    .pointAltitude(pointAltitude)
    .pointColor(altitudeColor)
    .pointRadius((aircraft) => aircraft.onGround ? 0.075 : 0.11)
    .pointResolution(5)
    .pointsTransitionDuration(500)
    .pointLabel(() => "") // Explicitly disable Globe.gl's default hover label.
    .onPointClick(selectAircraft);

  globe.controls().autoRotate = true;
  globe.controls().autoRotateSpeed = 0.24;
  globe.controls().enableDamping = true;
  const initialAltitude = window.matchMedia("(max-width: 820px)").matches ? 3.4 : 2.35;
  globe.pointOfView({ lat: 24, lng: -18, altitude: initialAltitude }, 900);
  resizeGlobe();
  window.addEventListener("resize", resizeGlobe);
}

function resizeGlobe() {
  placeAircraftCard();
  if (!globe) return;
  globe
    .width(window.innerWidth)
    .height(window.innerHeight)
    .pointRadius((aircraft) => {
      const base = aircraft.onGround ? 0.075 : 0.11;
      return window.innerWidth <= 820 ? base * 1.65 : base;
    });
}

function placeAircraftCard() {
  const card = $("#aircraft-card");
  const target = window.matchMedia("(max-width: 820px)").matches ? $(".app-shell") : $(".right-rail");
  if (card.parentElement !== target) target.appendChild(card);
}

function formatNumber(value, suffix = "") {
  return value == null || !Number.isFinite(value) ? "—" : `${Math.round(value).toLocaleString()}${suffix}`;
}

function filterAircraft() {
  const query = state.query.toLowerCase();
  state.filtered = state.aircraft.filter((aircraft) => {
    if (state.filter === "airborne" && aircraft.onGround) return false;
    if (state.filter === "ground" && !aircraft.onGround) return false;
    if (altitudeFeet(aircraft) > state.maxAltitude) return false;
    if (!query) return true;
    return [aircraft.callsign, aircraft.icao24, aircraft.country]
      .some((value) => String(value || "").toLowerCase().includes(query));
  });
  globe.pointsData(state.filtered);
  updateMetrics();
}

function updateMetrics() {
  const airborne = state.filtered.filter((aircraft) => !aircraft.onGround);
  const ground = state.filtered.length - airborne.length;
  const altitudes = airborne.map(altitudeFeet).filter((value) => value > 0);
  const speeds = airborne.map((aircraft) => aircraft.velocity == null ? null : aircraft.velocity * MPS_TO_KNOTS).filter((value) => value != null);
  const average = (values) => values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : null;
  $("#metric-visible").textContent = state.filtered.length.toLocaleString();
  $("#metric-airborne").textContent = airborne.length.toLocaleString();
  $("#metric-ground").textContent = ground.toLocaleString();
  $("#metric-altitude").textContent = formatNumber(average(altitudes));
  $("#metric-speed").textContent = formatNumber(average(speeds));
}

function selectAircraft(aircraft) {
  state.selected = aircraft;
  $("#aircraft-card").classList.remove("empty");
  $("#aircraft-empty").hidden = true;
  $("#aircraft-detail").hidden = false;
  $("#detail-callsign").textContent = aircraft.callsign || "UNIDENTIFIED";
  $("#detail-country").textContent = aircraft.country || "Unknown origin";
  $("#detail-icao").textContent = String(aircraft.icao24 || "—").toUpperCase();
  $("#detail-altitude").textContent = aircraft.onGround ? "GROUND" : formatNumber(altitudeFeet(aircraft), " FT");
  $("#detail-speed").textContent = formatNumber(aircraft.velocity == null ? null : aircraft.velocity * MPS_TO_KNOTS, " KT");
  $("#detail-track").textContent = formatNumber(aircraft.trueTrack, "°");
  $("#detail-vertical").textContent = formatNumber(aircraft.verticalRate == null ? null : aircraft.verticalRate * 196.85, " FPM");
  $("#detail-squawk").textContent = aircraft.squawk || "—";
  globe.controls().autoRotate = false;
  // Selection updates the detail card without moving the camera.
}

function setDetailExpanded(expanded) {
  const card = $("#aircraft-card");
  const toggle = $("#detail-toggle");
  card.classList.toggle("expanded", expanded);
  toggle.textContent = expanded ? "↓" : "↑";
  toggle.setAttribute("aria-expanded", String(expanded));
  toggle.setAttribute("aria-label", expanded ? "Collapse aircraft details" : "Expand aircraft details");
}

function applySnapshot(snapshot) {
  state.aircraft = snapshot.aircraft || [];
  $("#welcome").classList.add("hidden");
  $("#status-dot").classList.add("live");
  $("#status-label").textContent = "SNAPSHOT LOADED";
  $("#last-refresh").textContent = new Date(snapshot.fetchedAt).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  filterAircraft();
}

function applyStatus(status) {
  serviceStatus = status;
  const quota = status.quota;
  $("#quota-value").textContent = `${quota.spent.toLocaleString()} / ${quota.budget.toLocaleString()}`;
  $("#quota-bar").style.width = `${Math.min(100, quota.spent / quota.budget * 100)}%`;
  if (status.hasSnapshot) {
    $("#status-dot").classList.add("live");
    $("#status-label").textContent = "SNAPSHOT CACHED";
  }
}

async function api(path, options) {
  const response = await fetch(path, options);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(payload.error || `Request failed (${response.status})`);
    error.status = response.status;
    error.code = payload.code;
    throw error;
  }
  return payload;
}

function refreshKey() {
  if (!serviceStatus.requiresRefreshKey) return null;
  let key = sessionStorage.getItem("openskyRefreshKey");
  if (!key) {
    key = window.prompt("Enter the dashboard owner refresh key:")?.trim();
    if (key) sessionStorage.setItem("openskyRefreshKey", key);
  }
  return key || null;
}

async function refreshAircraft() {
  const key = refreshKey();
  if (serviceStatus.requiresRefreshKey && !key) return;
  const buttons = [$("#refresh-button"), $("#welcome-refresh")];
  buttons.forEach((button) => { button.disabled = true; });
  $("#refresh-button").classList.add("loading");
  $("#status-label").textContent = "REQUESTING OPENSKY";
  try {
    const headers = key ? { "X-Refresh-Key": key } : {};
    const payload = await api("/api/aircraft/refresh", { method: "POST", headers });
    let snapshot;
    if (payload.queued) {
      $("#status-label").textContent = "WAITING FOR COLLECTOR";
      snapshot = await waitForQueuedSnapshot(serviceStatus.lastRefresh);
    } else {
      snapshot = payload.snapshot || await api(payload.snapshotUrl);
    }
    applySnapshot(snapshot);
    applyStatus(payload.status);
  } catch (error) {
    if (error.status === 401) sessionStorage.removeItem("openskyRefreshKey");
    $("#status-label").textContent = "REFRESH FAILED";
    showToast(error.message);
  } finally {
    buttons.forEach((button) => { button.disabled = false; });
    $("#refresh-button").classList.remove("loading");
  }
}

async function waitForQueuedSnapshot(previousRefresh) {
  for (let attempt = 0; attempt < 40; attempt += 1) {
    await new Promise((resolve) => setTimeout(resolve, 2000));
    const current = await api("/api/status");
    applyStatus(current);
    if (current.hasSnapshot && current.lastRefresh !== previousRefresh) {
      return api(current.snapshotUrl);
    }
    if (!current.refreshPending) {
      throw new Error("The collector did not complete the requested refresh.");
    }
  }
  throw new Error("The collector is offline or the refresh timed out.");
}

function showToast(message) {
  const toast = $("#toast");
  toast.textContent = message;
  toast.classList.add("visible");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.remove("visible"), 5000);
}

function bindControls() {
  $("#refresh-button").addEventListener("click", refreshAircraft);
  $("#welcome-refresh").addEventListener("click", refreshAircraft);
  $("#search-input").addEventListener("input", (event) => { state.query = event.target.value.trim(); filterAircraft(); });
  $("#altitude-range").addEventListener("input", (event) => {
    state.maxAltitude = Number(event.target.value);
    $("#altitude-label").textContent = `${state.maxAltitude.toLocaleString()} ft`;
    filterAircraft();
  });
  document.querySelectorAll(".filter-chip").forEach((button) => button.addEventListener("click", () => {
    document.querySelectorAll(".filter-chip").forEach((chip) => chip.classList.remove("active"));
    button.classList.add("active");
    state.filter = button.dataset.filter;
    filterAircraft();
  }));
  $("#reset-filters").addEventListener("click", () => {
    state.query = ""; state.filter = "all"; state.maxAltitude = 60000;
    $("#search-input").value = ""; $("#altitude-range").value = "60000"; $("#altitude-label").textContent = "60,000 ft";
    document.querySelectorAll(".filter-chip").forEach((chip) => chip.classList.toggle("active", chip.dataset.filter === "all"));
    filterAircraft();
  });
  $("#mobile-filter-button").addEventListener("click", () => $(".filter-panel").classList.add("open"));
  $("#close-filters").addEventListener("click", () => $(".filter-panel").classList.remove("open"));
  $("#detail-toggle").addEventListener("click", () => {
    setDetailExpanded(!$("#aircraft-card").classList.contains("expanded"));
  });
  $("#aircraft-card").addEventListener("touchstart", (event) => {
    detailTouchStartY = event.touches[0]?.clientY ?? null;
  }, { passive: true });
  $("#aircraft-card").addEventListener("touchend", (event) => {
    if (detailTouchStartY == null) return;
    const delta = (event.changedTouches[0]?.clientY ?? detailTouchStartY) - detailTouchStartY;
    if (delta < -45) setDetailExpanded(true);
    if (delta > 45) setDetailExpanded(false);
    detailTouchStartY = null;
  }, { passive: true });
}

function startClock() {
  const update = () => { $("#utc-clock").textContent = `${new Date().toISOString().slice(11, 19)} UTC`; };
  update();
  setInterval(update, 1000); // UI clock only. This never calls OpenSky or a local API.
}

async function initialize() {
  initializeGlobe();
  bindControls();
  startClock();
  try {
    const status = await api("/api/status");
    applyStatus(status);
    if (status.hasSnapshot) applySnapshot(await api(status.snapshotUrl || "/api/aircraft"));
  } catch (error) {
    showToast(error.message);
  }
  // Intentionally no timer or automatic refresh. See README.md before adding one.
}

window.addEventListener("DOMContentLoaded", initialize);
