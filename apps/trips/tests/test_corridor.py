import dataclasses
import math
import random
from decimal import Decimal

import numpy as np
import pytest

from apps.common.geo import EARTH_RADIUS_MILES, Coordinates, haversine_miles, unit_vector
from apps.trips.domain.corridor import (
    DEFAULT_MARGIN_MILES,
    WIDENING_MARGINS_MILES,
    Corridor,
    StationOnRoute,
    StationSite,
)
from apps.trips.domain.route_path import RoutePath
from apps.trips.tests.geo_helpers import (
    along_track_miles,
    cross_track_miles,
    destination,
    north_of,
    random_route,
)

START = Coordinates(40.0, -100.0)
PRICE = Decimal("3.499")


@pytest.fixture
def road():
    """A straight road, 100 miles due north."""
    return RoutePath.from_coordinates([START, north_of(START, 100.0)])


def site(station_id, along, aside=0.0, price=PRICE):
    """A station ``along`` miles up the road and ``aside`` miles to its east (west if < 0)."""
    on_the_road = north_of(START, along)
    if aside == 0:
        return StationSite(station_id, on_the_road, price)
    bearing = 90.0 if aside > 0 else 270.0
    return StationSite(station_id, destination(on_the_road, bearing, abs(aside)), price)


def ids(stations):
    return [station.station_id for station in stations]


