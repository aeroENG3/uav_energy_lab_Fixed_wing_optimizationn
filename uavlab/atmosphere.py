"""Atmosphere layer.

Thermodynamic state (T, p, rho, humidity) comes from JSBSim's US-1976 standard
atmosphere with an ISA temperature offset, sea-level pressure and relative
humidity (set in FDM.set_atmosphere). This module builds the WIND FIELD:

  total wind = mean(t, h)  [schedule + shear profile + veer + slow OU variability]
             + turbulence  [Dryden, MIL-F-8785C low-altitude form, or JSBSim's own]
             + discrete gusts [1-cosine / ramp-hold]

Conventions: NED frame, m/s. 'from_deg' is meteorological (the direction the
wind blows FROM); the NED vector points where the air moves TO.

References
  MIL-F-8785C (1980), sec. 3.7 - Dryden spectra, low-altitude scales/intensities.
  MIL-HDBK-1797 (1997), sec. 4.9 - atmospheric disturbances.
  Hoblit, "Gust Loads on Aircraft", AIAA 1988 - 1-cosine discrete gust.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy.linalg import expm

from .units import DEG, FT, KT

W20_BY_INTENSITY = {"light": 15 * KT, "moderate": 30 * KT, "severe": 45 * KT}   # MIL-F-8785C
JSBSIM_SEVERITY = {"light": 3, "moderate": 4, "severe": 6}   # prob. of exceedance 1e-2/1e-3/1e-5


def wind_vector_ned(speed: float, from_deg: float, vertical_up: float = 0.0) -> np.ndarray:
    th = from_deg * DEG
    return np.array([-speed * math.cos(th), -speed * math.sin(th), -vertical_up])


def shear_factor(h: float, cfg_mean: dict) -> float:
    """Ratio V(h)/V(h_ref) of the mean-wind profile."""
    sh = cfg_mean["shear"]
    href = float(cfg_mean["ref_height_m"])
    hmin = float(sh.get("min_height_m", 1.0))
    model = sh["model"]
    if model == "none":
        return 1.0
    if model == "power":
        return (max(h, hmin) / href) ** float(sh["alpha"])
    z0 = float(sh["z0_m"])
    hh = max(h, hmin, 1.01 * z0)
    return math.log(hh / z0) / math.log(href / z0)


def dryden_scales(h_agl_m: float, w20_mps: float):
    """MIL-F-8785C low-altitude (h < 1000 ft) turbulence scale lengths (m) and
    intensities (m/s). Height clamped to [10, 1000] ft as the spec prescribes."""
    h = min(max(h_agl_m / FT, 10.0), 1000.0)
    k = 0.177 + 0.000823 * h
    Lu = Lv = h / k ** 1.2 * FT
    Lw = h * FT
    sw = 0.1 * w20_mps
    su = sv = sw / k ** 0.4
    return (Lu, Lv, Lw), (su, sv, sw)


class _DrydenFirstOrder:
    """u-component: H(s) = sigma*sqrt(2L/(pi V)) / (1 + (L/V) s).
    Exact update x' = a x + sigma*sqrt(1-a^2) n, a = exp(-V dt / L)."""

    def __init__(self):
        self.x = 0.0

    def step(self, rng, sigma, L, V, dt):
        a = math.exp(-V * dt / L)
        self.x = a * self.x + sigma * math.sqrt(max(1.0 - a * a, 0.0)) * rng.standard_normal()
        return self.x


