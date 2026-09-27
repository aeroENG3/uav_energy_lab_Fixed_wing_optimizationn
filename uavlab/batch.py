"""Batch / Monte-Carlo runner: builds a dataset for offline optimisation.

Sweep spec (YAML):
  name: wind_sweep
  scenario: [configs/missions/survey_box.yaml]      # base files (merged in order)
  fixed: {sim.log_rate_hz: 5}                        # overrides applied to every run
  grid:                                              # full-factorial part
    wind.mean.speed_mps: [0, 4, 8]
    wind.mean.from_deg: [270, 0]
  random:                                            # Latin-hypercube part (n samples)
    n: 20
    params:
      mission.cruise.airspeed_mps: {uniform: [14, 22]}
      wind.turbulence.intensity: {choice: [auto, light]}
  replicates: 2                                      # seeds per point (turbulence/noise)
  workers: 4

Outputs in <out>/<name>/:
  runs/<run_id>/...     full logs of every run
  dataset_runs.csv      one row per run: parameters + KPIs      (-> surrogate / BO / GA)
  dataset_legs.csv      one row per mission leg: parameters + wind + energy (-> wind-energy models)
  sweep_spec.yaml       the spec that produced the dataset
"""
from __future__ import annotations

import itertools
import json
import multiprocessing
import os
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from .config import load_config


def _flatten(d: dict, prefix="") -> dict:
    out = {}
    for k, v in d.items():
        key = f"{prefix}{k}"
        if isinstance(v, dict):
            out.update(_flatten(v, key + "."))
        elif isinstance(v, (list, tuple)):
            out[key] = json.dumps(v)
        else:
            out[key] = v
    return out


def run_one(job: dict) -> dict:
    """Run a single job in a worker process. Never raises: failures are recorded."""
    from .simulation import Simulation
    try:
        if job.get("base_config") is not None:
            from .config import config_from_dict
            cfg = config_from_dict(job["base_config"], job["overrides"])
        else:
            cfg = load_config(*job["scenario"], overrides=job["overrides"])
        cfg["logging"]["out_dir"] = job["out_dir"]
        sim = Simulation(cfg, run_dir=Path(job["out_dir"]) / job["run_id"], run_id=job["run_id"],
                         write_logs=job.get("write_logs", True), keep_timeseries=False)
        res = sim.run()
        legs_path = Path(job["out_dir"]) / job["run_id"] / "legs.csv"
        legs = pd.read_csv(legs_path).to_dict("records") if legs_path.exists() and legs_path.stat().st_size > 1 else []
        return {"ok": True, "job": job, "summary": res.summary, "legs": legs}
    except Exception as e:  # pragma: no cover - reported in the dataset
        return {"ok": False, "job": job, "error": f"{type(e).__name__}: {e}", "trace": traceback.format_exc()}


def _lhs(n: int, params: dict, rng: np.random.Generator) -> list[dict]:
    out = [dict() for _ in range(n)]
    for name, spec in params.items():
        u = (rng.permutation(n) + rng.random(n)) / n
        for i in range(n):
            if "uniform" in spec:
                lo, hi = spec["uniform"]
                out[i][name] = float(lo + (hi - lo) * u[i])
            elif "choice" in spec:
                ch = spec["choice"]
                out[i][name] = ch[min(int(u[i] * len(ch)), len(ch) - 1)]
            else:
                raise ValueError(f"random param {name}: use uniform or choice")
    return out


def build_jobs(spec: dict, out_dir: Path) -> list[dict]:
    rng = np.random.default_rng(int(spec.get("seed", 12345)))
    points: list[dict] = []
    grid = spec.get("grid") or {}
    if grid:
        keys = list(grid)
        for vals in itertools.product(*[grid[k] for k in keys]):
            points.append(dict(zip(keys, vals)))
    rnd = spec.get("random")
    if rnd:
        samples = _lhs(int(rnd["n"]), rnd["params"], rng)
        points = [dict(p, **s) for p in (points or [{}]) for s in samples]
    if not points:
        points = [{}]
    reps = int(spec.get("replicates", 1))
    jobs = []
    for i, p in enumerate(points):
        for r in range(reps):
            ov = dict(spec.get("fixed") or {})
            ov.update(p)
            ov.setdefault("sim.seed", 1000 * i + r + 1)
            jobs.append({"run_id": f"p{i:04d}_r{r}", "point": i, "replicate": r,
                         "scenario": spec.get("scenario", []), "base_config": spec.get("base_config"),
                         "overrides": ov,
                         "params": p, "out_dir": str(out_dir / "runs"),
                         "write_logs": bool(spec.get("write_logs", True))})
    return jobs


def run_sweep(spec_path: str | Path | dict, out_root: str | Path = "sweeps", workers: int | None = None,
              progress=print, on_result=None, cancel=None) -> Path:
    """spec_path: YAML file or an already-parsed spec dict (the UI passes a dict that
    may carry 'base_config'). on_result(record) is called per finished run;
    cancel() -> True stops submitting/collecting further runs."""
    spec = spec_path if isinstance(spec_path, dict) else yaml.safe_load(Path(spec_path).read_text(encoding="utf-8"))
    name = spec.get("name") or (Path(spec_path).stem if not isinstance(spec_path, dict) else "sweep")
    out = Path(out_root) / name
    (out / "runs").mkdir(parents=True, exist_ok=True)
    (out / "sweep_spec.yaml").write_text(yaml.safe_dump(spec, sort_keys=False), encoding="utf-8")
    (out / "status.json").write_text(json.dumps({"state": "running"}), encoding="utf-8")
    jobs = build_jobs(spec, out)
    workers = workers or int(spec.get("workers", max(1, (os.cpu_count() or 2) - 1)))
    progress(f"[sweep {name}] {len(jobs)} runs on {workers} workers -> {out}")
    run_rows, leg_rows, fails = [], [], []
    cancelled = False
    with ProcessPoolExecutor(max_workers=workers, mp_context=multiprocessing.get_context("spawn")) as ex:
        futs = [ex.submit(run_one, j) for j in jobs]
        for k, f in enumerate(as_completed(futs), 1):
            if cancel is not None and cancel():
                for g in futs:
                    g.cancel()
                cancelled = True
                break
            r = f.result()
            j = r["job"]
            base = {"run_id": j["run_id"], "point": j["point"], "replicate": j["replicate"],
                    "seed": j["overrides"].get("sim.seed")}
            base.update({f"param.{k2}": v for k2, v in j["params"].items()})
            if not r["ok"]:
                fails.append({**base, "error": r["error"]})
                progress(f"  [{k}/{len(jobs)}] {j['run_id']} FAILED: {r['error']}")
                continue
            s = _flatten(r["summary"])
            rec = {**base, **{f"kpi.{a}": b for a, b in s.items()}}
            run_rows.append(rec)
            for leg in r["legs"]:
                leg_rows.append({**base, **leg})
            if on_result is not None:
                on_result(rec)
            progress(f"  [{k}/{len(jobs)}] {j['run_id']} {r['summary']['status']} "
                     f"E={r['summary'].get('E_batt_Wh', float('nan')):.2f} Wh")
    if run_rows:
        pd.DataFrame(run_rows).sort_values("run_id").to_csv(out / "dataset_runs.csv", index=False)
    pd.DataFrame(leg_rows).to_csv(out / "dataset_legs.csv", index=False)
    if fails:
        pd.DataFrame(fails).to_csv(out / "failures.csv", index=False)
    (out / "status.json").write_text(json.dumps({"state": "cancelled" if cancelled else "done",
                                                 "runs": len(run_rows), "failed": len(fails)}), encoding="utf-8")
    return out
