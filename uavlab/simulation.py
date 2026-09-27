"""Simulation orchestrator: runs the full pipeline and writes the logs.

Per physics step (dt, default 5 ms):
  atmosphere/wind  -> JSBSim wind inputs
  [control tick]   sensors -> autonomy (mission, decisions, policy) -> controllers
  actuators        -> JSBSim FCS inputs
  powertrain       -> motor torque into JSBSim's propeller ODE
  JSBSim step      -> 6-DoF flight dynamics
  energy ledger    -> electrical + mechanical + wind energy terms
  [log tick]       -> time-series row
"""
from __future__ import annotations

import json
import math
import platform
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import yaml

import jsbsim

from . import __version__
from .actuators import ActuatorSet
from .atmosphere import JSBSIM_SEVERITY, WindField
from .autonomy import TERMINAL, Autopilot
from .config import config_hash
from .energy.powertrain import Powertrain
from .fdm import FDM
from .logger import RunLogger
from .mission import Mission
from .models import build_model_dir
from .policies import make_policy
from .sensors import Sensors, WindEstimator
from .units import DEG, FT, IN, RPM, wrap_pi

# structure points (JSBSim structural frame, inches; x aft, y right, z up) for crash detection
STRUCT_POINTS_IN = {"PROP_TIP": (1, 0, -9), "NOSE": (3, 0, -4), "LEFT_WINGTIP": (37, -55, 4),
                    "RIGHT_WINGTIP": (37, 55, 4), "BELLY": (45, 0, -5)}


def _dcm_b2n(phi, theta, psi):
    cp, sp, ct, st, cs, ss = math.cos(phi), math.sin(phi), math.cos(theta), math.sin(theta), math.cos(psi), math.sin(psi)
    return np.array([[ct * cs, sp * st * cs - cp * ss, cp * st * cs + sp * ss],
                     [ct * ss, sp * st * ss + cp * cs, cp * st * ss - sp * cs],
                     [-st, sp * ct, cp * ct]])


@dataclass
class RunResult:
    run_dir: Path | None
    summary: dict
    status: str
    timeseries: object = None     # pandas DataFrame
    events: list = field(default_factory=list)


