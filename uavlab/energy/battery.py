"""LiPo battery pack: 1-RC Thevenin equivalent-circuit model.

    V_term = N_s * OCV_cell(SOC) - I * R0 - V_1
    dV_1/dt = -V_1/(R1*C1) + I/C1                  (discretised exactly for constant I)
    dSOC/dt = -I / (3600 * Q_Ah)                   (coulomb counting)

Pack parameters are built from per-cell values: R_pack = N_s*R_cell/N_p (+ wiring),
C_pack = C_cell*N_p/N_s, Q_pack = N_p*Q_cell*derate.
Energy bookkeeping is exact per step, so chemical energy = terminal energy +
R0 heat + R1 heat + change of energy stored in C1 (checked in the V&V suite).

Reference: Plett, "Battery Management Systems, Vol. 1: Battery Modeling", Artech
House 2015, ch. 2 (equivalent-circuit cell models).
"""
from __future__ import annotations

import math

import numpy as np


class Battery:
    def __init__(self, cfg: dict):
        self.ns = int(cfg["cells_series"])
        self.np_ = int(cfg["cells_parallel"])
        self.capacity_ah = float(cfg["capacity_ah"]) * self.np_ * float(cfg.get("capacity_derate", 1.0))
        self.r0 = self.ns * float(cfg["r0_cell_ohm"]) / self.np_ + float(cfg.get("wiring_resistance_ohm", 0.0))
        self.r1 = self.ns * float(cfg["r1_cell_ohm"]) / self.np_
        self.c1 = float(cfg["c1_cell_f"]) * self.np_ / self.ns
        self.tau = self.r1 * self.c1
        self._soc_tab = np.asarray(cfg["ocv_table"]["soc"], float)
        self._v_tab = np.asarray(cfg["ocv_table"]["v"], float)
        self.cutoff_cell_v = float(cfg["cell_cutoff_v"])
        self.soc = float(cfg["soc_init"])
        self.v1 = 0.0
        self.i = 0.0
        self.depleted = False
        self.depleted_reason = ""
        self.v_cell_filt = None
        self._e_c1_delta = 0.0
        # energy meters (J)
        self.e_chem = 0.0
        self.e_term = 0.0
        self.e_r0 = 0.0
        self.e_r1 = 0.0
        self.ah_out = 0.0

    # ------------------------------------------------------------------
    def ocv_cell(self, soc: float | None = None) -> float:
        s = self.soc if soc is None else soc
        return float(np.interp(min(max(s, 0.0), 1.0), self._soc_tab, self._v_tab))

    def ocv(self) -> float:
        return self.ns * self.ocv_cell()

    def source_voltage(self) -> float:
        """OCV minus the polarisation voltage: the Thevenin source behind R0."""
        return self.ocv() - self.v1

    def terminal_voltage(self, i: float) -> float:
        return self.source_voltage() - i * self.r0

    def energy_capacity_wh(self) -> float:
        """Total chemical energy between SOC=0 and 1 (Wh) = Q * integral(OCV dSOC)."""
        s = np.linspace(0, 1, 2001)
        v = np.interp(s, self._soc_tab, self._v_tab) * self.ns
        return float(np.trapezoid(v, s) * self.capacity_ah)

    def stored_c1_energy(self) -> float:
        return 0.5 * self.c1 * self.v1 ** 2

    # ------------------------------------------------------------------
    def step(self, i: float, dt: float) -> None:
        """Advance with constant current i (A, + = discharge) over dt (s)."""
        ocv = self.ocv()
        v1_0 = self.v1
        a = math.exp(-dt / self.tau) if self.tau > 0 else 0.0
        v1_1 = v1_0 * a + self.r1 * (1.0 - a) * i
        # exact integral of v1 over the step (for energy bookkeeping)
        int_v1 = self.r1 * i * dt + (v1_0 - self.r1 * i) * self.tau * (1.0 - a)
        # exact integral of v1^2 / R1 (heat in R1):
        #   v1(t) = R1 i + (v1_0 - R1 i) e^{-t/tau}
        b = v1_0 - self.r1 * i
        int_v1sq = ((self.r1 * i) ** 2 * dt + 2 * self.r1 * i * b * self.tau * (1 - a)
                    + b * b * self.tau / 2.0 * (1 - a * a))
        e_c1_before = self.stored_c1_energy()
        self.v1 = v1_1
        e_c1_after = self.stored_c1_energy()

        dq = i * dt  # coulombs
        # Chemical energy uses OCV at the start of the step (first order in dSOC).
        self.e_chem += ocv * dq
        self.e_r0 += i * i * self.r0 * dt
        self.e_r1 += int_v1sq / self.r1 if self.r1 > 0 else 0.0
        self.e_term += (ocv * dq - i * i * self.r0 * dt - i * int_v1)
        self._e_c1_delta = e_c1_after - e_c1_before
        self.ah_out += dq / 3600.0
        self.soc -= dq / 3600.0 / self.capacity_ah
        self.i = i
        v_cell_loaded = (ocv - i * self.r0 - self.v1) / self.ns
        # ESC-style low-voltage cut-off acts on a 1 s filtered cell voltage so a
        # millisecond current spike does not trip it.
        k = dt / (1.0 + dt)
        self.v_cell_filt = v_cell_loaded if self.v_cell_filt is None else \
            self.v_cell_filt + k * (v_cell_loaded - self.v_cell_filt)
        if self.soc <= 0.0 and not self.depleted:
            self.depleted, self.depleted_reason = True, "soc_zero"
        elif self.v_cell_filt < self.cutoff_cell_v and not self.depleted:
            self.depleted, self.depleted_reason = True, "cell_voltage_cutoff"