class _DrydenSecondOrder:
    """v/w-components: H(s) = sigma*sqrt(L/(pi V)) (1 + sqrt(3) (L/V) s) / (1 + (L/V) s)^2.
    Implemented as a 2-state system driven by continuous white noise of intensity
    pi (so output variance = sigma^2), discretised exactly with Van Loan's method.
    Discretisation is cached on T = L/V rounded to 0.5 %."""

    def __init__(self):
        self.x = np.zeros(2)
        self._cache = {}

    def _disc(self, T, dt):
        key = (round(math.log(T) / 0.005), round(dt * 1e6))
        if key in self._cache:
            return self._cache[key]
        Tq = math.exp(key[0] * 0.005)
        A = np.array([[0.0, 1.0], [-1.0 / Tq ** 2, -2.0 / Tq]])
        B = np.array([[0.0], [1.0 / Tq ** 2]])
        Qc = B @ B.T * math.pi
        M = np.zeros((4, 4))
        M[:2, :2] = -A
        M[:2, 2:] = Qc
        M[2:, 2:] = A.T
        E = expm(M * dt)
        Ad = E[2:, 2:].T
        Qd = Ad @ E[:2, 2:]
        Qd = 0.5 * (Qd + Qd.T)
        Lc = np.linalg.cholesky(Qd + 1e-18 * np.eye(2))
        out = (Ad, Lc, Tq)
        if len(self._cache) > 5000:
            self._cache.clear()
        self._cache[key] = out
        return out

    def step(self, rng, sigma, L, V, dt):
        T = L / V
        Ad, Lc, Tq = self._disc(T, dt)
        self.x = Ad @ self.x + Lc @ rng.standard_normal(2)
        K = sigma * math.sqrt(Tq / math.pi)
        return K * (self.x[0] + math.sqrt(3.0) * Tq * self.x[1])


@dataclass
class WindSample:
    mean: np.ndarray
    turb: np.ndarray
    gust: np.ndarray
    w20: float
    sigma_uvw: tuple
    scale_uvw: tuple

    @property
    def total(self):
        return self.mean + self.turb + self.gust


