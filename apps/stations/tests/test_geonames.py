import io
import zipfile

import pytest
import requests
import responses

from apps.stations.geocoding.gazetteer import GazetteerError
from apps.stations.geocoding.geonames import download_geonames, load_gazetteer
from apps.stations.geocoding.types import Coordinates

URL_US = "https://download.geonames.org/export/dump/US.zip"
URL_CA = "https://download.geonames.org/export/dump/CA.zip"


def geonames_zip(member, name, admin1, lat, lon, country):
    fields = ["1", name, name, "", str(lat), str(lon), "P", "PPL", country, "", admin1]
    fields += ["", "", "", "100", "", "0", "", "2024-01-01"]
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(member, "\t".join(fields) + "\n")
    return buffer.getvalue()


class TestDownloadGeoNames:
    @responses.activate
    def test_downloads_the_zip_into_the_directory(self, tmp_path):
        responses.add(responses.GET, URL_US, body=b"zip-bytes")

        path = download_geonames("US", tmp_path)

        assert path == tmp_path / "US.zip"
        assert path.read_bytes() == b"zip-bytes"

    @responses.activate
    def test_creates_the_directory_if_needed(self, tmp_path):
        responses.add(responses.GET, URL_CA, body=b"x")
        target = tmp_path / "nested" / "geonames"

        path = download_geonames("CA", target)

        assert path.exists()

    @responses.activate
    def test_an_existing_file_is_not_downloaded_again(self, tmp_path):
        (tmp_path / "US.zip").write_bytes(b"old")

        path = download_geonames("US", tmp_path)

        assert path.read_bytes() == b"old"
        assert len(responses.calls) == 0

    @responses.activate
    def test_force_replaces_an_existing_file(self, tmp_path):
        (tmp_path / "US.zip").write_bytes(b"old")
        responses.add(responses.GET, URL_US, body=b"new")

        path = download_geonames("US", tmp_path, force=True)

        assert path.read_bytes() == b"new"

    @responses.activate
    def test_large_bodies_are_saved_completely(self, tmp_path):
        body = b"abcdefghij" * 500_000
        responses.add(responses.GET, URL_US, body=body)

        path = download_geonames("US", tmp_path)

        assert path.read_bytes() == body

    @responses.activate
    @pytest.mark.parametrize("status", [404, 500])
    def test_http_errors_are_reported_and_leave_no_files(self, tmp_path, status):
        responses.add(responses.GET, URL_US, status=status)

        with pytest.raises(GazetteerError, match=str(status)):
            download_geonames("US", tmp_path)

        assert list(tmp_path.iterdir()) == []

    @responses.activate
    def test_network_failures_are_reported_and_leave_no_files(self, tmp_path):
        responses.add(responses.GET, URL_US, body=requests.ConnectionError("offline"))

        with pytest.raises(GazetteerError, match="offline"):
            download_geonames("US", tmp_path)

        assert list(tmp_path.iterdir()) == []

    @pytest.mark.parametrize("country", ["us", "USA", "U", "", "../x", "U/"])
    def test_country_must_be_a_two_letter_uppercase_code(self, tmp_path, country):
        with pytest.raises(ValueError, match="country"):
            download_geonames(country, tmp_path)


class TestLoadGazetteer:
    @responses.activate
    def test_uses_files_already_on_disk_without_network(self, tmp_path):
        (tmp_path / "US.zip").write_bytes(geonames_zip("US.txt", "Austin", "TX", 30.0, -97.0, "US"))
        (tmp_path / "CA.zip").write_bytes(
            geonames_zip("CA.txt", "Toronto", "08", 43.7, -79.4, "CA")
        )

        gazetteer = load_gazetteer(tmp_path)

        assert gazetteer.lookup("Austin", "TX") == Coordinates(30.0, -97.0)
        assert gazetteer.lookup("Toronto", "ON") == Coordinates(43.7, -79.4)
        assert len(responses.calls) == 0

    @responses.activate
    def test_downloads_missing_files_first(self, tmp_path):
        responses.add(
            responses.GET, URL_US, body=geonames_zip("US.txt", "Austin", "TX", 30.0, -97.0, "US")
        )
        responses.add(
            responses.GET, URL_CA, body=geonames_zip("CA.txt", "Toronto", "08", 43.7, -79.4, "CA")
        )

        gazetteer = load_gazetteer(tmp_path)

        assert gazetteer.lookup("Austin", "TX") == Coordinates(30.0, -97.0)
        assert gazetteer.lookup("Toronto", "ON") == Coordinates(43.7, -79.4)
        assert len(responses.calls) == 2
