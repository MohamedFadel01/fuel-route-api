"""Which places the API is willing to plan a trip for.

The area is a pair of boxes around the United States (including Alaska and Hawaii) and
Canada. A box cannot follow a border, so a town just outside the country can be inside the
box, and the Aleutian Islands that sit past the date line are outside it.
"""

import pytest

from apps.common.geo import Coordinates
from apps.trips.area import in_service_area


def at(latitude, longitude):
    return Coordinates(latitude, longitude)


class TestInside:
    @pytest.mark.parametrize(
        ("name", "point"),
        [
            ("Austin", at(30.2672, -97.7431)),
            ("Honolulu", at(21.3069, -157.8583)),
            ("Anchorage", at(61.2181, -149.9003)),
            ("Key West", at(24.5551, -81.7800)),
            ("Toronto", at(43.6532, -79.3832)),
            ("Whitehorse", at(60.7212, -135.0568)),
            ("St. John's", at(47.5615, -52.7126)),
            ("Dutch Harbor, Alaska", at(53.8898, -166.5422)),
            ("Tijuana, just across the border", at(32.5149, -117.0382)),
        ],
    )
    def test_places_we_cover(self, name, point):
        assert in_service_area(point), name

    @pytest.mark.parametrize(
        "point",
        [
            at(24.0, -100.0),
            at(83.5, -100.0),
            at(60.0, -168.0),
            at(60.0, -52.0),
            at(18.5, -157.0),
            at(22.5, -157.0),
            at(21.0, -160.5),
            at(21.0, -154.5),
        ],
    )
    def test_the_edge_of_a_box_is_inside(self, point):
        assert in_service_area(point)


class TestOutside:
    @pytest.mark.parametrize(
        ("name", "point"),
        [
            ("London", at(51.5074, -0.1278)),
            ("Mexico City", at(19.4326, -99.1332)),
            ("Sydney", at(-33.8688, 151.2093)),
            ("the North Pole", at(90.0, 0.0)),
            ("a point in the Gulf, south of the boxes", at(23.9, -100.0)),
            ("past the northern edge", at(83.6, -100.0)),
            ("west of the Alaska box", at(60.0, -168.1)),
            ("east of Newfoundland", at(47.0, -51.9)),
            ("the date line, beyond the Alaska box", at(60.0, 180.0)),
            ("south of Hawaii", at(18.4, -157.0)),
            ("north of Hawaii", at(22.6, -157.0)),
            ("east of Hawaii", at(21.0, -154.4)),
            ("west of Hawaii", at(21.0, -160.6)),
        ],
    )
    def test_places_we_do_not_cover(self, name, point):
        assert not in_service_area(point), name
