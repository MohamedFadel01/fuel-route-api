from io import StringIO

import pytest
from django.conf import settings
from django.core.management import CommandError, call_command

from apps.stations.models import Station

pytestmark = pytest.mark.django_db

HEADER = "OPIS Truckstop ID,Truckstop Name,Address,City,State,Rack ID,Retail Price"
GOOD_ROWS = [
    "20,PILOT TRAVEL CENTER #1243,I-8 EXIT 119,Gila Bend,AZ,930,3.899",
    "20,PILOT #1243,I-8 EXIT 119,Gila Bend,AZ,930,3.799",
    "28,LITTLEFIELD EXPRESS #2,I-540 EXIT 12,Fort Smith,AR,645,3.399",
]


@pytest.fixture
def csv_file(tmp_path):
    def write(*rows, header=HEADER, encoding="utf-8"):
        path = tmp_path / "stations.csv"
        path.write_bytes(("\n".join([header, *rows]) + "\n").encode(encoding))
        return path

    return write


def run(*args):
    out, err = StringIO(), StringIO()
    call_command("import_stations", *args, stdout=out, stderr=err)
    return out.getvalue(), err.getvalue()


class TestImportStationsCommand:
    def test_imports_stations_from_the_given_file(self, csv_file):
        run(str(csv_file(*GOOD_ROWS)))

        assert Station.objects.count() == 2
        assert Station.objects.get(opis_id=20).name == "PILOT #1243"

    def test_prints_a_summary(self, csv_file):
        out, err = run(str(csv_file(*GOOD_ROWS)))

        assert "3 rows read" in out
        assert "2 stations created" in out
        assert "0 stations updated" in out
        assert "1 duplicate rows merged" in out
        assert "0 rows skipped" in out
        assert err == ""

    def test_running_twice_updates_instead_of_duplicating(self, csv_file):
        path = str(csv_file(*GOOD_ROWS))
        run(path)

        out, _ = run(path)

        assert Station.objects.count() == 2
        assert "0 stations created" in out
        assert "2 stations updated" in out

    def test_reports_skipped_rows_and_imports_the_rest(self, csv_file):
        path = csv_file(*GOOD_ROWS, "30,BAD PRICE,A,Austin,TX,1,abc")

        out, err = run(str(path))

        assert Station.objects.count() == 2
        assert "1 rows skipped" in out
        assert "line 5" in err
        assert "Retail Price" in err

    def test_uses_the_configured_default_file(self, csv_file, settings):
        settings.FUEL_PRICES_CSV = csv_file(*GOOD_ROWS)

        run()

        assert Station.objects.count() == 2

    def test_reads_files_that_start_with_a_byte_order_mark(self, csv_file):
        path = csv_file(*GOOD_ROWS, encoding="utf-8-sig")

        run(str(path))

        assert Station.objects.count() == 2

    def test_missing_file_is_a_clear_error(self, tmp_path):
        with pytest.raises(CommandError, match="not found"):
            run(str(tmp_path / "nope.csv"))

    def test_directory_instead_of_file_is_a_clear_error(self, tmp_path):
        with pytest.raises(CommandError, match="Cannot read"):
            run(str(tmp_path))

    def test_missing_columns_are_a_clear_error(self, csv_file):
        path = csv_file("1,GOOD", header="OPIS Truckstop ID,Truckstop Name")

        with pytest.raises(CommandError, match="Retail Price"):
            run(str(path))

        assert Station.objects.count() == 0

    def test_file_that_is_not_utf8_is_a_clear_error(self, csv_file):
        path = csv_file("1,CAF\xc9,A,Austin,TX,1,3.0", encoding="latin-1")

        with pytest.raises(CommandError, match="UTF-8"):
            run(str(path))

        assert Station.objects.count() == 0

    def test_empty_file_is_a_clear_error(self, tmp_path):
        path = tmp_path / "empty.csv"
        path.write_text("")

        with pytest.raises(CommandError, match="missing required columns"):
            run(str(path))


class TestRealDataset:
    def test_the_bundled_csv_imports_cleanly(self):
        assert settings.FUEL_PRICES_CSV.exists()

        out, err = run()

        assert Station.objects.count() == 6738
        assert "8151 rows read" in out
        assert "0 rows skipped" in out
        assert err == ""
        assert Station.objects.filter(state="ON").exists()
