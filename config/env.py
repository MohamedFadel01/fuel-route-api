"""Tiny helpers for reading typed values from environment variables."""

import os

_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})


def env_bool(name: str, default: bool = False) -> bool:
    """Return the variable as a boolean ("1", "true", "yes", "on" are true)."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in _TRUE_VALUES


def env_list(name: str, default: list[str] | None = None) -> list[str]:
    """Return a comma-separated variable as a list, dropping blank items."""
    raw = os.environ.get(name)
    if raw is None:
        return list(default) if default else []
    return [item.strip() for item in raw.split(",") if item.strip()]
