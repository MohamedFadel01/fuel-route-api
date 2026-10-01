from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Coordinates:
    """A point on Earth in decimal degrees."""

    latitude: float
    longitude: float
