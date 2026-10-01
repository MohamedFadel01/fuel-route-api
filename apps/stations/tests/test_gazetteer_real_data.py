"""Checks the gazetteer against the real GeoNames files and the real CSV.

These files are large and git-ignored, so the tests are skipped when they are absent.
Download them with ``python manage.py geocode_stations`` (a later step) or by hand into
``data/geonames/``.
"""

import csv

import pytest
from django.conf import settings

from apps.stations.geocoding.gazetteer import CityGazetteer

GEONAMES_DIR = settings.GEONAMES_DIR
ZIPS = {"US": GEONAMES_DIR / "US.zip", "CA": GEONAMES_DIR / "CA.zip"}

pytestmark = pytest.mark.skipif(
    not all(path.exists() for path in ZIPS.values()),
    reason="GeoNames files are not downloaded",
)


@pytest.fixture(scope="module")
def gazetteer():
    return CityGazetteer.from_geonames_zips(ZIPS)


@pytest.mark.parametrize(
    ("city", "state", "latitude", "longitude"),
    [
        ("Austin", "TX", 30.27, -97.74),
        ("Big Cabin", "OK", 36.54, -95.22),
        ("St. Louis", "MO", 38.63, -90.2),
        ("Toronto", "ON", 43.7, -79.4),
    ],
)
def test_known_cities_are_found_near_their_real_position(
    gazetteer, city, state, latitude, longitude
):
    found = gazetteer.lookup(city, state)

    assert found is not None
    assert found.latitude == pytest.approx(latitude, abs=0.2)
    assert found.longitude == pytest.approx(longitude, abs=0.2)


def test_almost_every_city_in_the_fuel_price_file_is_found(gazetteer):
    with settings.FUEL_PRICES_CSV.open(newline="", encoding="utf-8") as handle:
        pairs = {(row["City"], row["State"]) for row in csv.DictReader(handle)}

    missing = sorted(pair for pair in pairs if gazetteer.lookup(*pair) is None)

    assert len(missing) / len(pairs) < 0.005, missing
