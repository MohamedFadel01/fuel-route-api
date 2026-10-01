"""Tests for the fuel planner.

The car starts with a full, free tank (500 miles, 10 miles per gallon). The planner
chooses where to buy fuel and how much, to spend as little as possible.

Hand-made cases come first, each with an answer worked out on paper. The last class
compares the planner with an exact linear-programming solver on hundreds of random trips.
"""

import dataclasses
import math
import random
import time
from decimal import Decimal

import numpy as np
import pytest
from scipy.optimize import linprog

from apps.trips.domain.corridor import StationOnRoute
from apps.trips.domain.optimizer import (
    DEFAULT_MILES_PER_GALLON,
    DEFAULT_RANGE_MILES,
    FuelPlan,
    FuelStop,
    NoFuelPlanError,
    plan_fuel_stops,
)


def at(mile, price, station_id):
    """A station ``mile`` miles along the route, selling at ``price`` per gallon."""
    return StationOnRoute(
        station_id=station_id,
        mile_marker=float(mile),
        miles_from_route=1.0,
        price=Decimal(str(price)),
    )


def stops_of(plan):
    """(station id, gallons, cost) for every stop, to compare plans at a glance."""
    return [(stop.station_id, stop.gallons, stop.cost) for stop in plan.stops]


def d(text):
    return Decimal(text)


class TestTheDefaults:
    def test_the_car_drives_500_miles_on_a_tank_at_10_miles_per_gallon(self):
        assert DEFAULT_RANGE_MILES == 500.0
        assert DEFAULT_MILES_PER_GALLON == 10.0


class TestTripsThatNeedNoFuel:
    def test_a_short_trip_needs_no_stop_and_costs_nothing(self):
        plan = plan_fuel_stops(300.0, [])

        assert plan.stops == ()
        assert plan.total_cost == d("0.00")
        assert plan.gallons_purchased == d("0.000")
        assert plan.gallons_consumed == d("30.000")

    def test_stations_are_not_used_when_the_starting_tank_is_enough(self):
        plan = plan_fuel_stops(300.0, [at(100, "2.50", 1), at(250, "3.10", 2)])

        assert plan.stops == ()
        assert plan.total_cost == d("0.00")

    def test_exactly_one_tank_is_enough(self):
        assert plan_fuel_stops(500.0, []).stops == ()

    def test_a_hair_over_one_tank_is_still_enough(self):
        # Distances come from floating-point sums; 1e-10 mile is not a real difference.
        assert plan_fuel_stops(500.0 + 1e-10, []).stops == ()

    def test_a_trip_of_zero_miles(self):
        plan = plan_fuel_stops(0.0, [])

        assert plan.stops == ()
        assert plan.gallons_consumed == d("0.000")

    def test_a_station_exactly_where_a_zero_mile_trip_starts_and_ends_is_ignored(self):
        assert plan_fuel_stops(0.0, [at(0, "3.00", 1)]).stops == ()


