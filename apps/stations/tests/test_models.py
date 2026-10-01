from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError

from apps.stations.models import Station

pytestmark = pytest.mark.django_db


class TestStationFields:
    def test_saves_and_reloads_all_fields(self, make_station):
        station = make_station(
            opis_id=20,
            name="PILOT #1243",
            address="I-8, EXIT 119 & SR-85",
            city="Gila Bend",
            state="AZ",
            rack_id=930,
            price=Decimal("3.899"),
            latitude=32.9487,
            longitude=-112.7163,
            location_precision=Station.LocationPrecision.POI,
        )

        saved = Station.objects.get(pk=station.pk)

        assert saved.opis_id == 20
        assert saved.name == "PILOT #1243"
        assert saved.address == "I-8, EXIT 119 & SR-85"
        assert saved.city == "Gila Bend"
        assert saved.state == "AZ"
        assert saved.rack_id == 930
        assert saved.price == Decimal("3.899")
        assert saved.latitude == pytest.approx(32.9487)
        assert saved.longitude == pytest.approx(-112.7163)
        assert saved.location_precision == "poi"

    def test_keeps_the_full_precision_of_averaged_prices(self, make_station):
        station = make_station(price=Decimal("3.00733333"))

        assert Station.objects.get(pk=station.pk).price == Decimal("3.00733333")

    def test_is_not_geocoded_by_default(self, make_station):
        station = make_station()

        assert station.latitude is None
        assert station.longitude is None
        assert station.location_precision == ""

    def test_str_is_readable(self, make_station):
        station = make_station(name="TA SEYMOUR TRAVEL CENTER", city="Seymour", state="IN")

        assert str(station) == "TA SEYMOUR TRAVEL CENTER (Seymour, IN)"

    def test_location_precision_choices(self):
        assert Station.LocationPrecision.POI == "poi"
        assert Station.LocationPrecision.CITY == "city"


class TestStationUniqueness:
    def test_opis_id_must_be_unique(self, make_station):
        make_station(opis_id=7)

        with pytest.raises(IntegrityError):
            make_station(opis_id=7)


class TestStationPriceConstraint:
    @pytest.mark.parametrize("price", [Decimal("0"), Decimal("-1.50")])
    def test_price_must_be_positive_in_the_database(self, make_station, price):
        with pytest.raises(IntegrityError):
            make_station(price=price)

    def test_non_positive_price_fails_validation(self):
        station = Station(
            opis_id=1, name="X", address="A", city="C", state="TX", rack_id=1, price=Decimal("0")
        )

        with pytest.raises(ValidationError):
            station.full_clean()


class TestStationCoordinatesConstraints:
    @pytest.mark.parametrize(
        "coordinates",
        [
            {"latitude": 40.0, "location_precision": "city"},
            {"longitude": -100.0, "location_precision": "city"},
        ],
        ids=["latitude-only", "longitude-only"],
    )
    def test_latitude_and_longitude_must_be_set_together(self, make_station, coordinates):
        with pytest.raises(IntegrityError):
            make_station(**coordinates)

    @pytest.mark.parametrize(
        "coordinates",
        [
            {"latitude": 90.01, "longitude": 0.0, "location_precision": "city"},
            {"latitude": -90.01, "longitude": 0.0, "location_precision": "city"},
            {"latitude": 0.0, "longitude": 180.01, "location_precision": "city"},
            {"latitude": 0.0, "longitude": -180.01, "location_precision": "city"},
        ],
        ids=["lat-too-high", "lat-too-low", "lon-too-high", "lon-too-low"],
    )
    def test_out_of_range_coordinates_are_rejected(self, make_station, coordinates):
        with pytest.raises(IntegrityError):
            make_station(**coordinates)

    @pytest.mark.parametrize(
        ("latitude", "longitude"),
        [(90.0, 180.0), (-90.0, -180.0), (0.0, 0.0)],
        ids=["max-corner", "min-corner", "zero-zero"],
    )
    def test_boundary_and_zero_coordinates_are_accepted(self, make_station, latitude, longitude):
        station = make_station(latitude=latitude, longitude=longitude, location_precision="city")

        saved = Station.objects.get(pk=station.pk)
        assert (saved.latitude, saved.longitude) == (latitude, longitude)


class TestStationPrecisionConstraint:
    def test_precision_without_coordinates_is_rejected(self, make_station):
        with pytest.raises(IntegrityError):
            make_station(location_precision="poi")

    def test_coordinates_without_precision_are_rejected(self, make_station):
        with pytest.raises(IntegrityError):
            make_station(latitude=40.0, longitude=-100.0)

    @pytest.mark.parametrize("precision", ["poi", "city"])
    def test_coordinates_with_a_precision_are_accepted(self, make_station, precision):
        station = make_station(latitude=40.0, longitude=-100.0, location_precision=precision)

        assert Station.objects.get(pk=station.pk).location_precision == precision

    def test_inconsistent_station_fails_validation(self):
        station = Station(
            opis_id=1,
            name="X",
            address="A",
            city="C",
            state="TX",
            rack_id=1,
            price=Decimal("3.00"),
            location_precision="poi",
        )

        with pytest.raises(ValidationError):
            station.full_clean()


class TestStationValidation:
    def build(self, **overrides):
        fields = {
            "opis_id": 1,
            "name": "X",
            "address": "A",
            "city": "C",
            "state": "TX",
            "rack_id": 1,
            "price": Decimal("3.00"),
        }
        fields.update(overrides)
        return Station(**fields)

    def test_valid_station_passes(self):
        self.build().full_clean()

    def test_state_must_be_two_letters(self):
        with pytest.raises(ValidationError):
            self.build(state="TEXAS").full_clean()

    def test_unknown_location_precision_is_rejected(self):
        with pytest.raises(ValidationError):
            self.build(latitude=1.0, longitude=1.0, location_precision="guess").full_clean()


class TestStationIndexes:
    def test_coordinates_are_indexed_for_bounding_box_queries(self):
        indexed = [tuple(index.fields) for index in Station._meta.indexes]

        assert ("latitude", "longitude") in indexed
