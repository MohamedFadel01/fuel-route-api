import pytest

from apps.common.geo import Coordinates
from apps.stations.geocoding.nominatim import NominatimError
from apps.stations.geocoding.runner import RunSummary, TooManyFailuresError, geocode_stations
from apps.stations.geocoding.station_geocoder import LocatedPlace
from apps.stations.models import Station

pytestmark = pytest.mark.django_db

POI = Station.LocationPrecision.POI
CITY = Station.LocationPrecision.CITY


class FakeGeocoder:
    """Answers by station name: a LocatedPlace, None, or an exception to raise."""

    def __init__(self, answers):
        self.answers = answers
        self.calls = []

    def locate(self, name, city, state):
        self.calls.append((name, city, state))
        answer = self.answers[name]
        if isinstance(answer, BaseException):
            raise answer
        return answer


def placed(latitude, precision):
    return LocatedPlace(Coordinates(latitude, -97.0), precision)


class TestGeocodeStations:
    def test_saves_the_position_and_precision_of_each_station(self, make_station):
        exact = make_station(name="EXACT")
        centre = make_station(name="CENTRE")
        geocoder = FakeGeocoder({"EXACT": placed(30.1, POI), "CENTRE": placed(30.2, CITY)})

        geocode_stations([exact, centre], geocoder)

        exact.refresh_from_db()
        centre.refresh_from_db()
        assert (exact.latitude, exact.longitude, exact.location_precision) == (30.1, -97.0, "poi")
        assert (centre.latitude, centre.longitude, centre.location_precision) == (
            30.2,
            -97.0,
            "city",
        )

    def test_passes_the_name_city_and_state_to_the_geocoder(self, make_station):
        station = make_station(name="PILOT", city="Gila Bend", state="AZ")
        geocoder = FakeGeocoder({"PILOT": None})

        geocode_stations([station], geocoder)

        assert geocoder.calls == [("PILOT", "Gila Bend", "AZ")]

    def test_counts_every_outcome(self, make_station):
        stations = [make_station(name=name) for name in ("A", "B", "C", "D", "E")]
        geocoder = FakeGeocoder(
            {
                "A": placed(30.1, POI),
                "B": placed(30.2, POI),
                "C": placed(30.3, CITY),
                "D": None,
                "E": NominatimError("down"),
            }
        )

        summary = geocode_stations(stations, geocoder)

        assert summary == RunSummary(exact=2, city=1, unlocated=1, failed=1, interrupted=False)
        assert summary.processed == 5

    def test_unlocated_stations_are_left_untouched(self, make_station):
        station = make_station(name="LOST")

        geocode_stations([station], FakeGeocoder({"LOST": None}))

        station.refresh_from_db()
        assert (station.latitude, station.longitude, station.location_precision) == (None, None, "")

    def test_a_failed_station_is_left_untouched_and_the_rest_continue(self, make_station):
        broken = make_station(name="BROKEN")
        fine = make_station(name="FINE")
        geocoder = FakeGeocoder({"BROKEN": NominatimError("down"), "FINE": placed(30.1, POI)})

        summary = geocode_stations([broken, fine], geocoder)

        broken.refresh_from_db()
        fine.refresh_from_db()
        assert broken.location_precision == ""
        assert fine.location_precision == "poi"
        assert (summary.failed, summary.exact) == (1, 1)

    def test_reports_each_failure(self, make_station):
        station = make_station(name="BROKEN")
        error = NominatimError("down")
        reported = []

        geocode_stations(
            [station],
            FakeGeocoder({"BROKEN": error}),
            on_failure=lambda failed_station, failure: reported.append((failed_station, failure)),
        )

        assert reported == [(station, error)]

    def test_stops_after_too_many_failures_in_a_row(self, make_station):
        stations = [make_station(name=f"S{i}") for i in range(5)]
        answers = {"S0": placed(30.1, POI)} | {f"S{i}": NominatimError("down") for i in range(1, 5)}
        geocoder = FakeGeocoder(answers)

        with pytest.raises(TooManyFailuresError) as error:
            geocode_stations(stations, geocoder, max_consecutive_failures=3)

        assert error.value.summary == RunSummary(exact=1, city=0, unlocated=0, failed=3)
        assert len(geocoder.calls) == 4  # S4 was never tried
        stations[0].refresh_from_db()
        assert stations[0].location_precision == "poi"

    def test_a_success_resets_the_failure_streak(self, make_station):
        stations = [make_station(name=name) for name in "ABCDE"]
        down = NominatimError("down")
        geocoder = FakeGeocoder(
            {
                "A": down,
                "B": down,
                "C": placed(30.1, POI),
                "D": down,
                "E": down,
            }
        )

        summary = geocode_stations(stations, geocoder, max_consecutive_failures=3)

        assert summary.failed == 4

    def test_an_unlocated_station_also_resets_the_failure_streak(self, make_station):
        stations = [make_station(name=name) for name in "ABC"]
        down = NominatimError("down")
        geocoder = FakeGeocoder({"A": down, "B": None, "C": down})

        summary = geocode_stations(stations, geocoder, max_consecutive_failures=2)

        assert summary.failed == 2

    def test_ctrl_c_stops_cleanly_and_keeps_the_work_done_so_far(self, make_station):
        first = make_station(name="FIRST")
        second = make_station(name="SECOND")
        third = make_station(name="THIRD")
        geocoder = FakeGeocoder(
            {"FIRST": placed(30.1, POI), "SECOND": KeyboardInterrupt(), "THIRD": placed(30.3, POI)}
        )

        summary = geocode_stations([first, second, third], geocoder)

        assert summary.interrupted is True
        assert summary.exact == 1
        first.refresh_from_db()
        third.refresh_from_db()
        assert first.location_precision == "poi"
        assert third.location_precision == ""

    def test_reports_progress_every_n_stations(self, make_station):
        stations = [make_station(name=f"S{i}") for i in range(5)]
        geocoder = FakeGeocoder({f"S{i}": placed(30.0 + i / 100, CITY) for i in range(5)})
        snapshots = []

        geocode_stations(
            stations,
            geocoder,
            progress_every=2,
            on_progress=lambda s: snapshots.append(s.processed),
        )

        assert snapshots == [2, 4]

    def test_empty_input_gives_an_empty_summary(self):
        assert geocode_stations([], FakeGeocoder({})) == RunSummary()

    def test_accepts_any_iterable(self, make_station):
        station = make_station(name="A")

        summary = geocode_stations(iter([station]), FakeGeocoder({"A": placed(30.1, POI)}))

        assert summary.exact == 1

    @pytest.mark.parametrize("value", [0, -1])
    def test_settings_must_be_positive(self, value):
        with pytest.raises(ValueError, match="progress_every"):
            geocode_stations([], FakeGeocoder({}), progress_every=value)
        with pytest.raises(ValueError, match="max_consecutive_failures"):
            geocode_stations([], FakeGeocoder({}), max_consecutive_failures=value)
