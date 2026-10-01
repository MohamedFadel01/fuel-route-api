from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.stations.geocoding.gazetteer import GazetteerError
from apps.stations.geocoding.geonames import load_gazetteer
from apps.stations.geocoding.nominatim import NominatimClient
from apps.stations.geocoding.runner import RunSummary, TooManyFailuresError, geocode_stations
from apps.stations.geocoding.station_geocoder import StationGeocoder
from apps.stations.models import Station


def positive_int(text: str) -> int:
    value = int(text)
    if value < 1:
        raise ValueError("must be at least 1")
    return value


def format_duration(seconds: float) -> str:
    """Describe a length of time in the most readable unit."""
    if seconds < 1:
        return "less than a second"
    if seconds < 90:
        whole = round(seconds)
        return f"{whole} second{'' if whole == 1 else 's'}"
    if seconds < 5400:
        return f"{round(seconds / 60)} minutes"
    return f"{seconds / 3600:.1f} hours"


class NoSearch:
    """A place search that never finds anything (used for --city-only)."""

    def search(self, query: str, limit: int = 5) -> list:
        return []


class Command(BaseCommand):
    help = (
        "Give every station a latitude and longitude: an exact position from OpenStreetMap "
        "when it can be found and verified, otherwise the centre of the station's city. "
        "Progress is saved after every station, so the command can be stopped (Ctrl+C) and "
        "run again to continue."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit", type=positive_int, help="Process at most this many stations."
        )
        parser.add_argument(
            "--city-only",
            action="store_true",
            help="Skip OpenStreetMap and use city centres only (fast, works offline).",
        )
        parser.add_argument(
            "--redo-city",
            action="store_true",
            help="Also retry stations that only have a city-centre position.",
        )
        parser.add_argument(
            "--progress-every",
            type=positive_int,
            default=100,
            help="Print a progress line every N stations (default: %(default)s).",
        )
        parser.add_argument(
            "--max-failures",
            type=positive_int,
            default=5,
            help="Stop after this many failed searches in a row (default: %(default)s).",
        )

    def handle(self, *args, **options):
        if options["city_only"] and options["redo_city"]:
            raise CommandError("--city-only cannot be combined with --redo-city.")

        stations = self.pending_stations(options["redo_city"], options["limit"])
        self.stdout.write("Loading city centres (GeoNames)...")
        try:
            gazetteer = load_gazetteer(settings.GEONAMES_DIR)
        except GazetteerError as error:
            raise CommandError(str(error)) from error

        searcher = NoSearch() if options["city_only"] else self.build_client()
        geocoder = StationGeocoder(
            searcher, gazetteer, max_distance_miles=settings.STATION_MATCH_MAX_MILES
        )

        total = len(stations)
        self.announce(total, options["city_only"])
        try:
            summary = geocode_stations(
                stations,
                geocoder,
                max_consecutive_failures=options["max_failures"],
                progress_every=options["progress_every"],
                on_progress=lambda s: self.stdout.write(f"{s.processed}/{total} processed"),
                on_failure=self.report_failure,
            )
        except TooManyFailuresError as error:
            self.report(error.summary)
            raise CommandError(
                f"Stopped after {options['max_failures']} consecutive failures. "
                "Check your connection and run the command again to continue."
            ) from error

        self.report(summary)
        if summary.interrupted:
            self.stdout.write(
                self.style.WARNING(
                    "Interrupted. Progress is saved: run the command again to continue."
                )
            )

    @staticmethod
    def pending_stations(redo_city: bool, limit: int | None) -> list[Station]:
        precisions = ["", Station.LocationPrecision.CITY] if redo_city else [""]
        queryset = Station.objects.filter(location_precision__in=precisions).order_by("pk")
        return list(queryset[:limit] if limit else queryset)

    @staticmethod
    def build_client() -> NominatimClient:
        return NominatimClient(
            user_agent=settings.NOMINATIM_USER_AGENT,
            base_url=settings.NOMINATIM_BASE_URL,
            min_interval=settings.NOMINATIM_MIN_INTERVAL,
            backoff_seconds=settings.NOMINATIM_BACKOFF_SECONDS,
        )

    def announce(self, total: int, city_only: bool) -> None:
        message = f"Geocoding {total} stations"
        if total and not city_only:
            seconds = total * max(settings.NOMINATIM_MIN_INTERVAL, 0)
            message += f" (at least {format_duration(seconds)} at the polite request rate)"
        self.stdout.write(message + "...")

    def report_failure(self, station: Station, error: Exception) -> None:
        where = f"{station.city}, {station.state}"
        self.stderr.write(f"Could not search for {station.name} ({where}): {error}")

    def report(self, summary: RunSummary) -> None:
        self.stdout.write(
            self.style.SUCCESS(
                f"{summary.processed} stations processed: {summary.exact} exact, "
                f"{summary.city} city, {summary.unlocated} unlocated, {summary.failed} failed."
            )
        )
