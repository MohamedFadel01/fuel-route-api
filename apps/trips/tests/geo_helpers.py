"""Geometry helpers shared by the trip tests."""

import math
import random

from apps.common.geo import EARTH_RADIUS_MILES, Coordinates, haversine_miles


def destination(origin: Coordinates, bearing_degrees: float, miles: float) -> Coordinates:
    """The point reached by travelling ``miles`` from ``origin`` along a great circle.

    The bearing is a compass direction: 0 is north, 90 east, 180 south, 270 west.
    """
    distance = miles / EARTH_RADIUS_MILES
    bearing = math.radians(bearing_degrees)
    lat, lon = math.radians(origin.latitude), math.radians(origin.longitude)
    new_lat = math.asin(
        math.sin(lat) * math.cos(distance) + math.cos(lat) * math.sin(distance) * math.cos(bearing)
    )
    new_lon = lon + math.atan2(
        math.sin(bearing) * math.sin(distance) * math.cos(lat),
        math.cos(distance) - math.sin(lat) * math.sin(new_lat),
    )
    return Coordinates(math.degrees(new_lat), (math.degrees(new_lon) + 540) % 360 - 180)


def north_of(origin: Coordinates, miles: float) -> Coordinates:
    """The point ``miles`` due north of ``origin`` (a meridian is a great circle)."""
    return destination(origin, 0.0, miles)


def _bearing(origin: Coordinates, target: Coordinates) -> float:
    lat1, lat2 = math.radians(origin.latitude), math.radians(target.latitude)
    delta_lon = math.radians(target.longitude - origin.longitude)
    return math.atan2(
        math.sin(delta_lon) * math.cos(lat2),
        math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(delta_lon),
    )


def _cross_and_along(start: Coordinates, end: Coordinates, point: Coordinates):
    """Textbook spherical formulas: how far off the start-to-end great circle, and how far along.

    They share no code with the production KD-tree, so they can check it. The along-track
    distance is signed: negative for a point behind the start.
    """
    angle_to_point = haversine_miles(start, point) / EARTH_RADIUS_MILES
    turn = _bearing(start, point) - _bearing(start, end)
    cross = math.asin(math.sin(angle_to_point) * math.sin(turn))
    along = math.acos(min(1.0, math.cos(angle_to_point) / math.cos(cross)))
    return abs(cross) * EARTH_RADIUS_MILES, math.copysign(
        along, math.cos(turn)
    ) * EARTH_RADIUS_MILES


def along_track_miles(start: Coordinates, end: Coordinates, point: Coordinates) -> float:
    """Miles from ``start`` to the spot on the start-to-end great circle nearest to ``point``.

    Negative if that spot is behind the start; more than the route length if it is past the end.
    """
    return _cross_and_along(start, end, point)[1]


def cross_track_miles(start: Coordinates, end: Coordinates, point: Coordinates) -> float:
    """Miles from ``point`` to the start-to-end great circle (always zero or more)."""
    return _cross_and_along(start, end, point)[0]


def random_route(generator: random.Random) -> list[Coordinates]:
    """A messy route: repeated vertices, U-turns, short and long legs, odd places on Earth.

    The start may be in the continental US, anywhere else, on the equator, near the pole or
    beside the date line.
    """
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
        route.append(
            destination(route[-1], math.degrees(heading), 10 ** generator.uniform(-3, 1.9))
        )
    return route
