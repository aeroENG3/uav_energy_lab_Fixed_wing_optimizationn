"""Run logging: time series, events, per-leg and per-phase energy tables,
summary KPIs and full provenance metadata.

Output folder (one per run):
  timeseries.csv|parquet   one row per log tick; units in column names
  events.csv               mode changes, decisions (with reasons), waypoints, terminal
  legs.csv                 energy/wind per mission leg  (main table for wind-energy studies)
  phases.csv               energy per flight phase (take-off, climb, mission, approach, landing)
  summary.json             KPIs of the run
  metadata.json            config hash, seeds, software versions, model file hashes
  config_resolved.yaml     the exact configuration that ran
  jsbsim/                  the exact JSBSim XML files that ran
"""
from __future__ import annotations

import json
import math
import platform
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from . import __version__
from .units import DEG

J2WH = 1.0 / 3600.0


class RunLogger:
    def __init__(self, sim):
        self.sim = sim
        self.rows: list[dict] = []
        self.events: list[dict] = []

    # ------------------------------------------------------------------ events
    def event(self, t, kind, ev_name, **data):
        ev = {"t_s": round(float(t), 3), "kind": kind, "name": ev_name, "data": json.dumps(data, default=float)}
        self.events.append(ev)
        cb = getattr(self.sim, "on_event", None)
        if cb is not None:
            cb(ev)

    # --------------------------------------------------------------------- row
    def row(self, x, e):
        s = self.sim
        pt, b, ws, sp, cmd, act, m = s.pt.s, s.pt.battery, s.ws, s.sp, s.cmd, s.act, s.m
        wm = ws.mean
        # turbulence: the lab's Dryden (known exactly) or JSBSim's own (read back)
        turb = ws.turb if s.cfg["wind"]["turbulence"]["model"] != "jsbsim_milspec" else \
            np.array([x["turb_n"], x["turb_e"], x["turb_d"]])
        spd_h = math.hypot(wm[0], wm[1])
        gs = math.hypot(x["vn"], x["ve"])
        course = math.atan2(x["ve"], x["vn"]) if gs > 0.5 else x["psi"]
        wt = np.array([x["wind_tot_n"], x["wind_tot_e"], x["wind_tot_d"]])
        tail = wt[0] * math.cos(course) + wt[1] * math.sin(course)
        cross = -wt[0] * math.sin(course) + wt[1] * math.cos(course)
        qs = x["qbar"] * 0.98199       # wing area 10.57 ft^2 in m^2
        west = s.ap.west.w
        res_j, _ = s.energy_closure()
        r = {
            "t_s": x["t"], "mode": s.ap.mode, "phase": sp.phase if sp else "", "leg": sp.leg if sp else -1,
            "leg_name": sp.leg_name if sp else "",
            "lat_deg": x["lat"], "lon_deg": x["lon"], "n_m": s.pos_ne[0], "e_m": s.pos_ne[1],
            "alt_msl_m": x["h_msl"], "alt_agl_m": x["h_agl"],
            "phi_deg": x["phi"] / DEG, "theta_deg": x["theta"] / DEG, "psi_deg": (x["psi"] / DEG) % 360,
            "p_dps": x["p"] / DEG, "q_dps": x["q"] / DEG, "r_dps": x["r"] / DEG,
            "tas_mps": x["tas"], "cas_mps": x["cas"], "gs_mps": gs, "course_deg": (course / DEG) % 360,
            "vn_mps": x["vn"], "ve_mps": x["ve"], "vd_mps": x["vd"], "climb_mps": -x["vd"],
            "alpha_deg": x["alpha"] / DEG, "beta_deg": x["beta"] / DEG, "nz_g": x["nz"],
            "rho_kgm3": x["rho"], "T_K": x["T_K"], "P_pa": x["P_pa"],
            "wind_mean_n_mps": wm[0], "wind_mean_e_mps": wm[1], "wind_mean_d_mps": wm[2],
            "wind_turb_n_mps": turb[0], "wind_turb_e_mps": turb[1], "wind_turb_d_mps": turb[2],
            "wind_gust_n_mps": ws.gust[0], "wind_gust_e_mps": ws.gust[1], "wind_gust_d_mps": ws.gust[2],
            "wind_tot_n_mps": wt[0], "wind_tot_e_mps": wt[1], "wind_tot_d_mps": wt[2],
            "wind_mean_speed_mps": spd_h,
            "wind_mean_from_deg": (math.degrees(math.atan2(-wm[1], -wm[0])) % 360) if spd_h > 0.01 else 0.0,
            "tailwind_mps": tail, "crosswind_mps": cross, "w20_mps": ws.w20,
            "wind_est_n_mps": west[0], "wind_est_e_mps": west[1],
            "wind_est_mean_n_mps": s.ap.west.w_mean[0], "wind_est_mean_e_mps": s.ap.west.w_mean[1],
            "gust_sigma_est_mps": s.ap.west.gust_sigma,
            "cmd_ail": cmd.ail, "cmd_elev": cmd.elev, "cmd_rud": cmd.rud, "cmd_thr": cmd.thr, "cmd_steer": cmd.steer,
            "act_ail": act.ail.pos, "act_elev": act.elev.pos, "act_rud": act.rud.pos, "act_thr": act.thr.pos,
            "phi_cmd_deg": sp.phi_cmd / DEG if sp else 0.0, "theta_cmd_deg": sp.theta_cmd / DEG if sp else 0.0,
            "h_cmd_m": sp.h_cmd if sp else 0.0, "v_cmd_mps": sp.v_cmd if sp else 0.0,
            "xtrack_m": sp.xtrack if sp else 0.0, "wp_dist_m": sp.wp_dist if sp else 0.0,
            "pred_soc_landing": sp.pred_soc_landing if sp else float("nan"),
            "policy_v_mps": sp.policy_v if sp else float("nan"),
            "rpm": x["rpm"], "J": x["J"], "thrust_N": x["thrust"], "drag_N": x["drag"], "lift_N": x["lift"],
            "CL": x["lift"] / qs if qs > 1 else float("nan"), "CD": x["drag"] / qs if qs > 1 else float("nan"),
            "v_bus_V": pt.v_bus, "i_batt_A": pt.i_batt, "i_motor_A": pt.i_motor, "v_motor_V": pt.v_motor,
            "duty": pt.duty_eff, "back_emf_V": pt.back_emf, "torque_Nm": pt.torque,
            "esc_regime": pt.regime,
            "soc": b.soc, "v_cell_V": b.v_cell_filt if b.v_cell_filt is not None else float("nan"),
            "ocv_V": b.ocv(),
            "P_batt_chem_W": pt.p_batt_chem, "P_batt_W": pt.p_batt_term, "P_batt_loss_W": pt.p_batt_loss,
            "P_esc_loss_W": pt.p_esc_loss, "P_copper_W": pt.p_copper, "P_iron_W": pt.p_iron,
            "P_shaft_W": pt.p_shaft, "P_prop_req_W": x["prop_power_w"], "P_avionics_W": pt.p_avionics,
            "P_thrust_W": e["P_thrust"], "P_drag_W": e["P_drag"], "P_wind_W": e.get("P_wind", 0.0),
            "E_batt_Wh": b.e_term * J2WH, "E_chem_Wh": b.e_chem * J2WH,
            "E_batt_loss_Wh": (b.e_r0 + b.e_r1) * J2WH,
            "E_esc_loss_Wh": s.pt.e["esc_loss"] * J2WH, "E_copper_Wh": s.pt.e["copper"] * J2WH,
            "E_iron_Wh": s.pt.e["iron"] * J2WH, "E_shaft_Wh": s.pt.e["shaft"] * J2WH,
            "E_avionics_Wh": s.pt.e["avionics"] * J2WH,
            "E_thrust_Wh": s.E["thrust_useful"] * J2WH, "E_drag_Wh": s.E["drag"] * J2WH,
            "E_wind_Wh": s.E["wind"] * J2WH, "E_air_J": e["E_air"], "closure_residual_J": res_j,
            "dist_ground_m": s.dist_ground, "dist_air_m": s.dist_air,
        }
        self.rows.append(r)
        cb = getattr(s, "on_row", None)
        if cb is not None:
            cb(r)

    # ------------------------------------------------------------------ finish
    def finish(self):
        from .metrics import leg_table, phase_table, summarize
        from .simulation import RunResult
        s = self.sim
        df = pd.DataFrame(self.rows)
        legs = leg_table(df) if len(df) else pd.DataFrame()
        phases = phase_table(df) if len(df) else pd.DataFrame()
        summ = summarize(s, df, legs)
        if s.write_logs:
            d = s.run_dir
            fmt = s.cfg["logging"]["format"]
            if fmt == "parquet":
                df.to_parquet(d / "timeseries.parquet", index=False)
            else:
                df.to_csv(d / "timeseries.csv", index=False, float_format="%.6g")
            pd.DataFrame(self.events).to_csv(d / "events.csv", index=False)
            legs.to_csv(d / "legs.csv", index=False, float_format="%.6g")
            phases.to_csv(d / "phases.csv", index=False, float_format="%.6g")
            (d / "summary.json").write_text(json.dumps(summ, indent=2, default=_json_default), encoding="utf-8")
            (d / "metadata.json").write_text(json.dumps(self.metadata(), indent=2, default=_json_default), encoding="utf-8")
            (d / "config_resolved.yaml").write_text(yaml.safe_dump(s.cfg, sort_keys=False), encoding="utf-8")
        return RunResult(run_dir=s.run_dir, summary=summ, status=s.status,
                         timeseries=df if s.keep_ts else None, events=self.events)

    def metadata(self):
        import jsbsim
        import scipy
        s = self.sim
        return {
            "run_id": s.run_id,
            "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "uavlab_version": __version__,
            "jsbsim_version": jsbsim.__version__,
            "python": sys.version.split()[0], "numpy": np.__version__, "scipy": scipy.__version__,
            "pandas": pd.__version__, "platform": platform.platform(),
            "config_hash": s.cfg_hash, "seed": s.cfg["sim"]["seed"],
            "model": s.model_info,
            "wall_time_s": round(time.time() - s.wall0, 2),
            "sim_time_s": round(s.t, 3),
            "dt_physics_s": s.dt, "control_rate_hz": s.cfg["sim"]["control_rate_hz"],
            "log_rate_hz": s.cfg["sim"]["log_rate_hz"],
            "base_model_provenance": "ArduPilot Tools/autotest/aircraft/Rascal (commit 66c8985), "
                                     "from FlightGear Rascal110-JSBSim; see docs/MODEL_CARD.md",
        }


def _json_default(o):
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, Path):
        return str(o)
    return str(o)
