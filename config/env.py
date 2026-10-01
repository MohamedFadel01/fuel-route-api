"""Tiny helpers for reading typed values from environment variables."""

import math
import os

_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})


def env_str(name: str, default: str = "") -> str:
    """Return the stripped variable, or ``default`` when it is missing or blank.

    Blank counts as unset because ``.env`` files often contain placeholders such as ``NAME=``.
    """
    return os.environ.get(name, "").strip() or default


def env_bool(name: str, default: bool = False) -> bool:
    """Return the variable as a boolean ("1", "true", "yes", "on" are true)."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in _TRUE_VALUES


def env_float(name: str, default: float) -> float:
    """Return the variable as a finite number, or ``default`` when it is missing or blank.

    A value that is not a finite number stops the app at start-up with a message naming the
    variable, instead of failing later somewhere unrelated.
    """
    raw = env_str(name)
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        value = math.nan
    if not math.isfinite(value):
        raise ValueError(f"{name} must be a number, not {raw!r}")
    return value


def env_list(name: str, default: list[str] | None = None) -> list[str]:
    """Return a comma-separated variable as a list, dropping blank items."""
    raw = os.environ.get(name)
    if raw is None:
        return list(default) if default else []
    return [item.strip() for item in raw.split(",") if item.strip()]
