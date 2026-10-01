import dataclasses
import math

import pytest

from apps.common.geo import (
    EARTH_RADIUS_MILES,
    Coordinates,
    chord_to_miles,
    haversine_miles,
    miles_to_chord,
    unit_vector,
)

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


HALF_CIRCUMFERENCE = math.pi * EARTH_RADIUS_MILES

# A spread of points: both hemispheres, the poles, the date line, close and far pairs.
SAMPLE_POINTS = [
    NEW_YORK,
    LOS_ANGELES,
    Coordinates(30.2672, -97.7431),  # Austin
    Coordinates(47.6062, -122.3321),  # Seattle
    Coordinates(25.7617, -80.1918),  # Miami
    Coordinates(61.2181, -149.9003),  # Anchorage
    Coordinates(-33.8688, 151.2093),  # Sydney
    Coordinates(0.0, 0.0),
    Coordinates(0.0, 180.0),
    Coordinates(90.0, 0.0),
    Coordinates(-90.0, 0.0),
    Coordinates(40.0, -100.0),
    Coordinates(40.0001, -100.0),
]


def distance_between(a, b):
    return math.dist(a, b)


class TestUnitVector:
    @pytest.mark.parametrize(
        ("point", "expected"),
        [
            (Coordinates(0.0, 0.0), (1.0, 0.0, 0.0)),
            (Coordinates(0.0, 90.0), (0.0, 1.0, 0.0)),
            (Coordinates(0.0, -90.0), (0.0, -1.0, 0.0)),
            (Coordinates(0.0, 180.0), (-1.0, 0.0, 0.0)),
            (Coordinates(90.0, 0.0), (0.0, 0.0, 1.0)),
            (Coordinates(-90.0, 0.0), (0.0, 0.0, -1.0)),
        ],
    )
    def test_known_points(self, point, expected):
        assert unit_vector(point) == pytest.approx(expected, abs=1e-12)

    @pytest.mark.parametrize("point", SAMPLE_POINTS)
    def test_lies_on_the_unit_sphere(self, point):
        assert math.hypot(*unit_vector(point)) == pytest.approx(1.0, abs=1e-12)

    def test_the_two_sides_of_the_date_line_are_the_same_place(self):
        assert unit_vector(Coordinates(10.0, 180.0)) == pytest.approx(
            unit_vector(Coordinates(10.0, -180.0)), abs=1e-12
        )

    def test_longitude_is_irrelevant_at_a_pole(self):
        assert unit_vector(Coordinates(90.0, 0.0)) == pytest.approx(
            unit_vector(Coordinates(90.0, 123.0)), abs=1e-12
        )

    def test_returns_three_plain_floats(self):
        vector = unit_vector(NEW_YORK)

        assert isinstance(vector, tuple)
        assert len(vector) == 3
        assert all(isinstance(value, float) for value in vector)

    def test_north_is_up_and_east_is_positive_y(self):
        assert unit_vector(Coordinates(45.0, 0.0))[2] > 0
        assert unit_vector(Coordinates(-45.0, 0.0))[2] < 0
        assert unit_vector(Coordinates(0.0, 45.0))[1] > 0
        assert unit_vector(Coordinates(0.0, -45.0))[1] < 0


class TestMilesToChord:
    def test_zero_miles_is_zero(self):
        assert miles_to_chord(0.0) == 0.0

    def test_half_the_earth_is_the_diameter(self):
        assert miles_to_chord(HALF_CIRCUMFERENCE) == pytest.approx(2.0)

    def test_a_quarter_of_the_earth(self):
        assert miles_to_chord(HALF_CIRCUMFERENCE / 2) == pytest.approx(math.sqrt(2))

    def test_short_distances_are_almost_the_same_as_the_angle(self):
        assert miles_to_chord(10.0) == pytest.approx(10.0 / EARTH_RADIUS_MILES, rel=1e-5)

    def test_a_tiny_distance_keeps_its_precision(self):
        assert miles_to_chord(0.001) == pytest.approx(0.001 / EARTH_RADIUS_MILES, rel=1e-9)

    def test_grows_with_distance(self):
        chords = [miles_to_chord(miles) for miles in (0, 1, 10, 100, 1000, 5000, 12000)]

        assert chords == sorted(chords)
        assert len(set(chords)) == len(chords)

    @pytest.mark.parametrize("miles", [HALF_CIRCUMFERENCE + 1, 20000.0, 1e12, math.inf])
    def test_beyond_half_the_earth_covers_everything(self, miles):
        assert miles_to_chord(miles) == 2.0

    @pytest.mark.parametrize("miles", [-0.001, -10.0, -math.inf, math.nan])
    def test_rejects_negative_and_not_a_number(self, miles):
        with pytest.raises(ValueError, match="miles"):
            miles_to_chord(miles)


class TestChordToMiles:
    def test_zero_is_zero(self):
        assert chord_to_miles(0.0) == 0.0

    def test_the_diameter_is_half_the_earth(self):
        assert chord_to_miles(2.0) == pytest.approx(HALF_CIRCUMFERENCE)

    def test_a_tiny_chord_keeps_its_precision(self):
        assert chord_to_miles(1e-9) == pytest.approx(1e-9 * EARTH_RADIUS_MILES, rel=1e-9)

    def test_rounding_just_above_the_diameter_is_tolerated(self):
        assert chord_to_miles(2.0000000000000004) == pytest.approx(HALF_CIRCUMFERENCE)

    @pytest.mark.parametrize("chord", [-0.001, -1.0, math.nan, 2.001, 5.0, math.inf])
    def test_rejects_impossible_chords(self, chord):
        with pytest.raises(ValueError, match="chord"):
            chord_to_miles(chord)

    @pytest.mark.parametrize(
        "miles", [0.0, 0.01, 0.5, 10.0, 50.0, 500.0, 2445.5, 8000.0, HALF_CIRCUMFERENCE]
    )
    def test_undoes_miles_to_chord(self, miles):
        assert chord_to_miles(miles_to_chord(miles)) == pytest.approx(miles, rel=1e-9, abs=1e-9)


class TestStraightLineMatchesGroundDistance:
    """The KD-tree measures straight lines through the Earth; these must agree with miles."""

    @pytest.mark.parametrize("a", SAMPLE_POINTS)
    @pytest.mark.parametrize("b", SAMPLE_POINTS)
    def test_every_pair(self, a, b):
        chord = distance_between(unit_vector(a), unit_vector(b))

        assert chord == pytest.approx(miles_to_chord(haversine_miles(a, b)), abs=1e-9)
        assert chord_to_miles(min(chord, 2.0)) == pytest.approx(haversine_miles(a, b), abs=1e-3)

    def test_a_ten_mile_search_radius_finds_a_point_nine_miles_away_but_not_eleven(self):
        origin = Coordinates(40.0, -100.0)
        nine_miles_north = Coordinates(40.0 + 9 / 69.09, -100.0)
        eleven_miles_north = Coordinates(40.0 + 11 / 69.09, -100.0)
        radius = miles_to_chord(10.0)

        assert distance_between(unit_vector(origin), unit_vector(nine_miles_north)) < radius
        assert distance_between(unit_vector(origin), unit_vector(eleven_miles_north)) > radius
