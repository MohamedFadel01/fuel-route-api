"""Read, clean and de-duplicate the fuel price CSV.

Everything here is plain Python (no database), so it is fast to test.
The import command (a later step) simply stores the result.

Rules applied to the raw data:

* whitespace is trimmed and repeated inner spaces are collapsed;
* rows with missing or malformed values are skipped, and reported;
* the same station can appear on several rows with different prices; only the
  row with the lowest price is kept for each ``OPIS Truckstop ID``.
"""

import csv
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

OPIS_ID = "OPIS Truckstop ID"
NAME = "Truckstop Name"
ADDRESS = "Address"
CITY = "City"
STATE = "State"
RACK_ID = "Rack ID"
PRICE = "Retail Price"

REQUIRED_COLUMNS = (OPIS_ID, NAME, ADDRESS, CITY, STATE, RACK_ID, PRICE)

# Limits of the database columns (see ``Station``). A row beyond them is skipped and
# reported, instead of crashing the whole import when it is stored.
MAX_ID = 2**31 - 1
MAX_PRICE = Decimal(100)  # exclusive: the price column holds 2 whole digits


class InvalidRowError(ValueError):
    """A CSV row cannot be turned into a station."""


class MissingColumnsError(ValueError):
    """The CSV header does not contain every required column."""


@dataclass(frozen=True, slots=True)
class StationRecord:
    """One clean station row."""

    opis_id: int
    name: str
    address: str
    city: str
    state: str
    rack_id: int
    price: Decimal


@dataclass(frozen=True, slots=True)
class SkippedRow:
    """A row that was ignored, with the reason why."""

    line_number: int
    reason: str


@dataclass(frozen=True, slots=True)
class LoadResult:
    """Outcome of loading a CSV file."""

    stations: list[StationRecord]
    skipped: list[SkippedRow]
    rows_read: int

    @property
    def duplicates_merged(self) -> int:
        """Valid rows that were dropped because a cheaper row had the same ID."""
        return self.rows_read - len(self.skipped) - len(self.stations)


def _text(row: Mapping[str, str | None], column: str) -> str:
    value = row.get(column)
    cleaned = " ".join(value.split()) if value is not None else ""
    if not cleaned:
        raise InvalidRowError(f"{column}: value is missing")
    return cleaned


def _non_negative_int(row: Mapping[str, str | None], column: str) -> int:
    text = _text(row, column)
    if not (text.isascii() and text.isdigit()):
        raise InvalidRowError(f"{column}: {text!r} is not a non-negative integer")
    value = int(text)
    if value > MAX_ID:
        raise InvalidRowError(f"{column}: {text!r} is larger than {MAX_ID}")
    return value


def _state(row: Mapping[str, str | None]) -> str:
    text = _text(row, STATE)
    if not (len(text) == 2 and text.isascii() and text.isalpha()):
        raise InvalidRowError(f"{STATE}: {text!r} is not a two-letter code")
    return text.upper()


def _price(row: Mapping[str, str | None]) -> Decimal:
    text = _text(row, PRICE)
    try:
        price = Decimal(text)
    except InvalidOperation:
        raise InvalidRowError(f"{PRICE}: {text!r} is not a number") from None
    if not price.is_finite() or price <= 0:
        raise InvalidRowError(f"{PRICE}: {text!r} is not a positive number")
    if price >= MAX_PRICE:
        raise InvalidRowError(f"{PRICE}: {text!r} is not below {MAX_PRICE}")
    return price


def parse_row(row: Mapping[str, str | None]) -> StationRecord:
    """Validate and clean one CSV row, raising ``InvalidRowError`` if it is unusable."""
    return StationRecord(
        opis_id=_non_negative_int(row, OPIS_ID),
        name=_text(row, NAME),
        address=_text(row, ADDRESS),
        city=_text(row, CITY),
        state=_state(row),
        rack_id=_non_negative_int(row, RACK_ID),
        price=_price(row),
    )


def dedupe_lowest_price(records: Iterable[StationRecord]) -> list[StationRecord]:
    """Keep one record per station ID: the cheapest (the first one on a tie).

    The result keeps the order in which each ID first appeared.
    """
    cheapest: dict[int, StationRecord] = {}
    for record in records:
        current = cheapest.get(record.opis_id)
        if current is None or record.price < current.price:
            cheapest[record.opis_id] = record
    return list(cheapest.values())


def load_stations(lines: Iterable[str]) -> LoadResult:
    """Parse CSV text (an open file or any iterable of lines) into clean stations."""
    reader = csv.DictReader(lines)

    missing = [column for column in REQUIRED_COLUMNS if column not in (reader.fieldnames or [])]
    if missing:
        raise MissingColumnsError(f"CSV is missing required columns: {', '.join(missing)}")

    records: list[StationRecord] = []
    skipped: list[SkippedRow] = []
    rows_read = 0
    for row in reader:
        rows_read += 1
        try:
            records.append(parse_row(row))
        except InvalidRowError as error:
            skipped.append(SkippedRow(line_number=reader.line_num, reason=str(error)))

    return LoadResult(
        stations=dedupe_lowest_price(records),
        skipped=skipped,
        rows_read=rows_read,
    )
