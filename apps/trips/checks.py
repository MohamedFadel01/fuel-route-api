"""Refuse to start when the routing settings make no sense.

Checked when the app starts (``manage.py check``, and the runserver), so a bad timeout or
address fails immediately instead of at the first request.
"""

import math
from urllib.parse import urlparse

from django.conf import settings
from django.core.checks import Error, register


def _is_number(value: object) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)


@register()
def check_trip_settings(app_configs, **kwargs) -> list[Error]:
    errors = []
    timeout = settings.OSRM_TIMEOUT_SECONDS
    if not (_is_number(timeout) and timeout > 0):
        errors.append(
            Error(
                f"OSRM_TIMEOUT_SECONDS must be a positive number of seconds, not {timeout!r}.",
                id="trips.E001",
            )
        )

    url = settings.OSRM_BASE_URL if isinstance(settings.OSRM_BASE_URL, str) else ""
    address = urlparse(url.strip())
    if address.scheme not in ("http", "https") or not address.netloc:
        errors.append(
            Error(
                f"OSRM_BASE_URL must be an http(s) address, not {settings.OSRM_BASE_URL!r}.",
                id="trips.E002",
            )
        )

    snap = settings.MAX_SNAP_MILES
    if not (_is_number(snap) and snap > 0):
        errors.append(
            Error(
                f"MAX_SNAP_MILES must be a positive number of miles, not {snap!r}.",
                id="trips.E003",
            )
        )

    cache_seconds = settings.TRIP_CACHE_SECONDS
    if not (_is_number(cache_seconds) and cache_seconds >= 0):
        errors.append(
            Error(
                "TRIP_CACHE_SECONDS must be zero or a positive number of seconds, "
                f"not {cache_seconds!r}.",
                id="trips.E004",
            )
        )
    return errors
