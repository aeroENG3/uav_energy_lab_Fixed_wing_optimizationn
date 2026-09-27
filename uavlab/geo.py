"""WGS-84 geodesy: geodetic <-> ECEF <-> local NED about a home point.
Exact transforms (no flat-earth approximation), so local positions stay
accurate for missions of any size."""
from __future__ import annotations

import math

import numpy as np

A = 6378137.0                 # WGS-84 semi-major axis (m)
F = 1.0 / 298.257223563       # flattening
E2 = F * (2.0 - F)            # first eccentricity squared


def geodetic_to_ecef(lat_deg: float, lon_deg: float, h: float) -> np.ndarray:
    lat, lon = math.radians(lat_deg), math.radians(lon_deg)
    s, c = math.sin(lat), math.cos(lat)
    N = A / math.sqrt(1.0 - E2 * s * s)
    return np.array([(N + h) * c * math.cos(lon), (N + h) * c * math.sin(lon), (N * (1 - E2) + h) * s])


def ecef_to_geodetic(x: float, y: float, z: float) -> tuple[float, float, float]:
    """Bowring's method with iteration (sub-mm accuracy)."""
    lon = math.atan2(y, x)
    p = math.hypot(x, y)
    lat = math.atan2(z, p * (1 - E2))
    h = 0.0
    for _ in range(6):
        s = math.sin(lat)
        N = A / math.sqrt(1 - E2 * s * s)
        h = p / math.cos(lat) - N
        lat = math.atan2(z, p * (1 - E2 * N / (N + h)))
    return math.degrees(lat), math.degrees(lon), h


def _R_ecef_to_ned(lat_deg: float, lon_deg: float) -> np.ndarray:
    lat, lon = math.radians(lat_deg), math.radians(lon_deg)
    sl, cl, so, co = math.sin(lat), math.cos(lat), math.sin(lon), math.cos(lon)
    return np.array([[-sl * co, -sl * so, cl],
                     [-so, co, 0.0],
                     [-cl * co, -cl * so, -sl]])


class LocalFrame:
    """North-East-Down frame with origin at the home point."""

    def __init__(self, lat0_deg: float, lon0_deg: float, h0_m: float):
        self.lat0, self.lon0, self.h0 = lat0_deg, lon0_deg, h0_m
        self.o = geodetic_to_ecef(lat0_deg, lon0_deg, h0_m)
        self.R = _R_ecef_to_ned(lat0_deg, lon0_deg)

    def to_ned(self, lat_deg: float, lon_deg: float, h_m: float) -> np.ndarray:
        return self.R @ (geodetic_to_ecef(lat_deg, lon_deg, h_m) - self.o)

    def to_geodetic(self, n: float, e: float, d: float) -> tuple[float, float, float]:
        x = self.o + self.R.T @ np.array([n, e, d])
        return ecef_to_geodetic(*x)
