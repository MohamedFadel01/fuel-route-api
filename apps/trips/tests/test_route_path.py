import dataclasses
import math
import random
from itertools import pairwise

import numpy as np
import pytest

from apps.common.geo import EARTH_RADIUS_MILES, Coordinates, haversine_miles, unit_vector
from apps.trips.domain.route_path import DEFAULT_SPACING_MILES, RoutePath

START = Coordinates(40.0, -100.0)


def north_of(point, miles):
    """The point ``miles`` due north of ``point`` (a meridian is a great circle)."""
    return Coordinates(point.latitude + math.degrees(miles / EARTH_RADIUS_MILES), point.longitude)


def straight_north(total_miles, vertices=2):
    """A straight route going north, made of ``vertices`` evenly spread vertices."""
    return [north_of(START, total_miles * i / (vertices - 1)) for i in range(vertices)]


def close(a, b, miles=1e-6):
    return haversine_miles(a, b) < miles


class TestInput:
    @pytest.mark.parametrize("coordinates", [[], [START]])
    def test_a_route_needs_a_start_and_a_finish(self, coordinates):
        with pytest.raises(ValueError, match="at least 2"):
            RoutePath.from_coordinates(coordinates)

    @pytest.mark.parametrize("spacing", [0, -0.5, math.nan, math.inf, -math.inf])
    def test_spacing_must_be_a_positive_number(self, spacing):
        with pytest.raises(ValueError, match="spacing"):
            RoutePath.from_coordinates(straight_north(10), spacing_miles=spacing)

    def test_refuses_to_build_an_absurd_number_of_points(self):
        with pytest.raises(ValueError, match="too many"):
            RoutePath.from_coordinates(straight_north(100), spacing_miles=1e-6)

    @pytest.mark.parametrize("spacing", [1e-30, 1e-310, 5e-324])
    def test_a_microscopic_spacing_is_refused_not_a_crash(self, spacing):
        with pytest.raises(ValueError, match="too many"):
            RoutePath.from_coordinates(straight_north(100), spacing_miles=spacing)

    def test_the_point_limit_is_inclusive(self, monkeypatch):
        monkeypatch.setattr("apps.trips.domain.route_path.MAX_POINTS", 11)
        route = straight_north(10.0)
        length = haversine_miles(route[0], route[1])

        allowed = RoutePath.from_coordinates(route, spacing_miles=length / 10 * 1.0000001)
        with pytest.raises(ValueError, match="too many"):
            RoutePath.from_coordinates(route, spacing_miles=length / 11 * 1.0000001)

        assert len(allowed) == 11

    def test_accepts_any_iterable(self):
        from_tuple = RoutePath.from_coordinates(tuple(straight_north(10)))
        from_generator = RoutePath.from_coordinates(point for point in straight_north(10))

        assert from_tuple.total_miles == from_generator.total_miles

    def test_later_changes_to_the_input_list_do_not_matter(self):
        coordinates = straight_north(10)
        path = RoutePath.from_coordinates(coordinates)
        total = path.total_miles

        coordinates.append(north_of(START, 500))

        assert path.total_miles == total

    def test_the_default_spacing_is_half_a_mile(self):
        assert DEFAULT_SPACING_MILES == 0.5


class TestTotalMiles:
    def test_two_points(self):
        end = Coordinates(34.0522, -118.2437)

        path = RoutePath.from_coordinates([START, end])

        assert path.total_miles == pytest.approx(haversine_miles(START, end))

    def test_is_the_sum_of_all_legs(self):
        a, b, c = START, Coordinates(41.0, -99.0), Coordinates(41.5, -97.0)

        path = RoutePath.from_coordinates([a, b, c])

        assert path.total_miles == pytest.approx(haversine_miles(a, b) + haversine_miles(b, c))

    def test_a_curvy_road_is_longer_than_the_straight_line(self):
        end = north_of(START, 20)
        detour = Coordinates(START.latitude + 0.15, START.longitude + 0.2)

        straight = RoutePath.from_coordinates([START, end])
        curvy = RoutePath.from_coordinates([START, detour, end])

        assert curvy.total_miles > straight.total_miles

    def test_doubling_back_counts_both_ways(self):
        out_and_back = [START, north_of(START, 10), START]

        path = RoutePath.from_coordinates(out_and_back)

        assert path.total_miles == pytest.approx(20.0, rel=1e-9)

    def test_crossing_the_date_line_takes_the_short_way(self):
        path = RoutePath.from_coordinates([Coordinates(0.0, 179.5), Coordinates(0.0, -179.5)])

        assert path.total_miles == pytest.approx(69.09, rel=0.002)

    def test_repeated_points_add_nothing(self):
        a, b = START, north_of(START, 10)

        with_repeats = RoutePath.from_coordinates([a, a, a, b, b])
        without = RoutePath.from_coordinates([a, b])

        assert with_repeats.total_miles == pytest.approx(without.total_miles)


