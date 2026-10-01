"""Root URL configuration."""

from django.urls import include, path

from apps.trips.map_page import MapView

urlpatterns = [
    path("api/v1/", include("apps.trips.urls")),
    path("map/", MapView.as_view(), name="map"),
]