class TestSimpleChoices:
    def test_one_stop_buys_just_what_is_needed_to_finish(self):
        # 800 miles: the free tank covers 500, so 300 miles (30 gallons) must be bought.
        plan = plan_fuel_stops(800.0, [at(400, "3.00", 1)])

        assert stops_of(plan) == [(1, d("30.000"), d("90.00"))]
        assert plan.total_cost == d("90.00")
        assert plan.gallons_purchased == d("30.000")
        assert plan.gallons_consumed == d("80.000")

    def test_a_cheaper_station_ahead_means_buying_only_what_gets_there(self):
        # Mile 400 costs 5.00, mile 600 costs 3.00. At 400 the tank holds 100 miles; reaching
        # 600 needs 200, so only 100 miles (10 gallons) are bought at the dear station.
        plan = plan_fuel_stops(800.0, [at(400, "5.00", 1), at(600, "3.00", 2)])

        assert stops_of(plan) == [(1, d("10.000"), d("50.00")), (2, d("20.000"), d("60.00"))]
        assert plan.total_cost == d("110.00")

    def test_the_cheaper_station_is_used_even_when_the_finish_is_within_reach(self):
        # From mile 300 the finish (mile 700) is 400 away, within a full tank, but the
        # station at mile 450 is cheaper, so the fuel should be bought there.
        plan = plan_fuel_stops(700.0, [at(300, "5.00", 1), at(450, "3.00", 2)])

        assert stops_of(plan) == [(2, d("20.000"), d("60.00"))]
        assert plan.total_cost == d("60.00")

    def test_the_dear_station_is_skipped_entirely_when_a_cheaper_one_is_next(self):
        plan = plan_fuel_stops(700.0, [at(300, "4.00", 1), at(450, "3.50", 2)])

        assert stops_of(plan) == [(2, d("20.000"), d("70.00"))]

    def test_it_goes_for_the_cheapest_station_in_reach_not_the_nearest(self):
        # From mile 100 (price 3.00) nothing cheaper exists, and 300 / 500 are both in reach.
        # Fill up and head for the cheaper of the two, mile 500 at 3.20, not mile 300 at 3.50.
        plan = plan_fuel_stops(1000.0, [at(100, "3.00", 1), at(300, "3.50", 2), at(500, "3.20", 3)])

        assert stops_of(plan) == [(1, d("10.000"), d("30.00")), (3, d("40.000"), d("128.00"))]
        assert plan.total_cost == d("158.00")

    def test_the_only_station_is_used_even_when_it_is_dear(self):
        plan = plan_fuel_stops(900.0, [at(450, "9.99", 1)])

        assert stops_of(plan) == [(1, d("40.000"), d("399.60"))]


class TestPriceShapes:
    def test_rising_prices_fill_up_early_and_buy_the_rest_late(self):
        plan = plan_fuel_stops(1200.0, [at(450, "3.00", 1), at(900, "4.00", 2)])

        assert stops_of(plan) == [(1, d("45.000"), d("135.00")), (2, d("25.000"), d("100.00"))]
        assert plan.total_cost == d("235.00")

    def test_falling_prices_buy_only_what_reaches_the_next_cheaper_station(self):
        plan = plan_fuel_stops(1000.0, [at(200, "5.00", 1), at(400, "4.00", 2), at(600, "3.00", 3)])

        assert stops_of(plan) == [(2, d("10.000"), d("40.00")), (3, d("40.000"), d("120.00"))]
        assert plan.total_cost == d("160.00")

    def test_equal_prices_cost_the_same_however_they_are_split(self):
        plan = plan_fuel_stops(1200.0, [at(300, "3.00", 1), at(600, "3.00", 2), at(900, "3.00", 3)])

        assert plan.gallons_purchased == d("70.000")
        assert plan.total_cost == d("210.00")
        assert [stop.station_id for stop in plan.stops] == [1, 2, 3]

    def test_among_equally_cheap_stations_it_goes_to_the_farthest_one_in_reach(self):
        # Miles 400 and 480 both cost 3.00; driving to 480 skips a stop.
        plan = plan_fuel_stops(950.0, [at(200, "3.00", 1), at(400, "3.00", 2), at(480, "3.00", 3)])

        assert [stop.station_id for stop in plan.stops] == [1, 3]
        assert plan.total_cost == d("135.00")

    def test_a_dear_stretch_between_cheap_ones_is_driven_through(self):
        plan = plan_fuel_stops(
            1300.0,
            [at(400, "3.00", 1), at(700, "6.00", 2), at(850, "7.00", 3), at(900, "3.10", 4)],
        )

        assert [stop.station_id for stop in plan.stops] == [1, 4]

    def test_stops_are_always_in_driving_order(self):
        plan = plan_fuel_stops(
            2000.0, [at(m, "3.00", i) for i, m in enumerate([1500, 300, 900, 600, 1200], 1)]
        )

        markers = [stop.mile_marker for stop in plan.stops]
        assert markers == sorted(markers)