class TestStartEqualsFinish:
    @pytest.mark.parametrize("copies", [2, 3, 10])
    def test_the_path_is_a_single_point(self, copies):
        path = RoutePath.from_coordinates([START] * copies)

        assert path.total_miles == 0.0
        assert len(path) == 1
        assert path.mile_markers.tolist() == [0.0]
        assert close(path.points[0], START)
        assert path.spacing_miles == 0.0

    def test_the_vector_is_still_a_unit_vector(self):
        path = RoutePath.from_coordinates([START, START])

        assert path.unit_vectors.shape == (1, 3)
        assert np.linalg.norm(path.unit_vectors[0]) == pytest.approx(1.0)


class TestMileMarkers:
    def test_start_at_zero_and_end_at_the_total(self):
        path = RoutePath.from_coordinates(straight_north(37.3, vertices=5))

        assert path.mile_markers[0] == 0.0
        assert path.mile_markers[-1] == path.total_miles

    def test_are_strictly_increasing(self):
        path = RoutePath.from_coordinates(straight_north(123.4, vertices=9))

        assert np.all(np.diff(path.mile_markers) > 0)

    def test_are_evenly_spaced(self):
        path = RoutePath.from_coordinates(straight_north(123.4, vertices=9))

        gaps = np.diff(path.mile_markers)
        assert gaps == pytest.approx(gaps[0], rel=1e-9)

    def test_gaps_never_exceed_the_requested_spacing(self):
        for total in (0.1, 0.5, 0.51, 1.0, 9.99, 10.0, 10.01, 123.456):
            path = RoutePath.from_coordinates(straight_north(total), spacing_miles=0.5)

            assert np.diff(path.mile_markers).max() <= 0.5 + 1e-12, total

    def test_the_number_of_points_is_the_fewest_that_keeps_the_gaps_small(self):
        path = RoutePath.from_coordinates(straight_north(10.3), spacing_miles=0.5)

        # 10.3 / 0.5 = 20.6, so 21 gaps are needed, which means 22 points.
        assert len(path) == 22
        assert path.spacing_miles == pytest.approx(10.3 / 21, rel=1e-6)

    def test_a_length_that_is_almost_a_whole_number_of_spacings(self):
        route = straight_north(10.0)
        spacing = haversine_miles(route[0], route[1]) / 20 * 1.0000001

        path = RoutePath.from_coordinates(route, spacing_miles=spacing)

        assert len(path) == 21
        assert path.spacing_miles <= spacing

    def test_a_route_shorter_than_the_spacing_keeps_just_its_two_ends(self):
        path = RoutePath.from_coordinates(straight_north(0.2), spacing_miles=0.5)

        assert len(path) == 2
        assert path.mile_markers[0] == 0.0
        assert path.mile_markers[-1] == pytest.approx(0.2, rel=1e-6)

    def test_custom_spacing(self):
        path = RoutePath.from_coordinates(straight_north(100.0), spacing_miles=2.0)

        assert len(path) == math.ceil(path.total_miles / 2.0) + 1
        assert np.diff(path.mile_markers).max() <= 2.0 + 1e-12

    def test_a_very_long_route(self):
        path = RoutePath.from_coordinates(
            [Coordinates(40.7128, -74.0060), Coordinates(34.0522, -118.2437)]
        )

        assert path.total_miles == pytest.approx(2445.5, rel=0.002)
        assert len(path) == math.ceil(path.total_miles / 0.5) + 1


