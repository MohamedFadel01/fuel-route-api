"""The request body for planning a trip: two places, each a latitude and a longitude."""

import math

import pytest

from apps.common.geo import Coordinates
from apps.trips.serializers import RouteRequestSerializer

AUSTIN = {"lat": 30.2672, "lon": -97.7431}
DALLAS = {"lat": 32.7767, "lon": -96.7970}


def request(start=AUSTIN, finish=DALLAS, **overrides):
    body = {"start": start, "finish": finish}
    body.update(overrides)
    return body


def errors_of(body):
    serializer = RouteRequestSerializer(data=body)
    assert not serializer.is_valid()
    return serializer.errors


class TestAValidRequest:
    def test_two_places_become_coordinates(self):
        serializer = RouteRequestSerializer(data=request())

        assert serializer.is_valid(), serializer.errors
        assert serializer.validated_data["start"] == Coordinates(30.2672, -97.7431)
        assert serializer.validated_data["finish"] == Coordinates(32.7767, -96.7970)

    def test_the_same_place_twice_is_allowed(self):
        serializer = RouteRequestSerializer(data=request(finish=AUSTIN))

        assert serializer.is_valid(), serializer.errors

    def test_whole_numbers_and_numeric_text_are_accepted(self):
        serializer = RouteRequestSerializer(
            data=request(start={"lat": 30, "lon": "-97.7431"}, finish=DALLAS)
        )

        assert serializer.is_valid(), serializer.errors
        assert serializer.validated_data["start"] == Coordinates(30.0, -97.7431)

    def test_extra_fields_are_ignored(self):
        serializer = RouteRequestSerializer(data=request(vehicle="truck"))

        assert serializer.is_valid(), serializer.errors
        assert set(serializer.validated_data) == {"start", "finish"}

    @pytest.mark.parametrize(
        "point",
        [
            {"lat": 21.3069, "lon": -157.8583},  # Honolulu
            {"lat": 61.2181, "lon": -149.9003},  # Anchorage
            {"lat": 43.6532, "lon": -79.3832},  # Toronto
        ],
    )
    def test_hawaii_alaska_and_canada_are_inside_the_area(self, point):
        serializer = RouteRequestSerializer(data=request(finish=point))

        assert serializer.is_valid(), serializer.errors


class TestMissingAndMalformed:
    def test_an_empty_body(self):
        errors = errors_of({})

        assert "start" in errors
        assert "finish" in errors

    @pytest.mark.parametrize("field", ["start", "finish"])
    def test_a_place_without_a_latitude_or_longitude(self, field):
        body = request()
        body[field] = {"lat": 30.0}

        assert "lon" in errors_of(body)[field]

    @pytest.mark.parametrize("value", ["abc", None, [], {}, True, False, math.nan, math.inf])
    def test_a_latitude_that_is_not_a_number(self, value):
        errors = errors_of(request(start={"lat": value, "lon": -97.7}))

        assert "lat" in errors["start"]

    def test_a_longitude_that_is_not_a_number(self):
        assert "lon" in errors_of(request(start={"lat": 30.0, "lon": "west"}))["start"]


class TestTheLimits:
    @pytest.mark.parametrize("latitude", [-90.1, 90.1, 300])
    def test_a_latitude_past_the_ends_of_the_earth(self, latitude):
        errors = errors_of(request(start={"lat": latitude, "lon": -97.7}))

        assert "lat" in errors["start"]
        assert "90" in str(errors["start"]["lat"])

    @pytest.mark.parametrize("longitude", [-180.1, 180.1])
    def test_a_longitude_past_the_date_line(self, longitude):
        errors = errors_of(request(start={"lat": 30.0, "lon": longitude}))

        assert "lon" in errors["start"]
        assert "180" in str(errors["start"]["lon"])

    @pytest.mark.parametrize(
        ("name", "point"),
        [
            ("London", {"lat": 51.5074, "lon": -0.1278}),
            ("Mexico City", {"lat": 19.4326, "lon": -99.1332}),
            ("Sydney", {"lat": -33.8688, "lon": 151.2093}),
        ],
    )
    def test_a_place_outside_the_united_states_and_canada(self, name, point):
        message = str(errors_of(request(finish=point))["finish"])

        assert "Canada" in message, name

    def test_both_places_outside_the_area_are_both_reported(self):
        errors = errors_of(
            request(
                start={"lat": 51.5074, "lon": -0.1278},
                finish={"lat": -33.8688, "lon": 151.2093},
            )
        )

        assert "Canada" in str(errors["start"])
        assert "Canada" in str(errors["finish"])

    def test_a_bad_latitude_is_reported_rather_than_the_area(self):
        # 91 is not a place, so the message is about the number, not about the area.
        message = str(errors_of(request(start={"lat": 91, "lon": -97.7}))["start"])

        assert "90" in message
        assert "Canada" not in message
