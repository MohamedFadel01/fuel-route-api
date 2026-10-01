"""The geocoding demo script must work and must never touch the real database."""

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "demo_geocoding.sh"
GEONAMES_AVAILABLE = all((ROOT / "data" / "geonames" / f"{c}.zip").exists() for c in ("US", "CA"))


def run_script(*args, tmp_path):
    environment = {**os.environ, "TMPDIR": str(tmp_path)}
    environment.pop("DATABASE_PATH", None)
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


def test_script_exists_and_is_executable():
    assert SCRIPT.exists()
    assert os.access(SCRIPT, os.X_OK)


def test_script_has_valid_bash_syntax():
    result = subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True, text=True)

    assert result.returncode == 0, result.stderr


@pytest.mark.skipif(not GEONAMES_AVAILABLE, reason="GeoNames files are not downloaded")
class TestOfflineRun:
    """``--city-only`` skips OpenStreetMap, so this runs without network access."""

    def test_full_pipeline_round_trips(self, tmp_path):
        result = run_script("12", "--city-only", tmp_path=tmp_path)

        assert result.returncode == 0, result.stdout + result.stderr
        assert "12 stations processed" in result.stdout
        assert "12 station locations written" in result.stdout
        assert "12 stations located" in result.stdout
        assert "Round trip OK" in result.stdout

    def test_cleans_up_after_itself(self, tmp_path):
        run_script("5", "--city-only", tmp_path=tmp_path)

        assert list(tmp_path.iterdir()) == []

    def test_does_not_touch_the_real_database(self, tmp_path):
        real_database = ROOT / "db.sqlite3"
        before = real_database.stat().st_mtime_ns if real_database.exists() else None

        run_script("5", "--city-only", tmp_path=tmp_path)

        after = real_database.stat().st_mtime_ns if real_database.exists() else None
        assert before == after

    def test_a_bad_sample_size_fails_clearly(self, tmp_path):
        result = run_script("zero", "--city-only", tmp_path=tmp_path)

        assert result.returncode != 0
        assert "sample size" in (result.stdout + result.stderr).lower()
