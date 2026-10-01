from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.stations.location_file import write_locations
from apps.stations.models import Station


def plural(count: int, word: str) -> str:
    return f"{count} {word}" if count == 1 else f"{count} {word}s"


class Command(BaseCommand):
    help = (
        "Save the locations found by geocode_stations to a CSV file that can be committed "
        "and restored later with load_station_locations."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "path",
            nargs="?",
            type=Path,
            default=settings.STATION_LOCATIONS_CSV,
            help="File to write (default: %(default)s).",
        )

    def handle(self, *args, path: Path, **options):
        stations = list(Station.objects.all())
        located = [station for station in stations if station.location_precision]
        if not located:
            raise CommandError(
                "No stations have a location yet; run geocode_stations first. "
                f"Nothing was written to {path}."
            )

        try:
            count = write_locations(located, path)
        except OSError as error:
            raise CommandError(f"Cannot write {path}: {error}") from error

        exact = sum(1 for s in located if s.location_precision == Station.LocationPrecision.POI)
        message = (
            f"{plural(count, 'station location')} written to {path} "
            f"({exact} exact, {count - exact} approximate)."
        )
        missing = len(stations) - len(located)
        if missing:
            message += f" {plural(missing, 'station')} not located yet."
        self.stdout.write(self.style.SUCCESS(message))
