from urllib.parse import parse_qs, urlparse

import pytest
import requests
import responses

from apps.common.geo import Coordinates
from apps.stations.geocoding.nominatim import (
    DEFAULT_BASE_URL,
    NominatimClient,
    NominatimError,
    PlaceMatch,
)

USER_AGENT = "fuel-route-api-tests/1.0 (tests@example.com)"

PILOT = {
    "lat": "32.9303784",
    "lon": "-112.6731472",
    "category": "highway",
    "type": "services",
    "name": "Pilot Travel Center",
    "display_name": "Pilot Travel Center, South Butterfield Trail, Gila Bend, Arizona, USA",
    "address": {"state": "Arizona", "ISO3166-2-lvl4": "US-AZ", "country_code": "us"},
}


class FakeTime:
    """A clock that only moves when the client 'sleeps'."""

    def __init__(self):
        self.now = 1000.0
        self.sleeps = []

    def clock(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


@pytest.fixture
def fake_time():
    return FakeTime()


@pytest.fixture
def client(fake_time):
    return NominatimClient(
        user_agent=USER_AGENT,
        min_interval=1.0,
        backoff_seconds=5.0,
        sleep=fake_time.sleep,
        clock=fake_time.clock,
    )


def add_response(payload=None, **kwargs):
    kwargs.setdefault("status", 200)
    responses.add(
        responses.GET, DEFAULT_BASE_URL, json=[PILOT] if payload is None else payload, **kwargs
    )


class TestRequest:
    @responses.activate
    def test_sends_the_query_with_the_expected_parameters(self, client):
        add_response()

        client.search("Pilot, Gila Bend, AZ", limit=3)

        query = parse_qs(urlparse(responses.calls[0].request.url).query)
        assert query == {
            "q": ["Pilot, Gila Bend, AZ"],
            "format": ["jsonv2"],
            "limit": ["3"],
            "addressdetails": ["1"],
            "countrycodes": ["us,ca"],
        }

    @responses.activate
    def test_identifies_itself_with_the_user_agent(self, client):
        add_response()

        client.search("Pilot")

        assert responses.calls[0].request.headers["User-Agent"] == USER_AGENT

    @responses.activate
    def test_uses_a_timeout(self, client):
        add_response()

        client.search("Pilot")

        assert responses.calls[0].request.req_kwargs["timeout"] == 20.0

    @pytest.mark.parametrize("query", ["", "   "])
    @responses.activate
    def test_a_blank_query_is_rejected_without_a_request(self, client, query):
        with pytest.raises(ValueError, match="query"):
            client.search(query)

        assert len(responses.calls) == 0

    @pytest.mark.parametrize("limit", [0, -1, 41])
    def test_limit_must_be_between_1_and_40(self, client, limit):
        with pytest.raises(ValueError, match="limit"):
            client.search("Pilot", limit=limit)


class TestConfiguration:
    @pytest.mark.parametrize("user_agent", ["", "   "])
    def test_a_user_agent_is_required(self, user_agent):
        with pytest.raises(ValueError, match="user_agent"):
            NominatimClient(user_agent=user_agent)

    def test_negative_values_are_rejected(self):
        with pytest.raises(ValueError, match="min_interval"):
            NominatimClient(user_agent=USER_AGENT, min_interval=-1)
        with pytest.raises(ValueError, match="max_retries"):
            NominatimClient(user_agent=USER_AGENT, max_retries=-1)

    @responses.activate
    def test_a_custom_url_is_used(self):
        responses.add(responses.GET, "http://localhost:8080/search", json=[])
        client = NominatimClient(user_agent=USER_AGENT, base_url="http://localhost:8080/search")

        assert client.search("Pilot") == []


class TestParsing:
    @responses.activate
    def test_turns_results_into_place_matches(self, client):
        add_response()

        (match,) = client.search("Pilot")

        assert match == PlaceMatch(
            name="Pilot Travel Center",
            coordinates=Coordinates(32.9303784, -112.6731472),
            region="AZ",
            category="highway",
            kind="services",
        )

    @responses.activate
    def test_keeps_the_order_of_the_results(self, client):
        add_response([{**PILOT, "name": "First"}, {**PILOT, "name": "Second"}])

        assert [m.name for m in client.search("Pilot")] == ["First", "Second"]

    @responses.activate
    def test_no_results_gives_an_empty_list(self, client):
        add_response([])

        assert client.search("Nothing here") == []

    @responses.activate
    def test_the_name_falls_back_to_the_first_part_of_the_display_name(self, client):
        item = {**PILOT}
        del item["name"]
        add_response([item, {**PILOT, "name": ""}])

        names = [m.name for m in client.search("Pilot")]

        assert names == ["Pilot Travel Center", "Pilot Travel Center"]

    @responses.activate
    def test_canadian_provinces_are_read_from_the_iso_code(self, client):
        item = {**PILOT, "address": {"ISO3166-2-lvl4": "CA-ON", "country_code": "ca"}}
        add_response([item])

        assert client.search("Tim Hortons")[0].region == "ON"

    @pytest.mark.parametrize(
        "address",
        [{}, {"state": "Arizona"}, {"ISO3166-2-lvl4": "AZ"}, {"ISO3166-2-lvl4": ""}],
        ids=["no-address", "no-iso-code", "no-dash", "empty"],
    )
    @responses.activate
    def test_the_region_is_empty_when_it_cannot_be_determined(self, client, address):
        add_response([{**PILOT, "address": address}])

        assert client.search("Pilot")[0].region == ""

    @responses.activate
    def test_a_missing_address_block_is_tolerated(self, client):
        item = {**PILOT}
        del item["address"]
        add_response([item])

        assert client.search("Pilot")[0].region == ""

    @pytest.mark.parametrize(
        "broken",
        [
            {"lon": "-112.0"},
            {"lat": "32.0"},
            {"lat": "north", "lon": "-112.0"},
            {"lat": "95.0", "lon": "-112.0"},
            {"lat": "32.0", "lon": "nan"},
            "not-a-dict",
            None,
        ],
        ids=["no-lat", "no-lon", "bad-lat", "lat-range", "nan-lon", "string", "null"],
    )
    @responses.activate
    def test_malformed_results_are_skipped(self, client, broken):
        base = {k: v for k, v in PILOT.items() if k not in ("lat", "lon")}
        item = broken if not isinstance(broken, dict) else {**base, **broken}
        add_response([item, {**PILOT, "name": "Good"}])

        assert [m.name for m in client.search("Pilot")] == ["Good"]


class TestRateLimit:
    @responses.activate
    def test_the_first_request_does_not_wait(self, client, fake_time):
        add_response()

        client.search("one")

        assert fake_time.sleeps == []

    @responses.activate
    def test_back_to_back_requests_are_a_second_apart(self, client, fake_time):
        add_response()

        client.search("one")
        client.search("two")

        assert fake_time.sleeps == [1.0]

    @responses.activate
    def test_only_the_missing_part_of_the_interval_is_waited(self, client, fake_time):
        add_response()
        client.search("one")
        fake_time.now += 0.4

        client.search("two")

        assert fake_time.sleeps == [pytest.approx(0.6)]

    @responses.activate
    def test_no_wait_when_enough_time_has_passed(self, client, fake_time):
        add_response()
        client.search("one")
        fake_time.now += 5

        client.search("two")

        assert fake_time.sleeps == []

    @responses.activate
    def test_an_interval_of_zero_disables_waiting(self, fake_time):
        add_response()
        client = NominatimClient(
            user_agent=USER_AGENT, min_interval=0, sleep=fake_time.sleep, clock=fake_time.clock
        )

        client.search("one")
        client.search("two")

        assert fake_time.sleeps == []


class TestRetries:
    @pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
    @responses.activate
    def test_throttling_and_server_errors_are_retried(self, client, fake_time, status):
        add_response(payload={}, status=status)
        add_response()

        matches = client.search("Pilot")

        assert len(matches) == 1
        assert len(responses.calls) == 2
        assert fake_time.sleeps == [5.0]

    @responses.activate
    def test_the_wait_grows_with_every_retry(self, client, fake_time):
        add_response(payload={}, status=503)
        add_response(payload={}, status=503)
        add_response()

        client.search("Pilot")

        assert fake_time.sleeps == [5.0, 10.0]

    @responses.activate
    def test_gives_up_after_the_maximum_number_of_retries(self, client):
        for _ in range(3):
            add_response(payload={}, status=503)

        with pytest.raises(NominatimError, match="503"):
            client.search("Pilot")

        assert len(responses.calls) == 3

    @responses.activate
    def test_obeys_the_retry_after_header(self, client, fake_time):
        add_response(payload={}, status=429, headers={"Retry-After": "7"})
        add_response()

        client.search("Pilot")

        assert fake_time.sleeps == [7.0]

    @pytest.mark.parametrize(
        ("header", "expected"),
        [("3600", 60.0), ("-5", 5.0), ("soon", 5.0), ("Wed, 21 Oct 2026 07:28:00 GMT", 5.0)],
    )
    @responses.activate
    def test_unreasonable_retry_after_values_are_capped_or_ignored(
        self, client, fake_time, header, expected
    ):
        add_response(payload={}, status=429, headers={"Retry-After": header})
        add_response()

        client.search("Pilot")

        assert fake_time.sleeps == [expected]

    @pytest.mark.parametrize("error", [requests.ConnectionError("down"), requests.Timeout("slow")])
    @responses.activate
    def test_network_errors_are_retried(self, client, fake_time, error):
        responses.add(responses.GET, DEFAULT_BASE_URL, body=error)
        add_response()

        assert len(client.search("Pilot")) == 1
        assert fake_time.sleeps == [5.0]

    @responses.activate
    def test_persistent_network_errors_become_a_nominatim_error(self, client):
        for _ in range(3):
            responses.add(responses.GET, DEFAULT_BASE_URL, body=requests.ConnectionError("down"))

        with pytest.raises(NominatimError, match="down"):
            client.search("Pilot")

    @pytest.mark.parametrize("status", [400, 401, 403, 404])
    @responses.activate
    def test_other_client_errors_are_not_retried(self, client, fake_time, status):
        add_response(payload={}, status=status)

        with pytest.raises(NominatimError, match=str(status)):
            client.search("Pilot")

        assert len(responses.calls) == 1
        assert fake_time.sleeps == []

    @responses.activate
    def test_zero_retries_means_a_single_attempt(self, fake_time):
        add_response(payload={}, status=503)
        client = NominatimClient(
            user_agent=USER_AGENT, max_retries=0, sleep=fake_time.sleep, clock=fake_time.clock
        )

        with pytest.raises(NominatimError):
            client.search("Pilot")

        assert len(responses.calls) == 1


class TestBadResponses:
    @responses.activate
    def test_invalid_json_is_an_error(self, client):
        responses.add(responses.GET, DEFAULT_BASE_URL, body="<html>oops</html>")

        with pytest.raises(NominatimError, match="JSON"):
            client.search("Pilot")

        assert len(responses.calls) == 1

    @responses.activate
    def test_a_json_object_instead_of_a_list_is_an_error(self, client):
        add_response({"error": {"message": "bad"}})

        with pytest.raises(NominatimError, match="unexpected"):
            client.search("Pilot")
