"""POST /api/v1/route/: the whole trip, as JSON.

The routing service is a fake. The stations are rows in the test database. Nothing here
touches the network.
"""

import json
import math

import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

from apps.trips.providers.base import (
    NoRouteFoundError,
    RoutingError,
    RoutingServiceError,
    RoutingTimeoutError,
)
from apps.trips.tests.geo_helpers import north_of
from apps.trips.tests.test_service import ORIGIN, FakeRouting, road, station_at

URL = "/api/v1/route/"
pytestmark = pytest.mark.django_db


@pytest.fixture
def client():
    return APIClient()


@pytest.fixture(autouse=True)
def _empty_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def fake_router(monkeypatch):
    """Install a routing service that serves one prepared route and counts the calls."""

    def install(route):
        routing = FakeRouting(route)
        monkeypatch.setattr("apps.trips.services.get_shared_client", lambda: routing)
        return routing

    return install


def places(start, finish):
    return {
        "start": {"lat": start.latitude, "lon": start.longitude},
        "finish": {"lat": finish.latitude, "lon": finish.longitude},
    }


class TestAPlannedTrip:
    def test_the_response_has_the_road_the_stops_and_the_cost(
        self, client, fake_router, make_station
    ):
        route, finish = road(600, distance_miles=9999, duration_seconds=40000)
        point = north_of(ORIGIN, 300)
        station = station_at(make_station, point, name="MIDWAY FUEL", city="Nowhere", state="KS")
        routing = fake_router(route)

        response = client.post(URL, places(ORIGIN, finish), format="json")

        assert response.status_code == 200
        assert response["Content-Type"].startswith("application/json")
        body = response.json()
        assert set(body) == {"route", "fuel_stops", "totals", "margin_miles"}
        assert body["route"]["distance_miles"] == 9999  # what the router reported
        assert body["route"]["measured_miles"] == pytest.approx(600, abs=0.05)
        assert body["route"]["duration_seconds"] == 40000
        assert body["route"]["geometry"] == {
            "type": "LineString",
            # GeoJSON is longitude first, then latitude, to six decimals (about 10 cm).
            "coordinates": [
                [float(format(point.longitude, ".6f")), float(format(point.latitude, ".6f"))]
                for point in route.coordinates
            ],
        }
        assert body["margin_miles"] == 10
        assert body["fuel_stops"] == [
            {
                "station": {
                    "id": station.opis_id,
                    "name": "MIDWAY FUEL",
                    "city": "Nowhere",
                    "state": "KS",
                    # Where the station is, so a map can drop a pin on it.
                    "lat": float(format(point.latitude, ".6f")),
                    "lon": float(format(point.longitude, ".6f")),
                },
                "mile_marker": pytest.approx(300, abs=0.5),
                "price_per_gallon": "3.00",
                "gallons": "10.000",
                "cost": "30.00",
            }
        ]
        assert body["totals"] == {
            "gallons_purchased": "10.000",
            "gallons_consumed": "60.000",
            "total_cost": "30.00",
        }
        assert len(routing.calls) == 1
        # Money and gallons are text, so nothing is rounded by the JSON number format.
        assert isinstance(body["totals"]["total_cost"], str)
        assert isinstance(body["fuel_stops"][0]["gallons"], str)

    def test_a_short_trip_has_no_stops_and_costs_nothing(self, client, fake_router):
        route, finish = road(200)
        fake_router(route)

        body = client.post(URL, places(ORIGIN, finish), format="json").json()

        assert body["fuel_stops"] == []
        assert body["totals"]["total_cost"] == "0.00"
        assert body["totals"]["gallons_purchased"] == "0.000"
        assert body["totals"]["gallons_consumed"] == "20.000"

    def test_a_price_with_extra_decimal_places_is_kept(self, client, fake_router, make_station):
        route, finish = road(600)
        station_at(make_station, north_of(ORIGIN, 300), price="3.0599")
        fake_router(route)

        stop = client.post(URL, places(ORIGIN, finish), format="json").json()["fuel_stops"][0]

        assert stop["price_per_gallon"] == "3.0599"
        assert stop["cost"] == "30.60"  # 10.000 gallons at 3.0599, to the cent

    def test_the_database_is_read_once_and_a_repeat_reads_nothing(
        self, client, fake_router, make_station, django_assert_num_queries
    ):
        route, finish = road(600)
        station_at(make_station, north_of(ORIGIN, 300))
        routing = fake_router(route)
        payload = places(ORIGIN, finish)

        with django_assert_num_queries(1):
            first = client.post(URL, payload, format="json")
        with django_assert_num_queries(0):
            second = client.post(URL, payload, format="json")

        assert first.status_code == second.status_code == 200
        assert second.json() == first.json()
        assert len(routing.calls) == 1

    def test_the_first_point_of_the_road_is_longitude_then_latitude(self, client, fake_router):
        route, finish = road(200)
        fake_router(route)

        point = client.post(URL, places(ORIGIN, finish), format="json").json()["route"]["geometry"][
            "coordinates"
        ][0]

        assert point == [ORIGIN.longitude, ORIGIN.latitude]
        assert point != [ORIGIN.latitude, ORIGIN.longitude]

    def test_miles_and_coordinates_are_short_numbers(self, client, fake_router, make_station):
        # A straight 600-mile road measures 599.9999999999991. Sent raw, that is what the
        # caller would read, against a fuel total that already rounds to 60 gallons.
        route, finish = road(600, distance_miles=1379.339812345, duration_seconds=12467.65)
        station_at(make_station, north_of(ORIGIN, 300))
        fake_router(route)

        body = client.post(URL, places(ORIGIN, finish), format="json").json()

        assert _fraction_digits(body["route"]["distance_miles"]) <= 3
        assert _fraction_digits(body["route"]["measured_miles"]) <= 3
        assert _fraction_digits(body["route"]["duration_seconds"]) <= 1
        assert _fraction_digits(body["fuel_stops"][0]["mile_marker"]) <= 3
        assert _fraction_digits(body["fuel_stops"][0]["station"]["lat"]) <= 6
        assert _fraction_digits(body["fuel_stops"][0]["station"]["lon"]) <= 6
        for longitude, latitude in body["route"]["geometry"]["coordinates"]:
            assert _fraction_digits(longitude) <= 6
            assert _fraction_digits(latitude) <= 6
        assert body["route"]["measured_miles"] == 600
        assert body["totals"]["gallons_consumed"] == "60.000"


