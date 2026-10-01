import json
from io import StringIO

import pytest
import responses
from django.core.management import CommandError, call_command

from apps.stations.geocoding.nominatim import DEFAULT_BASE_URL, NominatimClient
from apps.stations.management.commands.geocode_stations import format_duration
from apps.stations.models import Station

pytestmark = pytest.mark.django_db

AUSTIN = (30.26715, -97.74306)  # the city centre stored by the geonames_dir fixture
USER_AGENT = "fuel-route-api-tests/1.0 (tests@example.com)"
GEONAMES_US = "https://download.geonames.org/export/dump/US.zip"


def hit(name="Pilot Travel Center", lat=30.30, lon=-97.70, state="US-TX"):
    return {
        "lat": str(lat),
        "lon": str(lon),
        "category": "amenity",
        "type": "fuel",
        "name": name,
        "display_name": f"{name}, Austin, Texas",
        "address": {"ISO3166-2-lvl4": state},
    }


@pytest.fixture(autouse=True)
def fast_polite_client(settings, geonames_dir):
    settings.NOMINATIM_USER_AGENT = USER_AGENT
    settings.NOMINATIM_MIN_INTERVAL = 0
    settings.NOMINATIM_BACKOFF_SECONDS = 0


def run(*args):
    out, err = StringIO(), StringIO()
    call_command("geocode_stations", *args, stdout=out, stderr=err)
    return out.getvalue(), err.getvalue()


def add_search(*results, **kwargs):
    responses.add(responses.GET, DEFAULT_BASE_URL, json=list(results), **kwargs)


def reload(station):
    station.refresh_from_db()
    return station


class TestGeocoding:
    @responses.activate
    def test_stores_an_exact_position_when_openstreetmap_has_the_station(self, make_station):
        station = make_station(name="PILOT TRAVEL CENTER #12", city="Austin", state="TX")
        add_search(hit())

        run()

        station = reload(station)
        assert (station.latitude, station.longitude) == (30.30, -97.70)
        assert station.location_precision == "poi"

    @responses.activate
    def test_falls_back_to_the_city_centre(self, make_station):
        station = make_station(name="PILOT TRAVEL CENTER #12", city="Austin", state="TX")
        add_search()

        run()

        station = reload(station)
        assert (station.latitude, station.longitude) == pytest.approx(AUSTIN)
        assert station.location_precision == "city"

    @responses.activate
    def test_leaves_stations_in_unknown_cities_without_a_position(self, make_station):
        station = make_station(name="PILOT TRAVEL CENTER", city="Nowhere", state="TX")
        add_search()

        out, _ = run()

        assert reload(station).location_precision == ""
        assert "1 unlocated" in out

    @responses.activate
    def test_prints_a_summary(self, make_station):
        make_station(name="PILOT TRAVEL CENTER", city="Austin", state="TX")
        make_station(name="LOVES TRAVEL STOP", city="Austin", state="TX")
        make_station(name="GHOST STOP", city="Nowhere", state="TX")
        add_search()

        out, err = run()

        assert "3 stations processed: 0 exact, 2 city, 1 unlocated, 0 failed" in out
        assert err == ""

    @responses.activate
    def test_sends_the_configured_user_agent(self, make_station):
        make_station(name="PILOT TRAVEL CENTER", city="Austin", state="TX")
        add_search()

        run()

        assert responses.calls[0].request.headers["User-Agent"] == USER_AGENT

    @responses.activate
    def test_stations_with_the_same_query_are_searched_once(self, make_station):
        make_station(name="PILOT TRAVEL CENTER #1", city="Austin", state="TX")
        make_station(name="PILOT TRAVEL CENTER #2", city="Austin", state="TX")
        add_search(hit())

        run()

        assert len(responses.calls) == 1
        # Both stations got the one place that was found, so neither is "exact".
        assert Station.objects.filter(location_precision="city").count() == 2


