"""The map page: one HTML document you open in a browser.

The click-by-click behaviour lives in the page's script and is checked separately.
Here the page has to come back at all, with the pieces that script expects, and without
asking the database or the routing service.
"""

from pathlib import Path

import pytest
from django.contrib.staticfiles import finders
from rest_framework.test import APIClient

PAGE = "/map/"
SCRIPT = Path("apps/trips/static/trips/map.mjs")
STYLE = Path("apps/trips/static/trips/map.css")


@pytest.fixture
def client():
    return APIClient()


@pytest.mark.django_db
def test_the_page_loads(client, django_assert_num_queries):
    with django_assert_num_queries(0):
        response = client.get(PAGE)

    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/html")
    html = response.content.decode()
    assert 'id="map"' in html
    assert 'id="instructions"' in html
    assert 'id="summary"' in html
    assert 'id="stops"' in html
    assert 'id="status"' in html
    assert "Start over" in html
    # The script and the style are part of the page. Static files are not served on their
    # own unless debug mode is on, and this project leaves debug off.
    assert "leaflet@1.9.4" in html
    assert "/api/v1/route/" in html
    assert "OpenStreetMap" in html
    assert html.count("<script") == 2  # Leaflet, then our page
    assert "&quot;" not in html.split('<script type="module">', 1)[1]


def test_the_page_refuses_to_be_put_in_a_frame(client):
    response = client.get(PAGE)

    assert response["X-Frame-Options"] == "DENY"


def test_posting_to_the_page_is_not_how_you_plan_a_trip(client):
    response = client.post(PAGE, {"start": {"lat": 40, "lon": -100}}, format="json")

    assert response.status_code == 405


def test_the_address_without_a_slash_redirects_to_the_page(client):
    response = client.get("/map")

    assert response.status_code == 301
    assert response["Location"].endswith("/map/")


def test_the_script_treats_station_names_as_text():
    source = SCRIPT.read_text()

    assert "innerHTML" not in source
    assert "insertAdjacentHTML" not in source
    # The script is pasted into the page. A closing tag in it would end the script early.
    assert "</script>" not in source.lower()
    assert "</style>" not in STYLE.read_text().lower()
    assert finders.find("trips/map.mjs")
    assert finders.find("trips/map.css")
    assert STYLE.read_text().strip()
