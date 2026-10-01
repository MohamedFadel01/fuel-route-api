"""A client for OSRM, the Open Source Routing Machine (https://project-osrm.org).

One call to ``route`` makes exactly one HTTP request and returns the whole route: the road
as a long list of points, the distance and the driving time. There are no retries: the
public server is shared, and a retry would turn a slow answer into a slower one. A failure
becomes a clear error (see ``providers.base``) that the API turns into a proper response.

What the server says, as seen from this client:

* ``200`` and ``"code": "Ok"``: a route.
* ``400`` and ``"code": "NoRoute"`` (or ``"NoSegment"``): the places cannot be joined by road.
* any other ``400`` (``InvalidValue``, ``InvalidQuery``, ``TooBig``...): we sent a bad request.
* ``429``, ``5xx``, a timeout, a dropped connection, or nonsense in the answer: the service
  is not working right now.
"""

import math
from typing import Any
from urllib.parse import urlparse

import requests
from django.conf import settings

from apps.common.geo import Coordinates
from apps.trips.providers.base import (
    NoRouteFoundError,
    ProviderRoute,
    RoutingServiceError,
    RoutingTimeoutError,
)

DEFAULT_BASE_URL = "https://router.project-osrm.org"
DEFAULT_TIMEOUT_SECONDS = 10.0
METERS_PER_MILE = 1609.344

_NOT_JSON = object()  # stands in for a body that could not be read as JSON

# We quote the server's message in our errors; never more than this many characters of it.
_MAX_MESSAGE_LENGTH = 200

# OSRM's own words for "these places cannot be joined by road".
_NO_ROUTE_CODES = frozenset({"NoRoute", "NoSegment"})

# Ask for the full road as GeoJSON, and leave out the turn-by-turn steps and alternatives:
# they would make the answer bigger and slower for nothing.
_QUERY = {
    "overview": "full",
    "geometries": "geojson",
    "steps": "false",
    "alternatives": "false",
}


