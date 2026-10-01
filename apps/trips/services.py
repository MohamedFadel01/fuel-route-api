"""Plan one trip: the road, the fuel stops and the cost.

The pieces, in order, for each new request:

1. Reject a place outside the area we cover, before spending a routing call on it.
2. If this exact trip was planned recently, return that plan. No routing call, no database.
3. Ask the routing service once.
4. Refuse the trip when it moved the start or the finish too far to reach a road.
5. Find the stations near the road and buy fuel as cheaply as possible. If none of them can
   get the car there, try the wider margins (10, then 25, then 50 miles) on the same road.

The distance the service reports is kept for the answer. The fuel is worked out from the
length of the road itself, which agrees with the reported distance to about 0.2%.
"""

import math
from dataclasses import dataclass
from decimal import Decimal

from django.conf import settings
from django.core.cache import cache

from apps.common.geo import Coordinates
from apps.stations.models import Station
from apps.trips.area import in_service_area
from apps.trips.domain.corridor import WIDENING_MARGINS_MILES, Corridor, StationSite
from apps.trips.domain.optimizer import NoFuelPlanError, plan_fuel_stops
from apps.trips.domain.route_path import RoutePath
from apps.trips.providers.base import ProviderRoute, RoutingProvider, RoutingServiceError
from apps.trips.providers.osrm import get_shared_client


class PointFarFromRoadError(Exception):
    """The routing service had to move this place too far to reach a road.

    The API answers 422: the coordinates are valid, but they are not where the trip would
    really start or end.
    """

    def __init__(self, which: str, miles: float, limit_miles: float) -> None:
        self.which = which
        self.miles = miles
        self.limit_miles = limit_miles
        super().__init__(
            f"Your {which} point is {_miles_past_the_limit(miles, limit_miles)} miles from "
            f"the nearest road (the limit is {limit_miles:g})."
        )

    def __reduce__(self):
        return (type(self), (self.which, self.miles, self.limit_miles))


class NoTripPlanError(Exception):
    """No way to buy fuel along this road, even at the widest margin. The API answers 422."""

    def __init__(
        self,
        gap_start_mile: float,
        gap_end_mile: float,
        range_miles: float,
        margin_miles: float,
    ) -> None:
        self.gap_start_mile = gap_start_mile
        self.gap_end_mile = gap_end_mile
        self.range_miles = range_miles
        self.margin_miles = margin_miles
        super().__init__(
            f"No fuel plan exists within {margin_miles:g} miles of the route: there is no "
            f"station for {self.gap_miles:.0f} miles, from mile {gap_start_mile:.0f} to mile "
            f"{gap_end_mile:.0f}, and the car can drive at most {range_miles:g} miles on a tank."
        )

    @property
    def gap_miles(self) -> float:
        return self.gap_end_mile - self.gap_start_mile

    def __reduce__(self):
        return (
            type(self),
            (self.gap_start_mile, self.gap_end_mile, self.range_miles, self.margin_miles),
        )


@dataclass(frozen=True, slots=True)
class PlannedStop:
    """One fuel stop, with the station's name and place as they were when the trip was planned."""

    station_id: int
    name: str
    city: str
    state: str
    latitude: float
    longitude: float
    mile_marker: float
    price_per_gallon: Decimal
    gallons: Decimal
    cost: Decimal


@dataclass(frozen=True, slots=True)
class TripPlan:
    """A planned trip.

    ``distance_miles`` is what the routing service reported. ``measured_miles`` is the length
    of ``geometry``, which is what the fuel figures are based on. ``margin_miles`` is how far
    off the road the search had to look to find a plan.
    """

    distance_miles: float
    duration_seconds: float
    geometry: tuple[Coordinates, ...]
    stops: tuple[PlannedStop, ...]
    gallons_purchased: Decimal
    gallons_consumed: Decimal
    total_cost: Decimal
    margin_miles: float
    measured_miles: float


def plan_trip(
    start: Coordinates,
    finish: Coordinates,
    *,
    provider: RoutingProvider | None = None,
) -> TripPlan:
    """The cheapest fuel plan for the drive from ``start`` to ``finish``.

    Pass ``provider`` to use a particular routing service (the tests do). Otherwise the
    shared OSRM client is used, one per process.

    Raises ``ValueError`` for a place outside the area we cover, ``PointFarFromRoadError``
    when a place is too far from any road, ``NoTripPlanError`` when the car cannot be fueled
    along the route, and the routing provider's own errors when the service fails.
    """
    _check_in_area(start, "start")
    _check_in_area(finish, "finish")
    # Read before the cache, so a broken limit fails the request instead of serving a saved
    # trip, and so two different limits never share a saved answer.
    limit = _snap_limit()

    key = _cache_key(start, finish, limit)
    cached = _read_cache(key)
    if cached is not None:
        return cached

    routing = get_shared_client() if provider is None else provider
    plan = _build(routing.route(start, finish), limit)
    _write_cache(key, plan)
    return plan


def _check_in_area(point: Coordinates, which: str) -> None:
    if not in_service_area(point):
        raise ValueError(
            f"The {which} point is outside the area we cover (the United States and Canada)."
        )


def _miles_past_the_limit(miles: float, limit: float) -> str:
    """The distance, to one decimal, unless that would round it back to the limit.

    A point 5.04 miles away with a limit of 5 must not be described as 5.0. That reads as
    if the point were allowed.
    """
    one_decimal = f"{miles:.1f}"
    if float(one_decimal) > limit:
        return one_decimal
    for places in (4, 10):
        text = f"{miles:.{places}f}"
        if float(text) > limit:
            return text.rstrip("0").rstrip(".")
    return f"{miles:.16f}".rstrip("0").rstrip(".")


