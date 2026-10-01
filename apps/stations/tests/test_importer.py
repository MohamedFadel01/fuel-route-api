from decimal import Decimal

import pytest

from apps.stations.csv_loader import StationRecord
from apps.stations.importer import ImportSummary, save_stations
from apps.stations.models import Station

pytestmark = pytest.mark.django_db


def make_record(opis_id=1, **overrides):
    fields = {
        "opis_id": opis_id,
        "name": "PILOT #1243",
        "address": "I-8, EXIT 119",
        "city": "Gila Bend",
        "state": "AZ",
        "rack_id": 930,
        "price": Decimal("3.899"),
    }
    fields.update(overrides)
    return StationRecord(**fields)


class TestSaveStations:
    def test_creates_new_stations(self):
        summary = save_stations([make_record(1), make_record(2, city="Tucson")])

        assert summary == ImportSummary(created=2, updated=0)
        assert Station.objects.count() == 2
        station = Station.objects.get(opis_id=2)
        assert (station.name, station.city, station.state) == ("PILOT #1243", "Tucson", "AZ")
        assert (station.address, station.rack_id) == ("I-8, EXIT 119", 930)

    def test_keeps_the_exact_price(self):
        save_stations([make_record(price=Decimal("3.00733333"))])

        assert Station.objects.get().price == Decimal("3.00733333")

    def test_new_stations_have_no_coordinates(self):
        save_stations([make_record()])

        station = Station.objects.get()
        assert station.latitude is None
        assert station.longitude is None
        assert station.location_precision == ""

    def test_running_twice_is_idempotent(self):
        records = [make_record(1), make_record(2)]

        save_stations(records)
        summary = save_stations(records)

        assert summary == ImportSummary(created=0, updated=2)
        assert Station.objects.count() == 2

    def test_updates_changed_fields_of_existing_stations(self):
        save_stations([make_record(1)])

        save_stations(
            [
                make_record(
                    1,
                    name="NEW NAME",
                    address="NEW ADDRESS",
                    city="Phoenix",
                    state="AZ",
                    rack_id=11,
                    price=Decimal("2.999"),
                )
            ]
        )

        station = Station.objects.get(opis_id=1)
        assert station.name == "NEW NAME"
        assert station.address == "NEW ADDRESS"
        assert station.city == "Phoenix"
        assert station.rack_id == 11
        assert station.price == Decimal("2.999")

    def test_keeps_coordinates_of_existing_stations(self, make_station):
        make_station(
            opis_id=1,
            latitude=32.9487,
            longitude=-112.7163,
            location_precision=Station.LocationPrecision.POI,
        )

        save_stations([make_record(1, price=Decimal("2.5"))])

        station = Station.objects.get(opis_id=1)
        assert station.price == Decimal("2.5")
        assert station.latitude == pytest.approx(32.9487)
        assert station.longitude == pytest.approx(-112.7163)
        assert station.location_precision == "poi"

    def test_mixes_new_and_existing_stations(self, make_station):
        make_station(opis_id=1)

        summary = save_stations([make_record(1), make_record(2), make_record(3)])

        assert summary == ImportSummary(created=2, updated=1)
        assert Station.objects.count() == 3

    def test_does_not_touch_stations_missing_from_the_input(self, make_station):
        make_station(opis_id=99, name="UNRELATED")

        save_stations([make_record(1)])

        assert Station.objects.get(opis_id=99).name == "UNRELATED"

    def test_empty_input_does_nothing(self):
        assert save_stations([]) == ImportSummary(created=0, updated=0)
        assert Station.objects.count() == 0

    def test_handles_more_records_than_one_batch(self):
        records = [make_record(i) for i in range(1, 1301)]

        summary = save_stations(records)

        assert summary == ImportSummary(created=1300, updated=0)
        assert Station.objects.count() == 1300

    def test_repeated_ids_in_the_input_are_rejected(self):
        records = [make_record(5), make_record(6), make_record(5, price=Decimal("2.0"))]

        with pytest.raises(ValueError, match="5"):
            save_stations(records)

    def test_a_rejected_input_writes_nothing(self):
        with pytest.raises(ValueError, match="Duplicate"):
            save_stations([make_record(1), make_record(2), make_record(1)])

        assert Station.objects.count() == 0

    def test_the_error_lists_every_repeated_id_once(self):
        records = [make_record(i) for i in (3, 3, 3, 4, 4, 9)]

        with pytest.raises(ValueError, match="Duplicate") as error:
            save_stations(records)

        message = str(error.value)
        assert message.count("3") == 1
        assert "4" in message
        assert "9" not in message

    def test_accepts_any_iterable(self):
        summary = save_stations(make_record(i) for i in (1, 2))

        assert summary.created == 2
