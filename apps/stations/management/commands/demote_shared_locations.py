from django.core.management.base import BaseCommand

from apps.stations.geocoding.ambiguity import demote_shared_locations


class Command(BaseCommand):
    help = (
        "Relabel exact positions that several stations share as approximate: one place found "
        "on the map cannot belong to more than one station. Positions are not changed. "
        "geocode_stations already does this at the end of every run."
    )

    def handle(self, *args, **options):
        demoted = demote_shared_locations()
        if demoted:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Relabelled as approximate: {demoted} (exact position shared with "
                    "another station)."
                )
            )
        else:
            self.stdout.write("No exact position is shared by several stations.")
