"""Project-wide pytest fixtures."""

import itertools
from decimal import Decimal

import pytest


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
