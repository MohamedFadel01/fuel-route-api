"""Small geography helpers shared by the stations and trips apps.

Two ways of measuring distance are used:

* ``haversine_miles``: the distance along the ground ("miles" as a driver thinks of it);
* straight lines through the Earth between points on a unit sphere (``unit_vector``).
  A KD-tree (a fast nearest-point index) only understands straight lines, so
  ``miles_to_chord`` and ``chord_to_miles`` convert between the two.
"""

import math
from dataclasses import dataclass

# Mean Earth radius (6371.0088 km) in statute miles.
EARTH_RADIUS_MILES = 3958.7613


@dataclass(frozen=True, slots=True)
class Coordinates:
    """A point on Earth in decimal degrees."""

    latitude: float
    longitude: float

    def __post_init__(self) -> None:
        # Written so that NaN fails too (every comparison with NaN is false).
        if not (-90 <= self.latitude <= 90 and -180 <= self.longitude <= 180):
            raise ValueError(
                f"Coordinates out of range: latitude={self.latitude}, longitude={self.longitude}"
            )


def haversine_miles(a: Coordinates, b: Coordinates) -> float:
    """Great-circle distance between two points, in miles."""
    lat_a, lat_b = math.radians(a.latitude), math.radians(b.latitude)
    delta_lat = lat_b - lat_a
    delta_lon = math.radians(b.longitude - a.longitude)

    h = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat_a) * math.cos(lat_b) * math.sin(delta_lon / 2) ** 2
    )
    # Rounding can push h marginally above 1 for antipodal points.
    return 2 * EARTH_RADIUS_MILES * math.asin(math.sqrt(min(1.0, h)))


# The longest possible straight line between two points on a unit sphere: its diameter.
_MAX_CHORD = 2.0
# Floating-point rounding can make a computed diameter marginally exceed 2.
_CHORD_TOLERANCE = 1e-9
_HALF_CIRCUMFERENCE_MILES = math.pi * EARTH_RADIUS_MILES


def unit_vector(point: Coordinates) -> tuple[float, float, float]:
    """Place a point on a sphere of radius 1 centred on the Earth: ``(x, y, z)``.

    ``x`` points to latitude 0 / longitude 0, ``y`` to longitude 90 East and ``z`` to the
    North Pole.
    """
    latitude = math.radians(point.latitude)
    longitude = math.radians(point.longitude)
    flat = math.cos(latitude)
    return (flat * math.cos(longitude), flat * math.sin(longitude), math.sin(latitude))


def miles_to_chord(miles: float) -> float:
    """Straight-line distance (on a unit sphere) between two points ``miles`` apart.

    Use it to turn a search radius in miles into the radius a KD-tree understands. A
    distance beyond half the Earth's circumference reaches every point, so it gives 2.

    A point exactly ``miles`` away can land on either side of the resulting limit, because
    floating-point numbers are rounded (by about 1e-16). Anything that must include the
    border should add a tiny margin, far below any real-world distance.
    """
    if math.isnan(miles) or miles < 0:
        raise ValueError(f"Distance must be zero or more miles, got {miles}")
    if miles >= _HALF_CIRCUMFERENCE_MILES:
        return _MAX_CHORD
    return 2 * math.sin(miles / (2 * EARTH_RADIUS_MILES))


def chord_to_miles(chord: float) -> float:
    """Ground distance in miles between two points a straight ``chord`` apart on a unit sphere.

    The inverse of ``miles_to_chord``.
    """
    # Written so that NaN fails too (every comparison with NaN is false).
    if not 0 <= chord <= _MAX_CHORD + _CHORD_TOLERANCE:
        raise ValueError(f"A chord on a unit sphere is between 0 and 2, got {chord}")
    return 2 * EARTH_RADIUS_MILES * math.asin(min(1.0, chord / _MAX_CHORD))
