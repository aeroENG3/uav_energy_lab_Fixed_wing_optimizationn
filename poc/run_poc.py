"""Proof of concept: wind-adaptive energy optimisation in a head-wind.

    Baseline   : fixed 17 m/s cruise (the mission default)
    Optimised  : linear_wind speed law  V = v0 + k_head * headwind,
                 with (v0, k_head) found by the lab's cross-entropy optimiser (CEM)
    Condition  : out-and-back mission (2.5 km legs east-west) in a steady 6 m/s westerly
                 (8.3 m/s at the 100 m cruise height), identical seed for every flight

Steps:  1 baseline flight  ->  2 CEM optimisation  ->  3 optimised flight (full logs)
        4 robustness: both designs in 3 unseen light-turbulence seeds
        5 physics cross-check against the independent performance map
        6 pre-stated criteria, results table, figures

Run from the repository folder:
    python poc/run_poc.py                 full PoC (40 optimisation flights; about 10-20 min on 4 cores)
    python poc/run_poc.py --quick         smaller search (16 flights), for a first check
    python poc/run_poc.py --workers 8
In an IDE (PyCharm, VS Code): open this file and press Run.
Results: poc_results/  (poc_results.json, comparison.csv, legs.csv, figures/*.png, run folders)
"""
from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SCENARIO = ["configs/missions/out_and_back.yaml", "configs/wind/steady_headwind_6.yaml"]
SEED = 1
ROBUST_SEEDS = [11, 12, 13]                       # never seen by the optimiser
BASELINE = {"autonomy.policy.name": "fixed", "mission.cruise.airspeed_mps": 17.0}
VARIABLES = [{"path": "autonomy.policy.params.v0", "lo": 12.0, "hi": 20.0},
             {"path": "autonomy.policy.params.k_head", "lo": 0.0, "hi": 1.2}]
OBJECTIVE = {"kpi": "mission_E_Wh", "sense": "min"}
# the mission must be flown completely: otherwise an early return (e.g. decision D5) "saves" energy
CONSTRAINTS = [{"kpi": "status", "op": "==", "value": "LANDED"},
               {"kpi": "rtl_reason", "op": "==", "value": "mission_complete"}]
V_MIN, V_MAX = 12.0, 26.0                          # linear_wind output limits (policy defaults)

# criteria are fixed BEFORE the experiment runs
CRITERIA = {
    "C1": "Both flights complete the mission and land on the runway (status LANDED, return reason mission_complete)",
    "C2": "Mechanical energy balance closes in both flights: |residual| < 0.1 % of gross work",
    "C3": "The optimised speed law needs at least 2 % less mission-leg battery energy than the baseline",
    "C4": "Optimised up-wind and down-wind airspeeds agree with the independent speed-to-fly prediction within 1.5 m/s",
    "C5": "The saving holds in each of 3 unseen light-turbulence seeds (paired comparison, complete missions)",
    "C6": "No safety regression: touchdown sink < 2.5 m/s and no energy-reserve decision (D4/D5) in the optimised flight",
}


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


RESUME = False


def fly(overrides: dict, run_dir: Path, seed: int = SEED, resume: bool | None = None) -> dict:
    """One full flight with complete logs in run_dir; returns summary.json. With --resume an
    existing, finished run folder is reused instead of flying again."""
    resume = RESUME if resume is None else resume
    if resume and (run_dir / "summary.json").exists():
        return json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    from uavlab import load_config
    from uavlab.simulation import Simulation
    cfg = load_config(*[ROOT / f for f in SCENARIO], overrides={**overrides, "sim.seed": seed})
    if run_dir.exists():
        shutil.rmtree(run_dir)
    res = Simulation(cfg, run_dir=run_dir).run()
    return res.summary


def _robust_job(args):
    overrides, run_dir, seed, resume = args
    return fly(overrides, Path(run_dir), seed, resume)


def speed_to_fly(fit: dict, headwind: float) -> float:
    """Airspeed minimising P(V)/Vg(V) for a pure head-wind (negative = tail-wind)."""
    best, vbest = math.inf, None
    v = V_MIN
    while v <= V_MAX + 1e-9:
        vg = v - headwind
        if vg > 1.0:
            cost = (fit["a"] * v ** 3 + fit["b"] / v + fit["c"]) / vg
            if cost < best:
                best, vbest = cost, v
        v += 0.01
    return vbest