class Simulation:
    def __init__(self, cfg: dict, run_dir: str | Path | None = None, policy=None, run_id: str | None = None,
                 write_logs: bool = True, keep_timeseries: bool = True, on_row=None, on_event=None):
        """on_row(row_dict) is called at every log tick and on_event(event_dict) for every
        event; both are optional hooks used by the UI for live telemetry."""
        self.on_row = on_row
        self.on_event = on_event
        self.cfg = cfg
        self.cfg_hash = config_hash(cfg)
        self.run_id = run_id or datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
        self.write_logs = write_logs
        self.keep_ts = keep_timeseries
        if write_logs:
            base = Path(cfg["logging"]["out_dir"])
            self.run_dir = Path(run_dir) if run_dir else base / self.run_id
            self.run_dir.mkdir(parents=True, exist_ok=True)
            self.model_root = self.run_dir / "jsbsim"
        else:
            self.run_dir = None
            self._tmp = tempfile.TemporaryDirectory(prefix="uavlab_", ignore_cleanup_errors=True)
            self.model_root = Path(self._tmp.name)
        self.policy = policy if policy is not None else make_policy(cfg["autonomy"].get("policy"))
        self._setup()

    # ------------------------------------------------------------------ setup
    def _setup(self):
        cfg = self.cfg
        s = cfg["sim"]
        self.dt = float(s["dt_physics_s"])
        self.n_ctrl = int(round(1.0 / (self.dt * s["control_rate_hz"])))
        self.n_log = max(1, int(round(1.0 / (self.dt * s["log_rate_hz"]))))
        self.t_max = float(s["t_max_s"])
        ss = np.random.SeedSequence(int(s["seed"]))
        r_wind, r_sens, r_misc = [np.random.default_rng(x) for x in ss.spawn(3)]
        self.model_info = build_model_dir(cfg, self.model_root, self.run_id, self.cfg_hash)
        self.fdm = FDM(self.model_root, self.dt)
        a = cfg["atmosphere"]
        self.fdm.set_atmosphere(a["delta_T_K"], a["sl_pressure_pa"], a["relative_humidity_pct"])
        self.fdm.set_seed(int(s["seed"]))
        self.wind = WindField(cfg["wind"], r_wind)
        tc = cfg["wind"]["turbulence"]
        if tc["model"] == "jsbsim_milspec":
            inten = tc["intensity"] if tc["intensity"] != "auto" else "light"
            self.fdm.set_jsbsim_turbulence(self.wind.w20(0.0), JSBSIM_SEVERITY[inten])
        self.mission = Mission(cfg)
        self.pt = Powertrain(cfg["powertrain"])
        self.act = ActuatorSet(cfg["actuators"], cfg["powertrain"]["avionics"])
        self.sensors = Sensors(cfg["sensors"], r_sens, dt=1.0 / s["control_rate_hz"])
        self.log = RunLogger(self)
        self.ap = Autopilot(cfg, self.mission, self.policy, self.log.event)
        if self.policy is not None and hasattr(self.policy, "reset"):
            self.policy.reset()
        # ---- pre-flight decision on the reported surface wind (10 m anemometer)
        w10 = self.wind.mean_wind(0.0, 10.0)[:2]
        ok = self.ap.preflight_decision(0.0, w10)
        rw = self.mission.runway
        if rw is None:
            self.mission.choose_runway(w10)
            rw = self.mission.runway
        start_ne = rw.start + 5.0 * rw.u
        lat, lon, _ = self.mission.frame.to_geodetic(start_ne[0], start_ne[1], 0.0)
        ws = self.wind.sample(0.0, 0.4, 0.0, rw.heading, self.dt)
        self.fdm.set_wind(ws.mean, ws.turb + ws.gust)
        self.fdm.init_on_ground(lat, lon, self.mission.field_elev, math.degrees(rw.heading))
        self._cg_in = (self.fdm.fdm["inertia/cg-x-in"], 0.0, self.fdm.fdm["inertia/cg-z-in"])
        self.capacity_j = self.pt.battery.energy_capacity_wh() * 3600.0
        self.soc0 = self.pt.battery.soc
        self.k = 0
        self.t = 0.0
        self.status = "RUNNING" if ok else "NO_GO"
        self.term_reason = "" if ok else "no_go"
        self.cmd = None
        self.sp = None
        self.m = None
        self.pos_ne = np.array(start_ne, float)
        self.ws = ws
        self._x = self.fdm.state()
        self._energy_prev = None
        self.E = {k: 0.0 for k in ("aero", "prop", "gear", "wind", "drag", "thrust_useful", "prop_req")}
        self.E_air0 = None
        self.max_sink_td = None
        self.crash_point = None
        self.wall0 = time.time()
        self._took_off = False
        self.t_takeoff = None
        self.t_landed = None
        self.dist_ground = 0.0
        self.dist_air = 0.0

    # ------------------------------------------------------------ energy ledger
    def _energy_terms(self, x):
        """Air-relative mechanical energy and the powers that change it.
        dE_air/dt = F.V_a - m g W_down - m V_a.dW/dt,  E_air = 1/2 m V_a^2 + m g h."""
        m, g = x["mass"], x["g"]
        va_b = np.array([x["u_air"], x["v_air"], x["w_air"]])
        W = np.array([x["wind_tot_n"], x["wind_tot_e"], x["wind_tot_d"]])
        vg = np.array([x["vn"], x["ve"], x["vd"]])
        f_aero = np.array([x["fx_aero"], x["fy_aero"], x["fz_aero"]])
        f_prop = np.array([x["fx_prop"], x["fy_prop"], x["fz_prop"]])
        f_gear = np.array([x["fx_gear"], x["fy_gear"], x["fz_gear"]])
        return {"m": m, "g": g, "va_ned": vg - W, "W": W,
                "E_air": 0.5 * m * float(va_b @ va_b) + m * g * x["h_msl"],
                "P_aero": float(f_aero @ va_b), "P_prop": float(f_prop @ va_b), "P_gear": float(f_gear @ va_b),
                "P_drag": x["drag"] * x["tas"], "P_thrust": x["thrust"] * x["u_air"]}

    def _ledger(self, x):
        e = self._energy_terms(x)
        if self._energy_prev is None:
            self.E_air0 = e["E_air"]
            self._energy_prev = e
            return e
        p, dt = self._energy_prev, self.dt
        for key, pk in (("aero", "P_aero"), ("prop", "P_prop"), ("gear", "P_gear"),
                        ("drag", "P_drag"), ("thrust_useful", "P_thrust")):
            self.E[key] += 0.5 * (p[pk] + e[pk]) * dt
        dW = e["W"] - p["W"]
        va_mid = p["va_ned"] - 0.5 * dW
        self.E["wind"] += -e["m"] * float(va_mid @ dW) - e["m"] * e["g"] * 0.5 * (p["W"][2] + e["W"][2]) * dt
        e["P_wind"] = (-e["m"] * float(va_mid @ dW)) / dt - e["m"] * e["g"] * e["W"][2]
        self._energy_prev = e
        return e

    def energy_closure(self):
        """Residual of the mechanical energy balance (J) and its size relative to
        the gross work terms."""
        if self._energy_prev is None:
            return 0.0, 0.0
        dE = self._energy_prev["E_air"] - self.E_air0
        rhs = self.E["aero"] + self.E["prop"] + self.E["gear"] + self.E["wind"]
        gross = abs(self.E["aero"]) + abs(self.E["prop"]) + abs(self.E["gear"]) + abs(self.E["wind"]) + 1e-9
        return dE - rhs, (dE - rhs) / gross

    # ------------------------------------------------------------ crash check
    def _crash_check(self, x):
        R = _dcm_b2n(x["phi"], x["theta"], x["psi"])
        cg = self._cg_in
        for name, (xs, ys, zs) in STRUCT_POINTS_IN.items():
            pb = np.array([-(xs - cg[0]) * IN, ys * IN, -(zs - cg[2]) * IN])
            down = float((R @ pb)[2])
            if x["h_agl"] - down < -0.01:
                return name
        return None

    # ------------------------------------------------------------------- step
    def step(self) -> bool:
        """Advance one physics step. Returns False when the run has ended."""
        if self.status != "RUNNING":
            return False
        fdm, dt, x = self.fdm, self.dt, self._x
        t = x["t"]
        # ---- atmosphere / wind
        self.ws = self.wind.sample(t, max(x["h_agl"], 0.0), x["tas"], x["psi"], dt)
        fdm.set_wind(self.ws.mean, self.ws.turb + self.ws.gust)
        # ---- control tick
        if self.k % self.n_ctrl == 0:
            self.pos_ne = self.mission.frame.to_ned(x["lat"], x["lon"], x["h_msl"])[:2]
            self.m = self.sensors.measure(x, self.pos_ne)
            if self.ap.mode == "PREFLIGHT" and t >= float(self.cfg["sim"]["settle_time_s"]):
                self.ap.set_mode(t, "TAKEOFF_ROLL", "armed")
                self.t_takeoff = t
            b = self.pt.battery
            energy = {"soc": b.soc, "p_batt": self.pt.s.p_batt_term, "v_cell": b.v_cell_filt,
                      "depleted": b.depleted, "depleted_reason": b.depleted_reason,
                      "capacity_j": self.capacity_j}
            self.cmd, self.sp = self.ap.update(t, dt * self.n_ctrl, self.m, energy, self.pos_ne)
        cmd = self.cmd
        # ---- actuators
        ail, elev, rud, thr = self.act.step(cmd.ail, cmd.elev, cmd.rud, cmd.thr, dt)
        fdm.set_surfaces(ail, elev, rud, cmd.steer)
        # ---- powertrain co-simulation
        rpm = fdm.prop_rpm()
        omega = rpm * RPM
        fdm.set_prop_krpm(min(max(rpm, 1000.0), 12000.0) / 1000.0)
        self.pt.p_avionics_extra = self.act.servo_power()
        q = self.pt.step(thr, omega, dt)
        fdm.set_motor_torque(q, omega)
        # ---- flight dynamics
        fdm.run()
        self.k += 1
        x = fdm.state()
        self._x = x
        self.t = x["t"]
        e = self._ledger(x)
        self.dist_ground += math.hypot(x["vn"], x["ve"]) * dt
        if not x["wow"]:
            self.dist_air += x["tas"] * dt
        # ---- touchdown sink rate record
        if self.ap.mode == "FLARE" or (self.ap.mode == "ROLLOUT" and self.max_sink_td is None):
            if x["wow"] > 0.5 and self.max_sink_td is None:
                self.max_sink_td = x["vd"]
        # ---- termination checks
        hit = self._crash_check(x) if not (self.ap.mode in ("PREFLIGHT",)) else None
        if hit:
            self.status, self.term_reason = "CRASHED", f"structure_contact:{hit}"
            self.log.event(self.t, "terminal", "crash", point=hit, tas=round(x["tas"], 2),
                           vd=round(x["vd"], 2), phi_deg=round(math.degrees(x["phi"]), 1))
            self.ap.mode = "CRASHED"
            self.ap.success = False
        elif self.ap.mode in TERMINAL:
            self.status = self.ap.mode
            self.term_reason = self.ap.mode.lower()
            if self.ap.mode == "LANDED":
                self.t_landed = self.t
        elif self.t >= self.t_max:
            self.status, self.term_reason = "TIMEOUT", "t_max"
            self.log.event(self.t, "terminal", "timeout")
        # ---- logging
        if self.k % self.n_log == 0 or self.status != "RUNNING":
            self.log.row(x, e)
        return self.status == "RUNNING"

    def run(self) -> RunResult:
        while self.step():
            pass
        return self.finish()

    def finish(self) -> RunResult:
        return self.log.finish()
