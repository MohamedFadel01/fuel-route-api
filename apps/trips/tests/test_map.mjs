import assert from "node:assert/strict";
import { test } from "node:test";

import {
  NETWORK_ERROR,
  afterClick,
  describeError,
  describePlan,
  fromLeaflet,
  instructions,
  loadPlan,
  requestBody,
  routeFetch,
  samePlace,
  stopText,
} from "../static/trips/map.mjs";

const austin = { lat: 30.2672, lon: -97.7431 };
const dallas = { lat: 32.7767, lon: -96.797 };

test("the first click sets the start and does not plan yet", () => {
  const next = afterClick({ start: null, finish: null }, austin);

  assert.deepEqual(next, { start: austin, finish: null, plan: false });
});

test("the second click sets the finish and plans", () => {
  const next = afterClick({ start: austin, finish: null }, dallas);

  assert.deepEqual(next, { start: austin, finish: dallas, plan: true });
});

test("a third click starts a new trip instead of moving the finish", () => {
  const next = afterClick({ start: austin, finish: dallas }, { lat: 29, lon: -98 });

  assert.deepEqual(next, { start: { lat: 29, lon: -98 }, finish: null, plan: false });
});

test("a click does not change the state it was given", () => {
  const state = { start: austin, finish: null };

  afterClick(state, dallas);

  assert.deepEqual(state, { start: austin, finish: null });
});

test("a leaflet click is latitude then longitude, not the other way round", () => {
  const point = fromLeaflet({ lat: 30.2672, lng: -97.7431 });

  assert.deepEqual(point, austin);
  assert.notDeepEqual(point, { lat: -97.7431, lon: 30.2672 });
});

test("the request body is the two places the API expects", () => {
  assert.deepEqual(requestBody(austin, dallas), {
    start: { lat: 30.2672, lon: -97.7431 },
    finish: { lat: 32.7767, lon: -96.797 },
  });
});

test("the same place twice is still a trip", () => {
  assert.equal(samePlace(austin, austin), true);
  assert.equal(samePlace(austin, dallas), false);
});

test("instructions follow the clicks, and a wait overrides them", () => {
  const empty = { start: null, finish: null };
  const started = { start: austin, finish: null };
  const both = { start: austin, finish: dallas };

  assert.match(instructions(empty, false), /start/i);
  assert.match(instructions(started, false), /finish/i);
  assert.match(instructions(both, false), /different trip/i);
  assert.match(instructions(started, true), /planning/i);
});

test("a plan with no stops says the tank covers the trip", () => {
  const described = describePlan({
    route: { distance_miles: 195.1, geometry: { type: "LineString", coordinates: [] } },
    fuel_stops: [],
    totals: { total_cost: "0.00", gallons_purchased: "0.000" },
  });

  assert.equal(described.headline, "195.1 miles · $0.00");
  assert.match(described.note, /starting tank/i);
  assert.deepEqual(described.stops, []);
});

test("a plan lists each stop and does not recompute the cost", () => {
  const described = describePlan({
    route: { distance_miles: 1379.34, geometry: { type: "LineString", coordinates: [] } },
    fuel_stops: [
      {
        station: { name: "Llanos Country Corner", city: "Eden", state: "TX", lat: 1, lon: 2 },
        gallons: "5.293",
        price_per_gallon: "2.919",
        cost: "15.45",
      },
    ],
    totals: { total_cost: "244.85", gallons_purchased: "80.000" },
  });

  assert.equal(described.headline, "1,379.3 miles · $244.85");
  assert.match(described.note, /1 stop/);
  assert.equal(described.stops.length, 1);
  assert.match(described.stops[0].title, /Llanos Country Corner, Eden, TX/);
  assert.match(described.stops[0].detail, /5\.293 gal at \$2\.919 · \$15\.45/);
});

test("two stops are called stops", () => {
  const described = describePlan({
    route: { distance_miles: 10, geometry: {} },
    fuel_stops: [{ station: { name: "A" } }, { station: { name: "B" } }],
    totals: { total_cost: "1.00", gallons_purchased: "1.000" },
  });

  assert.match(described.note, /2 stops/);
});