def _previous_wall(out: Path, resume: bool) -> float:
    """With --resume the reused steps keep their measured duration."""
    p = out / "poc_results.json"
    if resume and p.exists():
        try:
            return float(json.loads(p.read_text(encoding="utf-8")).get("wall_time_s", 0.0))
        except Exception:
            return 0.0
    return 0.0


def _vv_d1():
    """V&V check D1 flies the lab's physics speed-to-fly policy in exactly this condition (same seed)."""
    try:
        vv = json.loads((ROOT / "validation_report" / "vv_results.json").read_text(encoding="utf-8"))
        d1 = next(c for c in vv["checks"] if c["id"] == "D1")
        import re
        m = re.search(r"([\d.]+) -> ([\d.]+) Wh", d1["value"])
        return {"policy": "wind_aware_best_range", "baseline_mission_E_Wh": float(m.group(1)),
                "mission_E_Wh": float(m.group(2)), "source": "validation_report/vv_results.json, check D1"}
    except Exception:
        return None


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--quick", action="store_true", help="population 8 x 2 generations instead of 8 x 5")
    ap.add_argument("--workers", type=int, default=os.cpu_count() or 2)
    ap.add_argument("--out", default=str(ROOT / "poc_results"))
    ap.add_argument("--no-robustness", action="store_true", help="skip step 4")
    ap.add_argument("--resume", action="store_true", help="reuse finished flights and optimisation in --out")
    a = ap.parse_args(argv)
    global RESUME
    RESUME = a.resume
    os.chdir(ROOT)
    out = Path(a.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    import pandas as pd
    from uavlab.optimize import run_optimisation

    # ------------------------------------------------------------ 1 baseline
    log("STEP 1/6  baseline flight: fixed 17 m/s cruise, steady 6 m/s westerly, seed 1")
    s_base = fly(BASELINE, out / "baseline")
    log(f"          {s_base['status']}, mission-leg energy {s_base['mission_E_Wh']:.2f} Wh, "
        f"total {s_base['E_batt_Wh']:.2f} Wh")

    # ------------------------------------------------------------ 2 optimisation
    iters = 2 if a.quick else 5
    spec = {
        "name": "optimisation",
        "scenario": SCENARIO,
        # identical to the interface's Optimisation page (it logs optimisation flights at 2 Hz;
        # energies are integrated at 200 Hz either way)
        "fixed": {"autonomy.policy.name": "linear_wind", "sim.log_rate_hz": 2},
        "variables": VARIABLES,
        "objective": OBJECTIVE,
        "constraints": CONSTRAINTS,
        "conditions": [{"label": "headwind6", "overrides": {}}],
        "seeds": [SEED],
        "algorithm": {"population": 8, "elite_frac": 0.25, "iterations": iters, "init_sigma_frac": 0.3,
                      "min_sigma_frac": 0.02, "smoothing": 0.7, "seed": 0},
        "workers": a.workers,
    }
    log(f"STEP 2/6  cross-entropy optimisation of (v0, k_head): 8 candidates x {iters} generations, "
        f"{a.workers} parallel workers")
    opt_dir = out / "optimisation"
    if not (a.resume and (opt_dir / "result.json").exists()):
        opt_dir = run_optimisation(spec, out_root=out, progress=lambda m: log("          " + m.strip()))
    result = json.loads((opt_dir / "result.json").read_text(encoding="utf-8"))
    bv = result["best_variables"]
    v0, k = float(bv["autonomy.policy.params.v0"]), float(bv["autonomy.policy.params.k_head"])
    log(f"          best design: v0 = {v0:.2f} m/s, k_head = {k:.3f}")

    # ------------------------------------------------------------ 3 optimised flight
    OPT = {"autonomy.policy.name": "linear_wind", "autonomy.policy.params.v0": v0,
           "autonomy.policy.params.k_head": k}
    log("STEP 3/6  optimised flight with full logs (same condition, same seed)")
    s_opt = fly(OPT, out / "optimised")
    log(f"          {s_opt['status']}, mission-leg energy {s_opt['mission_E_Wh']:.2f} Wh, "
        f"total {s_opt['E_batt_Wh']:.2f} Wh")

    # ------------------------------------------------------------ 4 robustness
    robust = []
    if not a.no_robustness:
        log(f"STEP 4/6  robustness: both designs in light Dryden turbulence, seeds {ROBUST_SEEDS}")
        import multiprocessing
        from concurrent.futures import ProcessPoolExecutor
        turb = {"wind.turbulence.model": "dryden"}
        jobs = []
        for sd in ROBUST_SEEDS:
            jobs.append(({**BASELINE, **turb}, str(out / "robustness" / f"baseline_s{sd}"), sd, a.resume))
            jobs.append(({**OPT, **turb}, str(out / "robustness" / f"optimised_s{sd}"), sd, a.resume))
        with ProcessPoolExecutor(max_workers=a.workers, mp_context=multiprocessing.get_context("spawn")) as ex:
            res = list(ex.map(_robust_job, jobs))
        for i, sd in enumerate(ROBUST_SEEDS):
            b, o = res[2 * i], res[2 * i + 1]
            robust.append({"seed": sd, "baseline_status": b["status"], "optimised_status": o["status"],
                           "baseline_return": b.get("rtl_reason"), "optimised_return": o.get("rtl_reason"),
                           "baseline_mission_E_Wh": b["mission_E_Wh"], "optimised_mission_E_Wh": o["mission_E_Wh"],
                           "saving_pct": 100 * (1 - o["mission_E_Wh"] / b["mission_E_Wh"])})
            log(f"          seed {sd}: {b['mission_E_Wh']:.2f} -> {o['mission_E_Wh']:.2f} Wh "
                f"({robust[-1]['saving_pct']:+.1f} %)")
    else:
        log("STEP 4/6  robustness skipped (--no-robustness)")

    # ------------------------------------------------------------ 5 physics cross-check
    log("STEP 5/6  physics cross-check with the independent performance map")
    from uavlab.atmosphere import shear_factor
    from uavlab import load_config
    cfg = load_config(*[ROOT / f for f in SCENARIO])
    wind_h = cfg["wind"]["mean"]["speed_mps"] * shear_factor(cfg["mission"]["cruise"]["alt_agl_m"], cfg["wind"]["mean"])
    fit_p = ROOT / "validation_report" / "performance" / "performance_fit.json"
    fit = json.loads(fit_p.read_text(encoding="utf-8"))
    pred_up, pred_down = speed_to_fly(fit, wind_h), speed_to_fly(fit, -wind_h)
    law_up = min(max(v0 + k * wind_h, V_MIN), V_MAX)
    law_down = min(max(v0 - k * wind_h, V_MIN), V_MAX)
    log(f"          wind at cruise height {wind_h:.2f} m/s; speed-to-fly up-wind {pred_up:.2f}, "
        f"down-wind {pred_down:.2f} m/s; optimised law {law_up:.2f} / {law_down:.2f} m/s")
    # diagnostic (not a criterion): the same speed-to-fly from the measured map points themselves,
    # shape-preserving interpolation instead of the 3-parameter fit
    import numpy as np
    from scipy.interpolate import PchipInterpolator
    perf = pd.read_csv(ROOT / "validation_report" / "performance" / "performance.csv")
    vmap = perf["sim_tas"].to_numpy()

    def map_opt(col, h):
        g = PchipInterpolator(vmap, perf[col].to_numpy())
        vv = np.arange(V_MIN, min(V_MAX, vmap.max()), 0.01)
        cost = np.where(vv - h > 1.0, g(vv) / np.maximum(vv - h, 1e-9), np.inf)
        return float(vv[int(np.argmin(cost))])

    fit_p_w = fit["a"] * vmap ** 3 + fit["b"] / vmap + fit["c"]
    map_diag = {"sim": {"up": map_opt("sim_P_batt_W", wind_h), "down": map_opt("sim_P_batt_W", -wind_h)},
                "model": {"up": map_opt("model_P_batt_W", wind_h), "down": map_opt("model_P_batt_W", -wind_h)},
                "speeds": vmap.tolist(), "P_sim_W": perf["sim_P_batt_W"].tolist(),
                "P_model_W": perf["model_P_batt_W"].tolist(), "fit_minus_sim_W": (fit_p_w - perf["sim_P_batt_W"]).tolist()}
    log(f"          diagnostic, measured map points without the fit: up-wind optimum {map_diag['sim']['up']:.2f} m/s "
        f"(simulation) / {map_diag['model']['up']:.2f} m/s (independent model)")

    # ------------------------------------------------------------ 6 criteria, tables, figures
    log("STEP 6/6  criteria, tables and figures")
    legs_b = pd.read_csv(out / "baseline" / "legs.csv")
    legs_o = pd.read_csv(out / "optimised" / "legs.csv")
    legs_b["design"], legs_o["design"] = "baseline", "optimised"
    legs = pd.concat([legs_b, legs_o], ignore_index=True)
    legs["direction"] = legs["tailwind_mean_mps"].map(lambda w: "down-wind" if w > 0 else "up-wind")
    legs.to_csv(out / "legs.csv", index=False)

    def dec_names(s):
        return [d if isinstance(d, str) else d.get("name", "") for d in s.get("decisions", [])]

    saving = 100 * (1 - s_opt["mission_E_Wh"] / s_base["mission_E_Wh"])
    crit = {
        "C1": s_base["status"] == "LANDED" and s_opt["status"] == "LANDED"
              and s_base.get("rtl_reason") == "mission_complete" and s_opt.get("rtl_reason") == "mission_complete",
        "C2": abs(s_base["energy_closure"]["relative"]) < 1e-3 and abs(s_opt["energy_closure"]["relative"]) < 1e-3,
        "C3": saving >= 2.0,
        "C4": abs(law_up - pred_up) <= 1.5 and abs(law_down - pred_down) <= 1.5,
        "C5": (all(r["saving_pct"] > 0 and r["baseline_status"] == r["optimised_status"] == "LANDED"
                   and r["baseline_return"] == r["optimised_return"] == "mission_complete" for r in robust)
               if robust else None),
        "C6": (s_opt["touchdown"]["sink_mps"] is not None and abs(s_opt["touchdown"]["sink_mps"]) < 2.5
               and not any(n.startswith(("D4", "D5")) for n in dec_names(s_opt))),
    }

    def row(name, s):
        return {"design": name, "status": s["status"], "mission_E_Wh": s["mission_E_Wh"],
                "mission_Wh_per_km": s["mission_Wh_per_km"], "E_batt_Wh": s["E_batt_Wh"],
                "Wh_per_km": s["Wh_per_km"], "flight_time_s": s["flight_time_s"], "soc_end": s["soc_end"],
                "eta_propeller": s["eta"]["propeller"], "wind_work_Wh": s["energy_breakdown_Wh"]["wind_work"],
                "drag_work_Wh": s["energy_breakdown_Wh"]["drag_work"],
                "touchdown_sink_mps": s["touchdown"]["sink_mps"], "closure_relative": s["energy_closure"]["relative"]}

    comp = pd.DataFrame([row("baseline", s_base), row("optimised", s_opt)])
    comp.to_csv(out / "comparison.csv", index=False)
    results = {
        "scenario": SCENARIO, "seed": SEED, "baseline": BASELINE, "optimised": OPT,
        "optimisation": {"spec": spec, "result": result, "flights": 8 * iters + 1},
        "summary": {"baseline": row("baseline", s_base), "optimised": row("optimised", s_opt),
                    "mission_saving_pct": saving,
                    "total_saving_pct": 100 * (1 - s_opt["E_batt_Wh"] / s_base["E_batt_Wh"])},
        "physics": {"wind_at_cruise_mps": wind_h, "fit": {k2: fit[k2] for k2 in ("a", "b", "c")},
                    "pred_upwind_mps": pred_up, "pred_downwind_mps": pred_down,
                    "law_upwind_mps": law_up, "law_downwind_mps": law_down, "map_diagnostic": map_diag},
        "reference_policy": _vv_d1(),
        "robustness": robust, "criteria_text": CRITERIA, "criteria": crit,
        "wall_time_s": time.time() - t0 + _previous_wall(out, a.resume),
    }
    (out / "poc_results.json").write_text(json.dumps(results, indent=2, default=float), encoding="utf-8")
    try:
        from poc_figures import make_figures
    except ImportError:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from poc_figures import make_figures
    make_figures(out)

    print("\n" + "=" * 78)
    print(f"PoC result   mission-leg energy  baseline {s_base['mission_E_Wh']:.2f} Wh  ->  optimised "
          f"{s_opt['mission_E_Wh']:.2f} Wh   ({saving:+.1f} % saving)")
    print(f"             optimised law: V = {v0:.2f} + {k:.3f} x headwind  "
          f"(up-wind {law_up:.1f} m/s, down-wind {law_down:.1f} m/s)")
    for cid, ok in crit.items():
        tag = "n/a " if ok is None else ("PASS" if ok else "FAIL")
        print(f"  {cid} {tag}  {CRITERIA[cid]}")
    print(f"Results in {out}   (total {results['wall_time_s'] / 60:.1f} min)")
    return 0 if all(v in (True, None) for v in crit.values()) else 1


if __name__ == "__main__":        # required on Windows: the optimiser starts worker processes
    sys.exit(main())
