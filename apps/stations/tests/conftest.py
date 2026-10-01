"""Fixtures shared by the stations tests."""

import io
import zipfile

import pytest

AUSTIN = (30.26715, -97.74306)
TORONTO = (43.70011, -79.4163)


def geonames_zip(member, country, name, admin1, latitude, longitude):
    """Return the bytes of a minimal GeoNames zip with a single populated place."""
    fields = ["1", name, name, "", str(latitude), str(longitude), "P", "PPL", country, "", admin1]
    fields += ["", "", "", "900000", "", "0", "", "2024-01-01"]
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(member, "\t".join(fields) + "\n")
    return buffer.getvalue()


@pytest.fixture
def geonames_dir(tmp_path, settings):
    """A GeoNames cache that already holds Austin, TX and Toronto, ON."""
    directory = tmp_path / "geonames"
    directory.mkdir()
    (directory / "US.zip").write_bytes(geonames_zip("US.txt", "US", "Austin", "TX", *AUSTIN))
    (directory / "CA.zip").write_bytes(geonames_zip("CA.txt", "CA", "Toronto", "08", *TORONTO))
    settings.GEONAMES_DIR = directory
    return directory