class TestStartAndFinish:
    def test_a_station_at_the_start_is_not_used_because_the_tank_is_already_full(self):
        plan = plan_fuel_stops(800.0, [at(0, "1.00", 1), at(400, "3.00", 2)])

        assert stops_of(plan) == [(2, d("30.000"), d("90.00"))]

    def test_a_station_at_the_finish_is_not_a_stop(self):
        plan = plan_fuel_stops(800.0, [at(400, "3.00", 1), at(800, "1.00", 2)])

        assert [stop.station_id for stop in plan.stops] == [1]

    def test_a_station_at_the_finish_cannot_rescue_a_trip_that_cannot_reach_it(self):
        with pytest.raises(NoFuelPlanError):
            plan_fuel_stops(800.0, [at(800, "1.00", 1)])

    def test_stations_at_the_start_and_finish_do_not_hide_a_gap(self):
        with pytest.raises(NoFuelPlanError):
            plan_fuel_stops(1100.0, [at(0, "3.00", 1), at(1100, "3.00", 2)])

    def test_a_station_just_before_the_finish_is_used_when_it_is_the_cheapest(self):
        # Mile 500 costs 3.00 and mile 999.9 costs 1.00: buy only what reaches the cheap one
        # (499.9 miles), then the last 0.1 mile there.
        plan = plan_fuel_stops(1000.0, [at(500, "3.00", 1), at(999.9, "1.00", 2)])

        assert stops_of(plan) == [(1, d("49.990"), d("149.97")), (2, d("0.010"), d("0.01"))]


class TestWhenNoPlanExists:
    def test_a_long_trip_with_no_stations(self):
        with pytest.raises(NoFuelPlanError) as problem:
            plan_fuel_stops(1000.0, [])

        assert problem.value.gap_start_mile == 0.0
        assert problem.value.gap_end_mile == 1000.0
        assert problem.value.gap_miles == 1000.0

    def test_a_gap_before_the_first_station(self):
        with pytest.raises(NoFuelPlanError) as problem:
            plan_fuel_stops(1000.0, [at(600, "3.00", 1)])

        assert (problem.value.gap_start_mile, problem.value.gap_end_mile) == (0.0, 600.0)

    def test_a_gap_in_the_middle(self):
        with pytest.raises(NoFuelPlanError) as problem:
            plan_fuel_stops(1200.0, [at(300, "3.00", 1), at(900, "3.00", 2)])

        assert (problem.value.gap_start_mile, problem.value.gap_end_mile) == (300.0, 900.0)
        assert problem.value.gap_miles == 600.0

    def test_a_gap_after_the_last_station(self):
        with pytest.raises(NoFuelPlanError) as problem:
            plan_fuel_stops(1100.0, [at(300, "3.00", 1)])

        assert (problem.value.gap_start_mile, problem.value.gap_end_mile) == (300.0, 1100.0)

    def test_the_first_gap_is_the_one_reported(self):
        with pytest.raises(NoFuelPlanError) as problem:
            plan_fuel_stops(1400.0, [at(100, "3.00", 1), at(700, "3.00", 2)])

        assert (problem.value.gap_start_mile, problem.value.gap_end_mile) == (100.0, 700.0)

    def test_a_gap_of_exactly_one_tank_is_fine(self):
        plan = plan_fuel_stops(1000.0, [at(500, "3.00", 1)])

        assert stops_of(plan) == [(1, d("50.000"), d("150.00"))]

    def test_a_gap_a_little_over_one_tank_is_not(self):
        with pytest.raises(NoFuelPlanError):
            plan_fuel_stops(1000.01, [at(500, "3.00", 1)])

    def test_the_message_says_what_is_wrong_in_plain_words(self):
        with pytest.raises(NoFuelPlanError) as problem:
            plan_fuel_stops(1200.0, [at(300, "3.00", 1), at(900, "3.00", 2)])

        message = str(problem.value)
        assert "600" in message
        assert "300" in message
        assert "900" in message
        assert "500" in message

    def test_it_is_an_ordinary_exception_that_callers_can_catch_by_name(self):
        assert issubclass(NoFuelPlanError, Exception)
        assert not issubclass(NoFuelPlanError, ValueError)  # bad input is a different problem