class OsrmClient:
    """Asks an OSRM server for driving routes.

    Create one client and share it: it keeps its connection to the server open between
    requests, which saves a new TLS handshake (a few hundred milliseconds) every time.

    ``timeout`` is the longest the client waits at each step: to connect, for the answer to
    start, and for each further piece of it. A healthy server answers well inside it. A
    server that keeps sending a trickle of data can hold a request longer, which is why the
    web server that runs this app should have its own time limit per request.
    """

    def __init__(
        self,
        *,
        user_agent: str,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        if not user_agent.strip():
            raise ValueError("user_agent must not be blank")
        if not (math.isfinite(timeout) and timeout > 0):
            raise ValueError(f"timeout must be a positive number of seconds, not {timeout!r}")
        address = urlparse(base_url.strip())
        if address.scheme not in ("http", "https") or not address.netloc:
            raise ValueError(f"base_url must be an http(s) address, not {base_url!r}")

        self.base_url = base_url.strip().rstrip("/")
        self.timeout = timeout
        self.user_agent = user_agent.strip()
        self._session = requests.Session()
        self._session.headers["User-Agent"] = self.user_agent

    @classmethod
    def from_settings(cls) -> "OsrmClient":
        """A client configured from the Django settings (``OSRM_*``)."""
        return cls(
            base_url=settings.OSRM_BASE_URL,
            timeout=settings.OSRM_TIMEOUT_SECONDS,
            user_agent=settings.OSRM_USER_AGENT,
        )

    def route(self, start: Coordinates, finish: Coordinates) -> ProviderRoute:
        """The driving route from ``start`` to ``finish``, from a single request.

        Raises ``NoRouteFoundError`` when there is no route, ``RoutingTimeoutError`` when the
        server is too slow, and ``RoutingServiceError`` for every other failure.
        """
        places = f"{_place(start)};{_place(finish)}"
        url = f"{self.base_url}/route/v1/driving/{places}"
        try:
            response = self._session.get(url, params=_QUERY, timeout=self.timeout)
        except requests.Timeout as error:
            raise RoutingTimeoutError(
                f"The routing service did not answer within {self.timeout:g} seconds."
            ) from error
        except requests.RequestException as error:
            # Only the kind of failure goes in the message: what ``requests`` writes includes the
            # whole address and several lines of internals. The cause stays chained for logs.
            raise RoutingServiceError(
                f"Could not reach the routing service ({type(error).__name__})."
            ) from error
        return self._read(response)

    @staticmethod
    def _read(response: requests.Response) -> ProviderRoute:
        try:
            body: Any = response.json()
        except ValueError:
            body = _NOT_JSON
        fields = body if isinstance(body, dict) else {}
        code = fields.get("code")
        message = fields.get("message")
        text = message.strip()[:_MAX_MESSAGE_LENGTH] if isinstance(message, str) else ""
        detail = f": {text}" if text else ""

        if code in _NO_ROUTE_CODES:
            raise NoRouteFoundError(text or "No driving route exists between these two places.")
        if response.status_code != requests.codes.ok:
            raise RoutingServiceError(
                f"The routing service answered HTTP {response.status_code}{detail}"
            )
        if body is _NOT_JSON:
            raise RoutingServiceError("The routing service sent a response that is not valid JSON.")
        if not isinstance(body, dict):
            raise RoutingServiceError("The routing service sent an unexpected kind of response.")
        if code != "Ok":
            raise RoutingServiceError(f"The routing service answered with code {code!r}{detail}")
        return _parse_route(body)


_shared: OsrmClient | None = None


def get_shared_client() -> OsrmClient:
    """The one client for this process, built on first use and reused after that.

    Reusing it keeps the connection to the server open, which saves a new handshake on
    every trip.
    """
    global _shared
    if _shared is None:
        _shared = OsrmClient.from_settings()
    return _shared


def reset_shared_client() -> None:
    """Forget the shared client, so the next one is built from the current settings."""
    global _shared
    _shared = None


def _place(place: Coordinates) -> str:
    """``longitude,latitude``: OSRM wants them this way round, to six decimals (about 10 cm)."""
    return f"{place.longitude:.6f},{place.latitude:.6f}"


def _parse_route(body: dict[str, Any]) -> ProviderRoute:
    routes = body.get("routes")
    if not isinstance(routes, list) or not routes or not isinstance(routes[0], dict):
        raise RoutingServiceError("The routing service answered without a route.")
    route = routes[0]
    start_snap, finish_snap = _parse_snap_distances(body.get("waypoints"))
    return ProviderRoute(
        coordinates=_parse_geometry(route.get("geometry")),
        distance_miles=_number(route.get("distance"), "distance") / METERS_PER_MILE,
        duration_seconds=_number(route.get("duration"), "duration"),
        start_snap_miles=start_snap / METERS_PER_MILE,
        finish_snap_miles=finish_snap / METERS_PER_MILE,
    )


def _parse_snap_distances(waypoints: object) -> tuple[float, float]:
    """Metres each end of the trip was moved to reach a road (first and last waypoint)."""
    if (
        not isinstance(waypoints, list)
        or len(waypoints) < 2
        or not all(isinstance(waypoint, dict) for waypoint in waypoints)
    ):
        raise RoutingServiceError("The routing service answered without usable waypoints.")
    first, last = waypoints[0], waypoints[-1]
    return (
        _number(first.get("distance"), "waypoint distance"),
        _number(last.get("distance"), "waypoint distance"),
    )


def _number(value: object, name: str) -> float:
    """A finite number of zero or more, as a float (booleans and text are refused)."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise RoutingServiceError(f"The routing service sent a route with a bad {name}: {value!r}.")
    if not math.isfinite(value) or value < 0:
        raise RoutingServiceError(f"The routing service sent a route with a bad {name}: {value!r}.")
    return float(value)


def _parse_geometry(geometry: object) -> tuple[Coordinates, ...]:
    if not isinstance(geometry, dict) or geometry.get("type") != "LineString":
        raise RoutingServiceError("The routing service sent a route without a usable geometry.")
    points = geometry.get("coordinates")
    if not isinstance(points, list) or len(points) < 2:
        raise RoutingServiceError("The routing service sent a route geometry with too few points.")
    try:
        return tuple(_point(point) for point in points)
    except (TypeError, ValueError):
        raise RoutingServiceError(
            "The routing service sent a route geometry with an invalid point."
        ) from None


def _point(point: object) -> Coordinates:
    """GeoJSON order is ``[longitude, latitude]``, with an optional altitude we ignore."""
    if not isinstance(point, list | tuple) or len(point) < 2:
        raise ValueError("a point needs a longitude and a latitude")
    longitude, latitude = point[0], point[1]
    if isinstance(longitude, bool) or isinstance(latitude, bool):
        raise ValueError("a coordinate cannot be a boolean")
    return Coordinates(latitude=float(latitude), longitude=float(longitude))
