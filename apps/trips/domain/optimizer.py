"""The cheapest way to buy fuel along a route.

The trip is a line from mile 0 to ``total_miles``. The car starts with a full tank that is
free (it is not charged for), holds ``range_miles`` miles of fuel, and can buy fuel at the
stations along the line, each with its own price. The planner decides where to buy and how
much, so that the whole trip costs as little as possible.

The rule it follows, standing at a station with some fuel in the tank:

1. If a station that is *strictly cheaper* lies within reach of a full tank, buy only enough
   to get to the nearest such station (maybe nothing at all): the cheaper fuel is better.
   The finish counts as a station with a price of zero, so the finish is the "cheaper
   station" when nothing else is cheaper and it is within reach.
2. Otherwise this station is the cheapest within reach: fill the tank, then drive to the
   cheapest station within reach (the farthest one if several cost the same).

This is the classic greedy answer to the "gas station problem", and it is provably the
cheapest. The tests check it against an exact linear-programming solver on random trips.

If two consecutive stations (or the start, or the finish) are further apart than one tank
can cover, no plan exists and ``NoFuelPlanError`` says where the gap is.

Money and gallons are ``Decimal``: gallons are rounded to a thousandth and each stop's cost
to the cent (halves round up). The totals are sums of the rounded stops, so the numbers the
caller shows always add up. The rounding moves the fuel in the tank by at most 0.005 of a
mile per stop (about 25 feet), so over a whole trip the tank can end up a few hundred feet
from what the numbers say, which does not matter.

Everything here is plain Python, with no database and no network.
"""

import math
from bisect import bisect_right
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from itertools import pairwise

from apps.trips.domain.corridor import StationOnRoute

DEFAULT_RANGE_MILES = 500.0
DEFAULT_MILES_PER_GALLON = 10.0

# Distances are sums of floating-point numbers. A difference this small is not real, so
# "exactly one tank away" must still count as reachable.
_MILES_TOLERANCE = 1e-9

_GALLON_PLACES = Decimal("0.001")
_CENT = Decimal("0.01")

_NO_PRICE_LIMIT = Decimal("Infinity")  # the start of the trip: nothing is cheaper than free
_FREE = Decimal(0)  # the finish: cheaper than every real station


class NoFuelPlanError(Exception):
    """The stations along the route leave a stretch longer than one tank can cover.

    ``gap_start_mile`` and ``gap_end_mile`` are the two points either side of the first such
    stretch: the start of the trip or a station, and the next station or the finish.
    """

    def __init__(self, gap_start_mile: float, gap_end_mile: float, range_miles: float) -> None:
        self.gap_start_mile = gap_start_mile
        self.gap_end_mile = gap_end_mile
        self.range_miles = range_miles
        super().__init__(
            f"No fuel plan exists: there is no station for {self.gap_miles:.1f} miles, from "
            f"mile {gap_start_mile:.1f} to mile {gap_end_mile:.1f}, and the car can drive at "
            f"most {range_miles:g} miles on a tank."
        )

    @property
    def gap_miles(self) -> float:
        return self.gap_end_mile - self.gap_start_mile

    def __reduce__(self):
        # Exceptions are rebuilt from their message by default, which does not fit these
        # arguments. This makes copying and pickling work (caches, other processes).
        return (type(self), (self.gap_start_mile, self.gap_end_mile, self.range_miles))


@dataclass(frozen=True, slots=True)
class FuelStop:
    """Buy ``gallons`` at the station, at ``price`` a gallon, for ``cost`` in total."""

    station_id: int
    mile_marker: float
    price: Decimal
    gallons: Decimal
    cost: Decimal


@dataclass(frozen=True, slots=True)
class FuelPlan:
    """Where to buy fuel, and what the trip costs.

    ``gallons_consumed`` is all the fuel the trip burns; ``gallons_purchased`` is only what is
    bought at the stops, because the starting tank is free.
    """

    stops: tuple[FuelStop, ...]
    gallons_purchased: Decimal
    gallons_consumed: Decimal
    total_cost: Decimal


