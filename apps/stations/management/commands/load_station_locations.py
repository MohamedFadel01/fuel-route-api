from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.stations.csv_loader import MissingColumnsError
from apps.stations.location_file import apply_locations, parse_locations


class Command(BaseCommand):
    help = (
        "Restore station locations from the CSV written by export_station_locations. "
        "Run import_stations first. Safe to run repeatedly."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "path",
            nargs="?",
            type=Path,
            default=settings.STATION_LOCATIONS_CSV,
            help="File to load (default: %(default)s).",
        )

    def handle(self, *args, path: Path, **options):
        result = self.read(path)

        for skipped in result.skipped:
            self.stderr.write(f"Skipped line {skipped.line_number}: {skipped.reason}")

        summary = apply_locations(result.locations)

        self.stdout.write(
            self.style.SUCCESS(
                f"{result.rows_read} rows read, "
                f"{summary.updated} stations located, "
                f"{summary.unknown} not in the database, "
                f"{len(result.skipped)} rows skipped."
            )
        )

    @staticmethod
    def read(path: Path):
        if not path.exists():
            raise CommandError(
                f"File not found: {path}. Create it with geocode_stations followed by "
                "export_station_locations."
            )
        try:
            with path.open(newline="", encoding="utf-8-sig") as handle:
                return parse_locations(handle)
        except OSError as error:
            raise CommandError(f"Cannot read {path}: {error}") from error
        except UnicodeDecodeError as error:
            raise CommandError(f"{path} is not valid UTF-8: {error}") from error
        except MissingColumnsError as error:
            raise CommandError(str(error)) from error