class TestStationsAtTheSameSpot:
    def test_the_cheaper_of_two_stations_at_one_mile_marker_is_used(self):
        # The dear one has the lower ID, so only the price can explain the choice.
        plan = plan_fuel_stops(800.0, [at(300, "3.50", 3), at(300, "3.00", 7)])

        assert stops_of(plan) == [(7, d("30.000"), d("90.00"))]

    def test_equal_prices_at_one_mile_marker_go_to_the_lowest_id(self):
        plan = plan_fuel_stops(800.0, [at(300, "3.00", 9), at(300, "3.00", 4)])

        assert [stop.station_id for stop in plan.stops] == [4]

    def test_equal_prices_at_one_marker_go_to_the_lowest_id_when_filling_up_first(self):
        # Mile 100 (2.00) is the cheapest in reach, so the car fills up there and heads for
        # mile 300, where two stations tie on price: it must be the one with the lower ID.
        stations = [at(100, "2.00", 1), at(300, "3.00", 9), at(300, "3.00", 4)]

        plan = plan_fuel_stops(700.0, stations)

        assert [stop.station_id for stop in plan.stops] == [1, 4]

    def test_equal_prices_at_one_spot_reached_when_filling_up_also_go_to_the_lowest_id(self):
        # Nothing is cheaper than mile 200, so the car fills up there and heads for the
        # cheapest station in reach: mile 480, where two stations tie.
        stations = [at(200, "3.00", 1), at(480, "3.00", 9), at(480, "3.00", 4)]

        plan = plan_fuel_stops(950.0, stations)

        assert [stop.station_id for stop in plan.stops] == [1, 4]

    def test_a_station_a_hair_further_on_but_cheaper_replaces_the_nearer_one(self):
        plan = plan_fuel_stops(800.0, [at(300, "4.00", 1), at(300.0001, "3.00", 2)])

        assert [stop.station_id for stop in plan.stops] == [2]

    def test_many_stations_at_the_same_marker(self):
        stations = [at(250, price, i) for i, price in enumerate(["3.3", "3.1", "3.2", "3.1"], 1)]

        plan = plan_fuel_stops(750.0, stations)

        assert [stop.station_id for stop in plan.stops] == [2]


class TestMoneyAndGallons:
    def test_gallons_are_rounded_to_a_thousandth_and_costs_to_the_cent(self):
        # 7.776 miles over the starting tank is 0.7776 gallons: 0.778, costing 2.334: 2.33.
        plan = plan_fuel_stops(507.776, [at(100, "3.00", 1)])

        assert stops_of(plan) == [(1, d("0.778"), d("2.33"))]
        assert plan.gallons_consumed == d("50.778")

    def test_half_a_cent_rounds_up(self):
        # 10 miles = 1.000 gallon at 3.005 is 3.005, which must become 3.01, not 3.00.
        plan = plan_fuel_stops(510.0, [at(100, "3.005", 1)])

        assert plan.stops[0].cost == d("3.01")

    def test_just_under_half_a_cent_rounds_down(self):
        plan = plan_fuel_stops(510.0, [at(100, "3.004", 1)])

        assert plan.stops[0].cost == d("3.00")

    def test_prices_with_many_decimals_are_used_exactly(self):
        plan = plan_fuel_stops(550.0, [at(100, "3.0599", 1)])

        # 5.000 gallons at 3.0599 = 15.2995 -> 15.30
        assert plan.stops[0].gallons == d("5.000")
        assert plan.stops[0].cost == d("15.30")

    def test_the_totals_are_the_sums_of_the_stops(self):
        plan = plan_fuel_stops(
            1600.0,
            [at(250, "3.337", 1), at(700, "3.911", 2), at(1100, "3.045", 3), at(1500, "3.5", 4)],
        )

        assert plan.total_cost == sum((stop.cost for stop in plan.stops), d("0"))
        assert plan.gallons_purchased == sum((stop.gallons for stop in plan.stops), d("0"))

    def test_the_numbers_are_decimals_with_fixed_places(self):
        plan = plan_fuel_stops(800.0, [at(400, "3.00", 1)])

        assert isinstance(plan.total_cost, Decimal)
        assert plan.total_cost.as_tuple().exponent == -2
        assert plan.stops[0].cost.as_tuple().exponent == -2
        assert plan.stops[0].gallons.as_tuple().exponent == -3
        assert plan.gallons_purchased.as_tuple().exponent == -3
        assert plan.gallons_consumed.as_tuple().exponent == -3

    def test_a_stop_reports_where_it_is_and_the_price(self):
        stop = plan_fuel_stops(800.0, [at(400.5, "3.019", 42)]).stops[0]

        assert stop.station_id == 42
        assert stop.mile_marker == 400.5
        assert stop.price == d("3.019")

    def test_a_stop_that_would_buy_less_than_a_drop_is_left_out(self):
        # 0.0004 miles over the tank is 0.00004 gallons, which rounds to nothing.
        plan = plan_fuel_stops(500.0004, [at(100, "3.00", 1)])

        assert plan.stops == ()
        assert plan.total_cost == d("0.00")

    def test_results_cannot_be_changed(self):
        plan = plan_fuel_stops(800.0, [at(400, "3.00", 1)])

        with pytest.raises(dataclasses.FrozenInstanceError):
            plan.total_cost = d("0")  # type: ignore[misc]
        with pytest.raises(dataclasses.FrozenInstanceError):
            plan.stops[0].gallons = d("0")  # type: ignore[misc]
        assert isinstance(plan.stops, tuple)
        assert isinstance(plan, FuelPlan)
        assert isinstance(plan.stops[0], FuelStop)