class TestSharedPositions:
    @responses.activate
    def test_stations_given_the_same_place_are_labelled_approximate(self, make_station):
        first = make_station(name="PILOT TRAVEL CENTER #1", opis_id=1, city="Austin", state="TX")
        second = make_station(name="PILOT TRAVEL CENTER #2", opis_id=2, city="Austin", state="TX")
        add_search(hit(lat=30.30, lon=-97.70))

        out, _ = run()

        for station in (first, second):
            station = reload(station)
            assert (station.latitude, station.longitude) == (30.30, -97.70)
            assert station.location_precision == "city"
        assert "Relabelled as approximate: 2" in out

    @responses.activate
    def test_stations_with_their_own_place_stay_exact(self, make_station):
        pilot = make_station(name="PILOT TRAVEL CENTER #1", opis_id=1, city="Austin", state="TX")
        loves = make_station(name="LOVES TRAVEL STOP #2", opis_id=2, city="Austin", state="TX")

        def answer(request):
            if "pilot" in request.params["q"].lower():
                found = hit(name="Pilot Travel Center", lat=30.30, lon=-97.70)
            else:
                found = hit(name="Love's Travel Stop", lat=30.40, lon=-97.80)
            return (200, {}, json.dumps([found]))

        responses.add_callback(responses.GET, DEFAULT_BASE_URL, callback=answer)

        out, _ = run()

        assert reload(pilot).location_precision == "poi"
        assert reload(loves).location_precision == "poi"
        assert "Relabelled" not in out

    @responses.activate
    def test_a_station_found_in_an_earlier_run_is_included(self, make_station):
        earlier = make_station(
            name="PILOT TRAVEL CENTER #1",
            opis_id=1,
            city="Austin",
            state="TX",
            latitude=30.30,
            longitude=-97.70,
            location_precision="poi",
        )
        later = make_station(name="PILOT TRAVEL CENTER #2", opis_id=2, city="Austin", state="TX")
        add_search(hit(lat=30.30, lon=-97.70))

        run()

        assert reload(earlier).location_precision == "city"
        assert reload(later).location_precision == "city"

    @responses.activate
    def test_stations_are_relabelled_even_when_the_run_aborts(self, make_station):
        for opis_id in (1, 2):
            make_station(
                opis_id=opis_id,
                city="Austin",
                state="TX",
                latitude=30.30,
                longitude=-97.70,
                location_precision="poi",
            )
        for i in range(5):
            make_station(name=f"PILOT {i}", opis_id=i + 10, city="Austin", state="TX")
        responses.add(responses.GET, DEFAULT_BASE_URL, json={}, status=403)

        with pytest.raises(CommandError, match="consecutive"):
            run("--max-failures", "2")

        assert Station.objects.filter(location_precision="poi").count() == 0

    @responses.activate
    def test_city_only_mode_also_relabels(self, make_station):
        for opis_id in (1, 2):
            make_station(
                opis_id=opis_id,
                city="Austin",
                state="TX",
                latitude=30.30,
                longitude=-97.70,
                location_precision="poi",
            )

        run("--city-only")

        assert Station.objects.filter(location_precision="poi").count() == 0


class TestWhichStationsAreProcessed:
    @responses.activate
    def test_stations_that_already_have_a_position_are_skipped(self, make_station):
        make_station(
            name="PILOT", latitude=1.0, longitude=2.0, location_precision="poi", city="Austin"
        )
        make_station(
            name="LOVES", latitude=3.0, longitude=4.0, location_precision="city", city="Austin"
        )

        out, _ = run()

        assert len(responses.calls) == 0
        assert "0 stations processed" in out

    @responses.activate
    def test_redo_city_retries_stations_that_only_have_a_city_position(self, make_station):
        station = make_station(
            name="PILOT TRAVEL CENTER",
            city="Austin",
            state="TX",
            latitude=30.0,
            longitude=-97.0,
            location_precision="city",
        )
        exact = make_station(
            name="LOVES TRAVEL STOP",
            city="Austin",
            state="TX",
            latitude=1.0,
            longitude=2.0,
            location_precision="poi",
        )
        add_search(hit())

        run("--redo-city")

        station = reload(station)
        assert (station.latitude, station.location_precision) == (30.30, "poi")
        assert (reload(exact).latitude, reload(exact).location_precision) == (1.0, "poi")

    @responses.activate
    def test_limit_caps_how_many_stations_are_processed(self, make_station):
        stations = [make_station(name=f"PILOT {i}", city="Austin", state="TX") for i in range(4)]
        add_search()

        out, _ = run("--limit", "2")

        assert "2 stations processed" in out
        assert [reload(s).location_precision for s in stations] == ["city", "city", "", ""]

    @responses.activate
    def test_stations_are_processed_in_id_order(self, make_station):
        make_station(name="SECOND", opis_id=99, city="Austin", state="TX")
        make_station(name="FIRST", opis_id=1, city="Austin", state="TX")
        add_search()

        run()

        queries = [call.request.params["q"] for call in responses.calls]
        assert queries == ["SECOND, Austin, TX", "FIRST, Austin, TX"]

    @pytest.mark.parametrize("value", ["0", "-3", "many"])
    def test_limit_must_be_a_positive_number(self, value):
        with pytest.raises(CommandError, match="limit"):
            run("--limit", value)


