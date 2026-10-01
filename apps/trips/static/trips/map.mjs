// The map page. This file is inlined into the HTML, and the tests import it directly.
// Station names are written with textContent, never as HTML.

export const NETWORK_ERROR = "Could not reach the server.";
export const SLOW_SERVER = "The server took too long. Try again.";
const PLAN_TIMEOUT_MS = 30_000;

const START = { radius: 8, color: "#145c38", fillColor: "#1b7f4e", fillOpacity: 1, weight: 2 };
const FINISH = { radius: 8, color: "#6e1d1d", fillColor: "#9d2c2c", fillOpacity: 1, weight: 2 };
const STOP = { radius: 7, color: "#8a4b08", fillColor: "#e6a23c", fillOpacity: 0.95, weight: 2 };

export function fromLeaflet(latlng) {
  return { lat: latlng.lat, lon: latlng.lng };
}

export function afterClick(state, point) {
  if (state.start && !state.finish) {
    return { start: state.start, finish: point, plan: true };
  }
  return { start: point, finish: null, plan: false };
}

export function requestBody(start, finish) {
  return {
    start: { lat: start.lat, lon: start.lon },
    finish: { lat: finish.lat, lon: finish.lon },
  };
}

export function samePlace(start, finish) {
  return start.lat === finish.lat && start.lon === finish.lon;
}

export function instructions(state, busy) {
  if (busy) return "Planning the trip…";
  if (!state.start) return "Click the map to set the start, then click again to set the finish.";
  if (!state.finish) return "Now click the finish.";
  return "Click the map to plan a different trip.";
}

export function stopText(stop) {
  const station = stop?.station ?? {};
  const title = [station.name, station.city, station.state].filter(Boolean).join(", ");
  const gallons = stop?.gallons ?? "";
  const price = stop?.price_per_gallon ?? "";
  const cost = stop?.cost ?? "";
  const detail = gallons ? `${gallons} gal at $${price} · $${cost}` : "";
  return { title, detail };
}

export function describePlan(plan) {
  if (!plan?.route || !plan?.totals || !Array.isArray(plan.fuel_stops)) return null;
  const miles = Number(plan.route.distance_miles);
  if (!Number.isFinite(miles)) return null;
  const shown = miles.toLocaleString("en-US", { maximumFractionDigits: 1 });
  const stops = plan.fuel_stops.map(stopText);
  const count = plan.fuel_stops.length;
  const note =
    count === 0
      ? "No fuel stops. The starting tank covers this trip."
      : `${count} ${count === 1 ? "stop" : "stops"} · ${plan.totals.gallons_purchased} gallons bought`;
  return {
    headline: `${shown} miles · $${plan.totals.total_cost}`,
    note,
    stops,
  };
}

export function describeError(body) {
  if (body && typeof body.detail === "string" && body.detail) return body.detail;
  if (body && typeof body === "object") {
    const lines = [];
    for (const [key, value] of Object.entries(body)) {
      const text = Array.isArray(value) ? value.join(" ") : String(value);
      if (!text) continue;
      lines.push(key === "non_field_errors" ? text : `${key}: ${text}`);
    }
    if (lines.length) return lines.join(" ");
  }
  return "The trip could not be planned.";
}

export function routeFetch(body, fetchImpl = globalThis.fetch, timeoutMs = PLAN_TIMEOUT_MS) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  if (typeof timer.unref === "function") timer.unref();
  return Promise.resolve()
    .then(() =>
      fetchImpl("/api/v1/route/", {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify(body),
        signal: controller.signal,
      }),
    )
    .finally(() => clearTimeout(timer));
}

function failureMessage(error) {
  if (error && (error.name === "TimeoutError" || error.name === "AbortError")) return SLOW_SERVER;
  return NETWORK_ERROR;
}

export async function loadPlan(start, finish, post) {
  let response;
  try {
    response = await post("/api/v1/route/", requestBody(start, finish));
  } catch (error) {
    return { ok: false, message: failureMessage(error) };
  }
  let body = null;
  try {
    body = await response.json();
  } catch {
    body = null;
  }
  if (!response.ok) return { ok: false, message: describeError(body) };
  const described = describePlan(body);
  if (!described) return { ok: false, message: "The trip could not be planned." };
  return { ok: true, plan: body, described };
}

