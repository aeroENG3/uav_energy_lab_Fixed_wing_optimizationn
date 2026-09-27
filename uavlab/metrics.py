"""KPIs, per-leg and per-phase tables computed from a run's time series.

Energies come from cumulative meters integrated at the physics rate, so segment
energies are exact up to the log-tick quantisation of segment boundaries."""
from __future__ import annotations

import json
import math

import numpy as np
import pandas as pd

PHASE_OF_MODE = {"PREFLIGHT": "ground", "TAKEOFF_ROLL": "takeoff", "ROTATE": "takeoff",
                 "CLIMB_OUT": "climb", "MISSION": "mission", "APPROACH": "approach",
                 "GO_AROUND": "approach", "FLARE": "landing", "ROLLOUT": "landing",
                 "LANDED": "landed", "NO_GO": "ground", "CRASHED": "crashed"}


def _seg_stats(g: pd.DataFrame, prev_row: pd.Series | None) -> dict:
    first = prev_row if prev_row is not None else g.iloc[0]
    last = g.iloc[-1]
    d = lambda c: float(last[c] - first[c])
    dur = d("t_s")
    dist = d("dist_ground_m")
    e = d("E_batt_Wh")
    shaft = d("E_shaft_Wh")
    turb = g[["wind_turb_n_mps", "wind_turb_e_mps", "wind_turb_d_mps"]].to_numpy()
    return {
        "t_start_s": float(first["t_s"]), "t_end_s": float(last["t_s"]), "duration_s": dur,
        "dist_ground_m": dist, "dist_air_m": d("dist_air_m"),
        "E_batt_Wh": e, "Wh_per_km": e / (dist / 1000.0) if dist > 1 else float("nan"),
        "P_batt_mean_W": e * 3600.0 / dur if dur > 0 else float("nan"),
        "tas_mean_mps": float(g["tas_mps"].mean()), "gs_mean_mps": float(g["gs_mps"].mean()),
        "alt_agl_mean_m": float(g["alt_agl_m"].mean()),
        "alt_agl_start_m": float(first["alt_agl_m"]), "alt_agl_end_m": float(last["alt_agl_m"]),
        "tailwind_mean_mps": float(g["tailwind_mps"].mean()), "crosswind_mean_mps": float(g["crosswind_mps"].mean()),
        "wind_mean_speed_mps": float(g["wind_mean_speed_mps"].mean()),
        "wind_vertical_mean_mps": float(-g["wind_tot_d_mps"].mean()),
        "turb_rms_mps": float(np.sqrt(np.mean(np.sum(turb ** 2, axis=1)))) if len(turb) else 0.0,
        "throttle_mean": float(g["act_thr"].mean()), "rpm_mean": float(g["rpm"].mean()),
        "alpha_mean_deg": float(g["alpha_deg"].mean()),
        "eta_prop": d("E_thrust_Wh") / shaft if shaft > 1e-6 else float("nan"),
        "eta_drive": shaft / e if e > 1e-6 else float("nan"),
        "E_shaft_Wh": shaft, "E_thrust_Wh": d("E_thrust_Wh"), "E_drag_Wh": d("E_drag_Wh"),
        "E_wind_Wh": d("E_wind_Wh"), "E_avionics_Wh": d("E_avionics_Wh"),
        "xtrack_rms_m": float(np.sqrt(np.mean(g["xtrack_m"] ** 2))),
        "alt_err_rms_m": float(np.sqrt(np.mean((g["h_cmd_m"] - g["alt_agl_m"]) ** 2))),
        "tas_err_rms_mps": float(np.sqrt(np.mean((g["v_cmd_mps"] - g["tas_mps"]) ** 2))),
        "soc_start": float(first["soc"]), "soc_end": float(last["soc"]),
    }


def leg_table(df: pd.DataFrame) -> pd.DataFrame:
    mis = df["mode"] == "MISSION"
    if not mis.any():
        return pd.DataFrame()
    seg_id = ((df["leg"] != df["leg"].shift()) | (df["mode"] != df["mode"].shift())).cumsum()
    rows = []
    for sid, g in df[mis].groupby(seg_id[mis], sort=True):
        i0 = g.index[0]
        prev = df.loc[i0 - 1] if i0 > 0 else None
        r = {"leg": int(g["leg"].iloc[0]), "leg_name": g["leg_name"].iloc[0]}
        # leg geometry: mean ground course over the leg
        r["course_mean_deg"] = float(np.degrees(np.arctan2(g["ve_mps"].mean(), g["vn_mps"].mean())) % 360)
        r.update(_seg_stats(g, prev))
        rows.append(r)
    return pd.DataFrame(rows)


def phase_table(df: pd.DataFrame) -> pd.DataFrame:
    ph = df["mode"].map(PHASE_OF_MODE).fillna("other")
    seg = (ph != ph.shift()).cumsum()
    rows = []
    for sid, g in df.groupby(seg, sort=True):
        i0 = g.index[0]
        prev = df.loc[i0 - 1] if i0 > 0 else None
        r = {"phase": ph.loc[i0]}
        r.update(_seg_stats(g, prev))
        rows.append(r)
    out = pd.DataFrame(rows)
    return out


