"""Download the GeoNames dumps and turn them into a ready-to-use gazetteer."""

import os
import re
from pathlib import Path

import requests

from apps.stations.geocoding.gazetteer import CityGazetteer, GazetteerError

GEONAMES_URL = "https://download.geonames.org/export/dump/{country}.zip"
COUNTRIES = ("US", "CA")
CHUNK_SIZE = 1024 * 1024
# (connect, read) timeouts in seconds; the US file is about 70 MB.
TIMEOUT = (10, 120)


def download_geonames(country: str, directory: Path, *, force: bool = False) -> Path:
    """Download ``<country>.zip`` into ``directory`` and return its path.

    An existing file is reused unless ``force`` is set. The file is written to a
    temporary name first, so an interrupted download never leaves a broken zip behind.
    """
    if not re.fullmatch(r"[A-Z]{2}", country):
        raise ValueError(f"country must be a two-letter uppercase code, got {country!r}")

    target = directory / f"{country}.zip"
    if target.exists() and not force:
        return target

    url = GEONAMES_URL.format(country=country)
    directory.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".part")
    try:
        with requests.get(url, stream=True, timeout=TIMEOUT) as response:
            if not response.ok:
                raise GazetteerError(f"Download of {url} failed with HTTP {response.status_code}")
            with partial.open("wb") as handle:
                for chunk in response.iter_content(CHUNK_SIZE):
                    handle.write(chunk)
        os.replace(partial, target)
    except requests.RequestException as error:
        raise GazetteerError(f"Download of {url} failed: {error}") from error
    finally:
        partial.unlink(missing_ok=True)
    return target


def load_gazetteer(directory: Path, countries: tuple[str, ...] = COUNTRIES) -> CityGazetteer:
    """Load the gazetteer for ``countries``, downloading any file that is missing."""
    zips = {country: download_geonames(country, directory) for country in countries}
    return CityGazetteer.from_geonames_zips(zips)
