"""What every routing service has to give us, and the ways it can fail.

The trip logic never talks to a particular service. It asks a ``RoutingProvider`` for the
driving route between two places and gets back a ``ProviderRoute``. To use a different
service, write another class with the same ``route`` method that raises the same errors.
"""

from dataclasses import dataclass
from typing import Protocol

from apps.common.geo import Coordinates


class RoutingError(Exception):
    """The routing service could not give us a route."""


class NoRouteFoundError(RoutingError):
    """The places are fine but there is no driving route between them (an ocean, no road)."""


class RoutingServiceError(RoutingError):
    """The routing service failed, was unreachable, or answered with something unusable."""


class RoutingTimeoutError(RoutingServiceError):
    """The routing service did not answer in time."""


@dataclass(frozen=True, slots=True)
class ProviderRoute:
    """A driving route: the road as points from start to finish, and how long it is.

    ``distance_miles`` and ``duration_seconds`` are what the service reports. The trip logic
    measures the points itself for its mile markers, and the two agree to within about 0.2%.

    Routing services put each place on the nearest road, however far away that is: a point
    in the sea can be moved a hundred miles. ``start_snap_miles`` and ``finish_snap_miles``
    say how far each place was moved, so the caller can refuse a trip that does not really
    start or end where the user asked. They default to 0 (on the road), which is what a
    hand-made route in a test usually means.
    """

    coordinates: tuple[Coordinates, ...]
    distance_miles: float
    duration_seconds: float
    start_snap_miles: float = 0.0
    finish_snap_miles: float = 0.0


class RoutingProvider(Protocol):
    def route(self, start: Coordinates, finish: Coordinates) -> ProviderRoute:
        """The driving route from ``start`` to ``finish``, using one request to the service."""
        ...
