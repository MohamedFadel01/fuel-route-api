"""Store cleaned station records in the database."""

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass

from django.db import transaction

from apps.stations.csv_loader import StationRecord
from apps.stations.models import Station

BATCH_SIZE = 500

# Columns that come from the CSV. Coordinates are deliberately NOT listed:
# re-importing prices must never erase locations found by the geocoder.
CSV_FIELDS = ["name", "address", "city", "state", "rack_id", "price"]


@dataclass(frozen=True, slots=True)
class ImportSummary:
    created: int
    updated: int


def save_stations(records: Iterable[StationRecord]) -> ImportSummary:
    """Insert new stations and refresh the CSV fields of existing ones (matched by OPIS ID).

    Each OPIS ID may appear only once in ``records`` (``load_stations`` guarantees this);
    otherwise a ``ValueError`` is raised before anything is written. The whole import
    runs in one transaction, so a failure leaves the database untouched.
    """
    stations = [
        Station(
            opis_id=record.opis_id,
            name=record.name,
            address=record.address,
            city=record.city,
            state=record.state,
            rack_id=record.rack_id,
            price=record.price,
        )
        for record in records
    ]
    if not stations:
        return ImportSummary(created=0, updated=0)

    repeated = sorted(id_ for id_, n in Counter(s.opis_id for s in stations).items() if n > 1)
    if repeated:
        listed = ", ".join(map(str, repeated[:10]))
        raise ValueError(f"Duplicate OPIS IDs in input: {listed}")

    with transaction.atomic():
        count_before = Station.objects.count()
        Station.objects.bulk_create(
            stations,
            batch_size=BATCH_SIZE,
            update_conflicts=True,
            unique_fields=["opis_id"],
            update_fields=CSV_FIELDS,
        )
        created = Station.objects.count() - count_before

    return ImportSummary(created=created, updated=len(stations) - created)
