"""The request body for planning a trip: a start place and a finish place.

Each place is a latitude and a longitude. Anything outside the area this API covers (see
``area.in_service_area``) is rejected here, before any routing call is made.
"""

from decimal import Decimal

from rest_framework import serializers

from apps.common.geo import Coordinates
from apps.trips.area import in_service_area
from apps.trips.services import PlannedStop, TripPlan

OUTSIDE_AREA = "This point is outside the area we cover (the United States and Canada)."


class _CoordinateField(serializers.FloatField):
    def to_internal_value(self, data):
        # ``bool`` is a subclass of ``int``, so without this ``true`` would become 1.0.
        # Anything else that is not a finite number is already rejected by FloatField.
        if isinstance(data, bool):
            self.fail("invalid")
        return super().to_internal_value(data)


class _PlaceSerializer(serializers.Serializer):
    lat = _CoordinateField(min_value=-90, max_value=90)
    lon = _CoordinateField(min_value=-180, max_value=180)


class RouteRequestSerializer(serializers.Serializer):
    """``{"start": {"lat", "lon"}, "finish": {"lat", "lon"}}``.

    ``validated_data`` holds the two places as ``Coordinates``.
    """

    start = _PlaceSerializer()
    finish = _PlaceSerializer()

    def validate(self, attrs):
        start = Coordinates(attrs["start"]["lat"], attrs["start"]["lon"])
        finish = Coordinates(attrs["finish"]["lat"], attrs["finish"]["lon"])
        errors = {}
        if not in_service_area(start):
            errors["start"] = OUTSIDE_AREA
        if not in_service_area(finish):
            errors["finish"] = OUTSIDE_AREA
        if errors:
            raise serializers.ValidationError(errors)
        return {"start": start, "finish": finish}


def _decimal_text(value: Decimal, places: int) -> str:
    """The number as text, with at least ``places`` digits after the point.

    Further digits are kept, so a price of 3.0599 is not cut to 3.06, and a whole number
    of dollars still shows the cents.
    """
    text = format(value, "f")
    whole, _, fraction = text.partition(".")
    fraction = fraction.rstrip("0")
    return f"{whole}.{fraction.ljust(places, '0')}"


class _StationSerializer(serializers.Serializer):
    id = serializers.IntegerField(source="station_id")
    name = serializers.CharField()
    city = serializers.CharField()
    state = serializers.CharField()


class _FuelStopSerializer(serializers.Serializer):
    station = _StationSerializer(source="*")
    mile_marker = serializers.FloatField()
    price_per_gallon = serializers.SerializerMethodField()
    gallons = serializers.DecimalField(max_digits=14, decimal_places=3)
    cost = serializers.DecimalField(max_digits=14, decimal_places=2)

    def get_price_per_gallon(self, stop: PlannedStop) -> str:
        return _decimal_text(stop.price_per_gallon, 2)


class _TotalsSerializer(serializers.Serializer):
    gallons_purchased = serializers.DecimalField(max_digits=14, decimal_places=3)
    gallons_consumed = serializers.DecimalField(max_digits=14, decimal_places=3)
    total_cost = serializers.DecimalField(max_digits=14, decimal_places=2)


class TripPlanSerializer(serializers.Serializer):
    """A planned trip as the API returns it.

    ``route.distance_miles`` is what the routing service reported. ``route.measured_miles``
    is the length of the road, which is what the fuel figures are based on. The geometry is
    GeoJSON, so each point is longitude then latitude.
    """

    route = serializers.SerializerMethodField()
    fuel_stops = _FuelStopSerializer(source="stops", many=True)
    totals = _TotalsSerializer(source="*")
    margin_miles = serializers.FloatField()

    def get_route(self, plan: TripPlan) -> dict:
        return {
            "distance_miles": plan.distance_miles,
            "measured_miles": plan.measured_miles,
            "duration_seconds": plan.duration_seconds,
            "geometry": {
                "type": "LineString",
                "coordinates": [[point.longitude, point.latitude] for point in plan.geometry],
            },
        }