class TestBadRequests:
    def test_a_missing_place(self, client):
        response = client.post(URL, {"start": {"lat": 40, "lon": -100}}, format="json")

        assert response.status_code == 400
        assert "finish" in response.json()

    def test_a_latitude_past_the_end_of_the_earth(self, client):
        response = client.post(
            URL, places_raw({"lat": 91, "lon": -100}, {"lat": 41, "lon": -100}), format="json"
        )

        assert response.status_code == 400
        assert "90" in str(response.json())

    def test_a_place_outside_the_area(self, client):
        response = client.post(
            URL,
            places_raw({"lat": 51.5074, "lon": -0.1278}, {"lat": 40, "lon": -100}),
            format="json",
        )

        assert response.status_code == 400
        assert "Canada" in str(response.json())

    @pytest.mark.parametrize("payload", ["{", "null", "[]", ""])
    def test_a_body_that_is_not_a_json_object(self, client, payload):
        response = client.post(URL, data=payload, content_type="application/json")

        assert response.status_code == 400
        assert response["Content-Type"].startswith("application/json")

    def test_a_body_that_is_not_json_at_all(self, client):
        response = client.post(URL, data="start=1", content_type="text/plain")

        assert response.status_code == 415

    def test_get_is_not_allowed(self, client):
        response = client.get(URL)

        assert response.status_code == 405

    def test_a_broken_snap_limit_is_a_bad_request_not_a_crash(self, client, fake_router, settings):
        settings.MAX_SNAP_MILES = math.nan
        route, finish = road(200)
        fake_router(route)

        response = client.post(URL, places(ORIGIN, finish), format="json")

        assert response.status_code == 400
        assert "MAX_SNAP_MILES" in response.json()["detail"]


