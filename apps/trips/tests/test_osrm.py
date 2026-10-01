"""Tests for the OSRM routing client.

No test touches the network: ``responses`` stands in for the server. The sample answers
are modelled on what the public server really returns (checked by hand): a successful
route is ``{"code": "Ok", "routes": [...]}``; an impossible route is HTTP 400 with
``{"code": "NoRoute"}``; and a bad request is HTTP 400 with ``{"code": "InvalidValue"}``.
"""

import copy
import math
import pickle
from urllib.parse import parse_qs, urlparse

import pytest
import requests
import responses

from apps.common.geo import Coordinates
from apps.trips.providers.base import (
    NoRouteFoundError,
    ProviderRoute,
    RoutingError,
    RoutingServiceError,
    RoutingTimeoutError,
)
from apps.trips.providers.osrm import DEFAULT_BASE_URL, METERS_PER_MILE, OsrmClient

USER_AGENT = "fuel-route-api-tests/1.0 (tests@example.com)"
AUSTIN = Coordinates(30.2672, -97.7431)
DALLAS = Coordinates(32.7767, -96.7970)
ROUTE_URL = f"{DEFAULT_BASE_URL}/route/v1/driving/-97.743100,30.267200;-96.797000,32.776700"

# The first points of a real Austin -> Dallas answer, with the real distance and duration.
GOOD_ROUTE = {
    "distance": 313948.1,
    "duration": 12467.7,
    "geometry": {
        "type": "LineString",
        "coordinates": [
            [-97.74313, 30.267208],
            [-97.743127, 30.267215],
            [-97.743038, 30.267454],
            [-97.742979, 30.267611],
        ],
    },
    "legs": [{"steps": [], "summary": "", "weight": 12467.7}],
    "weight_name": "routability",
    "weight": 12467.7,
}
GOOD_ANSWER = {
    "code": "Ok",
    "routes": [GOOD_ROUTE],
    "waypoints": [{"name": "Congress Avenue", "location": [-97.74313, 30.267208]}],
}


@pytest.fixture
def client():
    return OsrmClient(user_agent=USER_AGENT)


def answer(body=GOOD_ANSWER, *, status=200, url=ROUTE_URL):
    responses.add(responses.GET, url, json=body, status=status)


def with_route(**changes):
    """The good answer with some fields of its first route changed."""
    route = copy.deepcopy(GOOD_ROUTE)
    route.update(changes)
    return {"code": "Ok", "routes": [route]}


class TestTheRequest:
    @responses.activate
    def test_exactly_one_request_is_made(self, client):
        answer()

        client.route(AUSTIN, DALLAS)

        assert len(responses.calls) == 1

    @responses.activate
    def test_the_path_has_longitude_first_and_both_places(self, client):
        answer()

        client.route(AUSTIN, DALLAS)

        # (not urlparse().path: it treats the ";" as the start of path parameters)
        url_without_query = responses.calls[0].request.url.split("?")[0]
        assert url_without_query == ROUTE_URL

    @responses.activate
    def test_it_asks_for_the_full_geometry_as_geojson_and_nothing_else(self, client):
        answer()

        client.route(AUSTIN, DALLAS)

        query = parse_qs(urlparse(responses.calls[0].request.url).query)
        assert query == {
            "overview": ["full"],
            "geometries": ["geojson"],
            "steps": ["false"],
            "alternatives": ["false"],
        }

    @responses.activate
    def test_it_identifies_itself_with_the_given_user_agent(self, client):
        answer()

        client.route(AUSTIN, DALLAS)

        assert responses.calls[0].request.headers["User-Agent"] == USER_AGENT

    @responses.activate
    def test_the_request_has_a_timeout(self):
        answer()

        OsrmClient(user_agent=USER_AGENT, timeout=7.5).route(AUSTIN, DALLAS)

        assert responses.calls[0].request.req_kwargs["timeout"] == 7.5

    @responses.activate
    def test_the_default_timeout_is_ten_seconds(self, client):
        answer()

        client.route(AUSTIN, DALLAS)

        assert responses.calls[0].request.req_kwargs["timeout"] == 10.0

    @responses.activate
    @pytest.mark.parametrize("base", ["http://osrm.local:5000", "http://osrm.local:5000/"])
    def test_a_different_server_can_be_used_with_or_without_a_trailing_slash(self, base):
        url = "http://osrm.local:5000/route/v1/driving/-97.743100,30.267200;-96.797000,32.776700"
        answer(url=url)

        OsrmClient(base_url=base, user_agent=USER_AGENT).route(AUSTIN, DALLAS)

        assert len(responses.calls) == 1

    @responses.activate
    def test_coordinates_are_sent_to_six_decimals_whatever_their_size(self, client):
        url = f"{DEFAULT_BASE_URL}/route/v1/driving/0.000001,-0.000000;-179.999999,89.500000"
        answer(url=url)

        client.route(Coordinates(-0.0, 0.000001), Coordinates(89.5, -179.999999))

        assert len(responses.calls) == 1

    @responses.activate
    def test_the_client_can_be_used_again_for_another_route(self, client):
        answer()
        answer(url=f"{DEFAULT_BASE_URL}/route/v1/driving/-96.797000,32.776700;-97.743100,30.267200")

        client.route(AUSTIN, DALLAS)
        client.route(DALLAS, AUSTIN)

        assert len(responses.calls) == 2