class TestVehicleSettings:
    def test_another_range_and_fuel_economy(self):
        # 100 miles per tank at 20 miles per gallon, over 250 miles.
        plan = plan_fuel_stops(
            250.0,
            [at(90, "3.00", 1), at(180, "3.00", 2)],
            range_miles=100.0,
            miles_per_gallon=20.0,
        )

        assert stops_of(plan) == [(1, d("4.500"), d("13.50")), (2, d("3.000"), d("9.00"))]
        assert plan.gallons_consumed == d("12.500")

    def test_a_shorter_range_makes_a_gap_impossible(self):
        stations = [at(300, "3.00", 1)]
        assert plan_fuel_stops(700.0, stations, range_miles=400.0).stops
        with pytest.raises(NoFuelPlanError):
            plan_fuel_stops(700.0, stations, range_miles=250.0)

    def test_the_error_message_uses_the_range_it_was_given(self):
        with pytest.raises(NoFuelPlanError, match="250"):
            plan_fuel_stops(700.0, [], range_miles=250.0)


class TestInputChecks:
    @pytest.mark.parametrize("total", [-1.0, -1e-9, math.nan, math.inf, -math.inf])
    def test_the_trip_length_must_be_a_finite_number_of_miles_not_below_zero(self, total):
        with pytest.raises(ValueError, match="trip"):
            plan_fuel_stops(total, [])

    @pytest.mark.parametrize("value", [0.0, -5.0, math.nan, math.inf])
    def test_the_range_must_be_positive_and_finite(self, value):
        with pytest.raises(ValueError, match="range"):
            plan_fuel_stops(100.0, [], range_miles=value)

    @pytest.mark.parametrize("value", [0.0, -5.0, math.nan, math.inf])
    def test_the_fuel_economy_must_be_positive_and_finite(self, value):
        with pytest.raises(ValueError, match="miles per gallon"):
            plan_fuel_stops(100.0, [], miles_per_gallon=value)

    @pytest.mark.parametrize("price", ["0", "-3.00", "NaN", "Infinity", "-Infinity"])
    def test_prices_must_be_positive_and_finite(self, price):
        with pytest.raises(ValueError, match="price"):
            plan_fuel_stops(800.0, [at(100, price, 1)])

    @pytest.mark.parametrize("marker", [-0.001, math.nan, math.inf, -math.inf])
    def test_mile_markers_must_be_finite_and_not_below_zero(self, marker):
        with pytest.raises(ValueError, match="mile marker"):
            plan_fuel_stops(800.0, [at(marker, "3.00", 1)])

    def test_a_station_beyond_the_finish_is_a_mistake(self):
        with pytest.raises(ValueError, match="beyond the finish"):
            plan_fuel_stops(800.0, [at(800.001, "3.00", 1)])

    def test_duplicate_station_ids_are_refused(self):
        with pytest.raises(ValueError, match="Duplicate station IDs: 5"):
            plan_fuel_stops(800.0, [at(100, "3.00", 5), at(200, "3.10", 5)])

    def test_a_problem_is_reported_even_for_a_station_that_would_not_be_used(self):
        with pytest.raises(ValueError, match="price"):
            plan_fuel_stops(100.0, [at(50, "0", 1)])

    def test_the_input_order_does_not_matter(self):
        stations = [
            at(m, p, i)
            for i, (m, p) in enumerate(
                [
                    (200, "3.1"),
                    (350, "3.0"),
                    (350, "2.9"),
                    (700, "3.4"),
                    (900, "3.2"),
                    (1100, "3.0"),
                ],
                1,
            )
        ]
        expected = plan_fuel_stops(1500.0, stations)

        generator = random.Random(3)
        for _ in range(20):
            shuffled = stations[:]
            generator.shuffle(shuffled)
            assert plan_fuel_stops(1500.0, shuffled) == expected

    def test_the_stations_are_not_modified_and_any_iterable_works(self):
        stations = [at(600, "3.0", 2), at(300, "3.0", 1)]
        before = stations[:]

        from_list = plan_fuel_stops(1000.0, stations)
        from_generator = plan_fuel_stops(1000.0, (s for s in stations))

        assert stations == before
        assert from_list == from_generator


