import pytest

from apps.common.geo import Coordinates, haversine_miles
from apps.stations.geocoding.nominatim import NominatimError, PlaceMatch
from apps.stations.geocoding.station_geocoder import (
    LocatedPlace,
    StationGeocoder,
    build_search_query,
    names_match,
)
from apps.stations.models import Station

AUSTIN = Coordinates(30.2672, -97.7431)
NEAR_AUSTIN = Coordinates(30.30, -97.70)  # about 3 miles from the centre
NEAR_ELGIN = Coordinates(30.35, -97.37)  # about 25 miles away
FAR_FROM_AUSTIN = Coordinates(31.50, -97.70)  # about 85 miles away


class TestBuildSearchQuery:
    @pytest.mark.parametrize(
        ("name", "city", "state", "expected"),
        [
            ("PILOT TRAVEL CENTER #1243", "Gila Bend", "AZ", "PILOT TRAVEL CENTER, Gila Bend, AZ"),
            ("KWIK TRIP #796", "Tomah", "WI", "KWIK TRIP, Tomah, WI"),
            ("  KWIK   TRIP  #796 ", "  Tomah ", "WI", "KWIK TRIP, Tomah, WI"),
            ("CIRCLE K #2612042", "Jarrell", "TX", "CIRCLE K, Jarrell, TX"),
            ("Hucks Travel Center #052", "Kuttawa", "KY", "Hucks Travel Center, Kuttawa, KY"),
            ("STORE #A-12 DIESEL", "Austin", "TX", "STORE DIESEL, Austin, TX"),
        ],
        ids=["store-number", "simple", "extra-spaces", "long-number", "mixed-case", "alnum-number"],
    )
    def test_removes_store_numbers_and_tidies_spacing(self, name, city, state, expected):
        assert build_search_query(name, city, state) == expected

    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            ("LOVES TRAVEL STOP #766", "Love's TRAVEL STOP, Austin, TX"),
            ("loves travel stop", "Love's travel stop, Austin, TX"),
            ("CASEYS #3842", "Casey's, Austin, TX"),
            ("GLOVES DEPOT", "GLOVES DEPOT, Austin, TX"),
        ],
    )
    def test_spells_well_known_brands_the_way_openstreetmap_does(self, name, expected):
        assert build_search_query(name, "Austin", "TX") == expected

    def test_plural_center_becomes_singular(self):
        query = build_search_query("PILOT TRAVEL CENTERS #918", "Rapid City", "SD")

        assert query == "PILOT TRAVEL CENTER, Rapid City, SD"

    @pytest.mark.parametrize(
        ("name", "city", "expected"),
        [
            ("TA SEYMOUR TRAVEL CENTER", "Seymour", "TA TRAVEL CENTER, Seymour, IN"),
            ("ta seymour travel center", "SEYMOUR", "ta travel center, SEYMOUR, IN"),
            ("WOODSHED OF BIG CABIN", "Big Cabin", "WOODSHED, Big Cabin, IN"),
            ("SEYMOUR", "Seymour", "SEYMOUR, Seymour, IN"),
            ("SEYMOURS DINER", "Seymour", "SEYMOURS DINER, Seymour, IN"),
        ],
        ids=["city-in-name", "city-case", "dangling-of", "only-the-city", "city-inside-word"],
    )
    def test_drops_the_city_from_the_name_because_it_is_added_separately(
        self, name, city, expected
    ):
        assert build_search_query(name, city, "IN") == expected

    def test_a_name_that_is_only_a_store_number_is_kept(self):
        assert build_search_query("#12", "Austin", "TX") == "#12, Austin, TX"