class TestAGoodAnswer:
    @responses.activate
    def test_the_route_is_returned_with_miles_seconds_and_points(self, client):
        answer()

        route = client.route(AUSTIN, DALLAS)

        assert isinstance(route, ProviderRoute)
        assert route.distance_miles == pytest.approx(313948.1 / 1609.344)
        assert route.duration_seconds == 12467.7
        assert route.coordinates == (
            Coordinates(30.267208, -97.74313),
            Coordinates(30.267215, -97.743127),
            Coordinates(30.267454, -97.743038),
            Coordinates(30.267611, -97.742979),
        )

    def test_a_mile_is_1609_point_344_meters(self):
        assert METERS_PER_MILE == 1609.344

    @responses.activate
    def test_the_points_are_in_latitude_longitude_order_not_geojson_order(self, client):
        answer()

        first = client.route(AUSTIN, DALLAS).coordinates[0]

        assert (first.latitude, first.longitude) == (30.267208, -97.74313)

    @responses.activate
    def test_extra_fields_are_ignored(self, client):
        body = {**GOOD_ANSWER, "something_new": {"a": 1}}
        body["routes"] = [{**GOOD_ROUTE, "also_new": [1, 2, 3]}]
        answer(body)

        assert client.route(AUSTIN, DALLAS).duration_seconds == 12467.7

    @responses.activate
    def test_only_the_first_route_is_used_when_there_are_several(self, client):
        second = copy.deepcopy(GOOD_ROUTE)
        second["distance"] = 1.0
        answer({"code": "Ok", "routes": [GOOD_ROUTE, second]})

        assert client.route(AUSTIN, DALLAS).distance_miles == pytest.approx(313948.1 / 1609.344)

    @responses.activate
    def test_a_trip_from_a_place_to_itself_is_a_route_of_zero_miles(self, client):
        # The real server answers exactly this way: distance 0 and the point twice.
        body = with_route(
            distance=0,
            duration=0,
            geometry={"type": "LineString", "coordinates": [[-97.74313, 30.267208]] * 2},
        )
        answer(
            body,
            url=f"{DEFAULT_BASE_URL}/route/v1/driving/-97.743100,30.267200;-97.743100,30.267200",
        )

        route = client.route(AUSTIN, AUSTIN)

        assert route.distance_miles == 0.0
        assert route.duration_seconds == 0.0
        assert len(route.coordinates) == 2

    @responses.activate
    def test_integer_numbers_are_accepted(self, client):
        answer(with_route(distance=1609, duration=60))

        route = client.route(AUSTIN, DALLAS)

        assert route.distance_miles == pytest.approx(1609 / 1609.344)
        assert isinstance(route.duration_seconds, float)

    @responses.activate
    def test_a_third_value_such_as_altitude_in_a_point_is_ignored(self, client):
        geometry = {
            "type": "LineString",
            "coordinates": [[-97.7, 30.2, 150.0], [-97.6, 30.3, 160.0]],
        }
        answer(with_route(geometry=geometry))

        route = client.route(AUSTIN, DALLAS)

        assert route.coordinates == (Coordinates(30.2, -97.7), Coordinates(30.3, -97.6))

    @responses.activate
    def test_the_result_cannot_be_changed(self, client):
        answer()

        route = client.route(AUSTIN, DALLAS)

        assert isinstance(route.coordinates, tuple)
        with pytest.raises(AttributeError):
            route.distance_miles = 1.0  # type: ignore[misc]