class TestPositions:
    def test_first_and_last_points_are_the_start_and_finish(self):
        route = [START, Coordinates(41.0, -99.0), Coordinates(41.5, -97.0)]

        path = RoutePath.from_coordinates(route)

        assert close(path.points[0], route[0])
        assert close(path.points[-1], route[-1])

    def test_every_point_is_as_far_along_as_its_mile_marker_says(self):
        path = RoutePath.from_coordinates(straight_north(50.0, vertices=3))

        for marker, point in zip(path.mile_markers, path.points, strict=True):
            assert haversine_miles(START, point) == pytest.approx(marker, abs=1e-6)

    def test_neighbouring_points_are_one_gap_apart(self):
        path = RoutePath.from_coordinates(straight_north(50.0, vertices=3))

        for first, second in pairwise(path.points):
            assert haversine_miles(first, second) == pytest.approx(path.spacing_miles, abs=1e-6)

    def test_a_long_straight_leg_follows_the_great_circle(self):
        end = Coordinates(34.0522, -118.2437)
        # A spacing that gives exactly 1000 gaps, so point 500 is the exact middle.
        spacing = haversine_miles(START, end) / 1000 * 1.0000001
        path = RoutePath.from_coordinates([START, end], spacing_miles=spacing)

        middle = path.points[500]

        assert len(path) == 1001
        assert haversine_miles(START, middle) == pytest.approx(path.total_miles / 2, abs=1e-6)
        assert haversine_miles(middle, end) == pytest.approx(path.total_miles / 2, abs=1e-6)

    def test_points_follow_a_bend_in_the_road(self):
        corner = north_of(START, 10)
        end = Coordinates(corner.latitude, corner.longitude + 0.2)
        path = RoutePath.from_coordinates([START, corner, end])

        leg_one = haversine_miles(START, corner)
        before_corner = path.points[np.searchsorted(path.mile_markers, leg_one / 2)]
        after_corner = path.points[np.searchsorted(path.mile_markers, leg_one + 3.0)]

        assert before_corner.longitude == pytest.approx(START.longitude, abs=1e-9)
        assert haversine_miles(START, before_corner) == pytest.approx(
            path.mile_markers[np.searchsorted(path.mile_markers, leg_one / 2)], abs=1e-6
        )
        assert after_corner.longitude > corner.longitude
        assert haversine_miles(corner, after_corner) == pytest.approx(
            path.mile_markers[np.searchsorted(path.mile_markers, leg_one + 3.0)] - leg_one,
            abs=1e-3,
        )

    def test_after_doubling_back_the_markers_keep_counting_up(self):
        path = RoutePath.from_coordinates([START, north_of(START, 10), START])

        index = int(np.argmin(np.abs(path.mile_markers - 15.0)))

        assert path.mile_markers[index] == pytest.approx(15.0, abs=0.01)
        assert haversine_miles(START, path.points[index]) == pytest.approx(
            20.0 - path.mile_markers[index], abs=1e-6
        )

    def test_dense_vertices_are_thinned_out_to_the_spacing(self):
        path = RoutePath.from_coordinates(straight_north(10.3, vertices=2061))  # every 0.005 mi

        assert len(path) == 22  # 10.3 / 0.5 = 20.6, so 21 gaps
        for marker, point in zip(path.mile_markers, path.points, strict=True):
            assert haversine_miles(START, point) == pytest.approx(marker, abs=1e-6)

    def test_repeated_vertices_do_not_disturb_the_positions(self):
        a, b, c = START, north_of(START, 5), north_of(START, 10)

        path = RoutePath.from_coordinates([a, a, b, b, b, c, c])

        assert path.total_miles == pytest.approx(10.0, rel=1e-9)
        for marker, point in zip(path.mile_markers, path.points, strict=True):
            assert haversine_miles(START, point) == pytest.approx(marker, abs=1e-6)

    def test_a_repeated_last_vertex_still_ends_at_the_finish(self):
        finish = north_of(START, 3)

        path = RoutePath.from_coordinates([START, finish, finish])

        assert close(path.points[-1], finish)
        assert path.mile_markers[-1] == path.total_miles

    def test_no_point_jumps_across_the_date_line(self):
        path = RoutePath.from_coordinates([Coordinates(0.0, 179.9), Coordinates(0.0, -179.9)])

        for first, second in pairwise(path.points):
            assert haversine_miles(first, second) < 1.0

    def test_works_close_to_the_pole(self):
        path = RoutePath.from_coordinates([Coordinates(89.0, 0.0), Coordinates(89.0, 90.0)])

        assert path.total_miles == pytest.approx(
            haversine_miles(Coordinates(89.0, 0.0), Coordinates(89.0, 90.0))
        )
        assert np.isfinite(path.unit_vectors).all()


