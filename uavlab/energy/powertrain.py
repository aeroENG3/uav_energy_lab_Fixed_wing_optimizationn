"""Electric powertrain: battery -> ESC -> motor -> (JSBSim propeller).

Each physics step:
  1. Read propeller speed omega from JSBSim (end of the previous step).
  2. Solve the electrical network (battery Thevenin source, R0, averaged ESC,
     motor winding) for the bus voltage and currents at throttle d.
  3. Give the motor shaft torque to JSBSim, which integrates the rotor speed
     I_rotor * domega/dt = Q_motor - Q_prop(J, RPM) and computes thrust.
  4. Advance the battery state and all energy meters.

ESC (averaged switch model):
  V_m   = d * V_bus - I_m * R_esc                        (motor terminal voltage)
  I_in  = d * I_m + (k_sw * V_bus * I_m + P_q) / V_bus  (ESC input current)
  P_esc = I_m^2 R_esc + k_sw V_bus I_m + P_q            (loss; exact power balance)
Current limiting reduces the effective duty so that I_m <= I_max. Without regen
(default) the freewheel diode blocks negative winding current (I_m >= 0).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .battery import Battery
from .motor import Motor


@dataclass
class PowertrainSample:
    throttle: float = 0.0
    duty_eff: float = 0.0
    omega: float = 0.0
    v_bus: float = 0.0
    i_batt: float = 0.0
    i_esc_in: float = 0.0
    i_motor: float = 0.0
    v_motor: float = 0.0
    back_emf: float = 0.0
    torque: float = 0.0
    p_batt_chem: float = 0.0
    p_batt_term: float = 0.0
    p_batt_loss: float = 0.0
    p_esc_in: float = 0.0
    p_esc_loss: float = 0.0
    p_motor_in: float = 0.0
    p_copper: float = 0.0
    p_iron: float = 0.0
    p_shaft: float = 0.0
    p_avionics: float = 0.0
    current_limited: bool = False
    regime: str = "normal"


class Powertrain:
    def __init__(self, cfg_pt: dict):
        self.battery = Battery(cfg_pt["battery"])
        self.motor = Motor(cfg_pt["motor"])
        esc = cfg_pt["esc"]
        self.r_esc = float(esc["resistance_ohm"])
        self.k_sw = float(esc["switching_loss_frac"])
        self.p_q = float(esc["quiescent_power_w"])
        self.regen = bool(esc.get("allow_regen", False))
        self.p_avionics_extra = 0.0          # servo power etc., set each step by the caller
        av = cfg_pt["avionics"]
        self.p_avionics_base = float(av["base_power_w"])
        self.s = PowertrainSample()
        # energy meters (J)
        self.e = {k: 0.0 for k in ("esc_loss", "copper", "iron", "shaft", "avionics", "motor_in")}

    # ------------------------------------------------------------------
    @staticmethod
    def _quad_root(a2: float, a1: float, a0: float) -> float:
        """Larger root of a2 v^2 - a1 v + a0 = 0 (the physical bus voltage)."""
        disc = a1 * a1 - 4.0 * a2 * a0
        if disc < 0.0:          # load exceeds what the source can deliver (collapse)
            disc = 0.0
        return (a1 + disc ** 0.5) / (2.0 * a2)

    def _solve(self, d: float, omega: float, p_aux: float):
        """Closed-form solution of the bus voltage for the three ESC regimes
        (normal, current-limited, freewheeling). Each regime gives a quadratic
        in V_bus from V = V_s - R0 * I_batt(V)."""
        m, b = self.motor, self.battery
        vs, r0 = b.source_voltage(), b.r0
        e_emf = m.back_emf(omega)
        R = m.r + self.r_esc
        k = self.k_sw
        P = p_aux + (self.p_q if d > 0 else 0.0)
        regime = "normal"
        # --- normal regime: I_m = (d V - E)/R,  I_b = (d + k s)(d V - E)/R + P/V
        sgn = 1.0 if d * vs - e_emf >= 0 else -1.0
        a = (d + k * sgn) * d / R
        c = (d + k * sgn) * e_emf / R
        v = self._quad_root(1.0 + r0 * a, vs + r0 * c, r0 * P)
        i_m = (d * v - e_emf) / R if d > 0 else 0.0
        d_eff = d
        if i_m > m.i_max:
            regime = "limited"
            i_m = m.i_max
            v = self._quad_root(1.0, vs - r0 * k * i_m, r0 * ((e_emf + i_m * R) * i_m + P))
            d_eff = min((e_emf + i_m * R) / max(v, 1e-6), 1.0)
        elif i_m < 0.0 and not self.regen:
            regime = "freewheel"
            i_m, d_eff = 0.0, (d if d > 0 else 0.0)
            v = self._quad_root(1.0, vs, r0 * P)
        i_in = d_eff * i_m + (k * v * abs(i_m) + (self.p_q if d > 0 else 0.0)) / max(v, 1e-6)
        i_b = i_in + p_aux / max(v, 1e-6)
        # residual of V = Vs - R0*I_b (should be ~1e-12; checked in V&V)
        self.solve_residual = v - (vs - r0 * i_b)
        return v, i_m, d_eff, i_in, i_b, regime == "limited", regime

    def step(self, throttle: float, omega: float, dt: float) -> float:
        """Advance one step; returns motor shaft torque (N*m) for JSBSim."""
        d = min(max(throttle, 0.0), 1.0)
        m, b = self.motor, self.battery
        if b.depleted:
            d = 0.0
        p_aux = self.p_avionics_base + self.p_avionics_extra
        v, i_m, d_eff, i_in, i_b, limited, regime = self._solve(d, omega, p_aux)
        e_emf = m.back_emf(omega)
        v_m = d_eff * v - i_m * self.r_esc
        q = m.torque(i_m, omega)
        s = self.s
        s.throttle, s.duty_eff, s.omega, s.v_bus = d, d_eff, omega, v
        s.i_batt, s.i_esc_in, s.i_motor, s.v_motor, s.back_emf = i_b, i_in, i_m, v_m, e_emf
        s.torque = q
        s.p_motor_in = v_m * i_m
        s.p_copper = i_m * i_m * m.r
        s.p_iron = m.i0(omega) * e_emf if omega > 1e-3 else 0.0
        s.p_shaft = q * omega
        s.p_esc_in = v * i_in
        s.p_esc_loss = s.p_esc_in - s.p_motor_in
        s.p_avionics = p_aux
        s.current_limited, s.regime = limited, regime
        ocv = b.ocv()
        s.p_batt_chem = ocv * i_b
        s.p_batt_term = v * i_b
        s.p_batt_loss = s.p_batt_chem - s.p_batt_term
        b.step(i_b, dt)
        self.e["esc_loss"] += s.p_esc_loss * dt
        self.e["copper"] += s.p_copper * dt
        self.e["iron"] += s.p_iron * dt
        self.e["shaft"] += s.p_shaft * dt
        self.e["avionics"] += p_aux * dt
        self.e["motor_in"] += s.p_motor_in * dt
        return q
