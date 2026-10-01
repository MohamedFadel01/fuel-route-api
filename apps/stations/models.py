from django.db import models
from django.db.models import Q


class Station(models.Model):
    """A fuel station (truck stop) with its current retail price per gallon."""

    class LocationPrecision(models.TextChoices):
        """How trustworthy the stored coordinates are."""

        POI = "poi", "Exact place found by name"
        CITY = "city", "Centre of the station's city"

    opis_id = models.PositiveIntegerField(unique=True, help_text="OPIS truckstop ID.")
    name = models.CharField(max_length=200)
    address = models.CharField(max_length=200, help_text="Highway/exit description.")
    city = models.CharField(max_length=100)
    state = models.CharField(max_length=2, help_text="US state or Canadian province code.")
    rack_id = models.PositiveIntegerField(help_text="OPIS wholesale pricing region.")
    price = models.DecimalField(
        max_digits=10, decimal_places=8, help_text="Retail price per gallon."
    )

    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    location_precision = models.CharField(
        max_length=4, choices=LocationPrecision, blank=True, default=""
    )

    class Meta:
        indexes = [models.Index(fields=["latitude", "longitude"], name="station_coords_idx")]
        constraints = [
            models.CheckConstraint(condition=Q(price__gt=0), name="station_price_positive"),
            models.CheckConstraint(
                condition=(
                    Q(latitude__isnull=True, longitude__isnull=True)
                    | Q(latitude__isnull=False, longitude__isnull=False)
                ),
                name="station_coords_set_together",
            ),
            models.CheckConstraint(
                condition=Q(latitude__isnull=True) | Q(latitude__range=(-90, 90)),
                name="station_latitude_in_range",
            ),
            models.CheckConstraint(
                condition=Q(longitude__isnull=True) | Q(longitude__range=(-180, 180)),
                name="station_longitude_in_range",
            ),
        ]

    def __str__(self):
        return f"{self.name} ({self.city}, {self.state})"
