"""Planning a trip: one routing call, the stations near the road, and the cheapest fuel.

The routing service is a fake, so nothing here touches the network. The stations are real
rows in the test database.
"""

import copy
import math
import pickle
from decimal import Decimal

import pytest
from django.core.cache import cache

from apps.common.geo import Coordinates
from apps.trips.domain.route_path import RoutePath
from apps.trips.providers.base import (
    NoRouteFoundError,
    ProviderRoute,
    RoutingServiceError,
    RoutingTimeoutError,
)
from apps.trips.services import (
    NoTripPlanError,
    PointFarFromRoadError,
    TripPlan,
    plan_trip,
)
from apps.trips.tests.geo_helpers import destination, north_of

ORIGIN = Coordinates(40.0, -100.0)
pytestmark = pytest.mark.django_db


class FakeRouting:
    """Stands in for OSRM: returns one prepared route, and counts the calls."""

    def __init__(self, route):
        self.prepared = route
        self.calls = []

    def route(self, start, finish):
        self.calls.append((start, finish))
        if isinstance(self.prepared, Exception):
            raise self.prepared
        return self.prepared


@pytest.fixture(autouse=True)
def _empty_cache():
    cache.clear()
    yield
    cache.clear()


def road(miles, **overrides):
    """A straight road of ``miles`` going north from ORIGIN, and its far end."""
    finish = north_of(ORIGIN, miles)
    fields = {
        "coordinates": (ORIGIN, north_of(ORIGIN, miles / 2), finish),
        "distance_miles": float(miles),
        "duration_seconds": float(miles) * 60,
    }
    fields.update(overrides)
    return ProviderRoute(**fields), finish


def station_at(make_station, point, price="3.000", **overrides):
    return make_station(
        latitude=point.latitude,
        longitude=point.longitude,
        location_precision=overrides.pop("location_precision", "poi"),
        price=Decimal(price),
        **overrides,
    )