class TestWhichStationsAreKept:
    def test_a_station_on_the_road_is_kept(self, road):
        found = Corridor(road, [site(1, 50.0)]).within(10.0)

        assert ids(found) == [1]
        assert found[0].miles_from_route == pytest.approx(0.0, abs=1e-6)

    def test_a_station_inside_the_margin_is_kept_and_one_outside_is_dropped(self, road):
        corridor = Corridor(road, [site(1, 50.0, aside=9.0), site(2, 50.0, aside=11.0)])

        assert ids(corridor.within(10.0)) == [1]

    def test_both_sides_of_the_road_count(self, road):
        corridor = Corridor(road, [site(1, 50.0, aside=9.0), site(2, 50.0, aside=-9.0)])

        assert ids(corridor.within(10.0)) == [1, 2]

    def test_a_station_exactly_on_the_border_is_kept(self, road):
        # Placed relative to a route point, so the nearest route point is exactly 10 miles away.
        base = road.points[len(road) // 2]
        on_the_border = StationSite(1, destination(base, 90.0, 10.0), PRICE)
        just_outside = StationSite(2, destination(base, 90.0, 10.001), PRICE)

        found = Corridor(road, [on_the_border, just_outside]).within(10.0)

        assert ids(found) == [1]

    def test_the_border_is_kept_at_every_margin(self, road):
        base = road.points[len(road) // 3]
        for margin in (0.5, 1.0, 10.0, 25.0, 50.0, 123.456):
            station = StationSite(1, destination(base, 270.0, margin), PRICE)

            assert ids(Corridor(road, [station]).within(margin)) == [1], margin

    def test_stations_before_the_start_and_after_the_finish_count_when_close_enough(self, road):
        corridor = Corridor(
            road,
            [
                site(1, -5.0),  # 5 miles behind the start
                site(2, -20.0),
                site(3, 105.0),  # 5 miles past the finish
                site(4, 120.0),
            ],
        )

        found = corridor.within(10.0)

        assert ids(found) == [1, 3]
        assert found[0].mile_marker == 0.0
        assert found[1].mile_marker == road.total_miles
        assert found[0].miles_from_route == pytest.approx(5.0, abs=1e-6)
        assert found[1].miles_from_route == pytest.approx(5.0, abs=1e-6)

    def test_the_default_margin_is_ten_miles(self, road):
        corridor = Corridor(road, [site(1, 50.0, aside=9.0), site(2, 50.0, aside=11.0)])

        assert DEFAULT_MARGIN_MILES == 10.0
        assert ids(corridor.within()) == [1]

    def test_no_stations_means_no_results(self, road):
        assert Corridor(road, []).within(10.0) == []

    def test_a_zero_margin_keeps_only_stations_on_a_route_point(self, road):
        on_a_point = StationSite(1, road.points[10], PRICE)
        beside = site(2, 5.0, aside=0.01)

        assert ids(Corridor(road, [on_a_point, beside]).within(0.0)) == [1]

    def test_an_unlimited_margin_keeps_every_station(self, road):
        stations = [site(1, 50.0, aside=500.0), site(2, -3000.0)]

        # Station 2 is 3000 miles behind the start, so it comes first.
        assert ids(Corridor(road, stations).within(math.inf)) == [2, 1]

    @pytest.mark.parametrize("margin", [-0.001, -10.0, math.nan])
    def test_a_margin_must_be_zero_or_more(self, road, margin):
        with pytest.raises(ValueError, match="miles"):
            Corridor(road, [site(1, 50.0)]).within(margin)


class TestWideningTheMargin:
    def test_the_standard_margins_are_ten_twenty_five_and_fifty_miles(self):
        assert WIDENING_MARGINS_MILES == (10.0, 25.0, 50.0)

    def test_each_wider_margin_keeps_everything_the_narrower_one_kept_and_more(self, road):
        stations = [site(1, 20.0, aside=5.0), site(2, 40.0, aside=12.0)]
        stations += [site(3, 60.0, aside=30.0), site(4, 80.0, aside=60.0)]
        corridor = Corridor(road, stations)

        kept = [ids(corridor.within(margin)) for margin in WIDENING_MARGINS_MILES]

        assert kept == [[1], [1, 2], [1, 2, 3]]
        assert ids(corridor.within(100.0)) == [1, 2, 3, 4]

    def test_asking_again_gives_the_same_answer(self, road):
        corridor = Corridor(road, [site(1, 20.0, aside=5.0), site(2, 40.0, aside=12.0)])

        first = corridor.within(25.0)
        corridor.within(10.0)

        assert corridor.within(25.0) == first


class TestMileMarkers:
    @pytest.mark.parametrize("along", [0.0, 0.3, 10.0, 33.3, 50.0, 77.7, 99.9, 100.0])
    def test_a_station_is_placed_where_the_road_passes_it(self, road, along):
        found = Corridor(road, [site(1, along, aside=4.0)]).within(10.0)

        assert found[0].mile_marker == pytest.approx(along, abs=road.spacing_miles / 2 + 1e-6)

    def test_the_marker_is_one_of_the_routes_own_markers(self, road):
        found = Corridor(road, [site(1, 33.3, aside=4.0)]).within(10.0)

        assert found[0].mile_marker in road.mile_markers

    def test_distance_from_the_route_is_the_sideways_distance(self, road):
        found = Corridor(road, [site(1, 50.0, aside=7.0)]).within(10.0)

        # Measured to the nearest route point (at most 0.25 miles along), which can only add a
        # sliver: sqrt(7**2 + 0.25**2) - 7 is about 0.0045 miles.
        assert found[0].miles_from_route == pytest.approx(7.0, abs=0.005)
        assert found[0].miles_from_route >= 7.0 - 1e-6

    def test_results_come_in_driving_order(self, road):
        stations = [site(1, 80.0, 2.0), site(2, 10.0, 2.0), site(3, 45.0, 2.0), site(4, 0.0, 2.0)]

        found = Corridor(road, stations).within(10.0)

        assert ids(found) == [4, 2, 3, 1]
        markers = [station.mile_marker for station in found]
        assert markers == sorted(markers)

    def test_stations_at_the_same_marker_are_ordered_by_id(self, road):
        stations = [site(9, 50.0), site(3, 50.0), site(5, 50.0)]

        assert ids(Corridor(road, stations).within(10.0)) == [3, 5, 9]

    def test_the_price_and_id_are_passed_through_untouched(self, road):
        price = Decimal("2.87654321")

        found = Corridor(road, [site(42, 10.0, price=price)]).within(10.0)

        assert found[0].station_id == 42
        assert found[0].price is price


class TestBendsAndSpecialRoutes:
    def test_stations_near_each_leg_of_an_l_shaped_road_get_markers_on_that_leg(self):
        corner = north_of(START, 50.0)
        end = destination(corner, 90.0, 50.0)
        road = RoutePath.from_coordinates([START, corner, end])
        first_leg = destination(north_of(START, 20.0), 270.0, 3.0)
        second_leg = destination(destination(corner, 90.0, 30.0), 180.0, 3.0)

        found = Corridor(
            road, [StationSite(1, first_leg, PRICE), StationSite(2, second_leg, PRICE)]
        ).within(10.0)

        assert ids(found) == [1, 2]
        assert found[0].mile_marker == pytest.approx(20.0, abs=0.3)
        assert found[1].mile_marker == pytest.approx(road.total_miles - 20.0, abs=0.3)

    def test_a_station_inside_a_bend_belongs_to_the_nearer_leg(self):
        corner = north_of(START, 50.0)
        road = RoutePath.from_coordinates([START, corner, destination(corner, 90.0, 50.0)])
        # Both are inside the corner, each within 10 miles of both legs.
        nearer_the_first = destination(
            north_of(START, 44.0), 90.0, 3.0
        )  # 3 mi from leg 1, 6 from leg 2
        nearer_the_second = destination(
            north_of(START, 47.0), 90.0, 6.0
        )  # 6 mi from leg 1, 3 from leg 2

        found = Corridor(
            road,
            [StationSite(1, nearer_the_first, PRICE), StationSite(2, nearer_the_second, PRICE)],
        ).within(10.0)

        first, second = found
        assert first.station_id == 1
        assert first.mile_marker == pytest.approx(44.0, abs=0.3)
        assert first.miles_from_route == pytest.approx(3.0, abs=0.3)
        assert second.station_id == 2
        assert second.mile_marker == pytest.approx(50.0 + 6.0, abs=0.3)  # past the corner
        assert second.miles_from_route == pytest.approx(3.0, abs=0.3)

    def test_a_road_that_doubles_back_gives_a_station_one_of_its_two_passes(self):
        out_and_back = RoutePath.from_coordinates([START, north_of(START, 20.0), START])
        station = site(1, 5.0, aside=2.0)

        found = Corridor(out_and_back, [station]).within(10.0)

        outbound, homebound = 5.0, out_and_back.total_miles - 5.0
        marker = found[0].mile_marker
        assert min(abs(marker - outbound), abs(marker - homebound)) < 0.3

    def test_a_route_that_goes_nowhere_has_just_the_start(self):
        road = RoutePath.from_coordinates([START, START])
        near = StationSite(1, destination(START, 90.0, 4.0), PRICE)
        far = StationSite(2, destination(START, 90.0, 40.0), PRICE)

        found = Corridor(road, [near, far]).within(10.0)

        assert ids(found) == [1]
        assert found[0].mile_marker == 0.0
        assert found[0].miles_from_route == pytest.approx(4.0, abs=1e-6)

    def test_works_across_the_date_line(self):
        start = Coordinates(0.0, 179.0)
        road = RoutePath.from_coordinates([start, Coordinates(0.0, -179.0)])
        station = StationSite(1, Coordinates(2.0, -180.0), PRICE)  # 138 miles north of the line

        corridor = Corridor(road, [station])

        assert corridor.within(10.0) == []
        found = corridor.within(150.0)
        assert ids(found) == [1]
        assert found[0].mile_marker == pytest.approx(road.total_miles / 2, abs=0.3)

    def test_a_very_long_route(self):
        new_york, los_angeles = Coordinates(40.7128, -74.0060), Coordinates(34.0522, -118.2437)
        road = RoutePath.from_coordinates([new_york, los_angeles])
        # Due north of the middle. The road heads west-south-west there, so the nearest spot
        # on it is not the middle: the textbook formula says where.
        station = StationSite(1, destination(road.points[len(road) // 2], 0.0, 6.0), PRICE)

        found = Corridor(road, [station]).within(10.0)

        expected = along_track_miles(new_york, los_angeles, station.coordinates)
        assert found[0].mile_marker == pytest.approx(expected, abs=road.spacing_miles / 2)


class TestInputAndOutput:
    def test_repeated_station_ids_are_refused(self, road):
        with pytest.raises(ValueError, match="Duplicate station IDs: 7"):
            Corridor(road, [site(7, 10.0), site(7, 20.0)])

    def test_accepts_any_iterable_of_stations(self, road):
        found = Corridor(road, (site(i, float(i)) for i in range(1, 4))).within(10.0)

        assert ids(found) == [1, 2, 3]

    def test_the_results_are_immutable(self, road):
        found = Corridor(road, [site(1, 10.0)]).within(10.0)

        with pytest.raises(dataclasses.FrozenInstanceError):
            found[0].mile_marker = 5.0

    def test_the_results_are_plain_python_numbers(self, road):
        found = Corridor(road, [site(1, 10.0)]).within(10.0)[0]

        assert isinstance(found, StationOnRoute)
        assert type(found.station_id) is int
        assert type(found.mile_marker) is float
        assert type(found.miles_from_route) is float

    def test_the_caller_can_change_their_list_afterwards(self, road):
        stations = [site(1, 10.0)]
        corridor = Corridor(road, stations)

        stations.append(site(2, 20.0))

        assert ids(corridor.within(10.0)) == [1]


class TestAgainstBruteForce:
    """The KD-tree must agree with simply measuring every station against every route point."""

    def test_random_stations_along_a_random_route(self):
        generator = random.Random(11)
        vertices = [Coordinates(36.0, -95.0)]
        heading = 70.0
        for _ in range(60):
            heading += generator.gauss(0, 12)
            vertices.append(destination(vertices[-1], heading, generator.uniform(2, 25)))
        road = RoutePath.from_coordinates(vertices)

        stations = []
        for station_id in range(1500):
            base = vertices[generator.randrange(len(vertices))]
            stations.append(
                StationSite(
                    station_id,
                    destination(base, generator.uniform(0, 360), generator.uniform(0, 120)),
                    PRICE,
                )
            )
        corridor = Corridor(road, stations)

        points = road.unit_vectors
        for margin in (10.0, 25.0, 50.0):
            expected = {}
            for station in stations:
                chords = np.linalg.norm(points - np.array(unit_vector(station.coordinates)), axis=1)
                nearest = int(np.argmin(chords))
                miles = 2 * EARTH_RADIUS_MILES * math.asin(chords[nearest] / 2)
                if miles <= margin:
                    expected[station.station_id] = (road.mile_markers[nearest], miles)

            found = {
                s.station_id: (s.mile_marker, s.miles_from_route) for s in corridor.within(margin)
            }

            assert found.keys() == expected.keys(), margin
            for station_id, (marker, miles) in expected.items():
                assert found[station_id][0] == marker
                assert found[station_id][1] == pytest.approx(miles, abs=1e-9)
            assert len(found) > 50, margin  # the check is meaningful

    def test_a_thousand_stations_agree_with_haversine(self):
        generator = random.Random(5)
        road = RoutePath.from_coordinates([START, north_of(START, 100.0)])
        stations = [
            StationSite(
                i,
                Coordinates(generator.uniform(39.0, 42.0), generator.uniform(-102.0, -98.0)),
                PRICE,
            )
            for i in range(1000)
        ]

        for found in Corridor(road, stations).within(25.0):
            station = stations[found.station_id]
            nearest = min(haversine_miles(station.coordinates, point) for point in road.points)
            assert found.miles_from_route == pytest.approx(nearest, abs=1e-6)
            assert nearest <= 25.0 + 1e-6


class TestAccuracyAgainstTheTextbook:
    """Measured against the real route line, not just against the route's sample points."""

    def test_distances_and_markers_are_within_half_a_gap_of_the_truth(self):
        new_york, los_angeles = Coordinates(40.7128, -74.0060), Coordinates(34.0522, -118.2437)
        road = RoutePath.from_coordinates([new_york, los_angeles])
        half_gap = road.spacing_miles / 2
        generator = random.Random(8)
        stations = [
            StationSite(
                i,
                destination(
                    road.points[generator.randrange(len(road))],
                    generator.uniform(0, 360),
                    generator.uniform(0, 60),
                ),
                PRICE,
            )
            for i in range(600)
        ]

        checked = 0
        for found in Corridor(road, stations).within(60.0):
            point = stations[found.station_id].coordinates
            along = along_track_miles(new_york, los_angeles, point)
            if not 0 <= along <= road.total_miles:
                continue  # the nearest spot is an end of the route, not the line itself
            checked += 1
            overstated = found.miles_from_route - cross_track_miles(new_york, los_angeles, point)
            assert -1e-6 <= overstated <= half_gap + 1e-6
            assert abs(found.mile_marker - along) <= half_gap + 1e-6
        assert checked > 300  # the check is meaningful

    def test_at_the_edge_of_the_margin_the_error_is_a_few_feet(self, road):
        # sqrt(10**2 + 0.25**2) - 10 = 0.0031 miles = 16 feet at most.
        base = road.points[len(road) // 2]
        halfway = destination(base, 0.0, road.spacing_miles / 2)  # between two route points
        station = StationSite(1, destination(halfway, 90.0, 10.0), PRICE)

        found = Corridor(road, [station]).within(10.1)[0]

        assert 10.0 <= found.miles_from_route <= 10.0 + 17 / 5280


class TestMessyRoutesAgainstBruteForce:
    def test_repeats_u_turns_the_date_line_and_the_poles(self):
        generator = random.Random(99)
        compared = 0
        for _ in range(40):
            route = random_route(generator)
            road = RoutePath.from_coordinates(
                route, spacing_miles=10 ** generator.uniform(-0.7, 0.4)
            )
            stations = [
                StationSite(
                    i,
                    destination(
                        route[generator.randrange(len(route))],
                        generator.uniform(0, 360),
                        10 ** generator.uniform(-1, 2.2),
                    ),
                    PRICE,
                )
                for i in range(120)
            ]
            corridor = Corridor(road, stations)
            latitudes = np.radians([p.latitude for p in road.points])
            longitudes = np.radians([p.longitude for p in road.points])

            for margin in (generator.uniform(0.5, 60), 10.0, 25.0, 50.0):
                found = {s.station_id: s for s in corridor.within(margin)}
                for station in stations:
                    lat, lon = (math.radians(v) for v in dataclasses.astuple(station.coordinates))
                    h = (
                        np.sin((latitudes - lat) / 2) ** 2
                        + np.cos(lat) * np.cos(latitudes) * np.sin((longitudes - lon) / 2) ** 2
                    )
                    miles = 2 * EARTH_RADIUS_MILES * np.arcsin(np.sqrt(np.minimum(1.0, h)))
                    nearest = int(np.argmin(miles))
                    if abs(miles[nearest] - margin) < 1e-5:
                        continue  # exactly on the edge: either answer is fine
                    compared += 1
                    assert (miles[nearest] <= margin) == (station.station_id in found)
                    if station.station_id in found:
                        assert found[station.station_id].mile_marker == road.mile_markers[nearest]
                        assert found[station.station_id].miles_from_route == pytest.approx(
                            miles[nearest], abs=1e-6
                        )
        assert compared == 40 * 4 * 120
