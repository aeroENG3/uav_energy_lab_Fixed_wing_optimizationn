"""Control-surface (servo) and throttle actuator layer.

Each channel: command -> saturation [-1, 1] (throttle [0, 1]) -> deadband ->
rate limit -> first-order lag -> position sent to JSBSim's FCS
(fcs/*-cmd-norm; the aircraft FCS maps normalised position to radians).
Servo electrical power = idle power + k * |surface rate| (deg/s) per servo.
"""
from __future__ import annotations

import math

SURFACE_RANGE_DEG = {"aileron": 20.05, "elevator": 18.6, "rudder": 20.05}   # from the FCS tables


class Actuator:
    def __init__(self, cfg: dict, lo: float = -1.0, hi: float = 1.0, init: float = 0.0):
        self.tau = float(cfg["tau_s"])
        self.rate = float(cfg["rate_limit_norm_s"])
        self.db = float(cfg.get("deadband_norm", 0.0))
        self.lo, self.hi = lo, hi
        self.pos = init
        self._ref = init
        self.rate_now = 0.0

    def step(self, cmd: float, dt: float) -> float:
        cmd = min(max(cmd, self.lo), self.hi)
        if abs(cmd - self._ref) > self.db:
            self._ref = cmd
        prev = self.pos
        # first-order lag towards the reference, then rate limiting
        a = 1.0 - math.exp(-dt / self.tau) if self.tau > 0 else 1.0
        target = self.pos + a * (self._ref - self.pos)
        dmax = self.rate * dt
        self.pos = prev + min(max(target - prev, -dmax), dmax)
        self.rate_now = (self.pos - prev) / dt
        return self.pos


class ActuatorSet:
    def __init__(self, cfg: dict, cfg_avionics: dict):
        self.ail = Actuator(cfg["aileron"])
        self.elev = Actuator(cfg["elevator"])
        self.rud = Actuator(cfg["rudder"])
        self.thr = Actuator(cfg["throttle"], 0.0, 1.0, 0.0)
        self.p_idle = float(cfg_avionics["servo_idle_power_w"])
        self.k_move = float(cfg_avionics["servo_power_w_per_dps"])

    def step(self, ail, elev, rud, thr, dt):
        return (self.ail.step(ail, dt), self.elev.step(elev, dt), self.rud.step(rud, dt),
                self.thr.step(thr, dt))

    def servo_power(self) -> float:
        rates = (abs(self.ail.rate_now) * SURFACE_RANGE_DEG["aileron"] * 2.0,   # two aileron servos
                 abs(self.elev.rate_now) * SURFACE_RANGE_DEG["elevator"],
                 abs(self.rud.rate_now) * SURFACE_RANGE_DEG["rudder"])
        return 4 * self.p_idle + self.k_move * sum(rates)
