from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.stations.csv_loader import MissingColumnsError, load_stations
from apps.stations.importer import save_stations


class Command(BaseCommand):
    help = (
        "Load fuel stations from the OPIS CSV file. Safe to run repeatedly: "
        "existing stations are updated and their coordinates are kept."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "path",
            nargs="?",
            type=Path,
            default=settings.FUEL_PRICES_CSV,
            help="CSV file to import (default: %(default)s).",
        )

    def handle(self, *args, path: Path, **options):
        result = self.read(path)

        for skipped in result.skipped:
            self.stderr.write(f"Skipped line {skipped.line_number}: {skipped.reason}")

        summary = save_stations(result.stations)

        self.stdout.write(
            self.style.SUCCESS(
                f"{result.rows_read} rows read, "
                f"{summary.created} stations created, "
                f"{summary.updated} stations updated, "
                f"{result.duplicates_merged} duplicate rows merged, "
                f"{len(result.skipped)} rows skipped."
            )
        )

    @staticmethod
    def read(path: Path):
        if not path.exists():
            raise CommandError(f"File not found: {path}")
        try:
            # utf-8-sig also accepts files saved with a byte order mark (e.g. by Excel).
            with path.open(newline="", encoding="utf-8-sig") as handle:
                return load_stations(handle)
        except OSError as error:
            raise CommandError(f"Cannot read {path}: {error}") from error
        except UnicodeDecodeError as error:
            raise CommandError(f"{path} is not valid UTF-8: {error}") from error
        except MissingColumnsError as error:
            raise CommandError(str(error)) from error
