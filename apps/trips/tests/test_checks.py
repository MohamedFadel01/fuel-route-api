"""The app refuses to start when the routing settings make no sense."""

import math

import pytest
from django.core.checks import run_checks

from apps.trips.providers.osrm import get_shared_client, reset_shared_client


def routing_errors():
    return [error for error in run_checks() if error.id.startswith("trips.")]


class TestTheRoutingSettings:
    def test_the_defaults_pass(self):
        assert routing_errors() == []

    @pytest.mark.parametrize("timeout", [0, -1, math.nan, math.inf])
    def test_the_timeout_must_be_a_positive_finite_number(self, settings, timeout):
        settings.OSRM_TIMEOUT_SECONDS = timeout

        errors = routing_errors()

        assert len(errors) == 1
        assert errors[0].id == "trips.E001"
        assert "OSRM_TIMEOUT_SECONDS" in errors[0].msg

    @pytest.mark.parametrize("url", ["", "not a url", "ftp://files.example.com", "osrm.local"])
    def test_the_base_url_must_be_an_http_address(self, settings, url):
        settings.OSRM_BASE_URL = url

        errors = routing_errors()

        assert [error.id for error in errors] == ["trips.E002"]
        assert "OSRM_BASE_URL" in errors[0].msg

    @pytest.mark.parametrize("url", ["https://router.project-osrm.org", "http://osrm:5000"])
    def test_an_http_address_passes(self, settings, url):
        settings.OSRM_BASE_URL = url

        assert routing_errors() == []

    @pytest.mark.parametrize("miles", [0, -5, math.nan])
    def test_the_snap_limit_must_be_a_positive_finite_number(self, settings, miles):
        settings.MAX_SNAP_MILES = miles

        errors = routing_errors()

        assert [error.id for error in errors] == ["trips.E003"]
        assert "MAX_SNAP_MILES" in errors[0].msg

    @pytest.mark.parametrize("seconds", [-1, math.nan, math.inf])
    def test_the_cache_time_must_be_zero_or_a_positive_finite_number(self, settings, seconds):
        settings.TRIP_CACHE_SECONDS = seconds

        errors = routing_errors()

        assert [error.id for error in errors] == ["trips.E004"]
        assert "TRIP_CACHE_SECONDS" in errors[0].msg

    def test_a_cache_time_of_zero_is_allowed(self, settings):
        settings.TRIP_CACHE_SECONDS = 0

        assert routing_errors() == []

    def test_every_problem_is_reported_together(self, settings):
        settings.OSRM_TIMEOUT_SECONDS = 0
        settings.OSRM_BASE_URL = "nope"
        settings.MAX_SNAP_MILES = 0

        assert {error.id for error in routing_errors()} == {
            "trips.E001",
            "trips.E002",
            "trips.E003",
        }


class TestTheSharedClient:
    def setup_method(self):
        reset_shared_client()

    def teardown_method(self):
        reset_shared_client()

    def test_one_client_is_reused(self):
        assert get_shared_client() is get_shared_client()

    def test_it_is_built_from_the_settings(self, settings):
        settings.OSRM_BASE_URL = "http://osrm.internal:5000"
        settings.OSRM_TIMEOUT_SECONDS = 4.5
        settings.OSRM_USER_AGENT = "tests/1.0"

        client = get_shared_client()

        assert client.base_url == "http://osrm.internal:5000"
        assert client.timeout == 4.5
        assert client.user_agent == "tests/1.0"

    def test_a_client_already_built_keeps_its_settings_until_reset(self, settings):
        settings.OSRM_TIMEOUT_SECONDS = 4
        first = get_shared_client()
        settings.OSRM_TIMEOUT_SECONDS = 9

        assert get_shared_client() is first
        assert get_shared_client().timeout == 4

        reset_shared_client()

        assert get_shared_client() is not first
        assert get_shared_client().timeout == 9