class WindField:
    def __init__(self, cfg_wind: dict, rng: np.random.Generator):
        self.cfg = cfg_wind
        self.rng = rng
        self.mean_cfg = cfg_wind["mean"]
        sched = sorted(self.mean_cfg.get("schedule") or [], key=lambda p: p["t_s"])
        self.sched = sched
        var = self.mean_cfg.get("variability") or {}
        self.var_on = bool(var.get("enabled", False))
        self.var_ss = float(var.get("speed_sigma_mps", 0.0))
        self.var_ds = float(var.get("dir_sigma_deg", 0.0))
        self.var_tau = float(var.get("tau_s", 300.0))
        self.ou_speed = 0.0
        self.ou_dir = 0.0
        tcfg = cfg_wind["turbulence"]
        self.turb_model = tcfg["model"]
        self.turb_intensity = tcfg.get("intensity", "auto")
        self.w20_fixed = tcfg.get("w20_mps")
        self.du, self.dv, self.dw = _DrydenFirstOrder(), _DrydenSecondOrder(), _DrydenSecondOrder()
        self.gusts = list(cfg_wind.get("gusts") or [])
        self._last_turb_axis = 0.0

    # ------------------------------------------------------------ mean wind
    def ref_speed_dir(self, t: float) -> tuple[float, float]:
        """Mean wind speed/direction at the reference height at time t
        (schedule interpolated component-wise, so direction wraps correctly)."""
        m = self.mean_cfg
        if not self.sched:
            spd, frm = float(m["speed_mps"]), float(m["from_deg"])
        else:
            ts = [p["t_s"] for p in self.sched]
            if t <= ts[0]:
                p = self.sched[0]
                spd, frm = p["speed_mps"], p["from_deg"]
            elif t >= ts[-1]:
                p = self.sched[-1]
                spd, frm = p["speed_mps"], p["from_deg"]
            else:
                i = int(np.searchsorted(ts, t)) - 1
                p0, p1 = self.sched[i], self.sched[i + 1]
                f = (t - p0["t_s"]) / (p1["t_s"] - p0["t_s"])
                v0 = wind_vector_ned(p0["speed_mps"], p0["from_deg"])
                v1 = wind_vector_ned(p1["speed_mps"], p1["from_deg"])
                v = v0 + f * (v1 - v0)
                spd = float(math.hypot(v[0], v[1]))
                frm = math.degrees(math.atan2(-v[1], -v[0])) % 360.0
        return spd, frm

    def advance_variability(self, dt: float):
        if not self.var_on:
            return
        a = math.exp(-dt / self.var_tau)
        s = math.sqrt(1 - a * a)
        self.ou_speed = a * self.ou_speed + self.var_ss * s * self.rng.standard_normal()
        self.ou_dir = a * self.ou_dir + self.var_ds * s * self.rng.standard_normal()

    def mean_wind(self, t: float, h_agl: float) -> np.ndarray:
        spd, frm = self.ref_speed_dir(t)
        spd = max(spd + self.ou_speed, 0.0)
        frm = frm + self.ou_dir
        m = self.mean_cfg
        spd_h = spd * shear_factor(h_agl, m)
        frm_h = frm + float(m.get("veer_deg_per_100m", 0.0)) * (h_agl - float(m["ref_height_m"])) / 100.0
        return wind_vector_ned(spd_h, frm_h, float(m.get("vertical_mps", 0.0)))

    def w20(self, t: float) -> float:
        if self.w20_fixed is not None:
            return float(self.w20_fixed)
        if self.turb_intensity in W20_BY_INTENSITY:
            return W20_BY_INTENSITY[self.turb_intensity]
        spd, _ = self.ref_speed_dir(t)
        return max(spd + self.ou_speed, 0.0) * shear_factor(20 * FT, self.mean_cfg)

    # ------------------------------------------------------------ gusts
    def gust_wind(self, t: float) -> np.ndarray:
        g = np.zeros(3)
        for gs in self.gusts:
            t0, dur = float(gs["t_s"]), float(gs["duration_s"])
            tau = t - t0
            if tau < 0:
                continue
            shape = gs.get("shape", "one_minus_cos")
            if shape == "one_minus_cos":
                if tau > dur:
                    continue
                f = 0.5 * (1.0 - math.cos(2.0 * math.pi * tau / dur))
            elif shape == "ramp_hold":
                hold = float(gs.get("hold_s", 1e9))
                if tau <= dur:
                    f = 0.5 * (1.0 - math.cos(math.pi * tau / dur))
                elif tau <= dur + hold:
                    f = 1.0
                else:
                    continue
            else:
                raise ValueError(f"unknown gust shape {shape}")
            g += f * wind_vector_ned(float(gs.get("amplitude_mps", 0.0)), float(gs.get("from_deg", 0.0)),
                                     float(gs.get("vertical_mps", 0.0)))
        return g

    # ------------------------------------------------------------ sample
    def sample(self, t: float, h_agl: float, tas: float, heading: float, dt: float) -> WindSample:
        self.advance_variability(dt)
        mean = self.mean_wind(t, h_agl)
        gust = self.gust_wind(t)
        turb = np.zeros(3)
        w20 = self.w20(t)
        scales, sig = dryden_scales(h_agl, w20)
        if self.turb_model == "dryden" and w20 > 0:
            V = max(tas, 3.0)   # Taylor frozen-turbulence speed, floored for ground roll
            u = self.du.step(self.rng, sig[0], scales[0], V, dt)
            v = self.dv.step(self.rng, sig[1], scales[1], V, dt)
            w = self.dw.step(self.rng, sig[2], scales[2], V, dt)
            # low-altitude axes: u along the mean wind, v across, w vertical (down +)
            hm = math.hypot(mean[0], mean[1])
            ax = math.atan2(mean[1], mean[0]) if hm > 0.1 else heading
            c, s = math.cos(ax), math.sin(ax)
            turb = np.array([c * u - s * v, s * u + c * v, w])
        return WindSample(mean=mean, turb=turb, gust=gust, w20=w20, sigma_uvw=sig, scale_uvw=scales)