test("a station name is kept as text, including characters that look like html", () => {
  const text = stopText({
    station: { name: 'Café "Fuel" <b>', city: "Town", state: "TX" },
    gallons: "1.000",
    price_per_gallon: "3.00",
    cost: "3.00",
  });

  assert.equal(text.title, 'Café "Fuel" <b>, Town, TX');
});

test("a broken plan is not described", () => {
  assert.equal(describePlan(null), null);
  assert.equal(describePlan({ route: {}, totals: {} }), null);
  assert.equal(describePlan({ route: {}, totals: {}, fuel_stops: "nope" }), null);
});

test("a distance that is not a real number is not shown as NaN miles", () => {
  const totals = { total_cost: "0.00", gallons_purchased: "0.000" };

  assert.equal(describePlan({ route: {}, totals, fuel_stops: [] }), null);
  assert.equal(describePlan({ route: { distance_miles: Number.NaN }, totals, fuel_stops: [] }), null);
  assert.equal(describePlan({ route: { distance_miles: 0 }, totals, fuel_stops: [] }).headline, "0 miles · $0.00");
});

test("an error message prefers the server's detail", () => {
  assert.equal(describeError({ detail: "Impossible route between points" }), "Impossible route between points");
});

test("a rejected place names the field", () => {
  const message = describeError({
    start: ["This point is outside the area we cover (the United States and Canada)."],
    finish: ["A valid number is required."],
  });

  assert.match(message, /start: This point is outside/);
  assert.match(message, /finish: A valid number is required/);
});

test("an empty or missing error still says the trip was not planned", () => {
  assert.match(describeError(null), /could not be planned/i);
  assert.match(describeError({}), /could not be planned/i);
  assert.match(describeError("nope"), /could not be planned/i);
});

test("a successful answer is returned with its summary", async () => {
  const plan = {
    route: { distance_miles: 10, geometry: { type: "LineString", coordinates: [] } },
    fuel_stops: [],
    totals: { total_cost: "0.00", gallons_purchased: "0.000" },
  };
  const calls = [];
  const result = await loadPlan(austin, dallas, async (url, body) => {
    calls.push({ url, body });
    return { ok: true, json: async () => plan };
  });

  assert.deepEqual(calls, [{ url: "/api/v1/route/", body: requestBody(austin, dallas) }]);
  assert.equal(result.ok, true);
  assert.equal(result.plan, plan);
  assert.equal(result.described.headline, "10 miles · $0.00");
});

test("a refusal comes back as the server's message", async () => {
  const result = await loadPlan(austin, dallas, async () => ({
    ok: false,
    json: async () => ({ detail: "Your start point is 100.5 miles from the nearest road (the limit is 5)." }),
  }));

  assert.equal(result.ok, false);
  assert.match(result.message, /100\.5 miles/);
});

test("a slow server is not described as unreachable", async () => {
  const error = new Error("The operation was aborted due to timeout");
  error.name = "TimeoutError";

  const result = await loadPlan(austin, dallas, async () => {
    throw error;
  });

  assert.deepEqual(result, { ok: false, message: "The server took too long. Try again." });
  assert.doesNotMatch(result.message, /aborted|timeout/i);
});

test("the route request stops waiting", async () => {
  const error = await routeFetch(
    requestBody(austin, dallas),
    (_url, init) =>
      new Promise((_resolve, reject) => {
        init.signal.addEventListener("abort", () => {
          const aborted = new Error("aborted");
          aborted.name = "AbortError";
          reject(aborted);
        });
      }),
    20,
  ).catch((caught) => caught);

  assert.equal(error.name, "AbortError");
});

test("a server that does not answer is a short message", async () => {
  const result = await loadPlan(austin, dallas, async () => {
    throw new Error("connect ECONNREFUSED 127.0.0.1");
  });

  assert.deepEqual(result, { ok: false, message: NETWORK_ERROR });
  assert.doesNotMatch(result.message, /ECONNREFUSED/);
});

test("a page of html instead of json is not thrown at the reader", async () => {
  const result = await loadPlan(austin, dallas, async () => ({
    ok: false,
    json: async () => {
      throw new SyntaxError("Unexpected token <");
    },
  }));

  assert.equal(result.ok, false);
  assert.match(result.message, /could not be planned/i);
});
