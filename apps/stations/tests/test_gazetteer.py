import tracemalloc
import zipfile

import pytest

from apps.stations.geocoding.gazetteer import (
    CityGazetteer,
    GazetteerError,
    normalize_place_name,
)
from apps.stations.geocoding.types import Coordinates


def geonames_line(
    name,
    lat,
    lon,
    admin1,
    *,
    population=0,
    feature_class="P",
    asciiname=None,
    alternates="",
    country="US",
):
    """Build one line of a GeoNames dump (19 tab-separated columns)."""
    fields = [
        "1",
        name,
        asciiname if asciiname is not None else name,
        alternates,
        str(lat),
        str(lon),
        feature_class,
        "PPL",
        country,
        "",
        admin1,
        "",
        "",
        "",
        str(population),
        "",
        "0",
        "America/Chicago",
        "2024-01-01",
    ]
    return "\t".join(fields)


class TestNormalizePlaceName:
    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            ("Austin", "austin"),
            ("AUSTIN", "austin"),
            ("  Fort   Smith  ", "fortsmith"),
            ("Effingham                               ", "effingham"),
            ("Winston-Salem", "winstonsalem"),
            ("Bois d'Arc", "boisdarc"),
            ("Montréal", "montreal"),
            ("Cañon City", "canoncity"),
        ],
    )
    def test_ignores_case_spacing_punctuation_and_accents(self, name, expected):
        assert normalize_place_name(name) == expected

    @pytest.mark.parametrize(
        ("variant", "canonical"),
        [
            ("St. Louis", "Saint Louis"),
            ("St Louis", "Saint Louis"),
            ("Ste. Genevieve", "Sainte Genevieve"),
            ("Ft. Smith", "Fort Smith"),
            ("Mt. Jackson", "Mount Jackson"),
            ("Mc Alpin", "McAlpin"),
            ("De Forest", "DeForest"),
            ("Bois D Arc", "Bois d'Arc"),
            ("S Coffeyville", "South Coffeyville"),
            ("N Platte", "North Platte"),
            ("E Liverpool", "East Liverpool"),
            ("W Point", "West Point"),
        ],
    )
    def test_common_variants_normalize_to_the_same_key(self, variant, canonical):
        assert normalize_place_name(variant) == normalize_place_name(canonical)

    def test_directional_letters_are_only_expanded_at_the_start(self):
        assert normalize_place_name("Lake S") == "lakes"
        assert normalize_place_name("Stanley") == "stanley"

    @pytest.mark.parametrize("name", ["", "   ", "!!!", "東京"])
    def test_names_without_latin_characters_become_empty(self, name):
        assert normalize_place_name(name) == ""


