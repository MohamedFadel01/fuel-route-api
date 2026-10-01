"""The route as evenly spaced points, each knowing how many miles it is from the start.

A routing service describes a road as a line through thousands of points, packed tightly
on bends and far apart on straight stretches. The rest of the trip logic wants something
simpler: "where is mile 137.5?" and "which part of the route is closest to this station?".
``RoutePath`` answers both by replacing the line with points that are the same distance
apart (never more than ``spacing_miles``), each labelled with its *mile marker*: the
distance driven from the start to reach it.

Everything here is plain geometry, with no database and no network.
"""

import math
from collections.abc import Iterable
from dataclasses import dataclass
from functools import cached_property
from itertools import pairwise

import numpy as np

from apps.common.geo import EARTH_RADIUS_MILES, Coordinates, haversine_miles, unit_vector

DEFAULT_SPACING_MILES = 0.5

# A guard against a typo (say, a spacing of 0.000001) exhausting the server's memory.
MAX_POINTS = 1_000_000

# Below this angle (radians) two vertices are the same place for interpolation purposes.
_TINY_ANGLE = 1e-12


@dataclass(frozen=True, eq=False)
class RoutePath:
    """A route resampled into evenly spaced points.

    Build one with ``RoutePath.from_coordinates``. The arrays are read-only and have one
    entry per point, in driving order:

    * ``mile_markers``: miles driven from the start; the first is 0 and the last is
      ``total_miles``;
    * ``unit_vectors``: the point as a 3D position on a sphere of radius 1 (see
      ``apps.common.geo.unit_vector``), ready for a KD-tree.

    ``spacing_miles`` is the real gap between neighbouring points: the requested spacing,
    shrunk slightly so that the points divide the route exactly. It is 0 for a route that
    goes nowhere.
    """

    total_miles: float
    spacing_miles: float
    mile_markers: np.ndarray
    unit_vectors: np.ndarray

    def __post_init__(self) -> None:
        # The arrays are copied, so later changes to the caller's arrays cannot reach us,
        # and then frozen. ``object.__setattr__`` is how a frozen dataclass sets fields.
        markers = np.array(self.mile_markers, dtype=float)
        vectors = np.array(self.unit_vectors, dtype=float)
        _check(self.total_miles, self.spacing_miles, markers, vectors)
        markers.setflags(write=False)
        vectors.setflags(write=False)
        object.__setattr__(self, "mile_markers", markers)
        object.__setattr__(self, "unit_vectors", vectors)

    def __len__(self) -> int:
        return len(self.mile_markers)

    @cached_property
    def points(self) -> list[Coordinates]:
        """The points as latitude/longitude pairs."""
        x, y, z = self.unit_vectors.T
        latitudes = np.degrees(np.arcsin(np.clip(z, -1.0, 1.0)))
        longitudes = np.degrees(np.arctan2(y, x))
        return [
            Coordinates(float(lat), float(lon))
            for lat, lon in zip(latitudes, longitudes, strict=True)
        ]

    @classmethod
    def from_coordinates(
        cls, coordinates: Iterable[Coordinates], spacing_miles: float = DEFAULT_SPACING_MILES
    ) -> "RoutePath":
        """Resample the line through ``coordinates`` (start first, finish last).

        The length of the route is the sum of the great-circle distances between
        consecutive coordinates, so it is only as detailed as the input line. Repeated
        coordinates are harmless. If the start is also the finish, the result is a single
        point at mile 0.

        Raises ``ValueError`` for fewer than two coordinates, a spacing that is not a
        positive finite number, or a spacing so small that it would create more than
        ``MAX_POINTS`` points.
        """
        if not (math.isfinite(spacing_miles) and spacing_miles > 0):
            raise ValueError(f"The spacing must be a positive number of miles, got {spacing_miles}")
        vertices = list(coordinates)
        if len(vertices) < 2:
            raise ValueError(f"A route needs at least 2 coordinates, got {len(vertices)}")

        legs = np.array([haversine_miles(a, b) for a, b in pairwise(vertices)])
        miles_at_vertex = np.concatenate(([0.0], np.cumsum(legs)))
        total = float(miles_at_vertex[-1])
        vectors = np.array([unit_vector(vertex) for vertex in vertices])

        if total == 0.0:
            return cls(0.0, 0.0, np.array([0.0]), vectors[:1])

        # Compared as a float first: an absurdly small spacing overflows to infinity, which
        # ``math.ceil`` cannot turn into an integer.
        if total / spacing_miles > MAX_POINTS - 1:
            raise ValueError(
                f"A spacing of {spacing_miles} miles on a {total:.0f}-mile route would "
                f"create too many points (the limit is {MAX_POINTS})"
            )
        gaps = math.ceil(total / spacing_miles)
        markers = np.linspace(0.0, total, gaps + 1)
        return cls(
            total_miles=total,
            spacing_miles=total / gaps,
            mile_markers=markers,
            unit_vectors=_vectors_at(markers, miles_at_vertex, legs, vectors),
        )