def _build(route: ProviderRoute, limit: float) -> TripPlan:
    _check_snap(route, limit)
    if _unusable(route.distance_miles) or _unusable(route.duration_seconds):
        raise RoutingServiceError(
            "The routing service sent a distance or duration that cannot be used."
        )
    try:
        path = RoutePath.from_coordinates(route.coordinates)
    except ValueError as error:
        raise RoutingServiceError(
            f"The routing service sent a route that cannot be used: {error}"
        ) from error
    sites, details = _load_stations()
    corridor = Corridor(path, sites)
    gap = None
    for margin in WIDENING_MARGINS_MILES:
        try:
            fuel = plan_fuel_stops(path.total_miles, corridor.within(margin))
        except NoFuelPlanError as error:
            gap = error
            continue
        stops = tuple(
            PlannedStop(
                station_id=stop.station_id,
                name=details[stop.station_id].name,
                city=details[stop.station_id].city,
                state=details[stop.station_id].state,
                latitude=details[stop.station_id].latitude,
                longitude=details[stop.station_id].longitude,
                mile_marker=stop.mile_marker,
                price_per_gallon=stop.price,
                gallons=stop.gallons,
                cost=stop.cost,
            )
            for stop in fuel.stops
        )
        return TripPlan(
            distance_miles=route.distance_miles,
            duration_seconds=route.duration_seconds,
            geometry=route.coordinates,
            stops=stops,
            gallons_purchased=fuel.gallons_purchased,
            gallons_consumed=fuel.gallons_consumed,
            total_cost=fuel.total_cost,
            margin_miles=margin,
            measured_miles=path.total_miles,
        )
    if gap is None:  # no margin was tried, which cannot happen with the margins above
        raise RuntimeError("No search margin was tried.")
    raise NoTripPlanError(gap.gap_start_mile, gap.gap_end_mile, gap.range_miles, margin)


def _snap_limit() -> float:
    """The configured limit, or ``ValueError`` when it is not a positive finite number.

    The start-up check catches this too. Checking here as well means a bad value cannot
    slip through to a comparison (``miles > nan`` is never true, so it would allow every
    point) just because nothing ran the check.
    """
    limit = settings.MAX_SNAP_MILES
    if isinstance(limit, bool) or not isinstance(limit, int | float):
        raise ValueError(f"MAX_SNAP_MILES must be a positive number of miles, not {limit!r}.")
    if not math.isfinite(limit) or limit <= 0:
        raise ValueError(f"MAX_SNAP_MILES must be a positive number of miles, not {limit!r}.")
    return float(limit)


def _unusable(value: object) -> bool:
    """True when a reported length is not a real, non-negative number."""
    return (
        isinstance(value, bool)
        or not isinstance(value, int | float)
        or not math.isfinite(value)
        or value < 0
    )


def _check_snap(route: ProviderRoute, limit: float) -> None:
    for which, miles in (("start", route.start_snap_miles), ("finish", route.finish_snap_miles)):
        if not math.isfinite(miles) or miles < 0:
            raise RoutingServiceError(
                f"The routing service sent a {which} point whose distance from a road "
                f"is unusable ({miles!r})."
            )
        if miles > limit:
            raise PointFarFromRoadError(which, miles, limit)


@dataclass(frozen=True, slots=True)
class _StationInfo:
    name: str
    city: str
    state: str
    latitude: float
    longitude: float


def _load_stations() -> tuple[list[StationSite], dict[int, _StationInfo]]:
    """Every located station, in one query, plus the name and place of each."""
    rows = Station.objects.exclude(latitude=None).values_list(
        "opis_id", "name", "city", "state", "price", "latitude", "longitude"
    )
    sites = []
    details: dict[int, _StationInfo] = {}
    for opis_id, name, city, state, price, latitude, longitude in rows:
        sites.append(StationSite(opis_id, Coordinates(latitude, longitude), price))
        details[opis_id] = _StationInfo(name, city, state, latitude, longitude)
    return sites, details


def _cache_key(start: Coordinates, finish: Coordinates, limit: float) -> str:
    """Points that agree to six decimals (about 10 cm, what we send the router) share a key.

    The snap limit is part of the key, so tightening it cannot keep serving a trip that was
    saved when a longer move to the nearest road was still allowed.
    """
    # v2 stores each stop's coordinates. A plan saved before that has nowhere to put a pin.
    return f"trip:v2:{limit:.6f}:{_rounded(start)}:{_rounded(finish)}"


def _rounded(point: Coordinates) -> str:
    return f"{point.latitude:.6f},{point.longitude:.6f}"


def _cache_seconds() -> float:
    """How long a plan is kept. Zero or an unusable value means it is not kept at all."""
    seconds = settings.TRIP_CACHE_SECONDS
    if isinstance(seconds, bool) or not isinstance(seconds, int | float):
        return 0
    if not math.isfinite(seconds) or seconds <= 0:
        return 0
    return float(seconds)


def _read_cache(key: str) -> TripPlan | None:
    if _cache_seconds() <= 0:
        return None
    found = cache.get(key)
    return found if isinstance(found, TripPlan) else None


def _write_cache(key: str, plan: TripPlan) -> None:
    seconds = _cache_seconds()
    if seconds > 0:
        cache.set(key, plan, timeout=seconds)