function boot() {
  // Leaflet's own script sets a global. A module does not see that name on its own.
  const L = globalThis.L;
  const map = L.map("map", { zoomControl: false, doubleClickZoom: false }).setView([39.8, -98.6], 4);
  L.control.zoom({ position: "topright" }).addTo(map);
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 18,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
  }).addTo(map);

  const instructionsEl = document.querySelector("#instructions");
  const statusEl = document.querySelector("#status");
  const summaryEl = document.querySelector("#summary");
  const noteEl = document.querySelector("#note");
  const stopsEl = document.querySelector("#stops");
  const resultEl = document.querySelector("#result");

  let state = { start: null, finish: null };
  let busy = false;
  let requestId = 0;
  let routeLine = null;
  let lastBounds = null;
  const markers = [];

  function showInstructions() {
    instructionsEl.textContent = instructions(state, busy);
  }

  function clearRoute() {
    if (routeLine) {
      map.removeLayer(routeLine);
      routeLine = null;
    }
    lastBounds = null;
  }

  function clearMarkers() {
    for (const marker of markers) map.removeLayer(marker);
    markers.length = 0;
  }

  function addMarker(point, style) {
    const marker = L.circleMarker([point.lat, point.lon], style).addTo(map);
    markers.push(marker);
    return marker;
  }

  function showEnds() {
    clearMarkers();
    if (state.start) addMarker(state.start, START);
    if (state.finish) addMarker(state.finish, FINISH);
  }

  function hideResult() {
    resultEl.hidden = true;
    summaryEl.textContent = "";
    noteEl.textContent = "";
    stopsEl.replaceChildren();
  }

  function showResult(described) {
    resultEl.hidden = false;
    summaryEl.textContent = described.headline;
    noteEl.textContent = described.note;
    stopsEl.replaceChildren();
    for (const stop of described.stops) {
      const item = document.createElement("li");
      const title = document.createElement("strong");
      title.textContent = stop.title;
      const detail = document.createElement("div");
      detail.textContent = stop.detail;
      item.append(title, detail);
      stopsEl.append(item);
    }
  }

  function drawPlan(plan) {
    clearRoute();
    clearMarkers();
    routeLine = L.geoJSON(
      { type: "Feature", properties: {}, geometry: plan.route.geometry },
      { style: { color: "#1d4e89", weight: 4 } },
    ).addTo(map);
    if (state.start) addMarker(state.start, START);
    if (state.finish) addMarker(state.finish, FINISH);
    for (const stop of plan.fuel_stops) {
      const station = stop.station;
      if (!station || !Number.isFinite(station.lat) || !Number.isFinite(station.lon)) continue;
      const marker = addMarker(station, STOP);
      const text = stopText(stop);
      const node = document.createElement("div");
      node.className = "popup";
      node.textContent = text.detail ? `${text.title}\n${text.detail}` : text.title;
      marker.bindPopup(node);
    }
    lastBounds = routeLine.getBounds();
    frameRoute();
  }

  function frameRoute() {
    if (!lastBounds || !lastBounds.isValid()) return;
    if (state.start && state.finish && samePlace(state.start, state.finish)) {
      map.setView([state.start.lat, state.start.lon], 12);
      return;
    }
    // Keep the line out from under the panel, but never pad by more than the map has.
    const size = map.getSize();
    const left = Math.min(window.innerWidth > 700 ? 380 : 28, Math.max(0, size.x / 2 - 40));
    try {
      map.fitBounds(lastBounds, { paddingTopLeft: [left, 28], paddingBottomRight: [28, 28] });
    } catch {
      // A very small map can refuse the frame. The line is already drawn.
    }
  }

  async function planTrip() {
    const id = ++requestId;
    busy = true;
    showInstructions();
    statusEl.textContent = "";
    try {
      const result = await loadPlan(state.start, state.finish, (_url, body) => routeFetch(body));
      if (id !== requestId) return;
      if (!result.ok) {
        hideResult();
        clearRoute();
        statusEl.textContent = result.message;
        return;
      }
      statusEl.textContent = "";
      showResult(result.described);
      try {
        drawPlan(result.plan);
      } catch {
        statusEl.textContent = "The trip is planned, but the map could not draw it.";
      }
    } catch {
      if (id !== requestId) return;
      hideResult();
      clearRoute();
      statusEl.textContent = "The trip could not be planned.";
    } finally {
      if (id === requestId) {
        busy = false;
        showInstructions();
      }
    }
  }

  map.on("click", (event) => {
    state = afterClick(state, fromLeaflet(event.latlng));
    clearRoute();
    hideResult();
    statusEl.textContent = "";
    showEnds();
    if (state.plan) {
      planTrip();
    } else {
      // A new start cancels a trip that was still being planned.
      requestId += 1;
      busy = false;
      showInstructions();
    }
  });

  window.addEventListener("resize", () => {
    map.invalidateSize();
    frameRoute();
  });

  document.querySelector("#reset").addEventListener("click", () => {
    requestId += 1;
    busy = false;
    state = { start: null, finish: null };
    clearRoute();
    clearMarkers();
    hideResult();
    statusEl.textContent = "";
    showInstructions();
  });

  showInstructions();
}

if (typeof document !== "undefined") {
  try {
    boot();
  } catch {
    const status = document.querySelector("#status");
    if (status) {
      status.textContent = "The map could not be loaded. Check your connection and reload the page.";
    }
  }
}
