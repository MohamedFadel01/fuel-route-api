import pytest

from apps.stations.geocoding.ambiguity import demote_shared_locations
from apps.stations.models import Station

pytestmark = pytest.mark.django_db

POI = Station.LocationPrecision.POI
CITY = Station.LocationPrecision.CITY


def place(make_station, lat, lon, precision=POI, **overrides):
    return make_station(latitude=lat, longitude=lon, location_precision=precision, **overrides)


def reload(station):
    station.refresh_from_db()
    return station


class TestDemoteSharedLocations:
    def test_stations_sharing_one_exact_point_become_approximate(self, make_station):
        first = place(make_station, 41.9633, -83.35369)
        second = place(make_station, 41.9633, -83.35369)

        demoted = demote_shared_locations()

        assert demoted == 2
        assert reload(first).location_precision == CITY
        assert reload(second).location_precision == CITY

    def test_positions_are_not_changed(self, make_station):
        first = place(make_station, 41.9633, -83.35369)
        place(make_station, 41.9633, -83.35369)

        demote_shared_locations()

        first = reload(first)
        assert (first.latitude, first.longitude) == (41.9633, -83.35369)

    def test_a_station_alone_on_its_point_stays_exact(self, make_station):
        alone = place(make_station, 30.0, -97.0)
        place(make_station, 31.0, -98.0)

        demoted = demote_shared_locations()

        assert demoted == 0
        assert reload(alone).location_precision == POI

    def test_a_group_of_three_is_demoted_together(self, make_station):
        group = [place(make_station, 37.57444, -77.46661) for _ in range(3)]
        alone = place(make_station, 10.0, 10.0)

        demoted = demote_shared_locations()

        assert demoted == 3
        assert {reload(s).location_precision for s in group} == {CITY}
        assert reload(alone).location_precision == POI

    def test_stations_in_different_cities_on_one_point_are_demoted(self, make_station):
        first = place(make_station, 35.15153, -81.85984, city="Chesnee", state="SC")
        second = place(make_station, 35.15153, -81.85984, city="Spartanburg", state="SC")

        demote_shared_locations()

        assert reload(first).location_precision == CITY
        assert reload(second).location_precision == CITY

    def test_points_a_metre_apart_count_as_the_same_place(self, make_station):
        first = place(make_station, 30.000001, -97.000001)
        second = place(make_station, 30.000002, -97.000002)

        demote_shared_locations()

        assert reload(first).location_precision == CITY
        assert reload(second).location_precision == CITY

    def test_points_about_a_hundred_metres_apart_are_different_places(self, make_station):
        first = place(make_station, 30.000, -97.000)
        second = place(make_station, 30.001, -97.000)

        demoted = demote_shared_locations()

        assert demoted == 0
        assert reload(first).location_precision == POI
        assert reload(second).location_precision == POI

    def test_an_exact_station_on_the_same_point_as_an_approximate_one_is_demoted(
        self, make_station
    ):
        # Approximate stations keep the shared point they were once demoted from.
        approximate = place(make_station, 30.0, -97.0, precision=CITY)
        exact = place(make_station, 30.0, -97.0)

        demoted = demote_shared_locations()

        assert demoted == 1
        assert reload(exact).location_precision == CITY
        assert reload(approximate).location_precision == CITY

    def test_approximate_stations_sharing_a_point_are_left_alone(self, make_station):
        first = place(make_station, 30.0, -97.0, precision=CITY)
        place(make_station, 30.0, -97.0, precision=CITY)

        demoted = demote_shared_locations()

        assert demoted == 0
        assert reload(first).location_precision == CITY

    def test_stations_without_a_position_are_ignored(self, make_station):
        make_station()
        make_station()
        exact = place(make_station, 30.0, -97.0)

        demoted = demote_shared_locations()

        assert demoted == 0
        assert reload(exact).location_precision == POI

    def test_running_it_again_changes_nothing(self, make_station):
        place(make_station, 30.0, -97.0)
        place(make_station, 30.0, -97.0)
        demote_shared_locations()

        assert demote_shared_locations() == 0

    def test_a_station_found_later_at_an_already_shared_point_is_demoted(self, make_station):
        place(make_station, 30.0, -97.0)
        place(make_station, 30.0, -97.0)
        demote_shared_locations()
        late = place(make_station, 30.0, -97.0)

        demoted = demote_shared_locations()

        assert demoted == 1
        assert reload(late).location_precision == CITY

    def test_empty_database(self):
        assert demote_shared_locations() == 0

    def test_handles_more_stations_than_one_batch(self, make_station):
        for index in range(7):
            place(make_station, 30.0 + index, -97.0)
            place(make_station, 30.0 + index, -97.0)

        demoted = demote_shared_locations(batch_size=3)

        assert demoted == 14
        assert Station.objects.filter(location_precision=CITY).count() == 14

    def test_other_fields_are_untouched(self, make_station):
        first = place(make_station, 30.0, -97.0, name="PILOT #1", city="Austin")
        place(make_station, 30.0, -97.0)

        demote_shared_locations()

        first = reload(first)
        assert (first.name, first.city) == ("PILOT #1", "Austin")
