from django.apps import AppConfig


class TripsConfig(AppConfig):
    name = "apps.trips"
    label = "trips"
    verbose_name = "Trips"

    def ready(self) -> None:
        from apps.trips import checks  # noqa: F401  (registers the start-up checks)
