"""Which stations are close enough to the route to be worth stopping at, and where along it.

A station counts when it is within a *margin* (10 miles by default) of the route. The
margin is generous on purpose: most station positions are approximate (see
``Station.location_precision``), so a tight margin would drop stations that really are on
the road.

Each station that counts gets its *mile marker*, the point of the route nearest to it, so
the fuel planner can treat the trip as a line from mile 0 to ``total_miles`` with priced
stations along it. The detour needed to reach a station is ignored; ``miles_from_route`` is
reported so callers can see how far off the road a station is.

Distances are measured to the nearest point of the ``RoutePath``, which are at most 0.5
miles apart. That makes a mile marker accurate to about a quarter of a mile, and a distance
at the edge of a 10-mile margin accurate to about 16 feet: far finer than the positions.

Everything here is plain Python and numpy, with no database and no network.
"""

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal

import numpy as np
from scipy.spatial import cKDTree

from apps.common.geo import Coordinates, chord_to_miles, miles_to_chord, unit_vector
from apps.trips.domain.route_path import RoutePath

DEFAULT_MARGIN_MILES = 10.0

# When no fuel plan exists with the default margin, the planner tries wider ones in turn.
WIDENING_MARGINS_MILES = (DEFAULT_MARGIN_MILES, 25.0, 50.0)

# A station exactly on the margin must count, but a distance computed through a KD-tree is
# only exact to about 1e-16, so a station placed exactly 10 miles away could land on either
# side. This extra slack (about 2 cm) makes the border reliably inclusive.
_BORDER_SLACK_CHORD = 1e-9


@dataclass(frozen=True, slots=True)
class StationSite:
    """A station as the corridor sees it: who, where, and what a gallon costs."""

    station_id: int
    coordinates: Coordinates
    price: Decimal


@dataclass(frozen=True, slots=True)
class StationOnRoute:
    """A station within the margin: where along the route it is, and how far off the road."""

    station_id: int
    mile_marker: float
    miles_from_route: float
    price: Decimal


class Corridor:
    """The stations around one route.

    Every station is measured against the route once, when the corridor is built. Asking
    for different margins with ``within`` afterwards only filters those measurements, so
    widening the margin costs almost nothing and needs no new route.

    If the route passes a station twice (it doubles back along the same road), the station
    gets the mile marker of whichever pass is nearest.
    """

    def __init__(self, path: RoutePath, stations: Iterable[StationSite]) -> None:
        sites = list(stations)
        repeated = sorted(id_ for id_, n in Counter(s.station_id for s in sites).items() if n > 1)
        if repeated:
            raise ValueError(f"Duplicate station IDs: {', '.join(map(str, repeated[:10]))}")

        self._sites = sites
        if sites:
            vectors = np.array([unit_vector(site.coordinates) for site in sites])
            chords, nearest = cKDTree(path.unit_vectors).query(vectors, k=1)
        else:
            chords, nearest = np.empty(0), np.empty(0, dtype=int)
        self._chords = chords
        self._mile_markers = path.mile_markers[nearest]

    def within(self, miles: float = DEFAULT_MARGIN_MILES) -> list[StationOnRoute]:
        """The stations at most ``miles`` from the route, in driving order.

        Stations at the same mile marker are ordered by ID. A margin of 0 keeps only
        stations standing on a route point; ``math.inf`` keeps every station. Raises
        ``ValueError`` for a negative or non-numeric margin.
        """
        limit = miles_to_chord(miles) + _BORDER_SLACK_CHORD
        found = [
            StationOnRoute(
                station_id=self._sites[i].station_id,
                mile_marker=float(self._mile_markers[i]),
                miles_from_route=chord_to_miles(float(self._chords[i])),
                price=self._sites[i].price,
            )
            for i in np.flatnonzero(self._chords <= limit)
        ]
        found.sort(key=lambda station: (station.mile_marker, station.station_id))
        return found