class TestATripThatCanBePlanned:
    def test_the_whole_flow_with_one_stop(self, make_station):
        route, finish = road(600, distance_miles=9999, duration_seconds=40000)
        station = station_at(
            make_station, north_of(ORIGIN, 300), name="MIDWAY FUEL", city="Nowhere", state="KS"
        )
        routing = FakeRouting(route)

        plan = plan_trip(ORIGIN, finish, provider=routing)

        assert routing.calls == [(ORIGIN, finish)]
        assert isinstance(plan, TripPlan)
        assert plan.distance_miles == 9999  # the service's own figure, kept as it sent it
        assert plan.duration_seconds == 40000
        assert plan.geometry is route.coordinates  # the road, not the resampled points
        assert plan.measured_miles == pytest.approx(600, abs=0.05)
        assert plan.measured_miles != pytest.approx(plan.distance_miles, rel=0.5)
        assert plan.margin_miles == 10
        assert [(stop.station_id, stop.name, stop.city, stop.state) for stop in plan.stops] == [
            (station.opis_id, "MIDWAY FUEL", "Nowhere", "KS")
        ]
        # Fuel is worked out from the measured road, so about 10 gallons are bought
        # (600 miles minus the free 500) and the other 990 gallons are not.
        assert plan.gallons_consumed == Decimal("60.000")
        assert plan.gallons_purchased == Decimal("10.000")
        assert plan.stops[0].gallons == Decimal("10.000")
        assert plan.stops[0].price_per_gallon == Decimal("3.000")
        assert plan.stops[0].cost == Decimal("30.00")
        assert plan.total_cost == Decimal("30.00")

    def test_the_gallons_follow_the_measured_road_when_it_is_not_a_round_number(self, make_station):
        route, finish = road(600, distance_miles=1.0)
        station_at(make_station, north_of(ORIGIN, 300))

        plan = plan_trip(ORIGIN, finish, provider=FakeRouting(route))

        measured = RoutePath.from_coordinates(route.coordinates).total_miles
        assert plan.measured_miles == measured
        assert float(plan.gallons_consumed) == pytest.approx(measured / 10, abs=0.001)
        assert float(plan.gallons_consumed) < 100  # not the 0.1 gallons of the reported mile

    def test_a_short_trip_costs_nothing_and_makes_no_stop(self, make_station):
        route, finish = road(200)
        station_at(make_station, north_of(ORIGIN, 100), price="9.99")

        plan = plan_trip(ORIGIN, finish, provider=FakeRouting(route))

        assert plan.stops == ()
        assert plan.total_cost == Decimal("0.00")
        assert plan.gallons_purchased == Decimal("0.000")
        assert plan.gallons_consumed == Decimal("20.000")
        assert plan.margin_miles == 10

    def test_a_trip_from_a_place_back_to_itself(self):
        route = ProviderRoute(coordinates=(ORIGIN, ORIGIN), distance_miles=0, duration_seconds=0)

        plan = plan_trip(ORIGIN, ORIGIN, provider=FakeRouting(route))

        assert plan.stops == ()
        assert plan.total_cost == Decimal("0.00")
        assert plan.distance_miles == 0
        assert plan.measured_miles == 0
        assert plan.gallons_consumed == Decimal("0.000")

    def test_the_cheaper_station_is_the_one_used(self, make_station):
        route, finish = road(700)
        station_at(make_station, north_of(ORIGIN, 200), price="5.00")
        cheap = station_at(make_station, north_of(ORIGIN, 400), price="3.00")

        plan = plan_trip(ORIGIN, finish, provider=FakeRouting(route))

        assert [stop.station_id for stop in plan.stops] == [cheap.opis_id]
        assert plan.total_cost == Decimal("60.00")

    def test_a_station_with_no_coordinates_is_ignored(self, make_station):
        route, finish = road(600)
        station_at(make_station, north_of(ORIGIN, 300))
        make_station()  # no latitude: not located yet

        plan = plan_trip(ORIGIN, finish, provider=FakeRouting(route))

        assert len(plan.stops) == 1

    def test_a_station_far_from_the_road_is_not_a_stop(self, make_station):
        route, finish = road(600)
        on_road = station_at(make_station, north_of(ORIGIN, 300), price="4.00")
        station_at(make_station, destination(north_of(ORIGIN, 300), 90, 80), price="1.00")

        plan = plan_trip(ORIGIN, finish, provider=FakeRouting(route))

        assert [stop.station_id for stop in plan.stops] == [on_road.opis_id]

    def test_the_database_is_read_once(self, make_station, django_assert_num_queries):
        route, finish = road(600)
        station_at(make_station, north_of(ORIGIN, 300))

        with django_assert_num_queries(1):
            plan_trip(ORIGIN, finish, provider=FakeRouting(route))


class TestWideningTheSearch:
    def test_twenty_miles_off_the_road_is_found_at_the_second_margin(self, make_station):
        route, finish = road(600)
        station = station_at(make_station, destination(north_of(ORIGIN, 300), 90, 20))
        routing = FakeRouting(route)

        plan = plan_trip(ORIGIN, finish, provider=routing)

        assert plan.margin_miles == 25
        assert [stop.station_id for stop in plan.stops] == [station.opis_id]
        assert len(routing.calls) == 1  # widening reuses the same route

    def test_forty_miles_off_the_road_is_found_at_the_widest_margin(self, make_station):
        route, finish = road(600)
        station_at(make_station, destination(north_of(ORIGIN, 300), 90, 40))

        plan = plan_trip(ORIGIN, finish, provider=FakeRouting(route))

        assert plan.margin_miles == 50

    def test_no_margin_can_bridge_the_gap(self, make_station):
        route, finish = road(600)
        station_at(make_station, destination(north_of(ORIGIN, 300), 90, 80))
        routing = FakeRouting(route)

        with pytest.raises(NoTripPlanError) as problem:
            plan_trip(ORIGIN, finish, provider=routing)

        assert problem.value.margin_miles == 50
        assert problem.value.gap_miles > 500
        assert "50" in str(problem.value)
        assert len(routing.calls) == 1

    def test_a_short_trip_does_not_widen_the_search_when_there_are_no_stations(self):
        route, finish = road(200)

        plan = plan_trip(ORIGIN, finish, provider=FakeRouting(route))

        assert plan.margin_miles == 10
        assert plan.stops == ()


