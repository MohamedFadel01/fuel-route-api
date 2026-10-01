from django.apps import AppConfig


class TripsConfig(AppConfig):
    name = "apps.trips"
    label = "trips"
    verbose_name = "Trips"

    def ready(self) -> None:
        # Importing registers the checks. Running them here stops the process at start-up:
        # a server such as gunicorn never runs Django's checks on its own.
        from django.core.exceptions import ImproperlyConfigured

        from apps.trips.checks import check_trip_settings

        errors = check_trip_settings(None)
        if errors:
            raise ImproperlyConfigured("\n".join(error.msg for error in errors))
