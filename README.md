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