class TestCityGazetteerLookup:
    def build(self, *lines, country="US"):
        gazetteer = CityGazetteer()
        gazetteer.add_geonames(country, lines)
        return gazetteer

    def test_finds_a_city_by_name_and_state(self):
        gazetteer = self.build(geonames_line("Austin", 30.26715, -97.74306, "TX"))

        assert gazetteer.lookup("Austin", "TX") == Coordinates(30.26715, -97.74306)

    def test_lookup_ignores_case_spacing_and_abbreviations(self):
        gazetteer = self.build(geonames_line("Saint Louis", 38.62727, -90.19789, "MO"))

        expected = Coordinates(38.62727, -90.19789)
        assert gazetteer.lookup("  ST.  LOUIS ", "mo") == expected
        assert gazetteer.lookup("saint louis", " MO ") == expected

    def test_the_state_must_match(self):
        gazetteer = self.build(
            geonames_line("Springfield", 39.8, -89.6, "IL", population=100),
            geonames_line("Springfield", 37.2, -93.3, "MO", population=100),
        )

        assert gazetteer.lookup("Springfield", "IL") == Coordinates(39.8, -89.6)
        assert gazetteer.lookup("Springfield", "MO") == Coordinates(37.2, -93.3)
        assert gazetteer.lookup("Springfield", "TX") is None

    def test_most_populous_place_wins_when_names_collide(self):
        gazetteer = self.build(
            geonames_line("Clinton", 1.0, 1.0, "IA", population=10),
            geonames_line("Clinton", 2.0, 2.0, "IA", population=5000),
            geonames_line("Clinton", 3.0, 3.0, "IA", population=300),
        )

        assert gazetteer.lookup("Clinton", "IA") == Coordinates(2.0, 2.0)

    def test_first_place_wins_when_populations_tie(self):
        gazetteer = self.build(
            geonames_line("Clinton", 1.0, 1.0, "IA"),
            geonames_line("Clinton", 2.0, 2.0, "IA"),
        )

        assert gazetteer.lookup("Clinton", "IA") == Coordinates(1.0, 1.0)

    def test_ignores_features_that_are_not_populated_places(self):
        gazetteer = self.build(
            geonames_line("Austin Lake", 1.0, 1.0, "TX", feature_class="H"),
            geonames_line("Austin", 2.0, 2.0, "TX", feature_class="S"),
        )

        assert len(gazetteer) == 0
        assert gazetteer.lookup("Austin", "TX") is None

    def test_matches_the_ascii_name_when_the_name_has_accents(self):
        gazetteer = self.build(
            geonames_line("Cañon City", 38.4, -105.2, "CO", asciiname="Canon City")
        )

        assert gazetteer.lookup("Canon City", "CO") == Coordinates(38.4, -105.2)
        assert gazetteer.lookup("Cañon City", "CO") == Coordinates(38.4, -105.2)

    def test_falls_back_to_alternate_names(self):
        gazetteer = self.build(
            geonames_line("Brookpark", 41.4, -81.8, "OH", alternates="Brook Park,Brookpark Village")
        )

        assert gazetteer.lookup("Brook Park", "OH") == Coordinates(41.4, -81.8)
        assert gazetteer.lookup("Brookpark Village", "OH") == Coordinates(41.4, -81.8)
        assert gazetteer.lookup("Brook Parkway", "OH") is None

    def test_an_official_name_beats_an_alternate_name_of_a_bigger_place(self):
        gazetteer = self.build(
            geonames_line("Bigtown", 1.0, 1.0, "TX", population=100000, alternates="Smallville"),
            geonames_line("Smallville", 2.0, 2.0, "TX", population=10),
        )

        assert gazetteer.lookup("Smallville", "TX") == Coordinates(2.0, 2.0)

    def test_the_most_populous_place_wins_among_alternate_names(self):
        gazetteer = self.build(
            geonames_line("Alpha", 1.0, 1.0, "TX", population=10, alternates="Shared"),
            geonames_line("Beta", 2.0, 2.0, "TX", population=900, alternates="Shared"),
        )

        assert gazetteer.lookup("Shared", "TX") == Coordinates(2.0, 2.0)

    def test_non_latin_alternate_names_never_create_empty_keys(self):
        gazetteer = self.build(geonames_line("Tokyo", 1.0, 1.0, "TX", alternates="東京,!!!,,"))

        assert gazetteer.lookup("", "TX") is None
        assert gazetteer.lookup("!!!", "TX") is None

    @pytest.mark.parametrize(
        ("city", "state"), [("", "TX"), ("   ", "TX"), ("Austin", ""), ("", "")]
    )
    def test_blank_city_or_state_finds_nothing(self, city, state):
        gazetteer = self.build(geonames_line("Austin", 30.0, -97.0, "TX"))

        assert gazetteer.lookup(city, state) is None

    def test_unknown_city_finds_nothing(self):
        gazetteer = self.build(geonames_line("Austin", 30.0, -97.0, "TX"))

        assert gazetteer.lookup("Atlantis", "TX") is None

    def test_zero_coordinates_are_valid(self):
        gazetteer = self.build(geonames_line("Nullville", 0.0, 0.0, "TX"))

        assert gazetteer.lookup("Nullville", "TX") == Coordinates(0.0, 0.0)

    def test_places_are_counted_once_even_with_several_names(self):
        gazetteer = self.build(
            geonames_line("Austin", 30.0, -97.0, "TX", alternates="Austin City,ATX")
        )

        assert len(gazetteer) == 1


