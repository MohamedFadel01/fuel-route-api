from io import StringIO

import pytest
from django.conf import settings
from django.core.management import CommandError, call_command

from apps.stations.models import Station

pytestmark = pytest.mark.django_db

HEADER = "opis_id,latitude,longitude,location_precision"


def run(command, *args):
    out, err = StringIO(), StringIO()
    call_command(command, *args, stdout=out, stderr=err)
    return out.getvalue(), err.getvalue()


@pytest.fixture
def located_stations(make_station):
    make_station(opis_id=1, latitude=32.9304, longitude=-112.6731, location_precision="poi")
    make_station(opis_id=2, latitude=35.3, longitude=-94.4, location_precision="city")
    make_station(opis_id=3, latitude=36.0, longitude=-95.0, location_precision="city")
    make_station(opis_id=4)


@pytest.fixture
def locations_file(tmp_path):
    def write(*rows, header=HEADER, encoding="utf-8"):
        path = tmp_path / "locations.csv"
        path.write_bytes(("\n".join([header, *rows]) + "\n").encode(encoding))
        return path

    return write


class TestExportStationLocations:
    def test_writes_the_located_stations(self, tmp_path, located_stations):
        path = tmp_path / "out.csv"

        run("export_station_locations", str(path))

        assert path.read_text().splitlines() == [
            HEADER,
            "1,32.930400,-112.673100,poi",
            "2,35.300000,-94.400000,city",
            "3,36.000000,-95.000000,city",
        ]

    def test_prints_a_summary(self, tmp_path, located_stations):
        out, err = run("export_station_locations", str(tmp_path / "out.csv"))

        assert "3 station locations written" in out
        assert "1 exact" in out
        assert "2 approximate" in out
        assert "1 station not located yet" in out
        assert err == ""

    def test_summary_uses_the_right_plural(self, tmp_path, make_station):
        make_station(latitude=1.0, longitude=2.0, location_precision="poi")
        make_station()
        make_station()

        out, _ = run("export_station_locations", str(tmp_path / "out.csv"))

        assert "1 station location written" in out
        assert "2 stations not located yet" in out

    def test_summary_does_not_mention_missing_stations_when_all_are_located(
        self, tmp_path, make_station
    ):
        make_station(latitude=1.0, longitude=2.0, location_precision="poi")

        out, _ = run("export_station_locations", str(tmp_path / "out.csv"))

        assert "not located" not in out

    def test_uses_the_configured_default_file(self, tmp_path, located_stations, settings):
        settings.STATION_LOCATIONS_CSV = tmp_path / "default.csv"

        run("export_station_locations")

        assert settings.STATION_LOCATIONS_CSV.exists()

    def test_refuses_to_write_an_empty_file(self, tmp_path, make_station):
        make_station()
        path = tmp_path / "out.csv"
        path.write_text("precious\n")

        with pytest.raises(CommandError, match="No stations have a location"):
            run("export_station_locations", str(path))

        assert path.read_text() == "precious\n"

    def test_unwritable_target_is_a_clear_error(self, tmp_path, located_stations):
        with pytest.raises(CommandError, match="Cannot write"):
            run("export_station_locations", str(tmp_path))  # a directory


