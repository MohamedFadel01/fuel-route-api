import pytest

from apps.common.geo import Coordinates
from apps.stations.csv_loader import MissingColumnsError
from apps.stations.location_file import (
    StationLocation,
    apply_locations,
    parse_locations,
    write_locations,
)
from apps.stations.models import Station

pytestmark = pytest.mark.django_db

HEADER = "opis_id,latitude,longitude,location_precision"


def parse(*rows, header=HEADER):
    return parse_locations([header, *rows])


class TestParseLocations:
    def test_reads_valid_rows(self):
        result = parse("20,32.930400,-112.673100,poi", "28,35.3,-94.4,city")

        assert result.locations == [
            StationLocation(20, Coordinates(32.9304, -112.6731), "poi"),
            StationLocation(28, Coordinates(35.3, -94.4), "city"),
        ]
        assert result.skipped == []
        assert result.rows_read == 2

    def test_header_only_file_has_no_rows(self):
        result = parse()

        assert result.locations == []
        assert result.rows_read == 0

    def test_column_order_and_extra_columns_do_not_matter(self):
        result = parse(
            "city,1.5,2.5,9,note", header="location_precision,latitude,longitude,opis_id,extra"
        )

        assert result.locations == [StationLocation(9, Coordinates(1.5, 2.5), "city")]

    def test_surrounding_whitespace_is_ignored(self):
        result = parse(" 20 , 32.9 , -112.6 , poi ")

        assert result.locations == [StationLocation(20, Coordinates(32.9, -112.6), "poi")]

    def test_missing_columns_raise(self):
        with pytest.raises(MissingColumnsError, match="latitude"):
            parse("1,2", header="opis_id,longitude,location_precision")

    def test_empty_input_raises(self):
        with pytest.raises(MissingColumnsError):
            parse_locations([])

    @pytest.mark.parametrize(
        ("row", "reason"),
        [
            ("abc,1,2,poi", "opis_id"),
            ("-5,1,2,poi", "opis_id"),
            (",1,2,poi", "opis_id"),
            ("99999999999,1,2,poi", "opis_id"),
            ("5,north,2,poi", "latitude"),
            ("5,,2,poi", "latitude"),
            ("5,1,east,poi", "longitude"),
            ("5,1,,poi", "longitude"),
            ("5,nan,2,poi", "latitude"),
            ("5,1,inf,poi", "longitude"),
            ("5,90.5,2,poi", "latitude"),
            ("5,-90.5,2,poi", "latitude"),
            ("5,1,180.5,poi", "longitude"),
            ("5,1,-180.5,poi", "longitude"),
            ("5,1,2,exact", "location_precision"),
            ("5,1,2,", "location_precision"),
            ("5,1,2,POI", "location_precision"),
        ],
    )
    def test_bad_rows_are_skipped_with_a_reason(self, row, reason):
        result = parse(row)

        assert result.locations == []
        assert result.rows_read == 1
        assert len(result.skipped) == 1
        assert result.skipped[0].line_number == 2
        assert reason in result.skipped[0].reason

    def test_a_short_row_is_skipped(self):
        result = parse("5,1")

        assert result.locations == []
        assert len(result.skipped) == 1

    def test_good_rows_survive_bad_ones(self):
        result = parse("1,1,2,poi", "2,bad,2,poi", "3,3,4,city")

        assert [location.opis_id for location in result.locations] == [1, 3]
        assert [skipped.line_number for skipped in result.skipped] == [3]
        assert result.rows_read == 3

    def test_boundary_coordinates_are_valid(self):
        result = parse("1,90,180,poi", "2,-90,-180,city", "3,0,0,poi")

        assert len(result.locations) == 3
        assert result.skipped == []

    def test_repeated_ids_keep_the_first_row_and_report_the_rest(self):
        result = parse("1,1,2,poi", "1,3,4,city")

        assert result.locations == [StationLocation(1, Coordinates(1, 2), "poi")]
        assert len(result.skipped) == 1
        assert result.skipped[0].line_number == 3
        assert "repeated" in result.skipped[0].reason