def plan_fuel_stops(
    total_miles: float,
    stations: Iterable[StationOnRoute],
    *,
    range_miles: float = DEFAULT_RANGE_MILES,
    miles_per_gallon: float = DEFAULT_MILES_PER_GALLON,
) -> FuelPlan:
    """The cheapest fuel plan for a trip of ``total_miles`` past ``stations``.

    Raises ``ValueError`` for input that makes no sense (a negative length, a price that is
    not positive, a station beyond the finish, a repeated station ID) and
    ``NoFuelPlanError`` when the trip cannot be done with these stations.
    """
    _check_vehicle(range_miles, miles_per_gallon)
    _check_trip(total_miles)
    usable = _sorted_stations(total_miles, stations)

    # The "nodes" are the start, the usable stations in driving order, and the finish.
    markers = [0.0, *(station.mile_marker for station in usable), total_miles]
    prices = [_NO_PRICE_LIMIT, *(station.price for station in usable), _FREE]
    _check_no_gap(markers, range_miles)
    nearest_cheaper = _nearest_cheaper_node(prices)

    reach = range_miles + _MILES_TOLERANCE
    purchases: list[tuple[int, float]] = []  # (node, miles of fuel bought there)
    node, fuel = 0, range_miles
    while node < len(markers) - 1:
        here = markers[node]
        cheaper = nearest_cheaper[node]
        if markers[cheaper] - here <= reach:
            target = cheaper
            to_buy = markers[target] - here - fuel
        else:
            end_of_reach = bisect_right(markers, here + reach)
            target = min(
                range(node + 1, end_of_reach),
                key=lambda k: (prices[k], -markers[k], k),
            )
            to_buy = range_miles - fuel
        # Never negative, never more than fits. At the start the tank is already full.
        to_buy = min(max(to_buy, 0.0), range_miles - fuel)
        if to_buy > 0:
            purchases.append((node, to_buy))
        fuel = max(fuel + to_buy - (markers[target] - here), 0.0)
        node = target

    try:
        return _build_plan(total_miles, usable, purchases, miles_per_gallon=miles_per_gallon)
    except InvalidOperation:
        raise ValueError(
            f"A trip of {total_miles:g} miles at {miles_per_gallon:g} miles per gallon is "
            f"too large to price."
        ) from None


def _check_vehicle(range_miles: float, miles_per_gallon: float) -> None:
    if not (math.isfinite(range_miles) and range_miles > 0):
        raise ValueError(f"The range must be a positive number of miles, not {range_miles!r}.")
    if not (math.isfinite(miles_per_gallon) and miles_per_gallon > 0):
        raise ValueError(
            f"The miles per gallon must be a positive number, not {miles_per_gallon!r}."
        )


def _check_trip(total_miles: float) -> None:
    if not (math.isfinite(total_miles) and total_miles >= 0):
        raise ValueError(
            f"The trip length must be a finite number of miles, not below zero: {total_miles!r}."
        )


def _sorted_stations(
    total_miles: float, stations: Iterable[StationOnRoute]
) -> list[StationOnRoute]:
    """Validate every station, then put them in driving order (ties by ID).

    A station at the finish is harmless: it is never worth stopping at once you have arrived.
    """
    given = list(stations)
    repeated = sorted(id_ for id_, n in Counter(s.station_id for s in given).items() if n > 1)
    if repeated:
        raise ValueError(f"Duplicate station IDs: {', '.join(map(str, repeated[:10]))}")
    for station in given:
        marker = station.mile_marker
        if not (math.isfinite(marker) and marker >= 0):
            raise ValueError(
                f"Station {station.station_id} has an invalid mile marker: {marker!r}."
            )
        if marker > total_miles:
            raise ValueError(
                f"Station {station.station_id} is beyond the finish "
                f"(mile {marker:g} of {total_miles:g})."
            )
        if not (station.price.is_finite() and station.price > 0):
            raise ValueError(
                f"Station {station.station_id} has an invalid price: {station.price!r}."
            )
    return sorted(given, key=lambda station: (station.mile_marker, station.station_id))


def _check_no_gap(markers: list[float], range_miles: float) -> None:
    """Raise for the first stretch between neighbouring nodes that one tank cannot cover."""
    for start, end in pairwise(markers):
        if end - start > range_miles + _MILES_TOLERANCE:
            raise NoFuelPlanError(start, end, range_miles)


def _nearest_cheaper_node(prices: list[Decimal]) -> list[int]:
    """For every node, the index of the next node with a strictly lower price.

    The finish is free and every station costs something, so every node but the finish has
    one. One pass from the back with a stack of candidates, instead of searching ahead from
    every node. The finish itself gets ``len(prices)``, an index that does not exist.
    """
    result = [len(prices)] * len(prices)
    candidates: list[int] = []
    for index in range(len(prices) - 1, -1, -1):
        while candidates and prices[candidates[-1]] >= prices[index]:
            candidates.pop()
        if candidates:
            result[index] = candidates[-1]
        candidates.append(index)
    return result


def _build_plan(
    total_miles: float,
    usable: list[StationOnRoute],
    purchases: list[tuple[int, float]],
    *,
    miles_per_gallon: float,
) -> FuelPlan:
    stops = []
    for node, miles in purchases:
        station = usable[node - 1]  # node 0 is the start
        gallons = _gallons(miles, miles_per_gallon)
        if gallons == 0:
            continue  # a drop too small to matter is not a stop
        stops.append(
            FuelStop(
                station_id=station.station_id,
                mile_marker=station.mile_marker,
                price=station.price,
                gallons=gallons,
                cost=(gallons * station.price).quantize(_CENT, rounding=ROUND_HALF_UP),
            )
        )
    return FuelPlan(
        stops=tuple(stops),
        gallons_purchased=sum((stop.gallons for stop in stops), Decimal(0)).quantize(
            _GALLON_PLACES
        ),
        gallons_consumed=_gallons(total_miles, miles_per_gallon),
        total_cost=sum((stop.cost for stop in stops), Decimal(0)).quantize(_CENT),
    )


def _gallons(miles: float, miles_per_gallon: float) -> Decimal:
    return Decimal(miles / miles_per_gallon).quantize(_GALLON_PLACES, rounding=ROUND_HALF_UP)
