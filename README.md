# fuel-route-api

Send a start and a finish in the United States or Canada. The API returns the driving route and the fuel stops that cost the least, and the money those stops come to.

The truck starts with a full tank. It can go 500 miles and does 10 mpg, so that first tank is 50 gallons and it is not charged. After that it buys fuel at stations from the price file, along the road. [How a trip is planned](docs/how-a-trip-is-planned.md) walks through one real drive, Austin to Denver, and shows each calculation.

## Run it

Docker is the whole setup. The first start creates the database, loads the prices, and restores the station locations already saved in this repo. It does not call the geocoder.

```bash
docker compose up --build
```

Then open [http://localhost:8000/map/](http://localhost:8000/map/). Click once for the start, again for the finish. A third click begins a new trip. Start over clears the map.

The page itself comes from the API. The browser then loads the map library and the map tiles, so it needs a network connection. Planning one trip calls the public routing server once. Asking for the same two places again, within an hour, does not.

The server stops a request after 30 seconds. The map stops waiting at the same point. One worker handles requests, because a saved trip lives in that process's memory.

To run without Docker, use the development setup below and then `python manage.py runserver`. The page is [http://127.0.0.1:8000/map/](http://127.0.0.1:8000/map/).

## Plan a trip

`POST /api/v1/route/` with JSON. The address needs the trailing slash.

Austin to Dallas fits in the starting tank, so nothing is bought:

```bash
curl -s -H 'Content-Type: application/json' \
  -d '{"start":{"lat":30.2672,"lon":-97.7431},"finish":{"lat":32.7767,"lon":-96.7970}}' \
  http://localhost:8000/api/v1/route/
```

```json
{
  "route": {
    "distance_miles": 195.078,
    "measured_miles": 195.456,
    "duration_seconds": 12467.7,
    "geometry": { "type": "LineString", "coordinates": [[-97.74313, 30.267208]] }
  },
  "fuel_stops": [],
  "totals": {
    "gallons_purchased": "0.000",
    "gallons_consumed": "19.546",
    "total_cost": "0.00"
  },
  "margin_miles": 10.0
}
```

`distance_miles` is the length the routing service reported. `measured_miles` is the length of the geometry, and the fuel figures use that. They usually agree to a fraction of a percent. `geometry.coordinates` is GeoJSON, so each point is longitude then latitude. The real Dallas answer has a few thousand points; one is shown here.

Austin to Los Angeles does not fit in one tank. On the public routing server this came back as 1,379 miles, 5 stops, and `"total_cost": "244.85"`, with `"margin_miles": 10`. The first stop looked like this:

```json
{
  "station": {
    "id": 72803,
    "name": "Llanos Country Corner",
    "city": "Junction",
    "state": "TX",
    "lat": 30.48936,
    "lon": -99.77201
  },
  "mile_marker": 138.983,
  "price_per_gallon": "2.919",
  "gallons": "5.293",
  "cost": "15.45"
}
```

Prices, gallons, and costs are strings, so a cent is a cent. A price can keep more than two decimal places (`"2.80233333"`). The road and the prices move when the public server or the file changes, so a later run can differ slightly.

The same requests are in [postman/fuel-route-api.postman_collection.json](postman/fuel-route-api.postman_collection.json). Import it and it talks to `http://localhost:8000`.

| Status | When |
| --- | --- |
| 200 | A plan. |
| 400 | The body is not the two places, a number is missing or out of range, or a place is outside the area. The body names the field. |
| 415 | The body is not JSON. |
| 422 | There is no road, a place is more than 5 miles from a road, or no stations along the road can fuel the truck (tried at 10, 25, and 50 miles). `{"detail": "..."}`. |
| 502 | The routing service failed or sent something unusable. |
| 504 | The routing service took too long. |
| 405 | Any method other than POST. |

A request to `/api/v1/route` (no trailing slash) is redirected to `/api/v1/route/`.

## How a plan is chosen

Stations are kept if they sit within 10 miles of the road. If that set cannot get the truck to the finish, the search widens to 25 miles and then to 50. `margin_miles` says which one was used.

Standing at a station, if a strictly cheaper one is within a full tank, the truck buys only enough to reach the nearest such station. Otherwise it fills the tank and drives to the cheapest station it can still reach. The finish needs no purchase. Side trips off the road into a station are not added to the miles.

Gallons are rounded to a thousandth and each stop's cost to the cent, halves up. The totals are the sums of those rounded stops.

An identical trip is remembered for an hour (`TRIP_CACHE_SECONDS`). A price change during that hour is not seen until the hour is up. Set the variable to `0` to ask every time.

## Assumptions

- The price file repeats some stations. The row with the lowest price is the one that is kept.
- Canadian stations are included.
- The truck starts full. That fuel is not on the bill. You pay only for gallons bought along the way.
- A station is either an exact place (`poi`) or its city centre (`city`). Several stations of one chain in a city share a centre, and none of those is labelled exact.
- The covered area is the continental United States, Canada, Alaska out to Dutch Harbor, and Hawaii. Puerto Rico and the US Virgin Islands are outside it. The price file has no stations there.
- The routing server is the public OSRM demo at `https://router.project-osrm.org`. It is meant for light use and sometimes answers with an error. Point `OSRM_BASE_URL` at your own server for anything heavier.
- A start or finish more than 5 miles from a road is refused (`MAX_SNAP_MILES`). The trip would not be the one that was asked for.

## Development setup

Requires Python 3.12+ (developed on 3.14).

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements/dev.txt
cp .env.example .env   # optional, see the file for available settings
```

Common commands:

```bash
pytest                          # run the tests
ruff check . && ruff format .   # lint and format
python manage.py migrate        # create the database tables
python manage.py import_stations          # prices and names (safe to re-run)
python manage.py load_station_locations    # coordinates, from data/stations_geocoded.csv
python manage.py runserver                 # http://127.0.0.1:8000/map/
```

## Station locations

The fuel price file has no coordinates, so each station is located in two tiers:

1. **Exact position** from OpenStreetMap (Nominatim), accepted only if it is in the right
   state, near the station's city and has a name that plausibly matches the station.
2. **City centre** from GeoNames, when no verified exact position exists.

Each station is labelled `poi` (exact) or `city` (approximate: somewhere in its city). A
search for a chain name returns one place, which would otherwise be given to every store of
that chain in the city. So whenever several stations end up on the same position, none of
them is called exact: they are relabelled `city` (their position is kept).
`geocode_stations` does this at the end of every run; `demote_shared_locations` does it on
its own.

```bash
python manage.py geocode_stations              # locate stations not yet located (resumable)
python manage.py geocode_stations --limit 20   # try a small batch first
python manage.py geocode_stations --city-only  # city centres only, no Nominatim (fast, offline)
python manage.py geocode_stations --redo-city  # retry the OpenStreetMap lookup for city-centre stations
```

Nominatim allows one request per second, so a full run takes about two hours. Progress is
saved after every station: stop it with Ctrl+C and run it again to continue. Set
`NOMINATIM_USER_AGENT` (see `.env.example`) to identify yourself, as the Nominatim usage
policy requires. The GeoNames files (`data/geonames/US.zip`, `CA.zip`) are downloaded on the
first run.

### Saving and restoring the result

Because the full run is slow, its result is committed as `data/stations_geocoded.csv`
(`opis_id, latitude, longitude, location_precision`). Anyone can restore it in a moment:

```bash
python manage.py import_stations           # prices and names, from the OPIS CSV
python manage.py load_station_locations    # locations, from data/stations_geocoded.csv
```

To regenerate the file after a geocoding run: `python manage.py export_station_locations`.

### Try it on a small sample first

```bash
scripts/demo_geocoding.sh          # 15 stations, about 30 seconds
scripts/demo_geocoding.sh 40       # a bigger sample
scripts/demo_geocoding.sh 15 --city-only   # offline, skips OpenStreetMap
```

The demo imports, locates, exports, restores into a second empty database and checks that
the restored data is identical. It uses throwaway databases, so nothing of yours is changed.