class TestUnitVectors:
    def test_one_row_per_point(self):
        path = RoutePath.from_coordinates(straight_north(30.0))

        assert path.unit_vectors.shape == (len(path), 3)
        assert len(path.mile_markers) == len(path)
        assert len(path.points) == len(path)

    def test_every_row_has_length_one(self):
        path = RoutePath.from_coordinates(straight_north(300.0, vertices=4))

        assert np.linalg.norm(path.unit_vectors, axis=1) == pytest.approx(1.0, abs=1e-12)

    def test_points_and_vectors_describe_the_same_places(self):
        path = RoutePath.from_coordinates(straight_north(30.0, vertices=4))

        for point, vector in zip(path.points, path.unit_vectors, strict=True):
            assert unit_vector(point) == pytest.approx(tuple(vector), abs=1e-12)

    def test_the_points_are_cached(self):
        path = RoutePath.from_coordinates(straight_north(30.0))

        assert path.points is path.points


class TestImmutability:
    def test_the_arrays_cannot_be_changed(self):
        path = RoutePath.from_coordinates(straight_north(10.0))

        with pytest.raises(ValueError, match="read-only"):
            path.mile_markers[0] = 5.0
        with pytest.raises(ValueError, match="read-only"):
            path.unit_vectors[0, 0] = 5.0

    def test_the_fields_cannot_be_replaced(self):
        path = RoutePath.from_coordinates(straight_north(10.0))

        with pytest.raises(dataclasses.FrozenInstanceError):
            path.total_miles = 1.0


def valid_arrays(count=3):
    markers = np.linspace(0.0, 2.0, count)
    vectors = np.array([unit_vector(north_of(START, mile)) for mile in markers])
    return markers, vectors


def build(markers=None, vectors=None, total=2.0, spacing=1.0):
    default_markers, default_vectors = valid_arrays()
    return RoutePath(
        total_miles=total,
        spacing_miles=spacing,
        mile_markers=default_markers if markers is None else markers,
        unit_vectors=default_vectors if vectors is None else vectors,
    )


class TestBuildingDirectly:
    """``from_coordinates`` is the normal way in, but the constructor must not accept nonsense."""

    def test_valid_arrays_are_accepted(self):
        path = build()

        assert len(path) == 3
        assert close(path.points[0], START)

    def test_the_arrays_are_copied_and_frozen_without_touching_the_callers(self):
        markers, vectors = valid_arrays()

        path = build(markers, vectors)
        markers[1] = 99.0

        assert path.mile_markers[1] == 1.0
        assert markers.flags.writeable
        assert not path.mile_markers.flags.writeable
        assert not path.unit_vectors.flags.writeable

    def test_a_single_point_path_is_accepted(self):
        markers, vectors = valid_arrays(count=1)

        path = build(markers[:1], vectors[:1], total=0.0, spacing=0.0)

        assert len(path) == 1

    @pytest.mark.parametrize(
        ("change", "message"),
        [
            ({"markers": np.zeros((3, 1))}, "one-dimensional"),
            ({"markers": np.array([])}, "at least one"),
            ({"markers": np.array([0.0, 1.0])}, "one unit vector per"),
            ({"vectors": np.zeros((3, 2))}, "one unit vector per"),
            ({"markers": np.array([0.0, np.nan, 2.0])}, "finite"),
            ({"markers": np.array([0.5, 1.0, 2.0])}, "start at 0"),
            ({"markers": np.array([0.0, 1.0, 1.0])}, "increasing"),
            ({"markers": np.array([0.0, 2.0, 1.0])}, "increasing"),
            ({"markers": np.array([0.0, 1.0, 3.0])}, "end at the total"),
            ({"vectors": np.full((3, 3), np.nan)}, "finite"),
            ({"vectors": np.full((3, 3), 2.0)}, "unit"),
            ({"total": -2.0}, "total_miles must"),
            ({"total": math.nan}, "total_miles must"),
            ({"spacing": -1.0}, "spacing_miles must"),
            ({"spacing": math.inf}, "spacing_miles must"),
        ],
    )
    def test_nonsense_is_refused(self, change, message):
        with pytest.raises(ValueError, match=message):
            build(**change)


