"""No-code design optimisation: Cross-Entropy Method (CEM) over any numeric
configuration parameters, minimising or maximising any run KPI, subject to
constraints, averaged over a set of evaluation conditions (e.g. several winds)
with common random numbers (the same seeds for every candidate).

Why CEM: derivative-free, robust to the noise that turbulence puts on every
evaluation, trivially parallel (a whole population per generation), and needs
only bounds. Reference: Rubinstein & Kroese, "The Cross-Entropy Method", 2004.

Spec (dict or YAML):
  name: speed_law
  base_config: {...}                 # full or partial config (UI) - or scenario: [files]
  variables:
    - {path: autonomy.policy.params.v0,     lo: 12, hi: 20}
    - {path: autonomy.policy.params.k_head, lo: 0.0, hi: 1.2}
  objective: {kpi: mission_E_Wh, sense: min}
  constraints:
    - {kpi: status, op: "==", value: LANDED}
  conditions:                        # objective = mean over conditions x seeds
    - {label: calm,  overrides: {wind.mean.speed_mps: 0}}
    - {label: west6, overrides: {wind.mean.speed_mps: 6, wind.mean.from_deg: 270}}
  seeds: [1]
  algorithm: {population: 8, elite_frac: 0.25, iterations: 5, init_sigma_frac: 0.3,
              min_sigma_frac: 0.02, smoothing: 0.7, seed: 0}
  workers: 2

Outputs in <out_root>/<name>/: spec.yaml, evaluations.csv (every run), generations.csv,
result.json (best design) and best_run/ (full logs of the best design, first condition).
"""
from __future__ import annotations

import json
import multiprocessing
import math
import operator
import os
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from .batch import _flatten, run_one

OPS = {"==": operator.eq, "!=": operator.ne, "<": operator.lt, "<=": operator.le, ">": operator.gt,
       ">=": operator.ge}
PENALTY = 1e6


def _kpi(summary_flat: dict, key: str):
    return summary_flat.get(key)


def _violations(flat: dict, constraints: list) -> int:
    n = 0
    for c in constraints or []:
        v = _kpi(flat, c["kpi"])
        try:
            ok = v is not None and OPS[c["op"]](v if isinstance(c["value"], str) else float(v), c["value"])
        except (TypeError, ValueError):
            ok = False
        n += 0 if ok else 1
    return n