def summarize(sim, df: pd.DataFrame, legs: pd.DataFrame) -> dict:
    b = sim.pt.battery
    s = {"run_id": sim.run_id, "status": sim.status, "termination": sim.term_reason,
         "success": bool(sim.status == "LANDED"), "config_hash": sim.cfg_hash, "seed": sim.cfg["sim"]["seed"],
         "sim_time_s": round(sim.t, 3)}
    evs = sim.log.events
    s["decisions"] = [e["name"] for e in evs if e["kind"] == "decision"]
    s["go_arounds"] = sim.ap.go_arounds
    s["rtl_reason"] = sim.ap.rtl_reason
    if len(df) == 0:
        return s
    air = df[df["mode"].isin(["CLIMB_OUT", "MISSION", "APPROACH", "GO_AROUND", "FLARE"])]
    fl = df[df["mode"] != "PREFLIGHT"]
    last = df.iloc[-1]
    E = last["E_batt_Wh"]
    dist = last["dist_ground_m"]
    s.update({
        "flight_time_s": float(fl["t_s"].iloc[-1] - fl["t_s"].iloc[0]) if len(fl) else 0.0,
        "air_time_s": float(len(air)) / sim.cfg["sim"]["log_rate_hz"],
        "dist_ground_km": dist / 1000.0, "dist_air_km": last["dist_air_m"] / 1000.0,
        "E_batt_Wh": float(E), "E_chem_Wh": float(last["E_chem_Wh"]),
        "Wh_per_km": float(E / (dist / 1000.0)) if dist > 10 else None,
        "soc_start": float(sim.soc0), "soc_end": float(b.soc),
        "battery_capacity_Wh": sim.capacity_j / 3600.0,
        "min_cell_v": float(df["v_cell_V"].min()), "max_i_batt_A": float(df["i_batt_A"].max()),
        "max_P_batt_W": float(df["P_batt_W"].max()),
        "mean_P_batt_air_W": float(air["P_batt_W"].mean()) if len(air) else None,
        "energy_breakdown_Wh": {
            "battery_internal_loss": float(last["E_batt_loss_Wh"]),
            "esc_loss": float(last["E_esc_loss_Wh"]),
            "motor_copper_loss": float(last["E_copper_Wh"]),
            "motor_iron_friction_loss": float(last["E_iron_Wh"]),
            "shaft": float(last["E_shaft_Wh"]),
            "thrust_useful": float(last["E_thrust_Wh"]),
            "propeller_loss": float(last["E_shaft_Wh"] - last["E_thrust_Wh"]),
            "avionics_servos": float(last["E_avionics_Wh"]),
            "drag_work": float(last["E_drag_Wh"]),
            "wind_work": float(last["E_wind_Wh"]),
        },
    })
    sh = last["E_shaft_Wh"]
    s["eta"] = {"propeller": float(last["E_thrust_Wh"] / sh) if sh > 0 else None,
                "motor": float(sh / (sh + last["E_copper_Wh"] + last["E_iron_Wh"])) if sh > 0 else None,
                "esc": float(1 - last["E_esc_loss_Wh"] / max(E - last["E_avionics_Wh"], 1e-9)) if E > 0 else None}
    mis = df[df["mode"] == "MISSION"]
    if len(mis):
        # steady tracking excludes the first 20 s of each leg (turn transients)
        leg_t0 = mis.groupby("leg")["t_s"].transform("min")
        st = mis[mis["t_s"] - leg_t0 > 20.0]
        s["tracking"] = {
            "xtrack_rms_m": float(np.sqrt(np.mean(mis["xtrack_m"] ** 2))),
            "xtrack_rms_steady_m": float(np.sqrt(np.mean(st["xtrack_m"] ** 2))) if len(st) else None,
            "alt_err_rms_steady_m": float(np.sqrt(np.mean((st["h_cmd_m"] - st["alt_agl_m"]) ** 2))) if len(st) else None,
            "tas_err_rms_steady_mps": float(np.sqrt(np.mean((st["v_cmd_mps"] - st["tas_mps"]) ** 2))) if len(st) else None,
            "throttle_tv_per_s": float(mis["act_thr"].diff().abs().sum() / max(mis["t_s"].iloc[-1] - mis["t_s"].iloc[0], 1.0)),
            "xtrack_max_m": float(mis["xtrack_m"].abs().max()),
            "alt_err_rms_m": float(np.sqrt(np.mean((mis["h_cmd_m"] - mis["alt_agl_m"]) ** 2))),
            "tas_err_rms_mps": float(np.sqrt(np.mean((mis["v_cmd_mps"] - mis["tas_mps"]) ** 2))),
        }
        s["mission_E_Wh"] = float(legs["E_batt_Wh"].sum()) if len(legs) else None
        s["mission_Wh_per_km"] = float(legs["E_batt_Wh"].sum() / (legs["dist_ground_m"].sum() / 1000)) \
            if len(legs) and legs["dist_ground_m"].sum() > 10 else None
    td = [e for e in evs if e["name"].endswith("->ROLLOUT")]
    if td:
        d = json.loads(td[0]["data"])
        s["touchdown"] = {"sink_mps": d.get("sink_mps"), "tas_mps": d.get("tas"),
                          "along_runway_m": d.get("along_m"), "xtrack_m": d.get("xtrack_m")}
    ld = [e for e in evs if e["name"].endswith("->LANDED")]
    if ld:
        s["stop"] = json.loads(ld[0]["data"])
    wind = df[["wind_tot_n_mps", "wind_tot_e_mps"]].to_numpy()
    s["wind"] = {"mean_speed_mps": float(np.mean(np.hypot(wind[:, 0], wind[:, 1]))),
                 "max_speed_mps": float(np.max(np.hypot(wind[:, 0], wind[:, 1]))),
                 "turb_rms_mps": float(np.sqrt(np.mean(df[["wind_turb_n_mps", "wind_turb_e_mps",
                                                            "wind_turb_d_mps"]].to_numpy() ** 2) * 3))}
    res_j, rel = sim.energy_closure()
    s["energy_closure"] = {"residual_J": float(res_j), "relative": float(rel)}
    s["wall_time_s"] = round(__import__("time").time() - sim.wall0, 2)
    s["realtime_factor"] = round(sim.t / max(s["wall_time_s"], 1e-6), 1)
    return s
