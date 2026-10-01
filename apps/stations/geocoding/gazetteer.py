"""Look up the centre of a city from the free GeoNames place dump.

This is the fallback location for a station: when we only know its city and state,
the city centre is usually within a few miles of the real position.
"""

import io
import re
import unicodedata
import zipfile
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

from apps.stations.geocoding.types import Coordinates

# GeoNames columns used (tab separated): name, asciiname, alternatenames,
# latitude, longitude, feature class, admin1 code (state) and population.
_NAME, _ASCII_NAME, _ALTERNATES, _LATITUDE, _LONGITUDE = 1, 2, 3, 4, 5
_FEATURE_CLASS, _ADMIN1, _POPULATION = 6, 10, 14
_MIN_COLUMNS = 15
_POPULATED_PLACE = "P"

# GeoNames numbers Canadian provinces; the fuel file uses the usual letters.
_CANADIAN_PROVINCES = {
    "01": "AB",
    "02": "BC",
    "03": "MB",
    "04": "NB",
    "05": "NL",
    "07": "NS",
    "08": "ON",
    "09": "PE",
    "10": "QC",
    "11": "SK",
    "12": "YT",
    "13": "NT",
    "14": "NU",
}

_WORD_EXPANSIONS = {"st": "saint", "ste": "sainte", "ft": "fort", "mt": "mount"}
_LEADING_DIRECTIONS = {"n": "north", "s": "south", "e": "east", "w": "west"}


class GazetteerError(Exception):
    """GeoNames data could not be downloaded or read."""


def normalize_place_name(name: str) -> str:
    """Reduce a place name to a key that ignores common spelling differences.

    Ignores case, accents, punctuation and spacing, and expands abbreviations, so
    ``"St. Louis"``, ``"Saint Louis"`` and ``"SAINT  LOUIS"`` match, as do
    ``"Mc Alpin"`` and ``"McAlpin"``. Names with no Latin letters give ``""``.
    """
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    words = re.sub(r"[^a-z0-9]+", " ", ascii_name.casefold().replace("'", "")).split()
    words = [_WORD_EXPANSIONS.get(word, word) for word in words]
    if words:
        words[0] = _LEADING_DIRECTIONS.get(words[0], words[0])
    return "".join(words)


def _us_state(admin1: str) -> str | None:
    code = admin1.strip().upper()
    return code if len(code) == 2 and code.isascii() and code.isalpha() else None


def _canadian_province(admin1: str) -> str | None:
    return _CANADIAN_PROVINCES.get(admin1.strip())


_STATE_RESOLVERS: dict[str, Callable[[str], str | None]] = {
    "US": _us_state,
    "CA": _canadian_province,
}


@dataclass(frozen=True, slots=True)
class _Place:
    population: int
    coordinates: Coordinates


class CityGazetteer:
    """Maps ``(city, state)`` to the coordinates of the city centre."""

    def __init__(self) -> None:
        # Official names are tried first; alternate names only fill the gaps.
        self._official: dict[tuple[str, str], _Place] = {}
        self._alternate: dict[tuple[str, str], _Place] = {}
        self._place_count = 0

    def __len__(self) -> int:
        return self._place_count

    def lookup(self, city: str, state: str) -> Coordinates | None:
        """Return the centre of ``city`` in ``state`` or ``None`` if unknown."""
        name = normalize_place_name(city)
        state = state.strip().upper()
        if not name or not state:
            return None
        place = self._official.get((name, state)) or self._alternate.get((name, state))
        return place.coordinates if place else None

    def add_geonames(self, country: str, lines: Iterable[str]) -> int:
        """Add the populated places from a GeoNames dump; return how many were added.

        When several places share a name within a state, the most populous wins
        (the first one on a tie). Malformed lines are ignored.
        """
        try:
            resolve_state = _STATE_RESOLVERS[country]
        except KeyError:
            supported = ", ".join(_STATE_RESOLVERS)
            raise ValueError(f"Unsupported country {country!r} (supported: {supported})") from None

        added = 0
        for line in lines:
            fields = line.rstrip("\r\n").split("\t")
            if len(fields) < _MIN_COLUMNS or fields[_FEATURE_CLASS] != _POPULATED_PLACE:
                continue
            state = resolve_state(fields[_ADMIN1])
            place = self._parse_place(fields)
            if state is None or place is None:
                continue

            for name in (fields[_NAME], fields[_ASCII_NAME]):
                self._remember(self._official, name, state, place)
            for name in fields[_ALTERNATES].split(","):
                self._remember(self._alternate, name, state, place)
            added += 1

        self._place_count += added
        return added

    @classmethod
    def from_geonames_zips(cls, zips: Mapping[str, Path]) -> "CityGazetteer":
        """Build a gazetteer from GeoNames ``<country>.zip`` files, e.g. ``{"US": path}``."""
        gazetteer = cls()
        for country, path in zips.items():
            gazetteer.add_geonames(country, _read_member(path, f"{country}.txt"))
        return gazetteer

    @staticmethod
    def _parse_place(fields: list[str]) -> _Place | None:
        try:
            latitude = float(fields[_LATITUDE])
            longitude = float(fields[_LONGITUDE])
        except ValueError:
            return None
        if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
            return None
        try:
            population = int(fields[_POPULATION])
        except ValueError:
            population = 0
        return _Place(population, Coordinates(latitude, longitude))

    @staticmethod
    def _remember(index: dict[tuple[str, str], _Place], name: str, state: str, place: _Place):
        key = normalize_place_name(name)
        if not key:
            return
        current = index.get((key, state))
        if current is None or place.population > current.population:
            index[(key, state)] = place


def _read_member(path: Path, member: str) -> list[str]:
    """Return the lines of ``member`` inside the zip at ``path``."""
    if not path.exists():
        raise GazetteerError(f"GeoNames file not found: {path}")
    try:
        with zipfile.ZipFile(path) as archive, archive.open(member) as raw:
            text = io.TextIOWrapper(raw, encoding="utf-8", errors="replace")
            return text.read().splitlines()
    except zipfile.BadZipFile:
        raise GazetteerError(f"{path} is not a valid zip file") from None
    except KeyError:
        raise GazetteerError(f"{path} does not contain {member}") from None
