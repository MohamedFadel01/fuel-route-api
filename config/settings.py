"""
Django settings for the fuel-route-api project.

Everything environment-specific is read from environment variables
(see ``.env.example``), so the same code runs locally, in CI and in Docker.
"""

from pathlib import Path

from django.core.management.utils import get_random_secret_key

from config.env import env_bool, env_float, env_list, env_str

BASE_DIR = Path(__file__).resolve().parent.parent

# --- Security ---------------------------------------------------------------
# Without DJANGO_SECRET_KEY a random key is generated for this process only.
# That is safe by default (nothing here relies on long-lived signed data).
SECRET_KEY = env_str("DJANGO_SECRET_KEY") or get_random_secret_key()
DEBUG = env_bool("DJANGO_DEBUG", default=False)
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])

# --- Applications -----------------------------------------------------------
INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.staticfiles",
    "rest_framework",
    "apps.stations",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.common.CommonMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

# --- Database ---------------------------------------------------------------
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": env_str("DATABASE_PATH", default=str(BASE_DIR / "db.sqlite3")),
    }
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Cache ------------------------------------------------------------------
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "fuel-route-api",
    }
}

# --- Internationalization ---------------------------------------------------
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = False
USE_TZ = True

# --- Static files -----------------------------------------------------------
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# --- Fuel data --------------------------------------------------------------
FUEL_PRICES_CSV = BASE_DIR / "data" / "fuel-prices-for-be-assessment.csv"
# Large public place files (downloaded on demand, not committed to git).
GEONAMES_DIR = BASE_DIR / "data" / "geonames"
# Result of the slow geocoding run, committed so locations can be restored instantly.
STATION_LOCATIONS_CSV = BASE_DIR / "data" / "stations_geocoded.csv"

# --- Station geocoding (OpenStreetMap Nominatim) -----------------------------
# The public server asks for an identifying User-Agent (ideally with a contact address)
# and at most one request per second: https://operations.osmfoundation.org/policies/nominatim/
NOMINATIM_BASE_URL = env_str(
    "NOMINATIM_BASE_URL", default="https://nominatim.openstreetmap.org/search"
)
NOMINATIM_USER_AGENT = env_str(
    "NOMINATIM_USER_AGENT", default="fuel-route-api/0.1 (assessment project)"
)
NOMINATIM_MIN_INTERVAL = 1.0  # seconds between requests
NOMINATIM_BACKOFF_SECONDS = 5.0  # first wait when the server is busy; doubles per retry
# A search hit further than this from the station's city is treated as a wrong match.
STATION_MATCH_MAX_MILES = 25.0

# --- Routing (OSRM) -----------------------------------------------------------
# One request per trip. The public demo server is best-effort and meant for light use; to
# use your own OSRM (or a compatible service) just change the base URL.
OSRM_BASE_URL = env_str("OSRM_BASE_URL", default="https://router.project-osrm.org")
OSRM_TIMEOUT_SECONDS = env_float("OSRM_TIMEOUT_SECONDS", default=10.0)
OSRM_USER_AGENT = env_str("OSRM_USER_AGENT", default="fuel-route-api/0.1 (assessment project)")

# --- Django REST framework --------------------------------------------------
# A public, stateless JSON API: no sessions, no auth, no browsable HTML.
REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "DEFAULT_PERMISSION_CLASSES": [],
    "UNAUTHENTICATED_USER": None,
}