class TestFarFromARoad:
    def test_just_under_the_limit_is_accepted(self, settings):
        settings.MAX_SNAP_MILES = 5
        route, finish = road(200, start_snap_miles=4.9, finish_snap_miles=5.0)

        plan = plan_trip(ORIGIN, finish, provider=FakeRouting(route))

        assert plan.stops == ()

    def test_exactly_the_limit_is_accepted(self, settings):
        settings.MAX_SNAP_MILES = 5
        route, finish = road(200, start_snap_miles=5.0, finish_snap_miles=5.0)

        assert plan_trip(ORIGIN, finish, provider=FakeRouting(route)).total_cost == Decimal("0.00")

    @pytest.mark.parametrize(
        ("start_snap", "finish_snap", "which"),
        [(5.1, 0.0, "start"), (0.0, 5.1, "finish"), (5.1, 9.0, "start")],
    )
    def test_just_over_the_limit_is_refused(self, settings, start_snap, finish_snap, which):
        settings.MAX_SNAP_MILES = 5
        route, finish = road(200, start_snap_miles=start_snap, finish_snap_miles=finish_snap)
        routing = FakeRouting(route)

        with pytest.raises(PointFarFromRoadError) as problem:
            plan_trip(ORIGIN, finish, provider=routing)

        assert problem.value.which == which
        assert problem.value.limit_miles == 5
        assert f"Your {which} point is" in str(problem.value)
        assert "nearest road" in str(problem.value)
        assert "5" in str(problem.value)
        assert len(routing.calls) == 1

    def test_the_message_quotes_the_distance(self, settings):
        settings.MAX_SNAP_MILES = 5
        route, finish = road(200, start_snap_miles=100.5)

        with pytest.raises(PointFarFromRoadError) as problem:
            plan_trip(ORIGIN, finish, provider=FakeRouting(route))

        assert str(problem.value) == (
            "Your start point is 100.5 miles from the nearest road (the limit is 5)."
        )

    def test_the_limit_comes_from_the_settings(self, settings):
        settings.MAX_SNAP_MILES = 30
        route, finish = road(200, start_snap_miles=20)

        assert plan_trip(ORIGIN, finish, provider=FakeRouting(route)).margin_miles == 10

    def test_a_refusal_does_not_read_the_database(
        self, make_station, django_assert_num_queries, settings
    ):
        settings.MAX_SNAP_MILES = 5
        station_at(make_station, north_of(ORIGIN, 100))
        route, finish = road(200, finish_snap_miles=80)

        with django_assert_num_queries(0), pytest.raises(PointFarFromRoadError):
            plan_trip(ORIGIN, finish, provider=FakeRouting(route))

    @pytest.mark.parametrize("snap", [math.nan, -1.0, math.inf])
    def test_a_snap_distance_that_is_not_a_real_one_is_a_bad_answer(self, snap):
        route, finish = road(200, start_snap_miles=snap)

        with pytest.raises(RoutingServiceError, match="distance from a road"):
            plan_trip(ORIGIN, finish, provider=FakeRouting(route))


class TestARouteThatCannotBeUsed:
    def test_a_line_of_one_point_is_a_bad_answer_not_a_crash(self):
        route = ProviderRoute(coordinates=(ORIGIN,), distance_miles=10, duration_seconds=10)

        with pytest.raises(RoutingServiceError, match="cannot be used"):
            plan_trip(ORIGIN, north_of(ORIGIN, 10), provider=FakeRouting(route))


class TestWhenTheRoutingServiceFails:
    @pytest.mark.parametrize(
        "error",
        [
            NoRouteFoundError("Impossible route between points"),
            RoutingTimeoutError("too slow"),
            RoutingServiceError("down"),
        ],
    )
    def test_the_error_reaches_the_caller_and_nothing_is_saved(self, error):
        routing = FakeRouting(error)

        with pytest.raises(type(error), match=str(error)):
            plan_trip(ORIGIN, north_of(ORIGIN, 200), provider=routing)
        with pytest.raises(type(error)):
            plan_trip(ORIGIN, north_of(ORIGIN, 200), provider=routing)

        assert len(routing.calls) == 2  # a failure is not cached


