"""Check how the real settings module reacts to environment variables.

Django's test runner overrides some settings (e.g. ``DEBUG``), so these tests load the
settings in a fresh Python process with a controlled environment.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

BASE_DIR = Path(__file__).resolve().parent.parent
MANAGED_VARIABLES = (
    "DJANGO_SECRET_KEY",
    "DJANGO_DEBUG",
    "DJANGO_ALLOWED_HOSTS",
    "DATABASE_PATH",
)
PROBE = """
import json
from django.conf import settings
print(json.dumps({
    "secret_key": settings.SECRET_KEY,
    "debug": settings.DEBUG,
    "allowed_hosts": settings.ALLOWED_HOSTS,
    "database": str(settings.DATABASES["default"]["NAME"]),
}))
"""


@pytest.fixture
def load_settings():
    """Return a function that loads the settings with exactly the given variables set."""

    def load(**variables):
        env = {k: v for k, v in os.environ.items() if k not in MANAGED_VARIABLES}
        env.update(variables, DJANGO_SETTINGS_MODULE="config.settings")
        result = subprocess.run(
            [sys.executable, "-c", PROBE],
            env=env,
            cwd=BASE_DIR,
            capture_output=True,
            text=True,
            check=True,
        )
        return json.loads(result.stdout)

    return load


DEFAULT_DATABASE = str(BASE_DIR / "db.sqlite3")


class TestDatabasePath:
    def test_defaults_to_a_file_in_the_project(self, load_settings):
        assert load_settings()["database"] == DEFAULT_DATABASE

    @pytest.mark.parametrize("empty", ["", "   "])
    def test_an_empty_value_is_treated_as_unset(self, load_settings, empty):
        # An empty NAME would silently give SQLite a throw-away temporary database.
        assert load_settings(DATABASE_PATH=empty)["database"] == DEFAULT_DATABASE

    def test_a_custom_path_is_used(self, load_settings):
        assert load_settings(DATABASE_PATH="/data/stations.sqlite3")["database"] == (
            "/data/stations.sqlite3"
        )


class TestDebug:
    def test_is_off_by_default(self, load_settings):
        assert load_settings()["debug"] is False

    @pytest.mark.parametrize("empty", ["", "   "])
    def test_blank_value_keeps_it_off(self, load_settings, empty):
        assert load_settings(DJANGO_DEBUG=empty)["debug"] is False

    def test_can_be_switched_on(self, load_settings):
        assert load_settings(DJANGO_DEBUG="true")["debug"] is True


class TestAllowedHosts:
    def test_defaults_to_local_hosts(self, load_settings):
        assert load_settings()["allowed_hosts"] == ["localhost", "127.0.0.1"]

    def test_can_be_configured(self, load_settings):
        hosts = load_settings(DJANGO_ALLOWED_HOSTS="api.example.com, other.example.com")

        assert hosts["allowed_hosts"] == ["api.example.com", "other.example.com"]


class TestSecretKey:
    def test_a_configured_key_is_used(self, load_settings):
        assert load_settings(DJANGO_SECRET_KEY="my-secret")["secret_key"] == "my-secret"

    @pytest.mark.parametrize("empty", [None, "", "   "])
    def test_a_random_key_is_generated_when_missing_or_empty(self, load_settings, empty):
        variables = {} if empty is None else {"DJANGO_SECRET_KEY": empty}

        secret_key = load_settings(**variables)["secret_key"]

        assert len(secret_key) >= 50
        assert secret_key.strip() == secret_key
