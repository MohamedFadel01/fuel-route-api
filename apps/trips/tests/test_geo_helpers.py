"""The test helpers are themselves checked: a wrong helper would weaken every test using it."""

import math
import random
from itertools import pairwise

import pytest

from apps.common.geo import EARTH_RADIUS_MILES, Coordinates, haversine_miles
from apps.trips.tests.geo_helpers import (
    _bearing,
    along_track_miles,
    cross_track_miles,
    destination,
    north_of,
    random_route,
)

START = Coordinates(40.0, -100.0)
END = north_of(START, 100.0)


class TestDestination:
    @pytest.mark.parametrize("bearing", [0, 45, 90, 135, 180, 225, 270, 315])
    def test_lands_the_requested_distance_away(self, bearing):
        assert haversine_miles(START, destination(START, bearing, 37.5)) == pytest.approx(
            37.5, abs=1e-6
        )

    def test_compass_directions(self):
        north, east = destination(START, 0, 10), destination(START, 90, 10)
        south, west = destination(START, 180, 10), destination(START, 270, 10)

        assert north.latitude > START.latitude
        assert north.longitude == pytest.approx(START.longitude)
        assert south.latitude < START.latitude
        assert east.longitude > START.longitude
        assert west.longitude < START.longitude

    def test_going_there_and_back_returns_to_the_start(self):
        there = destination(START, 63.0, 250.0)
        # The bearing changes along a great circle, so the way back is not 63 + 180.
        way_back = math.degrees(_bearing(there, START))

        back = destination(there, way_back, 250.0)

        assert haversine_miles(START, back) < 1e-6

    def test_wraps_around_the_date_line(self):
        east = destination(Coordinates(0.0, 179.9), 90.0, 50.0)

        # 50 miles east of 179.9 is 179.9 + 0.7236 = 180.6236, which wraps to -179.3764.
        assert east.longitude == pytest.approx(179.9 + math.degrees(50 / EARTH_RADIUS_MILES) - 360)

    def test_a_zero_distance_stays_put(self):
        assert haversine_miles(START, destination(START, 123.0, 0.0)) < 1e-9

    def test_north_of_is_a_northward_destination(self):
        assert north_of(START, 12.0) == destination(START, 0.0, 12.0)


class TestAlongAndCrossTrack:
    @pytest.mark.parametrize("along", [0.0, 0.5, 10.0, 50.0, 99.5, 100.0])
    def test_a_point_on_the_route(self, along):
        point = north_of(START, along)

        assert along_track_miles(START, END, point) == pytest.approx(along, abs=1e-6)
        assert cross_track_miles(START, END, point) == pytest.approx(0.0, abs=1e-6)

    def test_a_point_behind_the_start_is_negative(self):
        assert along_track_miles(START, END, north_of(START, -5.0)) == pytest.approx(-5.0, abs=1e-6)

    def test_a_point_past_the_end_is_beyond_the_length(self):
        assert along_track_miles(START, END, north_of(START, 105.0)) == pytest.approx(
            105.0, abs=1e-6
        )

    @pytest.mark.parametrize("bearing", [90.0, 270.0])
    def test_sideways_distance_is_the_cross_track_and_does_not_move_the_point_along(self, bearing):
        beside = destination(north_of(START, 40.0), bearing, 7.0)

        assert cross_track_miles(START, END, beside) == pytest.approx(7.0, abs=1e-3)
        assert along_track_miles(START, END, beside) == pytest.approx(40.0, abs=1e-2)

    def test_the_start_itself(self):
        assert along_track_miles(START, END, START) == pytest.approx(0.0, abs=1e-9)
        assert cross_track_miles(START, END, START) == pytest.approx(0.0, abs=1e-9)

    def test_on_a_long_diagonal_route(self):
        new_york, los_angeles = Coordinates(40.7128, -74.0060), Coordinates(34.0522, -118.2437)
        middle = destination(new_york, 273.7, 1000.0)  # roughly along it

        assert 900 < along_track_miles(new_york, los_angeles, middle) < 1100
        assert cross_track_miles(new_york, los_angeles, middle) < 60


class TestRandomRoute:
    def test_is_a_list_of_valid_coordinates(self):
        route = random_route(random.Random(1))

        assert len(route) >= 2
        assert all(isinstance(vertex, Coordinates) for vertex in route)

    def test_the_same_seed_gives_the_same_route(self):
        assert random_route(random.Random(5)) == random_route(random.Random(5))

    def test_different_seeds_give_different_routes(self):
        assert random_route(random.Random(5)) != random_route(random.Random(6))

    def test_over_many_seeds_it_covers_messy_cases(self):
        routes = [random_route(random.Random(seed)) for seed in range(200)]

        assert any(a == b for route in routes for a, b in pairwise(route))
        assert any(abs(vertex.longitude) > 179 for route in routes for vertex in route)
        assert any(vertex.latitude > 80 for route in routes for vertex in route)
        assert all(
            math.isfinite(v.latitude) and math.isfinite(v.longitude) for r in routes for v in r
        )
