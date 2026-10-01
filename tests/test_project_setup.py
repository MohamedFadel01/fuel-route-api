"""Smoke tests that prove the project is wired together correctly."""

import django
import pytest
from django.conf import settings
from django.core.management import call_command


def test_runs_on_django_6_1_or_newer():
    assert django.VERSION[:2] >= (6, 1)


def test_django_system_checks_pass():
    call_command("check")


@pytest.mark.django_db
def test_no_pending_model_changes():
    call_command("makemigrations", "--check", "--dry-run")


def test_rest_framework_is_installed():
    assert "rest_framework" in settings.INSTALLED_APPS


def test_secret_key_is_set_and_long_enough():
    assert len(settings.SECRET_KEY) >= 50


def test_debug_is_off_by_default():
    assert settings.DEBUG is False


def test_api_speaks_json_only():
    renderers = settings.REST_FRAMEWORK["DEFAULT_RENDERER_CLASSES"]
    assert renderers == ["rest_framework.renderers.JSONRenderer"]


def test_api_is_public_and_stateless():
    assert settings.REST_FRAMEWORK["DEFAULT_AUTHENTICATION_CLASSES"] == []
    assert settings.REST_FRAMEWORK["DEFAULT_PERMISSION_CLASSES"] == []
    assert settings.REST_FRAMEWORK["UNAUTHENTICATED_USER"] is None


def test_timezone_aware_utc():
    assert settings.USE_TZ is True
    assert settings.TIME_ZONE == "UTC"
