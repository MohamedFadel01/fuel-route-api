"""Save station locations to a small CSV file and load them back.

Finding locations takes about two hours (see ``geocode_stations``), so the result is
kept in ``data/stations_geocoded.csv`` and committed. Anyone can then restore every
location in a moment with ``load_station_locations``, without calling OpenStreetMap.

File format, one row per located station, sorted by ``opis_id``::

    opis_id,latitude,longitude,location_precision
    20,32.930400,-112.673100,poi
"""

import csv
import math
import os
import tempfile
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

from django.db import transaction

from apps.common.geo import Coordinates
from apps.stations.csv_loader import MAX_ID, MissingColumnsError, SkippedRow
from apps.stations.models import Station

COLUMNS = ("opis_id", "latitude", "longitude", "location_precision")
PRECISIONS = frozenset(Station.LocationPrecision.values)
BATCH_SIZE = 500

# Six decimals is about 11 centimetres: far finer than the data can justify.
_COORDINATE_FORMAT = "{:.6f}"


class InvalidLocationError(ValueError):
    """A row of the locations file cannot be used."""


@dataclass(frozen=True, slots=True)
class StationLocation:
    """Where one station is, and how that was found out."""

    opis_id: int
    coordinates: Coordinates
    precision: str


@dataclass(frozen=True, slots=True)
class LocationLoadResult:
    """Outcome of reading a locations file."""

    locations: list[StationLocation]
    skipped: list[SkippedRow]
    rows_read: int


@dataclass(frozen=True, slots=True)
class ApplySummary:
    updated: int
    unknown: int


def _cell(row: Mapping[str, str | None], column: str) -> str:
    value = row.get(column)
    text = value.strip() if value is not None else ""
    if not text:
        raise InvalidLocationError(f"{column}: value is missing")
    return text


def _opis_id(row: Mapping[str, str | None]) -> int:
    text = _cell(row, "opis_id")
    if not (text.isascii() and text.isdigit()):
        raise InvalidLocationError(f"opis_id: {text!r} is not a non-negative integer")
    value = int(text)
    if value > MAX_ID:
        raise InvalidLocationError(f"opis_id: {text!r} is larger than {MAX_ID}")
    return value


def _degrees(row: Mapping[str, str | None], column: str, limit: int) -> float:
    text = _cell(row, column)
    try:
        value = float(text)
    except ValueError:
        raise InvalidLocationError(f"{column}: {text!r} is not a number") from None
    if not math.isfinite(value) or abs(value) > limit:
        raise InvalidLocationError(f"{column}: {text!r} is not between -{limit} and {limit}")
    return value


def _precision(row: Mapping[str, str | None]) -> str:
    text = _cell(row, "location_precision")
    if text not in PRECISIONS:
        allowed = ", ".join(sorted(PRECISIONS))
        raise InvalidLocationError(f"location_precision: {text!r} is not one of {allowed}")
    return text


def parse_row(row: Mapping[str, str | None]) -> StationLocation:
    """Validate one row, raising ``InvalidLocationError`` if it is unusable."""
    return StationLocation(
        opis_id=_opis_id(row),
        coordinates=Coordinates(_degrees(row, "latitude", 90), _degrees(row, "longitude", 180)),
        precision=_precision(row),
    )


def parse_locations(lines: Iterable[str]) -> LocationLoadResult:
    """Parse CSV text (an open file or any iterable of lines) into station locations.

    Bad rows are skipped and reported. If an ID appears twice, the first valid row wins.
    """
    reader = csv.DictReader(lines)

    missing = [column for column in COLUMNS if column not in (reader.fieldnames or [])]
    if missing:
        raise MissingColumnsError(f"Locations file is missing columns: {', '.join(missing)}")

    locations: dict[int, StationLocation] = {}
    first_line: dict[int, int] = {}
    skipped: list[SkippedRow] = []
    rows_read = 0
    for row in reader:
        rows_read += 1
        try:
            location = parse_row(row)
        except InvalidLocationError as error:
            skipped.append(SkippedRow(line_number=reader.line_num, reason=str(error)))
            continue
        if location.opis_id in locations:
            reason = (
                f"opis_id: {location.opis_id} is repeated "
                f"(line {first_line[location.opis_id]} is used)"
            )
            skipped.append(SkippedRow(line_number=reader.line_num, reason=reason))
            continue
        locations[location.opis_id] = location
        first_line[location.opis_id] = reader.line_num

    return LocationLoadResult(
        locations=list(locations.values()), skipped=skipped, rows_read=rows_read
    )


def write_locations(stations: Iterable[Station], path: Path) -> int:
    """Write the located stations to ``path`` and return how many rows were written.

    Rows are sorted by ID so the file changes minimally between runs. The file is
    written under a temporary name and then moved into place, so a crash can never
    leave a half-written file behind.
    """
    located = sorted((s for s in stations if s.location_precision), key=lambda s: s.opis_id)

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            newline="",
            encoding="utf-8",
            dir=path.parent,
            prefix=f"{path.name}.",
            suffix=".part",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            writer = csv.writer(handle, lineterminator="\n")
            writer.writerow(COLUMNS)
            for station in located:
                writer.writerow(
                    [
                        station.opis_id,
                        _COORDINATE_FORMAT.format(station.latitude),
                        _COORDINATE_FORMAT.format(station.longitude),
                        station.location_precision,
                    ]
                )
        temporary.chmod(0o644)
        os.replace(temporary, path)
    except BaseException:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise
    return len(located)


def apply_locations(
    locations: Iterable[StationLocation], *, batch_size: int = BATCH_SIZE
) -> ApplySummary:
    """Store locations on the matching stations (matched by OPIS ID).

    The file is the source of truth, so it replaces any location already stored.
    Locations for stations that are not in the database are counted and ignored.
    Each ID may appear only once (``parse_locations`` guarantees this); otherwise a
    ``ValueError`` is raised before anything is written. Everything happens in one
    transaction.
    """
    items = list(locations)
    repeated = sorted(id_ for id_, n in Counter(i.opis_id for i in items).items() if n > 1)
    if repeated:
        listed = ", ".join(map(str, repeated[:10]))
        raise ValueError(f"Duplicate OPIS IDs in input: {listed}")

    updated = 0
    with transaction.atomic():
        for start in range(0, len(items), batch_size):
            chunk = {item.opis_id: item for item in items[start : start + batch_size]}
            stations = list(Station.objects.filter(opis_id__in=chunk))
            for station in stations:
                item = chunk[station.opis_id]
                station.latitude = item.coordinates.latitude
                station.longitude = item.coordinates.longitude
                station.location_precision = item.precision
            Station.objects.bulk_update(
                stations, ["latitude", "longitude", "location_precision"], batch_size=batch_size
            )
            updated += len(stations)

    return ApplySummary(updated=updated, unknown=len(items) - updated)
