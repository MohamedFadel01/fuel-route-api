"""A polite client for the OpenStreetMap Nominatim search API.

The public server (https://operations.osmfoundation.org/policies/nominatim/) allows at
most one request per second and requires an identifying ``User-Agent``. This client
enforces both and retries politely when the server is busy.
"""

import math
import time
from collections.abc import Callable
from dataclasses import dataclass

import requests

from apps.common.geo import Coordinates

DEFAULT_BASE_URL = "https://nominatim.openstreetmap.org/search"
MAX_LIMIT = 40
MAX_RETRY_AFTER_SECONDS = 60.0


class NominatimError(Exception):
    """Nominatim could not answer the request (after any retries)."""


@dataclass(frozen=True, slots=True)
class PlaceMatch:
    """One place returned by a search."""

    name: str
    coordinates: Coordinates
    region: str  # State or province code such as "AZ" or "ON"; "" when unknown.
    category: str  # OpenStreetMap class, e.g. "amenity".
    kind: str  # OpenStreetMap type, e.g. "fuel".


class NominatimClient:
    def __init__(
        self,
        *,
        user_agent: str,
        base_url: str = DEFAULT_BASE_URL,
        country_codes: str = "us,ca",
        min_interval: float = 1.0,
        timeout: float = 20.0,
        max_retries: int = 2,
        backoff_seconds: float = 5.0,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not user_agent.strip():
            raise ValueError("user_agent must not be blank (Nominatim blocks anonymous clients)")
        if min_interval < 0:
            raise ValueError("min_interval must not be negative")
        if max_retries < 0:
            raise ValueError("max_retries must not be negative")

        self.base_url = base_url
        self.country_codes = country_codes
        self.min_interval = min_interval
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_seconds = backoff_seconds
        self._sleep = sleep
        self._clock = clock
        self._last_request_at: float | None = None
        self._session = requests.Session()
        self._session.headers["User-Agent"] = user_agent.strip()

    def search(self, query: str, limit: int = 5) -> list[PlaceMatch]:
        """Return up to ``limit`` places matching the free-text ``query``, best first."""
        if not query.strip():
            raise ValueError("query must not be blank")
        if not 1 <= limit <= MAX_LIMIT:
            raise ValueError(f"limit must be between 1 and {MAX_LIMIT}")

        params = {
            "q": query,
            "format": "jsonv2",
            "limit": limit,
            "addressdetails": 1,
            "countrycodes": self.country_codes,
        }
        for attempt in range(self.max_retries + 1):
            self._wait_for_turn()
            retry_after = None
            try:
                response = self._session.get(self.base_url, params=params, timeout=self.timeout)
            except requests.RequestException as error:
                failure = f"Nominatim request failed: {error}"
            else:
                status = response.status_code
                if status == requests.codes.ok:
                    return self._parse(response)
                failure = f"Nominatim returned HTTP {status}"
                if status != requests.codes.too_many_requests and status < 500:
                    raise NominatimError(failure)
                retry_after = self._retry_after(response)

            if attempt == self.max_retries:
                raise NominatimError(failure)
            self._sleep(
                retry_after if retry_after is not None else self.backoff_seconds * (attempt + 1)
            )
        raise AssertionError("unreachable")  # pragma: no cover

    def _wait_for_turn(self) -> None:
        if self._last_request_at is not None:
            wait = self.min_interval - (self._clock() - self._last_request_at)
            if wait > 0:
                self._sleep(wait)
        self._last_request_at = self._clock()

    @staticmethod
    def _retry_after(response: requests.Response) -> float | None:
        """Seconds the server asked us to wait, capped; ``None`` if absent or unusable."""
        try:
            seconds = float(response.headers.get("Retry-After", ""))
        except ValueError:
            return None
        if not math.isfinite(seconds) or seconds < 0:
            return None
        return min(seconds, MAX_RETRY_AFTER_SECONDS)

    @classmethod
    def _parse(cls, response: requests.Response) -> list[PlaceMatch]:
        try:
            payload = response.json()
        except ValueError:
            raise NominatimError("Nominatim returned a response that is not valid JSON") from None
        if not isinstance(payload, list):
            raise NominatimError("Nominatim returned an unexpected response shape")

        matches = (cls._parse_item(item) for item in payload)
        return [match for match in matches if match is not None]

    @staticmethod
    def _parse_item(item: object) -> PlaceMatch | None:
        if not isinstance(item, dict):
            return None
        try:
            coordinates = Coordinates(float(item["lat"]), float(item["lon"]))
        except (KeyError, TypeError, ValueError):
            return None

        name = str(item.get("name") or "").strip()
        if not name:
            name = str(item.get("display_name") or "").split(",")[0].strip()

        address = item.get("address")
        iso_code = address.get("ISO3166-2-lvl4") if isinstance(address, dict) else None
        region = iso_code.split("-", 1)[1] if isinstance(iso_code, str) and "-" in iso_code else ""

        return PlaceMatch(
            name=name,
            coordinates=coordinates,
            region=region,
            category=str(item.get("category") or ""),
            kind=str(item.get("type") or ""),
        )
