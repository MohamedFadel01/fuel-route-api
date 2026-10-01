"""The places this API will plan a trip for.

Two boxes cover the United States, including Alaska and Hawaii, and Canada. A box cannot
follow a border, so a town just outside the country (Tijuana, for example) is included,
while the Aleutian Islands that sit past the date line are not.
"""

from apps.common.geo import Coordinates

# (min latitude, max latitude, min longitude, max longitude)
_BOXES = (
    (24.0, 83.5, -168.0, -52.0),  # continental US, Canada and Alaska
    (18.5, 22.5, -160.5, -154.5),  # Hawaii
)


def in_service_area(point: Coordinates) -> bool:
    """Whether ``point`` lies inside one of the boxes."""
    return any(
        min_lat <= point.latitude <= max_lat and min_lon <= point.longitude <= max_lon
        for min_lat, max_lat, min_lon, max_lon in _BOXES
    )