class TestNoRoute:
    @responses.activate
    @pytest.mark.parametrize("code", ["NoRoute", "NoSegment"])
    def test_a_400_saying_no_route_is_a_no_route_error(self, client, code):
        message = "Impossible route between points"
        answer({"code": code, "message": message}, status=400)

        with pytest.raises(NoRouteFoundError) as problem:
            client.route(AUSTIN, DALLAS)

        assert message in str(problem.value)

    @responses.activate
    def test_a_200_saying_no_route_is_also_a_no_route_error(self, client):
        # Some OSRM versions answer 200 with the error code in the body.
        answer({"code": "NoRoute", "message": "Impossible route between points"})

        with pytest.raises(NoRouteFoundError):
            client.route(AUSTIN, DALLAS)

    @responses.activate
    def test_a_missing_message_still_gives_a_readable_error(self, client):
        answer({"code": "NoRoute"}, status=400)

        with pytest.raises(NoRouteFoundError, match="No driving route"):
            client.route(AUSTIN, DALLAS)

    @responses.activate
    def test_no_route_is_not_retried(self, client):
        answer({"code": "NoRoute"}, status=400)

        with pytest.raises(NoRouteFoundError):
            client.route(AUSTIN, DALLAS)

        assert len(responses.calls) == 1


class TestTheServiceFailing:
    @responses.activate
    @pytest.mark.parametrize("status", [500, 502, 503, 504])
    def test_server_errors_are_service_errors_naming_the_status(self, client, status):
        answer({"message": "oops"}, status=status)

        with pytest.raises(RoutingServiceError, match=str(status)):
            client.route(AUSTIN, DALLAS)

    @responses.activate
    def test_a_server_error_with_an_html_body_is_still_a_service_error(self, client):
        responses.add(responses.GET, ROUTE_URL, body="<html>Bad gateway</html>", status=502)

        with pytest.raises(RoutingServiceError, match="502"):
            client.route(AUSTIN, DALLAS)

    @responses.activate
    @pytest.mark.parametrize("status", [403, 404, 429])
    def test_blocked_missing_and_busy_are_service_errors(self, client, status):
        responses.add(responses.GET, ROUTE_URL, body="no", status=status)

        with pytest.raises(RoutingServiceError, match=str(status)):
            client.route(AUSTIN, DALLAS)

    @responses.activate
    @pytest.mark.parametrize(
        "code", ["InvalidValue", "InvalidQuery", "InvalidUrl", "InvalidService", "TooBig"]
    )
    def test_a_request_the_server_rejects_is_a_service_error_with_its_message(self, client, code):
        answer({"code": code, "message": "Invalid coordinate value."}, status=400)

        with pytest.raises(RoutingServiceError, match="Invalid coordinate value") as problem:
            client.route(AUSTIN, DALLAS)

        assert not isinstance(problem.value, NoRouteFoundError)

    @responses.activate
    @pytest.mark.parametrize(
        ("status", "code", "error"),
        [(400, "InvalidValue", RoutingServiceError), (400, "NoRoute", NoRouteFoundError)],
    )
    def test_a_huge_message_from_the_server_is_cut_short(self, client, status, code, error):
        answer({"code": code, "message": "x" * 5000}, status=status)

        with pytest.raises(error) as problem:
            client.route(AUSTIN, DALLAS)

        assert 100 < len(str(problem.value)) < 400  # the server's words, shortened

    @responses.activate
    def test_an_unknown_error_code_is_a_service_error(self, client):
        answer({"code": "Surprise", "message": "Something new"}, status=200)

        with pytest.raises(RoutingServiceError, match="Surprise"):
            client.route(AUSTIN, DALLAS)

    @responses.activate
    @pytest.mark.parametrize("status", [429, 500, 503])
    def test_failures_are_not_retried(self, client, status):
        answer({"message": "busy"}, status=status)

        with pytest.raises(RoutingServiceError):
            client.route(AUSTIN, DALLAS)

        assert len(responses.calls) == 1

    @responses.activate
    @pytest.mark.parametrize("error", [requests.ConnectTimeout, requests.ReadTimeout])
    def test_a_timeout_is_a_timeout_error(self, client, error):
        responses.add(responses.GET, ROUTE_URL, body=error("too slow"))

        with pytest.raises(RoutingTimeoutError, match="10"):
            client.route(AUSTIN, DALLAS)

    @responses.activate
    def test_a_timeout_is_not_retried(self, client):
        responses.add(responses.GET, ROUTE_URL, body=requests.ReadTimeout("too slow"))

        with pytest.raises(RoutingTimeoutError):
            client.route(AUSTIN, DALLAS)

        assert len(responses.calls) == 1

    @responses.activate
    @pytest.mark.parametrize(
        "error",
        [requests.ConnectionError, requests.TooManyRedirects, requests.exceptions.SSLError],
    )
    def test_other_network_problems_are_service_errors(self, client, error):
        responses.add(responses.GET, ROUTE_URL, body=error("nope"))

        with pytest.raises(RoutingServiceError) as problem:
            client.route(AUSTIN, DALLAS)

        assert not isinstance(problem.value, RoutingTimeoutError)

    @responses.activate
    def test_the_message_is_short_and_does_not_leak_the_address_or_internals(self, client):
        # What ``requests`` says in such a case runs to several lines with the full address.
        cause = requests.ConnectionError(
            "HTTPSConnectionPool(host='router.project-osrm.org', port=443): Max retries "
            "exceeded with url: /route/v1/driving/-97.7,30.2;-96.7,32.7 (Caused by "
            "NewConnectionError('Failed to establish a new connection'))"
        )
        responses.add(responses.GET, ROUTE_URL, body=cause)

        with pytest.raises(RoutingServiceError) as problem:
            client.route(AUSTIN, DALLAS)

        message = str(problem.value)
        assert message == "Could not reach the routing service (ConnectionError)."
        assert "router.project-osrm.org" not in message
        assert "-97.7" not in message
        assert problem.value.__cause__ is cause  # the details stay available for the logs

    @responses.activate
    def test_an_unregistered_url_never_reaches_the_real_network(self, client):
        # With nothing registered, ``responses`` refuses the call instead of going out.
        with pytest.raises(RoutingServiceError):
            client.route(AUSTIN, DALLAS)


