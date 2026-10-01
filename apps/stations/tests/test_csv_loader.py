from decimal import Decimal

import pytest

from apps.stations.csv_loader import (
    InvalidRowError,
    MissingColumnsError,
    SkippedRow,
    StationRecord,
    dedupe_lowest_price,
    load_stations,
    parse_row,
)

HEADER = "OPIS Truckstop ID,Truckstop Name,Address,City,State,Rack ID,Retail Price"


def make_row(**overrides):
    row = {
        "OPIS Truckstop ID": "20",
        "Truckstop Name": "PILOT TRAVEL CENTER #1243",
        "Address": "I-8, EXIT 119 & SR-85",
        "City": "Gila Bend",
        "State": "AZ",
        "Rack ID": "930",
        "Retail Price": "3.899",
    }
    row.update(overrides)
    return row


def make_record(**overrides):
    fields = {
        "opis_id": 20,
        "name": "PILOT TRAVEL CENTER #1243",
        "address": "I-8, EXIT 119 & SR-85",
        "city": "Gila Bend",
        "state": "AZ",
        "rack_id": 930,
        "price": Decimal("3.899"),
    }
    fields.update(overrides)
    return StationRecord(**fields)


class TestParseRow:
    def test_parses_a_valid_row(self):
        assert parse_row(make_row()) == make_record()

    def test_trims_whitespace_around_every_field(self):
        row = make_row(
            **{
                "OPIS Truckstop ID": " 20 ",
                "Truckstop Name": "  PILOT  ",
                "Address": " I-8 ",
                "City": "Effingham                               ",
                "State": " AZ ",
                "Rack ID": " 930 ",
                "Retail Price": " 3.899 ",
            }
        )

        record = parse_row(row)

        assert record == make_record(name="PILOT", address="I-8", city="Effingham")

    def test_collapses_repeated_inner_whitespace(self):
        record = parse_row(make_row(Address="I-35,  EXIT 271", **{"Truckstop Name": "TA   TRAVEL"}))

        assert record.address == "I-35, EXIT 271"
        assert record.name == "TA TRAVEL"

    def test_uppercases_the_state(self):
        assert parse_row(make_row(State="az")).state == "AZ"

    def test_keeps_canadian_provinces(self):
        assert parse_row(make_row(State="ON", City="Toronto")).state == "ON"

    def test_keeps_the_exact_decimal_price(self):
        record = parse_row(make_row(**{"Retail Price": "3.00733333"}))

        assert record.price == Decimal("3.00733333")
        assert isinstance(record.price, Decimal)

    def test_accepts_zero_as_a_rack_id(self):
        assert parse_row(make_row(**{"Rack ID": "0"})).rack_id == 0

    @pytest.mark.parametrize(
        "column",
        [
            "OPIS Truckstop ID",
            "Truckstop Name",
            "Address",
            "City",
            "State",
            "Rack ID",
            "Retail Price",
        ],
    )
    @pytest.mark.parametrize("value", ["", "   ", None], ids=["empty", "blank", "missing"])
    def test_rejects_empty_required_fields(self, column, value):
        with pytest.raises(InvalidRowError, match=column):
            parse_row(make_row(**{column: value}))

    @pytest.mark.parametrize("price", ["abc", "3,50", "$3.50", "NaN", "Infinity", "-Infinity"])
    def test_rejects_prices_that_are_not_finite_numbers(self, price):
        with pytest.raises(InvalidRowError, match="Retail Price"):
            parse_row(make_row(**{"Retail Price": price}))

    @pytest.mark.parametrize("price", ["0", "0.000", "-3.5"])
    def test_rejects_non_positive_prices(self, price):
        with pytest.raises(InvalidRowError, match="Retail Price"):
            parse_row(make_row(**{"Retail Price": price}))

    @pytest.mark.parametrize("value", ["abc", "1.5", "-1", "1e3"])
    @pytest.mark.parametrize("column", ["OPIS Truckstop ID", "Rack ID"])
    def test_rejects_ids_that_are_not_non_negative_integers(self, column, value):
        with pytest.raises(InvalidRowError, match=column):
            parse_row(make_row(**{column: value}))

    @pytest.mark.parametrize("state", ["TEXAS", "T", "T1", "1A", "T-"])
    def test_rejects_states_that_are_not_two_letters(self, state):
        with pytest.raises(InvalidRowError, match="State"):
            parse_row(make_row(State=state))