class TestNamesMatch:
    @pytest.mark.parametrize(
        ("station", "place", "city"),
        [
            ("PILOT TRAVEL CENTER #1243", "Pilot Travel Center", "Gila Bend"),
            ("LOVES TRAVEL STOP #766", "Love's Travel Stop", "Atkinson"),
            ("CASEYS #3842", "Casey's General Store", "Norton"),
            ("TA SEYMOUR TRAVEL CENTER", "TA Travel Center", "Seymour"),
            ("HURLOCK CITGO", "Citgo", "Hurlock"),
            ("MARIO'S PLACE", "Marios Place", "Austin"),
            ("CAFÉ ROUTE", "Cafe Route", "Austin"),
            ("FLYING J TRAVEL PLAZA #726", "Flying J Travel Center", "Dallas"),
            ("PETRO STOPPING CENTER #348", "Petro Stopping Centers", "Shorter"),
        ],
    )
    def test_matches_when_a_distinctive_word_is_shared(self, station, place, city):
        assert names_match(station, place, city) is True

    @pytest.mark.parametrize(
        ("station", "place", "city"),
        [
            ("TA SEYMOUR TRAVEL CENTER", "Huck's Food & Fuel", "Seymour"),
            ("ACI TRUCK STOP", "US Fuel", "Columbia"),
            ("PILOT TRAVEL CENTER", "Love's Travel Stop", "Austin"),
        ],
    )
    def test_rejects_different_businesses(self, station, place, city):
        assert names_match(station, place, city) is False

    def test_the_city_name_alone_is_not_evidence(self):
        assert names_match("TA SEYMOUR TRAVEL CENTER", "Seymour Shell", "Seymour") is False

    @pytest.mark.parametrize(
        ("station", "place"),
        [
            ("TRUCK STOP", "Truck Stop"),
            ("TRAVEL CENTER #12", "Travel Center"),
            ("S&G", "Shell S"),
            ("I-75 TRAVEL PLAZA", "I-75 Exit Diner"),
            ("", "Anything"),
            ("Anything", ""),
        ],
        ids=["generic", "generic-number", "initials", "highway-number", "no-station", "no-place"],
    )
    def test_generic_words_numbers_and_initials_are_not_evidence(self, station, place):
        assert names_match(station, place, "Austin") is False

    def test_is_case_and_punctuation_insensitive(self):
        assert names_match("pilot, travel-center", "PILOT Travel Center", "Austin") is True
        assert names_match("PILOT!!!", "pilot", "Austin") is True


class FakeGazetteer:
    def __init__(self, places=None):
        self.places = places if places is not None else {("Austin", "TX"): AUSTIN}

    def lookup(self, city, state):
        return self.places.get((city.strip(), state.strip().upper()))


class FakeSearcher:
    def __init__(self, results=(), error=None):
        self.results = list(results)
        self.error = error
        self.queries = []

    def search(self, query, limit=5):
        self.queries.append((query, limit))
        if self.error is not None:
            raise self.error
        return list(self.results)


def place(name="Pilot Travel Center", coordinates=NEAR_AUSTIN, region="TX"):
    return PlaceMatch(
        name=name, coordinates=coordinates, region=region, category="amenity", kind="fuel"
    )


def locate(searcher, gazetteer=None, name="PILOT TRAVEL CENTER #12", **kwargs):
    geocoder = StationGeocoder(searcher, gazetteer or FakeGazetteer(), **kwargs)
    return geocoder.locate(name, "Austin", "TX")


CITY_CENTRE = LocatedPlace(AUSTIN, Station.LocationPrecision.CITY)


