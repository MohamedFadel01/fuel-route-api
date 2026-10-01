"""Stop claiming an exact position when several stations were given the same one.

Searching OpenStreetMap for "Pilot, Monroe, MI" returns a single Pilot, but the city may
have several. The geocoder then hands that one position to every Pilot in the city, so at
most one of them is really there. We cannot tell which, so none of them may be called
"exact": they are relabelled as approximate (their position is still somewhere in the
right city).
"""

from collections import defaultdict

from apps.stations.models import Station

BATCH_SIZE = 500

# Positions are compared to 5 decimals, about one metre.
_DECIMALS = 5


def demote_shared_locations(*, batch_size: int = BATCH_SIZE) -> int:
    """Relabel exact stations that share their position with any other located station.

    Positions are never changed. Stations that are already approximate count as sharers
    too (they keep the position they were demoted from), so a station found later at a
    shared point is demoted as well, and running this twice changes nothing.

    Returns the number of stations that were relabelled.
    """
    at_point: dict[tuple[float, float], list[tuple[int, str]]] = defaultdict(list)
    located = Station.objects.exclude(location_precision="").values_list(
        "pk", "latitude", "longitude", "location_precision"
    )
    for pk, latitude, longitude, precision in located:
        at_point[(round(latitude, _DECIMALS), round(longitude, _DECIMALS))].append((pk, precision))

    to_demote = [
        pk
        for stations in at_point.values()
        if len(stations) > 1
        for pk, precision in stations
        if precision == Station.LocationPrecision.POI
    ]

    for start in range(0, len(to_demote), batch_size):
        Station.objects.filter(pk__in=to_demote[start : start + batch_size]).update(
            location_precision=Station.LocationPrecision.CITY
        )
    return len(to_demote)