class TestRandomRoutes:
    """Messy routes (repeats, doubling back, odd places) checked against brute force."""

    @staticmethod
    def random_route(generator):
        def move(point, heading, miles):
            distance = miles / EARTH_RADIUS_MILES
            lat, lon = math.radians(point.latitude), math.radians(point.longitude)
            new_lat = math.asin(
                math.sin(lat) * math.cos(distance)
                + math.cos(lat) * math.sin(distance) * math.cos(heading)
            )
            new_lon = lon + math.atan2(
                math.sin(heading) * math.sin(distance) * math.cos(lat),
                math.cos(distance) - math.sin(lat) * math.sin(new_lat),
            )
            return Coordinates(math.degrees(new_lat), (math.degrees(new_lon) + 540) % 360 - 180)

        start = Coordinates(
            generator.choice([generator.uniform(25, 49), generator.uniform(-60, 80), 0.0, 88.0]),
            generator.choice([generator.uniform(-125, -67), 179.9, -179.9, 0.0]),
        )
        route, heading = [start], generator.uniform(0, 2 * math.pi)
        for _ in range(generator.randint(1, 120)):
            roll = generator.random()
            if roll < 0.05:
                route.append(route[-1])  # a repeated vertex
                continue
            if roll < 0.08:
                heading += math.pi  # turning back
            heading += generator.gauss(0, 0.4)
            route.append(move(route[-1], heading, 10 ** generator.uniform(-3, 1.9)))
        return route

    def test_invariants_and_positions(self):
        generator = random.Random(2024)

        def angle(a, b):
            return 2 * np.arcsin(np.clip(np.linalg.norm(a - b, axis=-1) / 2, 0, 1))

        for _ in range(150):
            route = self.random_route(generator)
            spacing = 10 ** generator.uniform(-1.3, 0.7)
            path = RoutePath.from_coordinates(route, spacing_miles=spacing)
            markers = path.mile_markers

            if path.total_miles == 0:
                assert len(path) == 1
                continue
            assert markers[0] == 0
            assert markers[-1] == path.total_miles
            assert len(path) == math.ceil(path.total_miles / spacing) + 1
            assert np.diff(markers).max() <= spacing * (1 + 1e-12)
            assert close(path.points[0], route[0])
            assert close(path.points[-1], route[-1])

            # Every point must lie on some leg, at exactly the distance its marker claims.
            vectors = np.array([unit_vector(vertex) for vertex in route])
            legs = np.array([haversine_miles(a, b) for a, b in pairwise(route)])
            before = np.concatenate(([0.0], np.cumsum(legs)))[:-1]
            start_vectors, end_vectors = vectors[:-1], vectors[1:]
            for k in generator.sample(range(len(path)), min(20, len(path))):
                here = path.unit_vectors[k]
                from_start, to_end = angle(start_vectors, here), angle(here, end_vectors)
                off_the_leg = (from_start + to_end - angle(start_vectors, end_vectors)) * (
                    EARTH_RADIUS_MILES
                )
                wrong_marker = np.abs(before + from_start * EARTH_RADIUS_MILES - markers[k])
                assert np.maximum(off_the_leg, wrong_marker).min() < 1e-4
