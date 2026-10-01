"""The request body for planning a trip: a start place and a finish place.

Each place is a latitude and a longitude. Anything outside the area this API covers (see
``area.in_service_area``) is rejected here, before any routing call is made.
"""

from rest_framework import serializers

from apps.common.geo import Coordinates
from apps.trips.area import in_service_area

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