# ----------------------------------------------------------------------------------------
# Comparison with an exact solver
# ----------------------------------------------------------------------------------------


def cheapest_possible_cost(total, stations, range_miles, miles_per_gallon):
    """The true minimum cost, from linear programming. ``None`` when no plan exists.

    ``x[i]`` is the number of miles' worth of fuel bought at station ``i``. Arriving at a
    station the tank must not be below empty, and after buying it must not exceed a full tank:

        range + sum(x[:i]) - marker[i]  >= 0            (arrive with fuel)
        range + sum(x[:i+1]) - marker[i] <= range       (never more than a full tank)

    and the same "arrive with fuel" condition holds at the finish.
    """
    usable = sorted((s for s in stations if s.mile_marker < total), key=lambda s: s.mile_marker)
    if not usable:
        return 0.0 if total <= range_miles else None
    count = len(usable)
    markers = np.array([s.mile_marker for s in usable])
    cost_per_mile = np.array([float(s.price) for s in usable]) / miles_per_gallon
    rows, limits = [], []
    for i in range(count):
        arrive = np.zeros(count)
        arrive[:i] = -1.0
        rows.append(arrive)
        limits.append(range_miles - markers[i])
        capacity = np.zeros(count)
        capacity[: i + 1] = 1.0
        rows.append(capacity)
        limits.append(markers[i])
    rows.append(-np.ones(count))
    limits.append(range_miles - total)
    result = linprog(
        cost_per_mile,
        A_ub=np.array(rows),
        b_ub=np.array(limits),
        bounds=(0, None),
        method="highs",
    )
    return float(result.fun) if result.status == 0 else None


def tank_after_driving(plan, total, range_miles, miles_per_gallon):
    """Replay the plan and return (lowest tank on arrival, highest tank after filling, tank at
    the finish), all in miles of fuel."""
    fuel, position = range_miles, 0.0
    lowest, highest = range_miles, range_miles
    for stop in plan.stops:
        fuel -= stop.mile_marker - position
        position = stop.mile_marker
        lowest = min(lowest, fuel)
        fuel += float(stop.gallons) * miles_per_gallon
        highest = max(highest, fuel)
    fuel -= total - position
    return min(lowest, fuel), highest, fuel


def random_trip(generator):
    total = generator.choice([generator.uniform(5, 499), generator.uniform(500, 3000)])
    stations = []
    markers = []
    for station_id in range(1, generator.randint(0, 40) + 1):
        roll = generator.random()
        if roll < 0.05:
            marker = 0.0
        elif roll < 0.10:
            marker = total
        elif roll < 0.25 and markers:
            marker = generator.choice(markers)  # exactly the same place as another station
        else:
            marker = generator.uniform(0, total)
        markers.append(marker)
        if generator.random() < 0.4:
            price = generator.choice(["3.000", "3.499"])  # plenty of ties
        else:
            price = f"{generator.uniform(2.5, 4.5):.3f}"
        stations.append(at(marker, price, station_id))
    return total, stations