class TestInput:
    @pytest.mark.parametrize("limit", [0, -1, math.nan, math.inf, "5"])
    def test_an_unusable_snap_limit_is_a_clear_error_and_makes_no_routing_call(
        self, settings, limit
    ):
        settings.MAX_SNAP_MILES = limit
        routing = FakeRouting(road(200)[0])

        with pytest.raises(ValueError, match="MAX_SNAP_MILES"):
            plan_trip(ORIGIN, north_of(ORIGIN, 200), provider=routing)

        assert routing.calls == []

    def test_a_place_outside_the_area_is_refused_before_any_routing(self):
        london = Coordinates(51.5074, -0.1278)
        routing = FakeRouting(road(10)[0])

        with pytest.raises(ValueError, match="Canada"):
            plan_trip(london, ORIGIN, provider=routing)

        assert routing.calls == []

    def test_the_finish_is_checked_too(self):
        with pytest.raises(ValueError, match="finish"):
            plan_trip(ORIGIN, Coordinates(-33.8, 151.2), provider=FakeRouting(road(10)[0]))


class TestCaching:
    def test_the_second_identical_request_makes_no_routing_call_and_no_query(
        self, make_station, django_assert_num_queries
    ):
        route, finish = road(600)
        station_at(make_station, north_of(ORIGIN, 300))
        routing = FakeRouting(route)

        first = plan_trip(ORIGIN, finish, provider=routing)
        with django_assert_num_queries(0):
            second = plan_trip(ORIGIN, finish, provider=routing)

        assert second == first
        assert len(routing.calls) == 1

    def test_a_different_trip_is_not_served_from_the_cache(self):
        route, finish = road(200)
        other = north_of(ORIGIN, 100)
        routing = FakeRouting(route)

        plan_trip(ORIGIN, finish, provider=routing)
        plan_trip(ORIGIN, other, provider=routing)

        assert routing.calls == [(ORIGIN, finish), (ORIGIN, other)]

    def test_the_reverse_trip_is_a_different_trip(self):
        route, finish = road(200)
        routing = FakeRouting(route)

        plan_trip(ORIGIN, finish, provider=routing)
        plan_trip(finish, ORIGIN, provider=routing)

        assert len(routing.calls) == 2

    def test_two_points_that_agree_to_six_decimals_share_a_cached_trip(self):
        route, finish = road(200)
        routing = FakeRouting(route)
        almost = Coordinates(ORIGIN.latitude + 4e-7, ORIGIN.longitude)

        plan_trip(ORIGIN, finish, provider=routing)
        plan_trip(almost, finish, provider=routing)

        assert len(routing.calls) == 1

    def test_two_points_that_differ_at_six_decimals_do_not(self):
        route, finish = road(200)
        routing = FakeRouting(route)
        moved = Coordinates(ORIGIN.latitude + 5e-6, ORIGIN.longitude)

        plan_trip(ORIGIN, finish, provider=routing)
        plan_trip(moved, finish, provider=routing)

        assert len(routing.calls) == 2

    def test_a_cached_trip_keeps_the_price_from_when_it_was_planned(self, make_station):
        route, finish = road(600)
        station = station_at(make_station, north_of(ORIGIN, 300), price="3.000")
        routing = FakeRouting(route)

        first = plan_trip(ORIGIN, finish, provider=routing)
        station.price = Decimal("9.000")
        station.save()
        second = plan_trip(ORIGIN, finish, provider=routing)

        assert second.total_cost == first.total_cost == Decimal("30.00")
        assert len(routing.calls) == 1

    def test_tightening_the_snap_limit_does_not_serve_a_trip_that_is_now_too_far(self, settings):
        # Saved under a generous limit. The limit is then tightened: the saved answer must
        # not skip the check, or a point 20 miles from any road would still be planned.
        settings.MAX_SNAP_MILES = 30
        route, finish = road(200, start_snap_miles=20)
        routing = FakeRouting(route)
        plan_trip(ORIGIN, finish, provider=routing)

        settings.MAX_SNAP_MILES = 5

        with pytest.raises(PointFarFromRoadError):
            plan_trip(ORIGIN, finish, provider=routing)
        assert len(routing.calls) == 2

    def test_a_saved_value_that_is_not_a_trip_is_ignored(self, monkeypatch):
        route, finish = road(200)
        routing = FakeRouting(route)
        monkeypatch.setattr(
            "apps.trips.services.cache.get", lambda *args, **kwargs: {"not": "a trip"}
        )

        plan = plan_trip(ORIGIN, finish, provider=routing)

        assert isinstance(plan, TripPlan)
        assert len(routing.calls) == 1

    def test_a_cache_time_of_zero_asks_the_routing_service_every_time(self, settings):
        settings.TRIP_CACHE_SECONDS = 0
        route, finish = road(200)
        routing = FakeRouting(route)

        plan_trip(ORIGIN, finish, provider=routing)
        plan_trip(ORIGIN, finish, provider=routing)

        assert len(routing.calls) == 2

    def test_a_negative_cache_time_does_not_crash_and_does_not_cache(self, settings):
        settings.TRIP_CACHE_SECONDS = -5
        route, finish = road(200)
        routing = FakeRouting(route)

        plan_trip(ORIGIN, finish, provider=routing)
        plan_trip(ORIGIN, finish, provider=routing)

        assert len(routing.calls) == 2

    def test_a_failed_trip_is_not_cached(self, make_station):
        route, finish = road(600)
        station_at(make_station, destination(north_of(ORIGIN, 300), 90, 80))
        routing = FakeRouting(route)

        with pytest.raises(NoTripPlanError):
            plan_trip(ORIGIN, finish, provider=routing)
        with pytest.raises(NoTripPlanError):
            plan_trip(ORIGIN, finish, provider=routing)

        assert len(routing.calls) == 2

    def test_a_point_far_from_a_road_is_not_cached(self, settings):
        settings.MAX_SNAP_MILES = 5
        route, finish = road(200, start_snap_miles=40)
        routing = FakeRouting(route)

        with pytest.raises(PointFarFromRoadError):
            plan_trip(ORIGIN, finish, provider=routing)
        with pytest.raises(PointFarFromRoadError):
            plan_trip(ORIGIN, finish, provider=routing)

        assert len(routing.calls) == 2

    def test_the_result_can_be_pickled_for_a_cache_that_needs_it(self, make_station):
        route, finish = road(600)
        station_at(make_station, north_of(ORIGIN, 300))

        plan = plan_trip(ORIGIN, finish, provider=FakeRouting(route))

        assert pickle.loads(pickle.dumps(plan)) == plan

    def test_the_result_cannot_be_changed(self, make_station):
        route, finish = road(600)
        station_at(make_station, north_of(ORIGIN, 300))
        plan = plan_trip(ORIGIN, finish, provider=FakeRouting(route))

        with pytest.raises(AttributeError):
            plan.total_cost = Decimal("0")  # type: ignore[misc]
        assert isinstance(plan.stops, tuple)