class TestWriteLocations:
    def test_writes_only_located_stations_sorted_by_id(self, tmp_path, make_station):
        make_station(opis_id=30, latitude=1.0, longitude=2.0, location_precision="city")
        make_station(opis_id=10, latitude=3.0, longitude=4.0, location_precision="poi")
        make_station(opis_id=20)  # not located yet

        count = write_locations(Station.objects.all(), tmp_path / "out.csv")

        assert count == 2
        assert (tmp_path / "out.csv").read_text().splitlines() == [
            HEADER,
            "10,3.000000,4.000000,poi",
            "30,1.000000,2.000000,city",
        ]

    def test_coordinates_keep_six_decimals(self, tmp_path, make_station):
        make_station(
            opis_id=1, latitude=32.93040049, longitude=-112.67309951, location_precision="poi"
        )

        write_locations(Station.objects.all(), tmp_path / "out.csv")

        assert (tmp_path / "out.csv").read_text().splitlines()[1] == "1,32.930400,-112.673100,poi"

    def test_writes_a_header_when_nothing_is_located(self, tmp_path, make_station):
        make_station()

        count = write_locations(Station.objects.all(), tmp_path / "out.csv")

        assert count == 0
        assert (tmp_path / "out.csv").read_text().splitlines() == [HEADER]

    def test_replaces_an_existing_file(self, tmp_path, make_station):
        path = tmp_path / "out.csv"
        path.write_text("old content\n")
        make_station(opis_id=1, latitude=1.0, longitude=2.0, location_precision="poi")

        write_locations(Station.objects.all(), path)

        assert "old content" not in path.read_text()

    def test_leaves_no_temporary_files_behind(self, tmp_path, make_station):
        make_station(opis_id=1, latitude=1.0, longitude=2.0, location_precision="poi")

        write_locations(Station.objects.all(), tmp_path / "out.csv")

        assert [p.name for p in tmp_path.iterdir()] == ["out.csv"]

    def test_failed_write_keeps_the_old_file(self, tmp_path, make_station, monkeypatch):
        path = tmp_path / "out.csv"
        path.write_text("precious\n")
        make_station(opis_id=1, latitude=1.0, longitude=2.0, location_precision="poi")

        def explode(*args, **kwargs):
            raise OSError("disk full")

        monkeypatch.setattr("apps.stations.location_file.os.replace", explode)

        with pytest.raises(OSError, match="disk full"):
            write_locations(Station.objects.all(), path)

        assert path.read_text() == "precious\n"
        assert [p.name for p in tmp_path.iterdir()] == ["out.csv"]

    def test_creates_missing_parent_directories(self, tmp_path, make_station):
        make_station(opis_id=1, latitude=1.0, longitude=2.0, location_precision="poi")

        write_locations(Station.objects.all(), tmp_path / "a" / "b" / "out.csv")

        assert (tmp_path / "a" / "b" / "out.csv").exists()


class TestApplyLocations:
    def test_stores_coordinates_and_precision(self, make_station):
        make_station(opis_id=20)

        summary = apply_locations([StationLocation(20, Coordinates(32.9304, -112.6731), "poi")])

        station = Station.objects.get(opis_id=20)
        assert (station.latitude, station.longitude) == (32.9304, -112.6731)
        assert station.location_precision == "poi"
        assert summary.updated == 1
        assert summary.unknown == 0

    def test_unknown_ids_are_counted_and_ignored(self, make_station):
        make_station(opis_id=20)

        summary = apply_locations(
            [
                StationLocation(20, Coordinates(1, 2), "city"),
                StationLocation(999, Coordinates(3, 4), "poi"),
            ]
        )

        assert summary.updated == 1
        assert summary.unknown == 1
        assert Station.objects.count() == 1

    def test_stations_missing_from_the_file_are_left_alone(self, make_station):
        make_station(opis_id=1, latitude=5.0, longitude=6.0, location_precision="city")
        make_station(opis_id=2)

        apply_locations([StationLocation(2, Coordinates(1, 2), "poi")])

        untouched = Station.objects.get(opis_id=1)
        assert (untouched.latitude, untouched.location_precision) == (5.0, "city")

    def test_the_file_wins_over_what_the_database_has(self, make_station):
        make_station(opis_id=1, latitude=5.0, longitude=6.0, location_precision="city")

        apply_locations([StationLocation(1, Coordinates(7, 8), "poi")])

        station = Station.objects.get(opis_id=1)
        assert (station.latitude, station.longitude, station.location_precision) == (7, 8, "poi")

    def test_nothing_to_apply(self):
        summary = apply_locations([])

        assert summary.updated == 0
        assert summary.unknown == 0

    def test_handles_more_stations_than_one_batch(self, make_station):
        for _ in range(7):
            make_station()
        ids = list(Station.objects.values_list("opis_id", flat=True))

        summary = apply_locations(
            [StationLocation(id_, Coordinates(1, 2), "city") for id_ in ids], batch_size=3
        )

        assert summary.updated == 7
        assert Station.objects.filter(location_precision="city").count() == 7

    def test_repeated_ids_are_rejected_before_anything_is_written(self, make_station):
        make_station(opis_id=1)

        with pytest.raises(ValueError, match="Duplicate"):
            apply_locations(
                [
                    StationLocation(1, Coordinates(1, 2), "poi"),
                    StationLocation(1, Coordinates(3, 4), "city"),
                ]
            )

        assert Station.objects.get(opis_id=1).location_precision == ""


class TestRoundTrip:
    def test_export_then_load_restores_every_location(self, tmp_path, make_station):
        make_station(opis_id=1, latitude=32.930401, longitude=-112.673102, location_precision="poi")
        make_station(opis_id=2, latitude=35.3, longitude=-94.4, location_precision="city")
        make_station(opis_id=3)
        path = tmp_path / "out.csv"
        write_locations(Station.objects.all(), path)
        Station.objects.update(latitude=None, longitude=None, location_precision="")

        with path.open(newline="") as handle:
            result = parse_locations(handle)
        summary = apply_locations(result.locations)

        assert summary.updated == 2
        first, second, third = Station.objects.order_by("opis_id")
        assert (first.latitude, first.longitude, first.location_precision) == (
            32.930401,
            -112.673102,
            "poi",
        )
        assert (second.latitude, second.longitude, second.location_precision) == (
            35.3,
            -94.4,
            "city",
        )
        assert third.location_precision == ""
