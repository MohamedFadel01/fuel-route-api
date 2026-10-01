"""Geometry helpers shared by the trip tests."""

import math

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


def along_track_miles(start: Coordinates, end: Coordinates, point: Coordinates) -> float:
    """How far along the great circle from ``start`` to ``end`` the point's nearest spot is.

    Uses the textbook spherical cross-track / along-track formulas, which share no code with
    the production KD-tree, so it can check it.
    """
    angle_to_point = haversine_miles(start, point) / EARTH_RADIUS_MILES
    cross_track = math.asin(
        math.sin(angle_to_point) * math.sin(_bearing(start, point) - _bearing(start, end))
    )
    return math.acos(math.cos(angle_to_point) / math.cos(cross_track)) * EARTH_RADIUS_MILES