class TestAgainstLinearProgramming:
    def test_random_trips_cost_exactly_the_minimum_and_the_car_never_runs_dry(self):
        generator = random.Random(2024)
        feasible = infeasible = with_stops = 0
        for _ in range(600):
            total, stations = random_trip(generator)
            best = cheapest_possible_cost(
                total, stations, DEFAULT_RANGE_MILES, DEFAULT_MILES_PER_GALLON
            )

            if best is None:
                infeasible += 1
                with pytest.raises(NoFuelPlanError):
                    plan_fuel_stops(total, stations)
                continue

            feasible += 1
            plan = plan_fuel_stops(total, stations)
            with_stops += bool(plan.stops)
            exact_cost = sum(float(stop.gallons * stop.price) for stop in plan.stops)
            assert exact_cost == pytest.approx(best, abs=0.003 * (len(plan.stops) + 1))
            lowest, highest, at_finish = tank_after_driving(
                plan, total, DEFAULT_RANGE_MILES, DEFAULT_MILES_PER_GALLON
            )
            assert lowest >= -0.05  # never below empty (gallons are rounded to 0.001)
            assert highest <= DEFAULT_RANGE_MILES + 0.05  # never above a full tank
            if plan.stops:
                assert at_finish <= 0.05  # nothing bought that was not needed
            assert all(stop.gallons > 0 for stop in plan.stops)

        # The comparison only means something if it covered both kinds of trips.
        assert feasible > 150
        assert infeasible > 30
        assert with_stops > 100

    @pytest.mark.parametrize(("range_miles", "miles_per_gallon"), [(120.0, 8.0), (800.0, 25.0)])
    def test_other_vehicles_also_match(self, range_miles, miles_per_gallon):
        generator = random.Random(int(range_miles))
        compared = 0
        for _ in range(250):
            total = generator.uniform(10, range_miles * 4)
            stations = [
                at(generator.uniform(0, total), f"{generator.uniform(2.5, 4.5):.3f}", i)
                for i in range(1, generator.randint(0, 30) + 1)
            ]
            best = cheapest_possible_cost(total, stations, range_miles, miles_per_gallon)
            if best is None:
                with pytest.raises(NoFuelPlanError):
                    plan_fuel_stops(
                        total, stations, range_miles=range_miles, miles_per_gallon=miles_per_gallon
                    )
                continue
            compared += 1
            plan = plan_fuel_stops(
                total, stations, range_miles=range_miles, miles_per_gallon=miles_per_gallon
            )
            exact_cost = sum(float(stop.gallons * stop.price) for stop in plan.stops)
            assert exact_cost == pytest.approx(best, abs=0.003 * (len(plan.stops) + 1))
        assert compared > 60

    def test_the_comparison_itself_can_tell_a_good_plan_from_a_bad_one(self):
        # Guard against a solver that accepts everything: here the optimum is known by hand.
        stations = [at(400, "5.00", 1), at(600, "3.00", 2)]

        assert cheapest_possible_cost(800.0, stations, 500.0, 10.0) == pytest.approx(110.0)
        assert cheapest_possible_cost(800.0, [stations[0]], 500.0, 10.0) == pytest.approx(150.0)
        assert cheapest_possible_cost(1100.0, [stations[0]], 500.0, 10.0) is None
        assert cheapest_possible_cost(300.0, [], 500.0, 10.0) == 0.0


class TestSpeed:
    def test_thousands_of_stations_are_planned_quickly(self):
        generator = random.Random(5)
        stations = [
            at(generator.uniform(0, 3000), f"{generator.uniform(2.5, 4.5):.3f}", i)
            for i in range(1, 4001)
        ]

        started = time.perf_counter()
        plan = plan_fuel_stops(3000.0, stations)
        elapsed = time.perf_counter() - started

        assert plan.stops
        assert elapsed < 2.0
        assert len({stop.station_id for stop in plan.stops}) == len(plan.stops)
