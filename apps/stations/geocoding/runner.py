"""Locate many stations and save each result immediately.

Saving after every station makes a long run safe to stop and resume: stations that
already have a position are simply not selected the next time.
"""

from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from typing import Protocol

from apps.stations.geocoding.nominatim import NominatimError
from apps.stations.geocoding.station_geocoder import LocatedPlace
from apps.stations.models import Station


class Locator(Protocol):
    def locate(self, name: str, city: str, state: str) -> LocatedPlace | None: ...


@dataclass(slots=True)
class RunSummary:
    exact: int = 0  # Found by name on OpenStreetMap.
    city: int = 0  # Placed at the centre of their city.
    unlocated: int = 0  # Neither found nor in a known city.
    failed: int = 0  # The search failed; they will be retried on the next run.
    interrupted: bool = False

    @property
    def processed(self) -> int:
        return self.exact + self.city + self.unlocated + self.failed


class TooManyFailuresError(Exception):
    """The search service kept failing, so the run was stopped early."""

    def __init__(self, summary: RunSummary) -> None:
        super().__init__(f"{summary.failed} stations failed")
        self.summary = summary


def geocode_stations(
    stations: Iterable[Station],
    geocoder: Locator,
    *,
    max_consecutive_failures: int = 5,
    progress_every: int = 100,
    on_progress: Callable[[RunSummary], None] | None = None,
    on_failure: Callable[[Station, NominatimError], None] | None = None,
) -> RunSummary:
    """Locate each station and store its position; return what happened.

    A failed search leaves the station untouched. After ``max_consecutive_failures``
    failures in a row the service is assumed to be down and ``TooManyFailuresError``
    is raised. Ctrl+C ends the run early with ``interrupted`` set.
    """
    if progress_every < 1:
        raise ValueError("progress_every must be at least 1")
    if max_consecutive_failures < 1:
        raise ValueError("max_consecutive_failures must be at least 1")

    summary = RunSummary()
    failures_in_a_row = 0
    try:
        for station in stations:
            try:
                located = geocoder.locate(station.name, station.city, station.state)
            except NominatimError as error:
                summary.failed += 1
                failures_in_a_row += 1
                if on_failure:
                    on_failure(station, error)
                if failures_in_a_row >= max_consecutive_failures:
                    raise TooManyFailuresError(replace(summary)) from error
            else:
                failures_in_a_row = 0
                _record(station, located, summary)

            if on_progress and summary.processed % progress_every == 0:
                on_progress(summary)
    except KeyboardInterrupt:
        summary.interrupted = True
    return summary


def _record(station: Station, located: LocatedPlace | None, summary: RunSummary) -> None:
    if located is None:
        summary.unlocated += 1
        return

    Station.objects.filter(pk=station.pk).update(
        latitude=located.coordinates.latitude,
        longitude=located.coordinates.longitude,
        location_precision=located.precision,
    )
    if located.precision == Station.LocationPrecision.POI:
        summary.exact += 1
    else:
        summary.city += 1
