"""Brushless DC motor: first-order (quasi-static) model.

    E   = omega / Kv                    back-EMF (Kv in rad/s/V)
    I   = (V_m - E) / R                 winding current
    Q   = (I - I0) / Kv                 shaft torque (Kq = Kv in SI units)
    P_shaft = Q * omega,  P_copper = I^2 R,  P_iron = I0 * E

The electrical time constant L/R (~0.1 ms) is far below the 5 ms step, so the
quasi-static form is appropriate. Reference: M. Drela, "First-Order DC Electric
Motor Model", MIT Aero & Astro, Feb. 2007 (the QPROP motor model).
"""
from __future__ import annotations

import math


class Motor:
    def __init__(self, cfg: dict):
        self.kv_rpm = float(cfg["kv_rpm_per_v"])
        self.kv = self.kv_rpm * math.pi / 30.0            # rad/s per V
        self.r = float(cfg["resistance_ohm"])
        self.i0_ref = float(cfg["no_load_current_a"])
        self.i0_vref = float(cfg.get("i0_ref_voltage_v", 10.0))
        self.i0_exp = float(cfg.get("i0_voltage_exponent", 0.0))
        self.i_max = float(cfg["max_current_a"])

    def i0(self, omega: float) -> float:
        if self.i0_exp == 0.0:
            return self.i0_ref
        e = max(omega / self.kv, 1e-6)
        return self.i0_ref * (e / self.i0_vref) ** self.i0_exp

    def back_emf(self, omega: float) -> float:
        return omega / self.kv

    def torque(self, i: float, omega: float) -> float:
        """Shaft torque; no-load (friction/iron) torque opposes rotation and
        cannot drive a stationary rotor."""
        i0 = self.i0(omega)
        if omega > 1e-3:
            return (i - i0) / self.kv
        return max(i - i0, 0.0) / self.kv

    # analytic reference points (used by the V&V suite)
    def no_load_speed_rad_s(self, v: float) -> float:
        return self.kv * (v - self.i0_ref * self.r)

    def max_efficiency_current(self, v: float) -> float:
        """Current of peak efficiency at fixed terminal voltage: I = sqrt(I0 * V / R)."""
        return math.sqrt(self.i0_ref * v / self.r)