class TestTripsThatCannotBePlanned:
    def test_no_road_between_the_places(self, client, fake_router):
        routing = fake_router(NoRouteFoundError("Impossible route between points"))

        response = client.post(URL, places(ORIGIN, north_of(ORIGIN, 200)), format="json")
        again = client.post(URL, places(ORIGIN, north_of(ORIGIN, 200)), format="json")

        assert response.status_code == again.status_code == 422
        assert response.json() == {"detail": "Impossible route between points"}
        assert len(routing.calls) == 2  # a failure is not remembered

    def test_a_point_far_from_any_road(self, client, fake_router, settings):
        settings.MAX_SNAP_MILES = 5
        route, finish = road(200, start_snap_miles=100.5)
        fake_router(route)

        response = client.post(URL, places(ORIGIN, finish), format="json")

        assert response.status_code == 422
        assert response.json()["detail"] == (
            "Your start point is 100.5 miles from the nearest road (the limit is 5)."
        )

    def test_a_point_just_past_the_limit_is_not_described_as_on_it(
        self, client, fake_router, settings
    ):
        settings.MAX_SNAP_MILES = 5
        route, finish = road(200, finish_snap_miles=5.04)
        fake_router(route)

        response = client.post(URL, places(ORIGIN, finish), format="json")

        assert response.status_code == 422
        assert response.json()["detail"] == (
            "Your finish point is 5.04 miles from the nearest road (the limit is 5)."
        )

    def test_no_way_to_buy_fuel_along_the_road(self, client, fake_router):
        route, finish = road(600)
        fake_router(route)

        response = client.post(URL, places(ORIGIN, finish), format="json")

        assert response.status_code == 422
        assert "50" in response.json()["detail"]
        assert set(response.json()) == {"detail"}


class TestWhenTheRouterFails:
    def test_a_route_that_is_not_a_line_is_502(self, client, fake_router):
        from apps.trips.providers.base import ProviderRoute

        fake_router(ProviderRoute(coordinates=(ORIGIN,), distance_miles=1, duration_seconds=1))

        response = client.post(URL, places(ORIGIN, north_of(ORIGIN, 10)), format="json")

        assert response.status_code == 502
        assert "cannot be used" in response.json()["detail"]

    def test_a_timeout_is_504(self, client, fake_router):
        fake_router(RoutingTimeoutError("The routing service did not answer within 10 seconds."))

        response = client.post(URL, places(ORIGIN, north_of(ORIGIN, 200)), format="json")

        assert response.status_code == 504
        assert "10" in response.json()["detail"]

    def test_any_other_failure_is_502_and_stays_short(self, client, fake_router):
        fake_router(RoutingServiceError("Could not reach the routing service (ConnectionError)."))

        response = client.post(URL, places(ORIGIN, north_of(ORIGIN, 200)), format="json")

        assert response.status_code == 502
        body = response.json()
        assert body == {"detail": "Could not reach the routing service (ConnectionError)."}
        assert "Traceback" not in str(body)

    def test_an_unclassified_routing_failure_is_502(self, client, fake_router):
        fake_router(RoutingError("The routing service failed."))

        response = client.post(URL, places(ORIGIN, north_of(ORIGIN, 200)), format="json")

        assert response.status_code == 502
        assert response.json() == {"detail": "The routing service failed."}

    @pytest.mark.parametrize(
        "overrides",
        [
            {"distance_miles": math.nan},
            {"duration_seconds": math.inf},
            {"distance_miles": -1.0},
            {"duration_seconds": -5.0},
        ],
    )
    def test_an_unusable_length_is_502_and_not_remembered(
        self, client, fake_router, overrides, django_assert_num_queries
    ):
        route, finish = road(200, **overrides)
        routing = fake_router(route)
        payload = places(ORIGIN, finish)

        with django_assert_num_queries(0):
            response = client.post(URL, payload, format="json")
        again = client.post(URL, payload, format="json")

        assert response.status_code == again.status_code == 502
        assert response.json()["detail"] == (
            "The routing service sent a distance or duration that cannot be used."
        )
        assert len(routing.calls) == 2


def _fraction_digits(number: float) -> int:
    return len(json.dumps(number).partition(".")[2])


def places_raw(start, finish):
    return {"start": start, "finish": finish}