class TestGeoNamesParsing:
    def test_add_geonames_returns_how_many_places_were_added(self):
        gazetteer = CityGazetteer()

        added = gazetteer.add_geonames(
            "US",
            [
                geonames_line("Austin", 30.0, -97.0, "TX"),
                geonames_line("Austin Lake", 1.0, 1.0, "TX", feature_class="H"),
                geonames_line("Dallas", 32.0, -96.0, "TX"),
            ],
        )

        assert added == 2

    @pytest.mark.parametrize(
        "line",
        [
            "",
            "just one field",
            "\t".join(["1", "Austin"]),
            geonames_line("Austin", "not-a-number", -97.0, "TX"),
            geonames_line("Austin", 30.0, "", "TX"),
            geonames_line("Austin", 91.0, -97.0, "TX"),
            geonames_line("Austin", 30.0, -181.0, "TX"),
        ],
        ids=["empty", "one-field", "short", "bad-lat", "empty-lon", "lat-range", "lon-range"],
    )
    def test_malformed_lines_are_skipped(self, line):
        gazetteer = CityGazetteer()

        assert gazetteer.add_geonames("US", [line]) == 0
        assert len(gazetteer) == 0

    def test_a_bad_population_counts_as_zero(self):
        gazetteer = CityGazetteer()
        line = geonames_line("Austin", 30.0, -97.0, "TX").split("\t")
        line[14] = "many"

        assert gazetteer.add_geonames("US", ["\t".join(line)]) == 1

    @pytest.mark.parametrize("admin1", ["", "TEXAS", "9", "00"])
    def test_us_places_need_a_two_letter_state(self, admin1):
        gazetteer = CityGazetteer()

        assert gazetteer.add_geonames("US", [geonames_line("Austin", 30.0, -97.0, admin1)]) == 0

    @pytest.mark.parametrize(
        ("admin1", "province"),
        [
            ("01", "AB"),
            ("02", "BC"),
            ("03", "MB"),
            ("04", "NB"),
            ("05", "NL"),
            ("07", "NS"),
            ("08", "ON"),
            ("09", "PE"),
            ("10", "QC"),
            ("11", "SK"),
            ("12", "YT"),
            ("13", "NT"),
            ("14", "NU"),
        ],
    )
    def test_canadian_numeric_codes_become_province_letters(self, admin1, province):
        gazetteer = CityGazetteer()
        gazetteer.add_geonames("CA", [geonames_line("Place", 50.0, -100.0, admin1, country="CA")])

        assert gazetteer.lookup("Place", province) == Coordinates(50.0, -100.0)

    def test_unknown_canadian_codes_are_skipped(self):
        gazetteer = CityGazetteer()

        added = gazetteer.add_geonames(
            "CA", [geonames_line("Place", 50.0, -100.0, "99", country="CA")]
        )

        assert added == 0

    def test_unsupported_country_is_rejected(self):
        with pytest.raises(ValueError, match="MX"):
            CityGazetteer().add_geonames("MX", [])

    def test_us_and_canada_can_share_one_gazetteer(self):
        gazetteer = CityGazetteer()
        gazetteer.add_geonames("US", [geonames_line("London", 1.0, 1.0, "KY")])
        gazetteer.add_geonames("CA", [geonames_line("London", 2.0, 2.0, "08", country="CA")])

        assert gazetteer.lookup("London", "KY") == Coordinates(1.0, 1.0)
        assert gazetteer.lookup("London", "ON") == Coordinates(2.0, 2.0)


