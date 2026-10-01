from django.urls import path

from apps.trips.views import RouteView

urlpatterns = [
    path("route/", RouteView.as_view(), name="route"),
]
