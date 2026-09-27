"""Online policy plug-ins for the autonomy layer (the adaptive-optimiser slot).

A policy is called every control step in MISSION mode with an observation dict
and may return {'airspeed_mps': ..., 'alt_agl_m': ...}; missing keys leave the
mission defaults. Register new policies with @register("name").

Observation keys: t, tas, gs, h, soc, p_batt, wind_ne (estimated, N/E m/s),
tailwind, crosswind (along the current leg), leg, leg_track (rad),
dist_to_wp, v_default, h_default.
"""
from __future__ import annotations

import math

import numpy as np

REGISTRY: dict[str, type] = {}


def register(name):
    def deco(cls):
        REGISTRY[name] = cls
        return cls
    return deco


def make_policy(cfg_policy: dict | None):
    if not cfg_policy:
        return None
    name = cfg_policy.get("name", "fixed")
    if name not in REGISTRY:
        raise KeyError(f"unknown policy '{name}'. Registered: {sorted(REGISTRY)}")
    return REGISTRY[name](**(cfg_policy.get("params") or {}))


class Policy:
    def reset(self):
        pass

    def update(self, obs: dict) -> dict:
        return {}


@register("fixed")
class FixedPolicy(Policy):
    """Baseline: fly the mission's airspeed and altitude unchanged."""

    def __init__(self, **_):
        pass


@register("external")
class ExternalPolicy(Policy):
    """Set-points written from outside (the Gymnasium env, a notebook, an optimiser)."""

    def __init__(self, **_):
        self.airspeed_mps = None
        self.alt_agl_m = None

    def update(self, obs):
        return {"airspeed_mps": self.airspeed_mps, "alt_agl_m": self.alt_agl_m}


@register("wind_aware_best_range")
class WindAwareBestRange(Policy):
    """Speed-to-fly for minimum battery energy per metre of ground track.

    Battery power model P(V) = a*V^3 + b/V + c (parasite + induced + fixed loads),
    with coefficients from a performance sweep (see validation/performance.py)
    and optionally refined online by recursive least squares on steady-flight
    samples. For tail-wind W_a and cross-wind W_c on the current leg:
        V_g(V) = sqrt(V^2 - W_c^2) + W_a,   V* = argmin_V P(V) / V_g(V)
    This is the classic 'speed-to-fly in wind' result: fly faster into a head-wind,
    slower with a tail-wind.
    """

    # default coefficients: `python -m uavlab performance` fit for the default
    # configuration at the example field (rho = 1.143 kg/m^3, mass 6.15 kg)
    def __init__(self, a=0.02029, b=176.6, c=88.62, v_min=12.0, v_max=26.0, dv=0.25,
                 smooth_tau_s=10.0, online_rls=False, rls_forget=0.999):
        self.theta = np.array([a, b, c], float)
        self.v_grid = np.arange(v_min, v_max + 1e-9, dv)
        self.tau = smooth_tau_s
        self.v_cmd = None
        self.t_prev = None
        self.rls = online_rls
        self.lam = rls_forget
        self.P = np.eye(3) * 1e3
        self._last_v = None

    def power(self, v):
        a, b, c = self.theta
        return a * v ** 3 + b / v + c

    def _rls_update(self, v, p):
        phi = np.array([v ** 3, 1.0 / v, 1.0])
        k = self.P @ phi / (self.lam + phi @ self.P @ phi)
        self.theta = self.theta + k * (p - phi @ self.theta)
        self.P = (self.P - np.outer(k, phi) @ self.P) / self.lam

    def update(self, obs):
        t = obs["t"]
        dt = 0.0 if self.t_prev is None else t - self.t_prev
        self.t_prev = t
        if self.rls and obs["tas"] > 10 and self._last_v is not None and abs(obs["tas"] - self._last_v) < 0.05:
            self._rls_update(obs["tas"], obs["p_batt"])
        self._last_v = obs["tas"]
        # use the slow (mean) wind estimate: speed-to-fly should not chase gusts
        wa = obs.get("tailwind_mean", obs["tailwind"])
        wc = obs.get("crosswind_mean", obs["crosswind"])
        v = self.v_grid
        vg = np.sqrt(np.maximum(v * v - wc * wc, 1e-3)) + wa
        cost = np.where(vg > 1.0, self.power(v) / vg, np.inf)
        v_star = float(v[int(np.argmin(cost))])
        if self.v_cmd is None:
            self.v_cmd = v_star
        else:
            k = dt / (self.tau + dt) if dt > 0 else 0.0
            self.v_cmd += k * (v_star - self.v_cmd)
        return {"airspeed_mps": self.v_cmd}


@register("linear_wind")
class LinearWindPolicy(Policy):
    """Parametric wind-adaptive law, made to be tuned by the optimiser:

        V_cmd = v0 + k_head * headwind + k_cross * |crosswind| + k_gust * gust_sigma
        h_cmd = h_mission + dh

    with the slow (60 s) wind estimate along/across the current leg. The classical
    speed-to-fly result predicts k_head of about 0.4-0.6 for this class of aircraft."""

    def __init__(self, v0=15.0, k_head=0.5, k_cross=0.0, k_gust=0.0, dh=0.0, v_min=12.0, v_max=26.0):
        self.v0, self.k_head, self.k_cross, self.k_gust, self.dh = v0, k_head, k_cross, k_gust, dh
        self.v_min, self.v_max = v_min, v_max

    def update(self, obs):
        head = -obs.get("tailwind_mean", obs["tailwind"])
        cross = abs(obs.get("crosswind_mean", obs["crosswind"]))
        v = self.v0 + self.k_head * head + self.k_cross * cross + self.k_gust * obs.get("gust_sigma", 0.0)
        out = {"airspeed_mps": min(max(v, self.v_min), self.v_max)}
        if self.dh:
            out["alt_agl_m"] = obs["h_default"] + self.dh
        return out


def policy_parameters(name: str) -> dict:
    """Constructor parameters and defaults of a registered policy (for the UI)."""
    import inspect
    cls = REGISTRY[name]
    sig = inspect.signature(cls.__init__)
    out = {}
    for pname, p in sig.parameters.items():
        if pname in ("self",) or p.kind in (p.VAR_KEYWORD, p.VAR_POSITIONAL):
            continue
        if p.default is not inspect.Parameter.empty:
            out[pname] = p.default
    return out


def policy_doc(name: str) -> str:
    import inspect
    return inspect.getdoc(REGISTRY[name]) or ""