class TestCityOnlyMode:
    @responses.activate
    def test_never_contacts_openstreetmap(self, make_station):
        station = make_station(name="PILOT TRAVEL CENTER", city="Austin", state="TX")

        out, _ = run("--city-only")

        assert len(responses.calls) == 0
        assert reload(station).location_precision == "city"
        assert "1 city" in out

    def test_cannot_be_combined_with_redo_city(self):
        with pytest.raises(CommandError, match="redo-city"):
            run("--city-only", "--redo-city")


class TestFailures:
    @responses.activate
    def test_a_station_that_cannot_be_searched_is_left_for_the_next_run(self, make_station):
        broken = make_station(name="BROKEN STOP", opis_id=1, city="Austin", state="TX")
        fine = make_station(name="FINE STOP", opis_id=2, city="Austin", state="TX")

        def answer(request):
            if "BROKEN" in request.params["q"]:
                return (403, {}, "{}")
            return (200, {}, "[]")

        responses.add_callback(responses.GET, DEFAULT_BASE_URL, callback=answer)

        out, err = run()

        assert reload(broken).location_precision == ""
        assert reload(fine).location_precision == "city"
        assert "BROKEN STOP" in err
        assert "1 failed" in out

    @responses.activate
    def test_aborts_after_too_many_consecutive_failures(self, make_station):
        for i in range(5):
            make_station(name=f"PILOT {i}", opis_id=i + 1, city="Austin", state="TX")
        responses.add(responses.GET, DEFAULT_BASE_URL, json={}, status=403)

        with pytest.raises(CommandError, match="consecutive"):
            run("--max-failures", "2")

        assert Station.objects.filter(location_precision="").count() == 5

    @responses.activate
    def test_ctrl_c_keeps_the_progress_and_explains_how_to_resume(self, make_station, monkeypatch):
        first = make_station(name="FIRST STOP", opis_id=1, city="Austin", state="TX")
        second = make_station(name="SECOND STOP", opis_id=2, city="Austin", state="TX")
        calls = []

        def search(self, query, limit=5):
            calls.append(query)
            if len(calls) == 2:
                raise KeyboardInterrupt
            return []

        monkeypatch.setattr(NominatimClient, "search", search)

        out, _ = run()

        assert reload(first).location_precision == "city"
        assert reload(second).location_precision == ""
        assert "Interrupted" in out
        assert "run the command again" in out

    @responses.activate
    def test_missing_geonames_files_that_cannot_be_downloaded_are_a_clear_error(
        self, tmp_path, settings
    ):
        settings.GEONAMES_DIR = tmp_path / "empty"
        responses.add(responses.GET, GEONAMES_US, status=404)

        with pytest.raises(CommandError, match="404"):
            run()


class TestProgress:
    @responses.activate
    def test_prints_progress_lines(self, make_station):
        for i in range(3):
            make_station(name=f"PILOT {i}", opis_id=i + 1, city="Austin", state="TX")
        add_search()

        out, _ = run("--progress-every", "2")

        progress = [line for line in out.splitlines() if "/3" in line]
        assert len(progress) == 1
        assert progress[0].startswith("2/3 processed")


class TestFormatDuration:
    @pytest.mark.parametrize(
        ("seconds", "expected"),
        [
            (0, "less than a second"),
            (0.4, "less than a second"),
            (1, "1 second"),
            (20, "20 seconds"),
            (89, "89 seconds"),
            (90, "2 minutes"),
            (120, "2 minutes"),
            (3000, "50 minutes"),
            (5399, "90 minutes"),
            (5400, "1.5 hours"),
            (7200, "2.0 hours"),
            (6738, "1.9 hours"),
        ],
    )
    def test_uses_the_most_readable_unit(self, seconds, expected):
        assert format_duration(seconds) == expected