class TestFromGeoNamesZips:
    def write_zip(self, path, member, *lines):
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr(member, "\n".join(lines) + "\n")
        return path

    def test_loads_the_text_file_inside_each_zip(self, tmp_path):
        us = self.write_zip(
            tmp_path / "US.zip", "US.txt", geonames_line("Austin", 30.0, -97.0, "TX")
        )
        ca = self.write_zip(
            tmp_path / "CA.zip",
            "CA.txt",
            geonames_line("Toronto", 43.7, -79.4, "08", country="CA"),
        )

        gazetteer = CityGazetteer.from_geonames_zips({"US": us, "CA": ca})

        assert gazetteer.lookup("Austin", "TX") == Coordinates(30.0, -97.0)
        assert gazetteer.lookup("Toronto", "ON") == Coordinates(43.7, -79.4)

    def test_reads_utf8_names(self, tmp_path):
        path = tmp_path / "CA.zip"
        with zipfile.ZipFile(path, "w") as archive:
            line = geonames_line("Montréal", 45.5, -73.6, "10", asciiname="Montreal", country="CA")
            archive.writestr("CA.txt", line.encode("utf-8"))

        gazetteer = CityGazetteer.from_geonames_zips({"CA": path})

        assert gazetteer.lookup("Montréal", "QC") == Coordinates(45.5, -73.6)

    def test_streams_the_file_instead_of_loading_it_into_memory(self, tmp_path):
        # About 20 MB of text that contains no populated place, so nothing is kept:
        # any real memory use would come from reading the file whole.
        filler = geonames_line("Some Lake", 1.0, 1.0, "TX", feature_class="H")
        path = self.write_zip(tmp_path / "US.zip", "US.txt", *[filler] * 150_000)

        tracemalloc.start()
        try:
            CityGazetteer.from_geonames_zips({"US": path})
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()

        assert peak < 3_000_000

    @pytest.mark.parametrize("separator", ["\x0b", "\x0c", "\x1c", "\x85", "\u2028"])
    def test_unusual_line_separators_inside_a_field_do_not_split_a_record(
        self, tmp_path, separator
    ):
        line = geonames_line("Austin", 30.0, -97.0, "TX", alternates=f"Aus{separator}tin City")
        path = self.write_zip(tmp_path / "US.zip", "US.txt", line)

        gazetteer = CityGazetteer.from_geonames_zips({"US": path})

        assert len(gazetteer) == 1
        assert gazetteer.lookup("Austin", "TX") == Coordinates(30.0, -97.0)

    def test_windows_line_endings_are_handled(self, tmp_path):
        path = tmp_path / "US.zip"
        with zipfile.ZipFile(path, "w") as archive:
            lines = [
                geonames_line("Austin", 30.0, -97.0, "TX"),
                geonames_line("Dallas", 1.0, 2.0, "TX"),
            ]
            archive.writestr("US.txt", "\r\n".join(lines) + "\r\n")

        gazetteer = CityGazetteer.from_geonames_zips({"US": path})

        assert len(gazetteer) == 2
        assert gazetteer.lookup("Dallas", "TX") == Coordinates(1.0, 2.0)

    def test_missing_zip_is_a_clear_error(self, tmp_path):
        with pytest.raises(GazetteerError, match=r"US\.zip"):
            CityGazetteer.from_geonames_zips({"US": tmp_path / "US.zip"})

    def test_zip_without_the_expected_file_is_a_clear_error(self, tmp_path):
        path = self.write_zip(tmp_path / "US.zip", "readme.txt", "hello")

        with pytest.raises(GazetteerError, match=r"US\.txt"):
            CityGazetteer.from_geonames_zips({"US": path})

    def test_corrupt_zip_is_a_clear_error(self, tmp_path):
        path = tmp_path / "US.zip"
        path.write_bytes(b"this is not a zip file")

        with pytest.raises(GazetteerError, match="not a valid zip"):
            CityGazetteer.from_geonames_zips({"US": path})
