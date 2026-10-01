"""The image has to come up ready to plan a trip, and it must not hang forever.

A routing reply can trickle in for a long time. The client's own timeout only limits each
wait, so the process that serves the request has to give up on its own.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_gunicorn_is_installed_with_the_app():
    assert "gunicorn" in (ROOT / "requirements" / "base.txt").read_text()


def test_startup_loads_stations_then_serves_with_a_thirty_second_limit():
    script = (ROOT / "scripts" / "serve.sh").read_text()

    migrate = script.index("migrate")
    import_stations = script.index("import_stations")
    locations = script.index("load_station_locations")
    serve = script.index("gunicorn")

    assert migrate < import_stations < locations < serve
    assert "--timeout 30" in script
    # Geocoding calls Nominatim. The image uses the locations already saved in the repo.
    assert "geocode_stations" not in script


def test_the_image_uses_the_same_python_as_ci_and_skips_local_files():
    dockerfile = (ROOT / "Dockerfile").read_text()
    ignore = (ROOT / ".dockerignore").read_text()

    assert "python:3.14" in dockerfile
    assert "requirements/base.txt" in dockerfile
    assert "scripts/serve.sh" in dockerfile
    assert ".venv" in ignore
    assert ".env" in ignore
    assert "data/geonames" in ignore


def test_compose_publishes_the_server_on_port_8000():
    compose = (ROOT / "docker-compose.yml").read_text()
    script = (ROOT / "scripts" / "serve.sh").read_text()

    assert "8000:8000" in compose
    assert "DJANGO_DEBUG" in compose
    # A missing .env must still start. When the file exists, the container should see it.
    assert "env_file" in compose
    assert "required: false" in compose
    # One worker serves both trips and this check. The check has to wait out a slow trip,
    # or a healthy server looks dead.
    assert "--timeout 30" in script
    assert "timeout: 30s" in compose
