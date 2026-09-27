"""Sensor layer (what the autopilot sees) and wind-triangle estimator.

Sensors are modelled as truth + zero-mean Gaussian noise at the control rate
(no bias, no latency). Set sensors.noise_enabled: false for an ideal-sensor
baseline. Sideslip is treated as known (as if estimated from a lateral
accelerometer); real vehicles do not measure it directly.
"""
from __future__ import annotations

import math

import numpy as np

from .units import DEG, wrap_pi


class _GaussMarkov:
    """First-order Gauss-Markov error: stationary std sigma, correlation time tau."""

    def __init__(self, rng, sigma, tau):
        self.rng, self.sigma, self.tau, self.x = rng, sigma, tau, rng.standard_normal() * sigma

    def step(self, dt):
        a = math.exp(-dt / self.tau)
        self.x = a * self.x + self.sigma * math.sqrt(1 - a * a) * self.rng.standard_normal()
        return self.x


class Sensors:
    """Navigation-estimate errors (what an EKF would output) are first-order
    Gauss-Markov processes with the configured std and correlation time;
    raw inertial signals (gyro, accelerometer) get white noise."""

    GM = {  # name: (sigma key, scale, correlation time s)
        "tas": ("airspeed_sigma_mps", 1.0, 0.5), "n": ("gps_pos_sigma_m", 1.0, 5.0),
        "e": ("gps_pos_sigma_m", 1.0, 5.0), "vn": ("gps_vel_sigma_mps", 1.0, 1.0),
        "ve": ("gps_vel_sigma_mps", 1.0, 1.0), "vd": ("gps_vel_sigma_mps", 1.0, 1.0),
        "h": ("baro_alt_sigma_m", 1.0, 2.0), "phi": ("attitude_sigma_deg", DEG, 1.0),
        "theta": ("attitude_sigma_deg", DEG, 1.0), "psi": ("heading_sigma_deg", DEG, 5.0),
    }

    def __init__(self, cfg: dict, rng: np.random.Generator, dt: float = 0.02):
        self.c = cfg
        self.on = bool(cfg.get("noise_enabled", True))
        self.rng = rng
        self.dt = dt
        self.gm = {k: _GaussMarkov(rng, float(cfg[s]) * sc, tau) for k, (s, sc, tau) in self.GM.items()}

    def _n(self, sigma):
        return self.rng.standard_normal() * sigma if self.on else 0.0

    def _g(self, k):
        return self.gm[k].step(self.dt) if self.on else 0.0

    def measure(self, x: dict, ne: np.ndarray) -> dict:
        c = self.c
        m = {}
        m["t"] = x["t"]
        m["tas"] = max(x["tas"] + self._g("tas"), 0.0)
        m["n"] = ne[0] + self._g("n")
        m["e"] = ne[1] + self._g("e")
        m["vn"] = x["vn"] + self._g("vn")
        m["ve"] = x["ve"] + self._g("ve")
        m["vd"] = x["vd"] + self._g("vd")
        m["h"] = x["h_agl"] + self._g("h")
        m["phi"] = x["phi"] + self._g("phi")
        m["theta"] = x["theta"] + self._g("theta")
        m["psi"] = wrap_pi(x["psi"] + self._g("psi"))
        m["p"] = x["p"] + self._n(c["gyro_sigma_dps"] * DEG)
        m["q"] = x["q"] + self._n(c["gyro_sigma_dps"] * DEG)
        m["r"] = x["r"] + self._n(c["gyro_sigma_dps"] * DEG)
        m["ax"] = x["ax"] + self._n(c.get("accel_sigma_mps2", 0.1))
        m["beta"] = x["beta"]
        m["gs"] = math.hypot(m["vn"], m["ve"])
        m["course"] = math.atan2(m["ve"], m["vn"])
        m["wow"] = x["wow"] > 0.5
        return m


class WindEstimator:
    """Horizontal wind from the wind triangle W = V_ground - V_air, with
    V_air ~ TAS*cos(theta)*[cos psi, sin psi] (sideslip neglected), low-pass
    filtered with time constant tau."""

    def __init__(self, tau_s: float, tau_mean_s: float = 60.0, gust_window_s: float = 30.0):
        self.tau = tau_s
        self.tau_mean = tau_mean_s
        self.w = np.zeros(2)          # fast estimate (guidance, policy)
        self.w_mean = np.zeros(2)     # slow estimate (energy prediction, planning)
        self.init = False
        self._var = 0.0               # running variance of the fast estimate about the mean
        self.gust_window = gust_window_s

    @property
    def gust_sigma(self) -> float:
        """Std of the horizontal wind about its slow mean (gust/turbulence level)."""
        return math.sqrt(max(self._var, 0.0))

    def update(self, m: dict, dt: float, airborne: bool) -> np.ndarray:
        if not airborne or m["tas"] < 5.0:
            return self.w
        va = m["tas"] * math.cos(m["theta"])
        raw = np.array([m["vn"] - va * math.cos(m["psi"]), m["ve"] - va * math.sin(m["psi"])])
        if not self.init:
            self.w, self.w_mean, self.init = raw.copy(), raw.copy(), True
        else:
            self.w = self.w + dt / (self.tau + dt) * (raw - self.w)
            self.w_mean = self.w_mean + dt / (self.tau_mean + dt) * (raw - self.w_mean)
            # gust level only from wings-level, steady segments (the wind-triangle
            # estimate is biased in turns because sideslip and alpha are neglected)
            if abs(m["phi"]) < math.radians(10.0):
                d = raw - self.w_mean
                self._var += dt / (self.gust_window + dt) * (0.5 * float(d @ d) - self._var)
        return self.w

    @staticmethod
    def along_cross(w_ne: np.ndarray, track_rad: float) -> tuple[float, float]:
        """Tail-wind (+) and cross-wind (+ from the left, pushing right) components
        relative to a track direction."""
        c, s = math.cos(track_rad), math.sin(track_rad)
        return float(w_ne[0] * c + w_ne[1] * s), float(-w_ne[0] * s + w_ne[1] * c)
