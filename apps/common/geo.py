"""Small geography helpers shared by the stations and trips apps."""

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