class TestLocate:
    def test_a_valid_match_gives_an_exact_position(self):
        searcher = FakeSearcher([place()])

        result = locate(searcher)

        assert result == LocatedPlace(NEAR_AUSTIN, Station.LocationPrecision.POI)
        assert result.precision == "poi"

    def test_searches_once_with_the_cleaned_query(self):
        searcher = FakeSearcher([place()])

        locate(searcher)

        assert searcher.queries == [("PILOT TRAVEL CENTER, Austin, TX", 5)]

    def test_a_match_in_the_wrong_state_is_rejected(self):
        assert locate(FakeSearcher([place(region="OK")])) == CITY_CENTRE

    def test_a_match_with_an_unknown_state_is_rejected(self):
        assert locate(FakeSearcher([place(region="")])) == CITY_CENTRE

    def test_state_comparison_ignores_case_and_spaces(self):
        geocoder = StationGeocoder(FakeSearcher([place(region="tx")]), FakeGazetteer())

        result = geocoder.locate("PILOT TRAVEL CENTER", "Austin", " TX ")

        assert result.precision == "poi"

    def test_a_match_far_from_the_city_is_rejected(self):
        assert locate(FakeSearcher([place(coordinates=FAR_FROM_AUSTIN)])) == CITY_CENTRE

    def test_the_distance_limit_is_inclusive(self):
        limit = haversine_miles(AUSTIN, NEAR_ELGIN)
        searcher = FakeSearcher([place(coordinates=NEAR_ELGIN)])

        assert locate(searcher, max_distance_miles=limit).precision == "poi"
        assert locate(searcher, max_distance_miles=limit - 0.001) == CITY_CENTRE

    def test_a_match_with_a_different_name_is_rejected(self):
        assert locate(FakeSearcher([place(name="Huck's Food & Fuel")])) == CITY_CENTRE

    def test_no_results_falls_back_to_the_city_centre(self):
        assert locate(FakeSearcher([])) == CITY_CENTRE

    def test_picks_the_first_valid_result_and_skips_invalid_ones(self):
        searcher = FakeSearcher(
            [
                place(name="Wrong Name"),
                place(region="OK"),
                place(coordinates=FAR_FROM_AUSTIN),
                place(coordinates=Coordinates(30.31, -97.71)),
                place(coordinates=Coordinates(30.32, -97.72)),
            ]
        )

        assert locate(searcher).coordinates == Coordinates(30.31, -97.71)

    def test_canadian_stations_match_their_province(self):
        toronto = Coordinates(43.7, -79.4)
        searcher = FakeSearcher([place("Petro-Canada", Coordinates(43.71, -79.41), region="ON")])
        geocoder = StationGeocoder(searcher, FakeGazetteer({("Toronto", "ON"): toronto}))

        result = geocoder.locate("PETRO-CANADA #12", "Toronto", "ON")

        assert result.precision == "poi"

    def test_without_a_city_centre_and_without_a_match_nothing_is_found(self):
        assert locate(FakeSearcher([]), FakeGazetteer({})) is None

    def test_without_a_city_centre_a_validated_match_is_still_accepted(self):
        far_but_unchecked = place(coordinates=FAR_FROM_AUSTIN)

        result = locate(FakeSearcher([far_but_unchecked]), FakeGazetteer({}))

        assert result == LocatedPlace(FAR_FROM_AUSTIN, Station.LocationPrecision.POI)

    def test_without_a_city_centre_the_state_and_name_are_still_checked(self):
        searcher = FakeSearcher([place(region="OK"), place(name="Other")])

        assert locate(searcher, FakeGazetteer({})) is None

    def test_a_name_with_no_distinctive_words_is_not_searched_at_all(self):
        searcher = FakeSearcher([place()])

        result = locate(searcher, name="TRUCK STOP #4")

        assert result == CITY_CENTRE
        assert searcher.queries == []

    def test_a_name_made_only_of_the_city_is_not_searched_either(self):
        searcher = FakeSearcher([place()])

        result = locate(searcher, name="AUSTIN TRUCK STOP")

        assert result == CITY_CENTRE
        assert searcher.queries == []

    def test_search_errors_are_not_hidden(self):
        searcher = FakeSearcher(error=NominatimError("down"))

        with pytest.raises(NominatimError):
            locate(searcher)

    def test_identical_queries_are_only_sent_once(self):
        searcher = FakeSearcher([place()])
        geocoder = StationGeocoder(searcher, FakeGazetteer())

        first = geocoder.locate("PILOT TRAVEL CENTER #1", "Austin", "TX")
        second = geocoder.locate("PILOT TRAVEL CENTER #2", "Austin", "TX")

        assert first == second
        assert len(searcher.queries) == 1

    def test_empty_answers_are_remembered_too(self):
        searcher = FakeSearcher([])
        geocoder = StationGeocoder(searcher, FakeGazetteer())

        geocoder.locate("PILOT TRAVEL CENTER #1", "Austin", "TX")
        geocoder.locate("PILOT TRAVEL CENTER #2", "Austin", "TX")

        assert len(searcher.queries) == 1

    def test_failed_searches_are_not_remembered(self):
        searcher = FakeSearcher(error=NominatimError("down"))
        geocoder = StationGeocoder(searcher, FakeGazetteer())
        for _ in range(2):
            with pytest.raises(NominatimError):
                geocoder.locate("PILOT TRAVEL CENTER", "Austin", "TX")

        assert len(searcher.queries) == 2

    @pytest.mark.parametrize("distance", [0, -1])
    def test_the_distance_limit_must_be_positive(self, distance):
        with pytest.raises(ValueError, match="max_distance_miles"):
            StationGeocoder(FakeSearcher(), FakeGazetteer(), max_distance_miles=distance)