class TestLoadStationLocations:
    def test_applies_the_file(self, locations_file, make_station):
        make_station(opis_id=1)
        make_station(opis_id=2)
        path = locations_file("1,32.9304,-112.6731,poi", "2,35.3,-94.4,city")

        run("load_station_locations", str(path))

        first = Station.objects.get(opis_id=1)
        assert (first.latitude, first.longitude, first.location_precision) == (
            32.9304,
            -112.6731,
            "poi",
        )
        assert Station.objects.get(opis_id=2).location_precision == "city"

    def test_prints_a_summary(self, locations_file, make_station):
        make_station(opis_id=1)
        path = locations_file("1,1,2,poi", "999,3,4,city", "5,bad,4,city")

        out, err = run("load_station_locations", str(path))

        assert "3 rows read" in out
        assert "1 stations located" in out
        assert "1 not in the database" in out
        assert "1 rows skipped" in out
        assert "line 4" in err
        assert "latitude" in err

    def test_stations_not_in_the_file_are_untouched(self, locations_file, make_station):
        make_station(opis_id=1)
        make_station(opis_id=2)

        run("load_station_locations", str(locations_file("1,1,2,poi")))

        assert Station.objects.get(opis_id=2).location_precision == ""

    def test_running_twice_gives_the_same_result(self, locations_file, make_station):
        make_station(opis_id=1)
        path = str(locations_file("1,1,2,poi"))
        run("load_station_locations", path)

        out, _ = run("load_station_locations", path)

        assert "1 stations located" in out
        assert Station.objects.get(opis_id=1).latitude == 1.0

    def test_repeated_ids_use_the_first_row(self, locations_file, make_station):
        make_station(opis_id=1)
        path = locations_file("1,1,2,poi", "1,3,4,city")

        _, err = run("load_station_locations", str(path))

        assert Station.objects.get(opis_id=1).location_precision == "poi"
        assert "repeated" in err

    def test_uses_the_configured_default_file(self, locations_file, make_station, settings):
        make_station(opis_id=1)
        settings.STATION_LOCATIONS_CSV = locations_file("1,1,2,poi")

        run("load_station_locations")

        assert Station.objects.get(opis_id=1).location_precision == "poi"

    def test_reads_files_that_start_with_a_byte_order_mark(self, locations_file, make_station):
        make_station(opis_id=1)

        run("load_station_locations", str(locations_file("1,1,2,poi", encoding="utf-8-sig")))

        assert Station.objects.get(opis_id=1).location_precision == "poi"

    def test_missing_file_explains_how_to_create_it(self, tmp_path):
        with pytest.raises(CommandError, match="not found") as error:
            run("load_station_locations", str(tmp_path / "nope.csv"))

        assert "geocode_stations" in str(error.value)

    def test_directory_instead_of_file_is_a_clear_error(self, tmp_path):
        with pytest.raises(CommandError, match="Cannot read"):
            run("load_station_locations", str(tmp_path))

    def test_missing_columns_are_a_clear_error(self, locations_file):
        path = locations_file("1,2", header="opis_id,latitude")

        with pytest.raises(CommandError, match="longitude"):
            run("load_station_locations", str(path))

    def test_empty_file_is_a_clear_error(self, tmp_path):
        path = tmp_path / "empty.csv"
        path.write_text("")

        with pytest.raises(CommandError, match="missing columns"):
            run("load_station_locations", str(path))

    def test_file_that_is_not_utf8_is_a_clear_error(self, locations_file):
        path = locations_file("1,1,2,caf\xe9", encoding="latin-1")

        with pytest.raises(CommandError, match="UTF-8"):
            run("load_station_locations", str(path))


class TestExportThenLoad:
    def test_a_fresh_database_gets_every_location_back(self, tmp_path, located_stations):
        path = tmp_path / "locations.csv"
        run("export_station_locations", str(path))
        before = list(
            Station.objects.order_by("opis_id").values_list(
                "opis_id", "latitude", "longitude", "location_precision"
            )
        )
        Station.objects.update(latitude=None, longitude=None, location_precision="")

        run("load_station_locations", str(path))

        after = list(
            Station.objects.order_by("opis_id").values_list(
                "opis_id", "latitude", "longitude", "location_precision"
            )
        )
        assert after == [*before[:3], (4, None, None, "")]

    def test_exporting_twice_gives_identical_files(self, tmp_path, located_stations):
        first, second = tmp_path / "first.csv", tmp_path / "second.csv"
        run("export_station_locations", str(first))
        Station.objects.update(latitude=None, longitude=None, location_precision="")
        run("load_station_locations", str(first))

        run("export_station_locations", str(second))

        assert first.read_bytes() == second.read_bytes()


class TestCommittedLocationsFile:
    """Checks the real ``data/stations_geocoded.csv`` once it has been generated."""

    @pytest.fixture(autouse=True)
    def _require_file(self):
        if not settings.STATION_LOCATIONS_CSV.exists():
            pytest.skip("data/stations_geocoded.csv has not been generated yet")

    def test_it_loads_cleanly_into_the_imported_stations(self):
        run("import_stations")

        out, err = run("load_station_locations")

        assert err == ""
        assert "0 rows skipped" in out
        assert "0 not in the database" in out

    def test_nearly_every_station_gets_a_location(self):
        run("import_stations")
        run("load_station_locations")

        total = Station.objects.count()
        located = Station.objects.exclude(location_precision="").count()

        assert located / total > 0.99