class TestAnAnswerThatMakesNoSense:
    @responses.activate
    def test_a_body_that_is_not_json(self, client):
        responses.add(responses.GET, ROUTE_URL, body="<html>hello</html>", status=200)

        with pytest.raises(RoutingServiceError, match="not valid JSON"):
            client.route(AUSTIN, DALLAS)

    @responses.activate
    @pytest.mark.parametrize("body", [[], "text", 5, [GOOD_ANSWER]])
    def test_json_that_is_not_an_object(self, client, body):
        answer(body)

        with pytest.raises(RoutingServiceError, match="unexpected"):
            client.route(AUSTIN, DALLAS)

    @responses.activate
    def test_json_null(self, client):
        responses.add(responses.GET, ROUTE_URL, body="null", status=200)

        with pytest.raises(RoutingServiceError, match="unexpected"):
            client.route(AUSTIN, DALLAS)

    @responses.activate
    @pytest.mark.parametrize(
        "body",
        [
            {},
            {"routes": [GOOD_ROUTE]},
            {"code": None, "routes": [GOOD_ROUTE]},
            {"code": "Ok"},
            {"code": "Ok", "routes": []},
            {"code": "Ok", "routes": None},
            {"code": "Ok", "routes": "route"},
            {"code": "Ok", "routes": [None]},
            {"code": "Ok", "routes": ["x"]},
            {"code": "Ok", "routes": [[]]},
        ],
    )
    def test_missing_or_empty_routes(self, client, body):
        answer(body)

        with pytest.raises(RoutingServiceError):
            client.route(AUSTIN, DALLAS)

    @responses.activate
    @pytest.mark.parametrize(
        "distance",
        [None, "313948.1", -1.0, math.inf, -math.inf, True, [1], {"m": 1}],
    )
    def test_a_distance_that_is_not_a_sensible_number(self, client, distance):
        answer(with_route(distance=distance))

        with pytest.raises(RoutingServiceError, match="distance"):
            client.route(AUSTIN, DALLAS)

    @responses.activate
    def test_a_missing_distance(self, client):
        route = copy.deepcopy(GOOD_ROUTE)
        del route["distance"]
        answer({"code": "Ok", "routes": [route]})

        with pytest.raises(RoutingServiceError, match="distance"):
            client.route(AUSTIN, DALLAS)

    @responses.activate
    @pytest.mark.parametrize("duration", [None, "60", -0.5, math.inf, False, []])
    def test_a_duration_that_is_not_a_sensible_number(self, client, duration):
        answer(with_route(duration=duration))

        with pytest.raises(RoutingServiceError, match="duration"):
            client.route(AUSTIN, DALLAS)

    @responses.activate
    def test_a_missing_duration(self, client):
        route = copy.deepcopy(GOOD_ROUTE)
        del route["duration"]
        answer({"code": "Ok", "routes": [route]})

        with pytest.raises(RoutingServiceError, match="duration"):
            client.route(AUSTIN, DALLAS)

    @responses.activate
    @pytest.mark.parametrize(
        "geometry",
        [
            None,
            "encoded_polyline",
            [],
            {},
            {"type": "Point", "coordinates": [-97.7, 30.2]},
            # Perfectly good points, but not a line: only a LineString is a road.
            {"type": "MultiPoint", "coordinates": [[-97.7, 30.2], [-97.6, 30.3]]},
            {"coordinates": [[-97.7, 30.2], [-97.6, 30.3]]},
            {"type": "LineString"},
            {"type": "LineString", "coordinates": None},
            {"type": "LineString", "coordinates": "abc"},
            {"type": "LineString", "coordinates": []},
            {"type": "LineString", "coordinates": [[-97.7, 30.2]]},  # a line needs two points
        ],
    )
    def test_geometry_that_is_not_a_line(self, client, geometry):
        answer(with_route(geometry=geometry))

        with pytest.raises(RoutingServiceError, match="geometry"):
            client.route(AUSTIN, DALLAS)

    @responses.activate
    @pytest.mark.parametrize(
        "bad_point",
        [
            None,
            "x",
            [],
            [1.0],
            ["a", "b"],
            [None, 30.2],
            [-97.7, math.nan],
            [-97.7, math.inf],
            [True, False],
            [-97.7, 91.0],  # latitude out of range
            [-97.7, -91.0],
            [181.0, 30.2],  # longitude out of range
            [-181.0, 30.2],
            {"lon": -97.7, "lat": 30.2},
        ],
    )
    def test_a_point_that_is_not_a_place(self, client, bad_point):
        coordinates = [[-97.7, 30.2], bad_point, [-97.6, 30.3]]
        answer(with_route(geometry={"type": "LineString", "coordinates": coordinates}))

        with pytest.raises(RoutingServiceError, match="geometry"):
            client.route(AUSTIN, DALLAS)

    @responses.activate
    def test_a_bad_point_in_the_middle_of_thousands_is_found(self, client):
        points = [[-97.0 - i * 1e-4, 30.0 + i * 1e-4] for i in range(5000)]
        points[2500] = [-97.0, 95.0]
        answer(with_route(geometry={"type": "LineString", "coordinates": points}))

        with pytest.raises(RoutingServiceError, match="geometry"):
            client.route(AUSTIN, DALLAS)

    @responses.activate
    def test_a_large_realistic_route_is_read_in_full(self, client):
        points = [[-97.0 - i * 1e-3, 30.0 + i * 1e-3] for i in range(40_000)]
        answer(with_route(geometry={"type": "LineString", "coordinates": points}))

        route = client.route(AUSTIN, DALLAS)

        assert len(route.coordinates) == 40_000
        assert route.coordinates[-1] == Coordinates(30.0 + 39_999e-3, -97.0 - 39_999e-3)


