import dataclasses
import math

import pytest

from apps.common.geo import EARTH_RADIUS_MILES, Coordinates, haversine_miles

NEW_YORK = Coordinates(40.7128, -74.0060)
LOS_ANGELES = Coordinates(34.0522, -118.2437)


class TestCoordinates:
    def test_holds_latitude_and_longitude(self):
        point = Coordinates(30.5, -97.25)

        assert (point.latitude, point.longitude) == (30.5, -97.25)

    def test_equal_points_are_equal_and_hashable(self):
        assert Coordinates(1.0, 2.0) == Coordinates(1.0, 2.0)
        assert len({Coordinates(1.0, 2.0), Coordinates(1.0, 2.0)}) == 1

    def test_is_immutable(self):
        point = Coordinates(1.0, 2.0)

        with pytest.raises(dataclasses.FrozenInstanceError):
            point.latitude = 5.0

    @pytest.mark.parametrize(
        ("latitude", "longitude"),
        [(90.0, 180.0), (-90.0, -180.0), (0.0, 0.0)],
    )
    def test_accepts_the_extreme_values(self, latitude, longitude):
        Coordinates(latitude, longitude)

    @pytest.mark.parametrize(
        ("latitude", "longitude"),
        [
            (90.01, 0.0),
            (-90.01, 0.0),
            (0.0, 180.01),
            (0.0, -180.01),
            (math.nan, 0.0),
            (0.0, math.nan),
            (math.inf, 0.0),
        ],
    )
    def test_rejects_impossible_values(self, latitude, longitude):
        with pytest.raises(ValueError, match="out of range"):
            Coordinates(latitude, longitude)


class TestHaversineMiles:
    def test_same_point_is_zero_miles(self):
        assert haversine_miles(NEW_YORK, NEW_YORK) == 0.0

    def test_new_york_to_los_angeles(self):
        assert haversine_miles(NEW_YORK, LOS_ANGELES) == pytest.approx(2445.5, rel=0.002)

    def test_distance_is_symmetric(self):
        assert haversine_miles(NEW_YORK, LOS_ANGELES) == haversine_miles(LOS_ANGELES, NEW_YORK)

    def test_one_degree_of_latitude_is_about_69_miles(self):
        distance = haversine_miles(Coordinates(10.0, 20.0), Coordinates(11.0, 20.0))

        assert distance == pytest.approx(69.09, rel=0.002)

    def test_one_degree_of_longitude_shrinks_towards_the_poles(self):
        at_equator = haversine_miles(Coordinates(0.0, 0.0), Coordinates(0.0, 1.0))
        at_60_north = haversine_miles(Coordinates(60.0, 0.0), Coordinates(60.0, 1.0))

        assert at_60_north == pytest.approx(at_equator / 2, rel=0.01)

    def test_crossing_the_antimeridian_takes_the_short_way(self):
        distance = haversine_miles(Coordinates(0.0, 179.5), Coordinates(0.0, -179.5))

        assert distance == pytest.approx(69.09, rel=0.002)

    def test_opposite_points_are_half_the_earth_apart(self):
        distance = haversine_miles(Coordinates(0.0, 0.0), Coordinates(0.0, 180.0))

        assert distance == pytest.approx(math.pi * EARTH_RADIUS_MILES)

    def test_exact_antipodes_do_not_break_on_rounding(self):
        distance = haversine_miles(Coordinates(45.0, 10.0), Coordinates(-45.0, -170.0))

        assert distance == pytest.approx(math.pi * EARTH_RADIUS_MILES)

    def test_poles_are_half_the_earth_apart(self):
        distance = haversine_miles(Coordinates(90.0, 0.0), Coordinates(-90.0, 0.0))

        assert distance == pytest.approx(math.pi * EARTH_RADIUS_MILES)

    def test_longitude_is_irrelevant_at_a_pole(self):
        distance = haversine_miles(Coordinates(90.0, 0.0), Coordinates(90.0, 123.0))

        assert distance == pytest.approx(0.0, abs=1e-6)

    def test_very_short_distances_stay_accurate(self):
        distance = haversine_miles(Coordinates(40.0, -100.0), Coordinates(40.0001, -100.0))

        assert distance == pytest.approx(0.0069, rel=0.01)
