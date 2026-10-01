#!/usr/bin/env bash
# Small, safe demo of the station geocoding pipeline.
#
# It runs every step on a handful of stations using throwaway databases, so your real
# database and data/stations_geocoded.csv are never touched:
#
#   1. import the stations into an empty database
#   2. locate N stations (OpenStreetMap exact position, else city centre)
#   3. export the result to a CSV file
#   4. restore that CSV into a second, brand-new database
#   5. check that the restored data is identical
#
# Usage: scripts/demo_geocoding.sh [N] [extra geocode_stations options]
#   scripts/demo_geocoding.sh            # 15 stations, about 20-30 seconds
#   scripts/demo_geocoding.sh 40         # a bigger sample
#   scripts/demo_geocoding.sh 15 --city-only   # offline, skips OpenStreetMap

set -euo pipefail
cd "$(dirname "$0")/.."

count="${1:-15}"
if [[ $# -gt 0 ]]; then
    shift
fi
if ! [[ "$count" =~ ^[1-9][0-9]*$ ]]; then
    echo "sample size must be a positive whole number, got '$count'" >&2
    exit 2
fi

python=".venv/bin/python"
if [[ ! -x "$python" ]]; then
    python="python"
fi

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

step() {
    printf '\n== %s ==\n' "$*"
}

step "1/5 Import the stations into a throwaway database"
export DATABASE_PATH="$work/demo.sqlite3"
"$python" manage.py migrate -v0
"$python" manage.py import_stations

step "2/5 Locate $count stations"
"$python" manage.py geocode_stations --limit "$count" --progress-every 5 "$@"

step "3/5 Export the locations to a CSV file"
"$python" manage.py export_station_locations "$work/locations.csv"

step "4/5 Restore them into a brand-new empty database"
export DATABASE_PATH="$work/restored.sqlite3"
"$python" manage.py migrate -v0
"$python" manage.py import_stations > /dev/null
"$python" manage.py load_station_locations "$work/locations.csv"

step "5/5 Check that the restored data is identical"
"$python" manage.py export_station_locations "$work/locations_again.csv" > /dev/null
if cmp -s "$work/locations.csv" "$work/locations_again.csv"; then
    echo "Round trip OK: the restored database holds exactly the same locations."
else
    echo "Round trip FAILED: the restored locations differ." >&2
    diff "$work/locations.csv" "$work/locations_again.csv" >&2 || true
    exit 1
fi

step "What was found"
"$python" manage.py shell -v 0 -c "
from apps.stations.models import Station

located = Station.objects.exclude(location_precision='').order_by('opis_id')
print(f'{'kind':5} {'station':36} {'city':18} {'lat':>9} {'lon':>10}')
for s in located:
    kind = 'exact' if s.location_precision == 'poi' else 'city'
    print(f'{kind:5} {s.name[:36]:36} {s.city[:16] + \", \" + s.state:18} '
          f'{s.latitude:9.4f} {s.longitude:10.4f}')
"