def run_optimisation(spec: dict | str | Path, out_root: str | Path = "optimisations", progress=print,
                     on_generation=None, cancel=None) -> Path:
    if not isinstance(spec, dict):
        spec = yaml.safe_load(Path(spec).read_text(encoding="utf-8"))
    name = spec.get("name", "optimisation")
    out = Path(out_root) / name
    out.mkdir(parents=True, exist_ok=True)
    (out / "spec.yaml").write_text(yaml.safe_dump(spec, sort_keys=False), encoding="utf-8")
    (out / "status.json").write_text(json.dumps({"state": "running"}), encoding="utf-8")
    var = spec["variables"]
    lo = np.array([float(v["lo"]) for v in var])
    hi = np.array([float(v["hi"]) for v in var])
    integer = np.array([bool(v.get("integer", False)) for v in var])
    alg = {"population": 8, "elite_frac": 0.25, "iterations": 5, "init_sigma_frac": 0.3,
           "min_sigma_frac": 0.02, "smoothing": 0.7, "seed": 0, **(spec.get("algorithm") or {})}
    rng = np.random.default_rng(int(alg["seed"]))
    mu = np.array([float(v["init"]) if v.get("init") is not None else 0.5 * (float(v["lo"]) + float(v["hi"]))
                   for v in var])
    sigma = float(alg["init_sigma_frac"]) * (hi - lo)
    sig_min = float(alg["min_sigma_frac"]) * (hi - lo)
    conds = spec.get("conditions") or [{"label": "base", "overrides": {}}]
    seeds = spec.get("seeds") or [1]
    obj = spec["objective"]
    sense = 1.0 if obj.get("sense", "min") == "min" else -1.0
    workers = int(spec.get("workers") or max(1, (os.cpu_count() or 2)))
    n_pop = int(alg["population"])
    n_elite = max(2, int(round(float(alg["elite_frac"]) * n_pop)))
    evals, gens = [], []
    best = {"objective": math.inf, "x": None}
    progress(f"[optimise {name}] {len(var)} variables, {n_pop} candidates x {len(conds)} conditions x "
             f"{len(seeds)} seeds per generation, {alg['iterations']} generations, {workers} workers")

    def make_job(gen, ci, x, cond, seed):
        ov = dict(spec.get("fixed") or {})
        ov.update(cond.get("overrides") or {})
        for v, xv, isint in zip(var, x, integer):
            ov[v["path"]] = int(round(xv)) if isint else float(xv)
        ov["sim.seed"] = int(seed)
        return {"run_id": f"g{gen:02d}_c{ci:02d}_{cond.get('label', 'c')}_s{seed}", "point": ci, "replicate": 0,
                "scenario": spec.get("scenario", []), "base_config": spec.get("base_config"), "overrides": ov,
                "params": {}, "out_dir": str(out / "runs"), "write_logs": False}

    cancelled = False
    with ProcessPoolExecutor(max_workers=workers, mp_context=multiprocessing.get_context("spawn")) as ex:
        for gen in range(int(alg["iterations"])):
            if cancel is not None and cancel():
                cancelled = True
                break
            X = np.clip(mu + sigma * rng.standard_normal((n_pop, len(var))), lo, hi)
            X[0] = np.clip(mu, lo, hi)                      # always evaluate the current mean
            X = np.where(integer, np.round(X), X)
            jobs, index = [], []
            for ci, x in enumerate(X):
                for cond in conds:
                    for sd in seeds:
                        jobs.append(make_job(gen, ci, x, cond, sd))
                        index.append((ci, cond.get("label", "c"), sd))
            results = list(ex.map(run_one, jobs))
            J = np.zeros(n_pop)
            nviol = np.zeros(n_pop)
            count = np.zeros(n_pop)
            for (ci, lab, sd), r in zip(index, results):
                flat = _flatten(r["summary"]) if r.get("ok") else {"status": "ERROR"}
                val = _kpi(flat, obj["kpi"])
                nv = _violations(flat, spec.get("constraints")) + (0 if r.get("ok") else 1)
                try:
                    val = float(val)
                except (TypeError, ValueError):
                    val = float("nan")
                if not math.isfinite(val):
                    nv += 1
                    val = 0.0
                J[ci] += sense * val
                nviol[ci] += nv
                count[ci] += 1
                evals.append({"generation": gen, "candidate": ci, "condition": lab, "seed": sd,
                              **{v["path"]: float(X[ci][k]) for k, v in enumerate(var)},
                              "objective_kpi": val, "violations": nv, "status": flat.get("status"),
                              "E_batt_Wh": flat.get("E_batt_Wh"), "Wh_per_km": flat.get("Wh_per_km"),
                              "flight_time_s": flat.get("flight_time_s")})
            J = J / np.maximum(count, 1)
            score = J + PENALTY * nviol                      # feasible designs always rank first
            order = np.argsort(score)
            elite = X[order[:n_elite]]
            a = float(alg["smoothing"])
            mu = (1 - a) * mu + a * elite.mean(axis=0)
            sigma = np.maximum((1 - a) * sigma + a * elite.std(axis=0), sig_min)
            ib = int(order[0])
            if nviol[ib] == 0 and J[ib] < best["objective"]:
                best = {"objective": float(J[ib]), "x": X[ib].tolist(), "generation": gen}
            g = {"generation": gen, "best_objective": float(sense * J[ib]) if nviol[ib] == 0 else None,
                 "mean_feasible_objective": float(sense * J[nviol == 0].mean()) if (nviol == 0).any() else None,
                 "feasible": int((nviol == 0).sum()), "population": n_pop,
                 **{f"mu.{v['path']}": float(m) for v, m in zip(var, mu)},
                 **{f"sigma.{v['path']}": float(s) for v, s in zip(var, sigma)}}
            gens.append(g)
            pd.DataFrame(evals).to_csv(out / "evaluations.csv", index=False)
            pd.DataFrame(gens).to_csv(out / "generations.csv", index=False)
            progress(f"  generation {gen + 1}/{alg['iterations']}: best {g['best_objective']} "
                     f"({g['feasible']}/{n_pop} feasible)")
            if on_generation is not None:
                on_generation(g)
    result = {"name": name, "objective": obj, "sense": obj.get("sense", "min"),
              "best_objective": (sense * best["objective"]) if best["x"] is not None else None,
              "best_variables": ({v["path"]: (int(round(x)) if isint else x)
                                  for v, x, isint in zip(var, best["x"], integer)} if best["x"] else None),
              "final_mean": {v["path"]: float(m) for v, m in zip(var, mu)},
              "generations": len(gens), "cancelled": cancelled}
    # verification run of the best design with full logs (first condition, first seed)
    if best["x"] is not None and not cancelled:
        job = make_job(99, 0, np.array(best["x"]), conds[0], seeds[0])
        job["run_id"], job["out_dir"], job["write_logs"] = "best_run", str(out), True
        r = run_one(job)
        result["best_run_status"] = r["summary"]["status"] if r.get("ok") else "ERROR"
    (out / "result.json").write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    (out / "status.json").write_text(json.dumps({"state": "cancelled" if cancelled else "done"}), encoding="utf-8")
    return out
