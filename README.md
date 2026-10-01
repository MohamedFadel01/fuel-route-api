# fuel-route-api

Django REST API for optimizing fuel stops along US routes based on vehicle range, fuel prices, and total fuel cost.

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
python manage.py import_stations  # load data/fuel-prices-for-be-assessment.csv (safe to re-run)
python manage.py runserver      # start the dev server
```

## Station locations

The fuel price file has no coordinates, so each station is located in two tiers:

1. **Exact position** from OpenStreetMap (Nominatim), accepted only if it is in the right
   state, near the station's city and has a name that plausibly matches the station.
2. **City centre** from GeoNames, when no verified exact position exists.

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
