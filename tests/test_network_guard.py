"""The test suite must never reach the internet.

``conftest.py`` blocks every connection that is not to this machine, so a test that forgets
to fake an outside service fails loudly at once instead of quietly calling the real one
(slow, flaky, and dependent on the network being there).
"""

import socket
import threading

import pytest

from apps.common.geo import Coordinates
from apps.trips.providers.osrm import OsrmClient

AUSTIN = Coordinates(30.2672, -97.7431)
DALLAS = Coordinates(32.7767, -96.7970)


class TestOutsideTheMachine:
    @pytest.mark.parametrize("address", ["93.184.216.34", "8.8.8.8", "2606:4700::1111"])
    def test_connecting_to_an_outside_address_is_blocked(self, address):
        with pytest.raises(RuntimeError, match="blocked in tests"):
            socket.create_connection((address, 80), timeout=1)

    def test_looking_up_an_outside_name_is_blocked(self):
        with pytest.raises(RuntimeError, match="blocked in tests"):
            socket.getaddrinfo("router.project-osrm.org", 443)

    def test_an_unfaked_call_to_the_routing_service_is_blocked(self):
        client = OsrmClient(user_agent="tests/1.0")

        with pytest.raises(RuntimeError, match="blocked in tests"):
            client.route(AUSTIN, DALLAS)

    def test_a_raw_socket_skipping_the_name_lookup_is_blocked_too(self):
        with socket.socket() as raw, pytest.raises(RuntimeError, match="blocked in tests"):
            raw.connect(("8.8.8.8", 53))

    def test_the_other_way_of_connecting_is_blocked_as_well(self):
        with socket.socket() as raw, pytest.raises(RuntimeError, match="blocked in tests"):
            raw.connect_ex(("8.8.8.8", 53))

    def test_the_error_names_what_was_attempted(self):
        with pytest.raises(RuntimeError, match=r"8\.8\.8\.8"):
            socket.create_connection(("8.8.8.8", 53), timeout=1)


class TestProxies:
    @pytest.mark.parametrize(
        "variable",
        ["HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"],
    )
    def test_a_proxy_in_the_environment_is_removed_for_the_tests(self, variable):
        import os

        assert variable not in os.environ

    def test_every_variable_ending_in_proxy_is_removed_whatever_its_case(self):
        import os

        assert [name for name in os.environ if name.lower().endswith("_proxy")] == []

    def test_requests_does_not_see_a_proxy(self):
        import requests

        assert requests.utils.getproxies() == {}


class TestThisMachine:
    @pytest.mark.parametrize("name", ["localhost", "127.0.0.1", "::1"])
    def test_looking_up_this_machine_is_allowed(self, name):
        assert socket.getaddrinfo(name, 80)

    def test_a_server_running_in_the_test_itself_can_be_reached(self):
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        port = server.getsockname()[1]
        accepted = []
        thread = threading.Thread(target=lambda: accepted.append(server.accept()[0]))
        thread.start()
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=2):
                thread.join(timeout=2)
                assert accepted
        finally:
            for connection in accepted:
                connection.close()
            server.close()

    def test_a_unix_socket_is_allowed(self, tmp_path):
        path = str(tmp_path / "s.sock")
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(path)
        server.listen(1)
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                client.connect(path)
        finally:
            server.close()
