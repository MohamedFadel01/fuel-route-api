#!/bin/sh
# Bring the database up, then serve. Safe to run on every start: importing and
# loading locations again updates rows and keeps the coordinates already stored.
set -eu

python manage.py migrate --noinput
python manage.py import_stations
python manage.py load_station_locations

# One worker, because the saved-trip cache lives in that process. The routing
# client's timeout limits each wait, not the whole reply, so a server that
# trickles bytes could hold the worker. This limit ends that.
exec gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers 1 --timeout 30