class TestTheErrors:
    def test_all_of_them_are_routing_errors(self):
        for error in (NoRouteFoundError, RoutingServiceError, RoutingTimeoutError):
            assert issubclass(error, RoutingError)

    def test_a_missing_route_is_different_from_a_failing_service(self):
        assert not issubclass(NoRouteFoundError, RoutingServiceError)
        assert not issubclass(RoutingServiceError, NoRouteFoundError)

    def test_a_timeout_is_a_kind_of_service_failure_for_callers_that_do_not_care(self):
        assert issubclass(RoutingTimeoutError, RoutingServiceError)

    @pytest.mark.parametrize("error", [NoRouteFoundError, RoutingServiceError, RoutingTimeoutError])
    def test_they_keep_their_message_when_copied_or_pickled(self, error):
        original = error("the message")

        for clone in (copy.copy(original), pickle.loads(pickle.dumps(original))):
            assert type(clone) is error
            assert str(clone) == "the message"


class TestSettingUpTheClient:
    def test_the_default_server_is_the_public_osrm_demo(self):
        assert DEFAULT_BASE_URL == "https://router.project-osrm.org"

    def test_a_blank_user_agent_is_refused(self):
        with pytest.raises(ValueError, match="user_agent"):
            OsrmClient(user_agent="   ")

    @pytest.mark.parametrize("timeout", [0, -1, math.nan, math.inf])
    def test_the_timeout_must_be_a_positive_number_of_seconds(self, timeout):
        with pytest.raises(ValueError, match="timeout"):
            OsrmClient(user_agent=USER_AGENT, timeout=timeout)

    @pytest.mark.parametrize("base", ["", "   ", "router.project-osrm.org", "ftp://host"])
    def test_the_base_url_must_be_an_http_address(self, base):
        with pytest.raises(ValueError, match="base_url"):
            OsrmClient(base_url=base, user_agent=USER_AGENT)

    def test_it_reads_its_settings_from_django(self, settings):
        settings.OSRM_BASE_URL = "http://osrm.local:5000/"
        settings.OSRM_TIMEOUT_SECONDS = 3.5
        settings.OSRM_USER_AGENT = "my-agent/2.0"

        client = OsrmClient.from_settings()

        assert client.base_url == "http://osrm.local:5000"
        assert client.timeout == 3.5
        assert client.user_agent == "my-agent/2.0"

    def test_the_real_settings_have_sensible_defaults(self, settings):
        client = OsrmClient.from_settings()

        assert client.base_url == "https://router.project-osrm.org"
        assert client.timeout == 10.0
        assert "fuel-route-api" in client.user_agent