class TestDedupeLowestPrice:
    def test_empty_input_gives_empty_output(self):
        assert dedupe_lowest_price([]) == []

    def test_unique_stations_are_returned_unchanged(self):
        records = [make_record(opis_id=1), make_record(opis_id=2)]

        assert dedupe_lowest_price(records) == records

    def test_keeps_the_lowest_price_for_a_repeated_id(self):
        records = [
            make_record(price=Decimal("3.429")),
            make_record(price=Decimal("3.269")),
            make_record(price=Decimal("3.339")),
        ]

        result = dedupe_lowest_price(records)

        assert [r.price for r in result] == [Decimal("3.269")]

    def test_keeps_the_details_of_the_cheapest_row(self):
        records = [
            make_record(name="PILOT TRAVEL CENTER #1243", price=Decimal("3.899")),
            make_record(name="PILOT #1243", price=Decimal("3.799")),
        ]

        (result,) = dedupe_lowest_price(records)

        assert result.name == "PILOT #1243"

    def test_on_equal_prices_the_first_row_wins(self):
        records = [
            make_record(name="FIRST", price=Decimal("3.5")),
            make_record(name="SECOND", price=Decimal("3.50")),
        ]

        (result,) = dedupe_lowest_price(records)

        assert result.name == "FIRST"

    def test_keeps_the_order_in_which_ids_first_appear(self):
        records = [
            make_record(opis_id=3),
            make_record(opis_id=1),
            make_record(opis_id=3, price=Decimal("1.0")),
            make_record(opis_id=2),
        ]

        assert [r.opis_id for r in dedupe_lowest_price(records)] == [3, 1, 2]

    def test_accepts_any_iterable(self):
        records = (make_record(opis_id=i) for i in (1, 1, 2))

        assert len(dedupe_lowest_price(records)) == 2


class TestLoadStations:
    def test_loads_and_dedupes_rows(self):
        lines = [
            HEADER,
            "20,PILOT TRAVEL CENTER #1243,I-8 EXIT 119,Gila Bend,AZ,930,3.899",
            "20,PILOT #1243,I-8 EXIT 119,Gila Bend,AZ,930,3.799",
            "28,LITTLEFIELD EXPRESS #2,I-540 EXIT 12,Fort Smith,AR,645,3.399",
        ]

        result = load_stations(lines)

        assert [(r.opis_id, r.price) for r in result.stations] == [
            (20, Decimal("3.799")),
            (28, Decimal("3.399")),
        ]
        assert result.rows_read == 3
        assert result.skipped == []
        assert result.duplicates_merged == 1

    def test_handles_quoted_fields_containing_commas(self):
        lines = [HEADER, '7,WOODSHED,"I-44, EXIT 283 & US-69",Big Cabin,OK,307,3.007']

        (record,) = load_stations(lines).stations

        assert record.address == "I-44, EXIT 283 & US-69"

    def test_reports_skipped_rows_with_line_numbers_and_reasons(self):
        lines = [
            HEADER,
            "1,GOOD,A,Austin,TX,1,3.00",
            "2,BAD PRICE,A,Austin,TX,1,abc",
            "3,GOOD TOO,A,Dallas,TX,1,3.10",
            "4,NO PRICE,A,Dallas,TX,1",
        ]

        result = load_stations(lines)

        assert [r.opis_id for r in result.stations] == [1, 3]
        assert result.rows_read == 4
        assert [s.line_number for s in result.skipped] == [3, 5]
        assert "Retail Price" in result.skipped[0].reason
        assert "Retail Price" in result.skipped[1].reason
        assert all(isinstance(s, SkippedRow) for s in result.skipped)

    def test_a_repeated_id_whose_cheapest_row_is_valid_survives_a_bad_duplicate(self):
        lines = [
            HEADER,
            "1,GOOD,A,Austin,TX,1,3.00",
            "1,GOOD,A,Austin,TX,1,not-a-price",
        ]

        result = load_stations(lines)

        assert [r.price for r in result.stations] == [Decimal("3.00")]
        assert len(result.skipped) == 1

    def test_ignores_blank_lines(self):
        lines = [HEADER, "", "1,GOOD,A,Austin,TX,1,3.00", ""]

        result = load_stations(lines)

        assert result.rows_read == 1

    def test_ignores_extra_columns_and_extra_values(self):
        lines = [HEADER + ",Notes", "1,GOOD,A,Austin,TX,1,3.00,hello,unexpected"]

        result = load_stations(lines)

        assert len(result.stations) == 1

    def test_header_only_file_gives_an_empty_result(self):
        result = load_stations([HEADER])

        assert result.stations == []
        assert result.rows_read == 0
        assert result.skipped == []
        assert result.duplicates_merged == 0

    def test_completely_empty_input_is_reported_as_missing_columns(self):
        with pytest.raises(MissingColumnsError):
            load_stations([])

    def test_missing_columns_are_named_in_the_error(self):
        lines = ["OPIS Truckstop ID,Truckstop Name", "1,GOOD"]

        with pytest.raises(MissingColumnsError) as error:
            load_stations(lines)

        message = str(error.value)
        assert "Retail Price" in message
        assert "City" in message
        assert "Truckstop Name" not in message

    def test_works_with_a_file_object(self, tmp_path):
        path = tmp_path / "stations.csv"
        path.write_text(HEADER + "\n1,GOOD,A,Austin,TX,1,3.00\n", encoding="utf-8")

        with path.open(newline="", encoding="utf-8") as handle:
            result = load_stations(handle)

        assert len(result.stations) == 1
