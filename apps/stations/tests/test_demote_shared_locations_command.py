from io import StringIO

import pytest
from django.core.management import call_command

from apps.stations.models import Station

pytestmark = pytest.mark.django_db


def run():
    out, err = StringIO(), StringIO()
    call_command("demote_shared_locations", stdout=out, stderr=err)
    return out.getvalue(), err.getvalue()


def exact(make_station, lat, lon):
    return make_station(latitude=lat, longitude=lon, location_precision="poi")


def test_relabels_shared_positions_and_reports_how_many(make_station):
    exact(make_station, 30.0, -97.0)
    exact(make_station, 30.0, -97.0)
    alone = exact(make_station, 31.0, -98.0)

    out, err = run()

    assert "Relabelled as approximate: 2" in out
    assert err == ""
    assert Station.objects.filter(location_precision="poi").get() == alone


def test_says_so_when_nothing_is_shared(make_station):
    exact(make_station, 30.0, -97.0)
    exact(make_station, 31.0, -98.0)

    out, _ = run()

    assert "No exact position is shared" in out
    assert Station.objects.filter(location_precision="poi").count() == 2


def test_running_twice_reports_nothing_the_second_time(make_station):
    exact(make_station, 30.0, -97.0)
    exact(make_station, 30.0, -97.0)
    run()

    out, _ = run()

    assert "No exact position is shared" in out


def test_works_on_an_empty_database():
    out, _ = run()

    assert "No exact position is shared" in out