class TestWhichClientIsUsed:
    def test_the_given_provider_is_the_one_asked(self):
        route, finish = road(200)
        routing = FakeRouting(route)

        plan_trip(ORIGIN, finish, provider=routing)

        assert len(routing.calls) == 1

    def test_without_one_the_shared_client_is_asked(self, monkeypatch):
        route, finish = road(200)
        routing = FakeRouting(route)
        monkeypatch.setattr("apps.trips.services.get_shared_client", lambda: routing)

        plan_trip(ORIGIN, finish)

        assert routing.calls == [(ORIGIN, finish)]


class TestTheErrorsThemselves:
    def test_a_point_far_from_a_road_survives_copying_and_pickling(self):
        original = PointFarFromRoadError("finish", 12.25, 5)

        for clone in (copy.copy(original), pickle.loads(pickle.dumps(original))):
            assert type(clone) is PointFarFromRoadError
            assert str(clone) == str(original)
            assert (clone.which, clone.miles, clone.limit_miles) == ("finish", 12.25, 5)

    def test_a_trip_with_no_plan_survives_copying_and_pickling(self):
        original = NoTripPlanError(
            gap_start_mile=100, gap_end_mile=700, range_miles=500, margin_miles=50
        )

        for clone in (copy.copy(original), pickle.loads(pickle.dumps(original))):
            assert type(clone) is NoTripPlanError
            assert str(clone) == str(original)
            assert clone.gap_miles == 600
            assert clone.margin_miles == 50

    def test_both_are_ordinary_exceptions(self):
        assert issubclass(PointFarFromRoadError, Exception)
        assert issubclass(NoTripPlanError, Exception)
