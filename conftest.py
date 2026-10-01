"""Project-wide pytest fixtures."""

import ipaddress
import itertools
import os
import socket
from decimal import Decimal

import pytest


def _is_this_machine(host) -> bool:
    if host is None:
        return True  # binding, not connecting
    if isinstance(host, bytes):
        host = host.decode(errors="replace")
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host.split("%")[0]).is_loopback
    except ValueError:
        return False  # a name that is not "localhost"


def _refuse_outside(host) -> None:
    if not _is_this_machine(host):
        raise RuntimeError(
            f"Network access to {host!r} is blocked in tests. Fake the outside service "
            "(for example with the `responses` library or a fake provider)."
        )


@pytest.fixture(autouse=True)
def _no_outside_network(monkeypatch):
    """Tests may talk to this machine only. Anything else must be faked (see the guard tests)."""
    # A proxy configured in the environment would carry requests out through "this machine",
    # past the checks below. Tests never need one.
    for variable in [name for name in os.environ if name.lower().endswith("_proxy")]:
        monkeypatch.delenv(variable)

    connect = socket.socket.connect
    connect_ex = socket.socket.connect_ex
    getaddrinfo = socket.getaddrinfo

    def guarded_connect(self, address):
        if not isinstance(address, str | bytes):  # str/bytes is a unix socket path
            _refuse_outside(address[0])
        return connect(self, address)

    def guarded_connect_ex(self, address):
        if not isinstance(address, str | bytes):
            _refuse_outside(address[0])
        return connect_ex(self, address)

    def guarded_getaddrinfo(host, *args, **kwargs):
        _refuse_outside(host)
        return getaddrinfo(host, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", guarded_connect_ex)
    monkeypatch.setattr(socket, "getaddrinfo", guarded_getaddrinfo)


@pytest.fixture
def make_station():
    """Return a factory that creates valid, ungeocoded stations with unique IDs."""
    from apps.stations.models import Station

    ids = itertools.count(1)

    def factory(**overrides):
        fields = {
            "opis_id": next(ids),
            "name": "PILOT TRAVEL CENTER #1243",
            "address": "I-8, EXIT 119 & SR-85",
            "city": "Gila Bend",
            "state": "AZ",
            "rack_id": 930,
            "price": Decimal("3.899"),
        }
        fields.update(overrides)
        return Station.objects.create(**fields)

    return factory