def _check(total: float, spacing: float, markers: np.ndarray, vectors: np.ndarray) -> None:
    """Refuse arrays that cannot describe a route resampled by ``from_coordinates``."""
    if not (math.isfinite(total) and total >= 0):
        raise ValueError(f"total_miles must be zero or more miles, got {total}")
    if not (math.isfinite(spacing) and spacing >= 0):
        raise ValueError(f"spacing_miles must be zero or more miles, got {spacing}")
    if markers.ndim != 1:
        raise ValueError("The mile markers must be one-dimensional")
    if len(markers) == 0:
        raise ValueError("A path needs at least one point")
    if vectors.shape != (len(markers), 3):
        raise ValueError(
            f"There must be one unit vector per mile marker: {len(markers)} markers "
            f"but vectors of shape {vectors.shape}"
        )
    if not (np.isfinite(markers).all() and np.isfinite(vectors).all()):
        raise ValueError("Mile markers and vectors must be finite numbers")
    if markers[0] != 0:
        raise ValueError("The mile markers must start at 0")
    if not np.all(np.diff(markers) > 0):
        raise ValueError("The mile markers must be strictly increasing")
    if not math.isclose(markers[-1], total, rel_tol=1e-9, abs_tol=1e-12):
        raise ValueError("The mile markers must end at the total miles")
    if not np.allclose(np.linalg.norm(vectors, axis=1), 1.0, atol=1e-9):
        raise ValueError("Every vector must be a unit vector (length 1)")


def _vectors_at(
    markers: np.ndarray, miles_at_vertex: np.ndarray, legs: np.ndarray, vectors: np.ndarray
) -> np.ndarray:
    """The position of each mile marker, found by walking along the great-circle legs."""
    # The last leg that starts at or before each marker (the final leg for the very end).
    leg = np.clip(np.searchsorted(miles_at_vertex, markers, side="right") - 1, 0, len(legs) - 1)
    length = legs[leg]
    # A leg of length 0 is a repeated vertex: stay on it instead of dividing by zero.
    fraction = np.divide(
        markers - miles_at_vertex[leg], length, out=np.zeros_like(markers), where=length > 0
    )
    fraction = np.clip(fraction, 0.0, 1.0)  # rounding can push it a hair outside

    # Spherical linear interpolation, so that a fraction of the leg is the same fraction of
    # the distance, however long the leg is.
    angle = length / EARTH_RADIUS_MILES
    sine = np.sin(angle)
    straight = angle < _TINY_ANGLE
    safe_sine = np.where(straight, 1.0, sine)
    weight_start = np.where(straight, 1.0 - fraction, np.sin((1.0 - fraction) * angle) / safe_sine)
    weight_end = np.where(straight, fraction, np.sin(fraction * angle) / safe_sine)

    # A blend of two unit vectors on their great circle is already a unit vector.
    return weight_start[:, None] * vectors[leg] + weight_end[:, None] * vectors[leg + 1]
