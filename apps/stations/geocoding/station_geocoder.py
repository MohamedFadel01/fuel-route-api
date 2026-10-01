"""Find the position of a fuel station.

Strategy, best result first:

1. Search OpenStreetMap for the station by name and accept a hit only if it is in the
   right state, close to the station's city and has a similar name ("exact" position).
2. Otherwise use the centre of the station's city ("city" position).
3. If the city is unknown too, give up (``None``).

A wrong exact position is worse than an honest city centre, so hits are validated hard.
"""

import re
import unicodedata
from dataclasses import dataclass
from typing import Protocol

from apps.common.geo import Coordinates, haversine_miles
from apps.stations.geocoding.nominatim import PlaceMatch
from apps.stations.models import Station

SEARCH_LIMIT = 5
DEFAULT_MAX_DISTANCE_MILES = 25.0

_STORE_NUMBER = re.compile(r"#\s*[\w-]+")
# Chains whose usual spelling in the fuel file differs from OpenStreetMap's.
_BRAND_SPELLINGS = {"loves": "Love's", "caseys": "Casey's"}
_CONNECTORS = frozenset({"of", "at", "in", "the", "and", "&", "-"})
# Words shared by countless unrelated stations: they prove nothing about identity.
_GENERIC_WORDS = frozenset(
    {
        # kinds of place
        *("travel", "center", "centers", "centre", "truck", "trucks", "plaza"),
        *("stop", "stops", "stopping", "station", "stations", "shop", "store", "stores"),
        *("mart", "market", "markets", "food", "foods", "convenience", "mini", "general"),
        # kinds of business
        *("fuel", "fuels", "gas", "oil", "petroleum", "diesel", "auto"),
        *("express", "service", "services"),
        # filler
        *("the", "of", "and", "inc", "llc", "co"),
    }
)


class PlaceSearcher(Protocol):
    def search(self, query: str, limit: int = ...) -> list[PlaceMatch]: ...


class CityLocator(Protocol):
    def lookup(self, city: str, state: str) -> Coordinates | None: ...


@dataclass(frozen=True, slots=True)
class LocatedPlace:
    coordinates: Coordinates
    precision: str  # A ``Station.LocationPrecision`` value.


def _words(text: str) -> list[str]:
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.findall(r"[a-z0-9]+", ascii_text.casefold().replace("'", ""))


def _distinctive_words(name: str, exclude: frozenset[str] = frozenset()) -> set[str]:
    """Words that can identify a business: not generic, not numbers, not single letters."""
    return {
        word
        for word in _words(name)
        if len(word) > 1 and not word.isdigit() and word not in _GENERIC_WORDS | exclude
    }


def names_match(station_name: str, place_name: str, city: str = "") -> bool:
    """Do the two names share a distinctive word? The city's own name does not count."""
    station_words = _distinctive_words(station_name, exclude=frozenset(_words(city)))
    return bool(station_words & _distinctive_words(place_name))


def _trim_connectors(words: list[str]) -> list[str]:
    while words and words[0].lower() in _CONNECTORS:
        words = words[1:]
    while words and words[-1].lower() in _CONNECTORS:
        words = words[:-1]
    return words


def _respell(word: str) -> str:
    lowered = word.lower()
    if lowered in _BRAND_SPELLINGS:
        return _BRAND_SPELLINGS[lowered]
    return word[:-1] if lowered == "centers" else word


def build_search_query(name: str, city: str, state: str) -> str:
    """Turn a fuel-file name such as ``LOVES TRAVEL STOP #766`` into a search query.

    Store numbers are dropped (OpenStreetMap does not use them), so is the city inside
    the name (it is added separately), and well-known brands get their usual spelling.
    """
    city = " ".join(city.split())
    without_number = " ".join(_STORE_NUMBER.sub(" ", name).split())
    city_pattern = r"\s+".join(re.escape(word) for word in city.split())
    without_city = re.sub(rf"(?<!\w){city_pattern}(?!\w)", " ", without_number, flags=re.I)

    core = _trim_connectors(without_city.split()) or without_number.split() or name.split()
    return f"{' '.join(_respell(word) for word in core)}, {city}, {state.strip()}"


class StationGeocoder:
    """Locates stations using a place search and a city gazetteer."""

    def __init__(
        self,
        searcher: PlaceSearcher,
        cities: CityLocator,
        *,
        max_distance_miles: float = DEFAULT_MAX_DISTANCE_MILES,
    ) -> None:
        if max_distance_miles <= 0:
            raise ValueError("max_distance_miles must be positive")
        self._searcher = searcher
        self._cities = cities
        self._max_distance_miles = max_distance_miles
        self._answers: dict[str, list[PlaceMatch]] = {}

    def locate(self, name: str, city: str, state: str) -> LocatedPlace | None:
        """Return the best known position, or ``None`` if neither search nor city helps.

        Search errors (``NominatimError``) are not caught: a temporary outage must not
        be mistaken for "this station does not exist".
        """
        state = state.strip().upper()
        city_centre = self._cities.lookup(city, state)

        if _distinctive_words(name, exclude=frozenset(_words(city))):
            for match in self._search(build_search_query(name, city, state)):
                if self._is_valid(match, name, city, state, city_centre):
                    return LocatedPlace(match.coordinates, Station.LocationPrecision.POI)

        if city_centre is not None:
            return LocatedPlace(city_centre, Station.LocationPrecision.CITY)
        return None

    def _search(self, query: str) -> list[PlaceMatch]:
        if query not in self._answers:
            self._answers[query] = self._searcher.search(query, limit=SEARCH_LIMIT)
        return self._answers[query]

    def _is_valid(
        self, match: PlaceMatch, name: str, city: str, state: str, city_centre: Coordinates | None
    ) -> bool:
        if match.region.upper() != state or not names_match(name, match.name, city):
            return False
        if city_centre is None:
            return True  # Nothing to measure against; state and name must be enough.
        return haversine_miles(city_centre, match.coordinates) <= self._max_distance_miles
