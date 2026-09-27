"""UAV Energy Lab - local web UI server (FastAPI).

    python -m uavlab ui                 # http://127.0.0.1:8050
    python -m uavlab ui --workspace D:/uav_study --port 8060

All results are plain folders in the workspace (runs/, sweeps/, optimisations/,
performance/, validation_report/, scenarios/), so everything done in the UI is
also usable from Python and the command line, and vice versa.
"""
from __future__ import annotations

import copy
import json
import math
import os
import platform
import time
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd
import yaml
from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from .. import __version__
from ..config import ROOT, ConfigError, config_from_dict, deep_merge, diff_from_defaults, validate, _load_yaml, DEFAULTS
from .jobs import JobManager
from .schema import build_schema

STATIC = Path(__file__).parent / "static"
HANDBOOK = ROOT / "docs" / "handbook" / "handbook.html"


def _clean(o):
    """JSON-safe: NaN/inf -> None, numpy -> python."""
    if isinstance(o, dict):
        return {str(k): _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, (np.floating, float)):
        f = float(o)
        return f if math.isfinite(f) else None
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.bool_):
        return bool(o)
    return o


def _first_comment(path: Path) -> str:
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s.startswith("#"):
            return s.lstrip("# ").strip()
        if s:
            break
    return ""


def create_app(workspace: str | Path = ".") -> FastAPI:
    ws = Path(workspace).resolve()
    for d in ("runs", "sweeps", "optimisations", "scenarios", "performance"):
        (ws / d).mkdir(parents=True, exist_ok=True)
    jobs = JobManager(ws)
    app = FastAPI(title="UAV Energy Lab", version=__version__, docs_url="/api/docs")
    schema_cache = {}

    repo_dirs = [(ROOT / "validation_report").resolve(), (ROOT / "poc_results").resolve()]

    def safe_ref(ref: str, write: bool = False) -> Path:
        """Resolve a reference to a folder in the workspace, or (read-only, prefix 'repo:')
        to the V&V report shipped with the repository."""
        if ref.startswith("repo:"):
            if write:
                raise HTTPException(403, "repository results are read-only")
            p = (ROOT / ref[5:]).resolve()
            ok = any(p == r or r in p.parents for r in repo_dirs)
        else:
            p = (ws / ref).resolve()
            ok = p == ws or ws in p.parents
        if not ok:
            raise HTTPException(400, "path outside the workspace")
        if not p.exists():
            raise HTTPException(404, f"not found: {ref}")
        return p

    def ref_of(d: Path) -> str:
        d = d.resolve()
        if d == ws or ws in d.parents:
            return d.relative_to(ws).as_posix()
        return "repo:" + d.relative_to(ROOT.resolve()).as_posix()

    # ------------------------------------------------------------------ static
    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.get("/", response_class=HTMLResponse)
    def index():
        return (STATIC / "index.html").read_text(encoding="utf-8")

    @app.get("/handbook", response_class=HTMLResponse)
    def handbook():
        if HANDBOOK.exists():
            return HANDBOOK.read_text(encoding="utf-8")
        return "<p>Handbook not built. See docs/handbook/HANDBOOK.md.</p>"

    @app.get("/reports/validation", response_class=HTMLResponse)
    def vv_report():
        for p in (ws / "validation_report" / "VV_REPORT.html", ROOT / "validation_report" / "VV_REPORT.html"):
            if p.exists():
                return p.read_text(encoding="utf-8")
        return "<p>No validation report yet. Run the V&amp;V suite from the Validation page.</p>"

    # -------------------------------------------------------------------- meta
    @app.get("/api/meta")
    def meta():
        import jsbsim
        return {"version": __version__, "jsbsim": jsbsim.__version__, "python": platform.python_version(),
                "platform": platform.platform(terse=True), "cpus": os.cpu_count(), "workspace": str(ws),
                "repo": str(ROOT)}

    @app.get("/api/schema")
    def schema():
        if "s" not in schema_cache:
            schema_cache["s"] = _clean(build_schema())
        return schema_cache["s"]

    # ------------------------------------------------------------------ config
    @app.get("/api/config/defaults")
    def defaults():
        return _clean(_load_yaml(DEFAULTS))

    @app.post("/api/config/validate")
    def validate_cfg(cfg: dict = Body(...)):
        try:
            full = config_from_dict(cfg)
            return {"ok": True, "errors": [], "diff": _clean(diff_from_defaults(full))}
        except ConfigError as e:
            errs = [l.strip()[2:] for l in str(e).splitlines() if l.strip().startswith("- ")] or [str(e)]
            return {"ok": False, "errors": errs}
        except Exception as e:  # malformed values
            return {"ok": False, "errors": [f"{type(e).__name__}: {e}"]}

    def _preset_dirs():
        return {"missions": ROOT / "configs" / "missions", "wind": ROOT / "configs" / "wind",
                "experiments": ROOT / "configs" / "experiments", "scenarios": ws / "scenarios"}

    @app.get("/api/presets")
    def presets():
        out = {}
        for kind, d in _preset_dirs().items():
            out[kind] = [{"name": p.stem, "description": _first_comment(p)} for p in sorted(d.glob("*.yaml"))]
        return out

    @app.post("/api/config/apply")
    def apply_preset(body: dict = Body(...)):
        """Merge a preset (mission / wind / saved scenario) into the given config."""
        kind, name, cfg = body["kind"], body["name"], body.get("config") or {}
        d = _preset_dirs()[kind]
        p = d / f"{name}.yaml"
        if not p.exists():
            raise HTTPException(404, f"preset not found: {kind}/{name}")
        sc = _load_yaml(p)
        d0 = _load_yaml(DEFAULTS)
        if kind == "scenarios":
            base = d0                                   # a saved scenario is a full definition
        else:
            base = copy.deepcopy(cfg) if cfg else d0
            section = {"wind": "wind", "missions": "mission"}.get(kind)
            if section:                                 # a preset defines its whole section
                base[section] = copy.deepcopy(d0[section])
        for inc in sc.pop("include", []) or []:
            base = deep_merge(base, _load_yaml(p.parent / inc))
        merged = deep_merge(base, sc)                   # lists are replaced, not merged
        return _clean(merged)

    @app.get("/api/preset/raw")
    def preset_raw(kind: str, name: str):
        p = _preset_dirs()[kind] / f"{name}.yaml"
        if not p.exists():
            raise HTTPException(404)
        return {"text": p.read_text(encoding="utf-8"), "data": _clean(_load_yaml(p))}

    @app.post("/api/scenarios/save")
    def save_scenario(body: dict = Body(...)):
        name = "".join(c for c in body["name"] if c.isalnum() or c in "-_").strip() or "scenario"
        cfg = config_from_dict(body["config"])
        diff = diff_from_defaults(cfg)
        txt = f"# {body.get('description', '').strip() or name}\n" + yaml.safe_dump(diff, sort_keys=False)
        p = ws / "scenarios" / f"{name}.yaml"
        p.write_text(txt, encoding="utf-8")
        return {"saved": p.relative_to(ws).as_posix(), "name": name, "changed_keys": _count(diff)}

    @app.post("/api/config/export")
    def export_yaml(body: dict = Body(...)):
        cfg = config_from_dict(body["config"])
        full = bool(body.get("full"))
        return Response(yaml.safe_dump(cfg if full else diff_from_defaults(cfg), sort_keys=False),
                        media_type="text/yaml")

    # ---------------------------------------------------------------- previews
    @app.post("/api/preview/mission")
    def preview_mission(cfg: dict = Body(...)):
        from ..atmosphere import WindField
        from ..mission import Mission
        full = config_from_dict(cfg)
        m = Mission(full)
        wf = WindField(full["wind"], np.random.default_rng(0))
        w10 = wf.mean_wind(0.0, 10.0)[:2]
        rw, why = m.choose_runway(w10)
        ap = m.approach_points()
        legs = m.legs()
        route = [m.climbout_point()] + [l[2] for l in legs] + [ap["align"], ap["entry"], ap["td"]]
        length = float(sum(np.hypot(*(b - a)) for a, b in zip(route[:-1], route[1:])))
        return _clean({"waypoints": [{"name": w.name, "n": w.ne[0], "e": w.ne[1], "alt": w.alt_agl}
                                     for w in m.waypoints[: len(full["mission"]["waypoints"])]],
                       "runway": {"start": rw.start.tolist(), "end": rw.end.tolist(),
                                  "heading_deg": math.degrees(rw.heading) % 360, "selection": why,
                                  "width": rw.width},
                       "approach": {k: v.tolist() for k, v in ap.items()},
                       "climbout": m.climbout_point().tolist(), "route_length_m": length,
                       "wind10": w10.tolist(), "repeat": full["mission"].get("repeat", 1)})

    @app.post("/api/preview/wind")
    def preview_wind(body: dict = Body(...)):
        from ..atmosphere import WindField, dryden_scales
        full = config_from_dict(body["config"])
        h_ref = float(body.get("height_m", full["mission"]["cruise"]["alt_agl_m"]))
        V = float(body.get("airspeed_mps", full["mission"]["cruise"]["airspeed_mps"]))
        T = float(body.get("duration_s", 300.0))
        wf = WindField(full["wind"], np.random.default_rng(int(full["sim"]["seed"])))
        hs = np.linspace(1, 200, 80)
        prof = [wf.mean_wind(0.0, h) for h in hs]
        speed = [float(np.hypot(p[0], p[1])) for p in prof]
        frm = [float((math.degrees(math.atan2(-p[1], -p[0])) % 360) if np.hypot(p[0], p[1]) > 0.01 else 0.0)
               for p in prof]
        dt = 0.05
        n = int(T / dt)
        ts, mean_s, tot_n, tot_e, tot_d = [], [], [], [], []
        for i in range(n):
            s = wf.sample(i * dt, h_ref, V, 0.0, dt)
            if i % 4 == 0:
                tot = s.total
                ts.append(i * dt)
                mean_s.append(float(np.hypot(s.mean[0], s.mean[1])))
                tot_n.append(float(tot[0]))
                tot_e.append(float(tot[1]))
                tot_d.append(float(tot[2]))
        sc, sg = dryden_scales(h_ref, wf.w20(0.0))
        return _clean({"profile": {"h": hs.tolist(), "speed": speed, "from_deg": frm},
                       "series": {"t": ts, "mean_speed": mean_s, "n": tot_n, "e": tot_e, "d": tot_d},
                       "dryden": {"L_uvw_m": sc, "sigma_uvw_mps": sg, "w20_mps": wf.w20(0.0), "height_m": h_ref},
                       "turbulence_model": full["wind"]["turbulence"]["model"]})

    @app.post("/api/preview/battery")
    def preview_battery(cfg: dict = Body(...)):
        from ..energy.battery import Battery
        full = config_from_dict(cfg)
        b = Battery(full["powertrain"]["battery"])
        socs = np.linspace(0, 1, 101)
        ocv = [b.ns * b.ocv_cell(s) for s in socs]
        rsoc = float(full["mission"]["reserve"]["rtl_soc"])
        use = float(np.trapezoid([b.ns * b.ocv_cell(s) for s in np.linspace(rsoc, 1, 200)],
                                 np.linspace(rsoc, 1, 200)) * b.capacity_ah)
        mass_b = float(full["powertrain"]["battery"]["mass_kg"])
        auw = float(full["aircraft"]["airframe_mass_kg"]) + mass_b + float(full["aircraft"].get("payload_mass_kg", 0))
        return _clean({"soc": socs.tolist(), "ocv": ocv, "energy_Wh": b.energy_capacity_wh(), "usable_to_rtl_Wh": use,
                       "nominal_V": b.ns * b.ocv_cell(0.5), "full_V": b.ns * b.ocv_cell(1.0), "R0_mohm": 1000 * b.r0,
                       "R1_mohm": 1000 * b.r1, "tau_s": b.tau, "capacity_Ah": b.capacity_ah,
                       "specific_Wh_per_kg": b.energy_capacity_wh() / mass_b if mass_b > 0 else None,
                       "all_up_mass_kg": auw})

    # -------------------------------------------------------------------- jobs
    @app.get("/api/jobs")
    def list_jobs():
        return _clean(jobs.list())

    @app.get("/api/jobs/{jid}")
    def job_detail(jid: str, since_row: int = 0, since_event: int = 0, since_log: int = 0, since_result: int = 0):
        try:
            return _clean(jobs.get(jid).detail(since_row, since_event, since_log, since_result))
        except KeyError:
            raise HTTPException(404, "unknown job")

    @app.get("/api/jobs/{jid}/config")
    def job_config(jid: str):
        try:
            j = jobs.get(jid)
        except KeyError:
            raise HTTPException(404, "unknown job")
        return _clean(j.config or {})

    @app.post("/api/jobs/{jid}/cancel")
    def job_cancel(jid: str):
        return _clean(jobs.cancel(jid))

    @app.post("/api/run")
    def start_run(body: dict = Body(...)):
        try:
            cfg = config_from_dict(body["config"])
        except ConfigError as e:
            raise HTTPException(422, str(e))
        return jobs.submit_run(cfg, body.get("label", "")).brief()

    @app.post("/api/sweep")
    def start_sweep(spec: dict = Body(...)):
        try:
            config_from_dict(spec["base_config"])
        except ConfigError as e:
            raise HTTPException(422, str(e))
        name = "".join(c for c in spec.get("name", "sweep") if c.isalnum() or c in "-_") or "sweep"
        spec["name"] = name
        return jobs.submit_sweep(spec).brief()

    @app.post("/api/optimise")
    def start_optimise(spec: dict = Body(...)):
        try:
            config_from_dict(spec["base_config"])
        except ConfigError as e:
            raise HTTPException(422, str(e))
        name = "".join(c for c in spec.get("name", "opt") if c.isalnum() or c in "-_") or "opt"
        spec["name"] = name
        return jobs.submit_optimise(spec).brief()

    @app.post("/api/tools/performance")
    def start_perf(body: dict = Body(...)):
        return jobs.submit_performance(config_from_dict(body["config"]), bool(body.get("quick", False))).brief()

    @app.post("/api/tools/validate")
    def start_validate(body: dict = Body(...)):
        return jobs.submit_validate(bool(body.get("quick", False))).brief()

    # -------------------------------------------------------------------- runs
    def _run_brief(d: Path) -> dict | None:
        try:
            s = json.loads((d / "summary.json").read_text(encoding="utf-8"))
        except Exception:
            return None
        cfgp = d / "config_resolved.yaml"
        wind, pol, cruise = None, None, None
        label = ""
        if (d / "ui_meta.json").exists():
            try:
                label = json.loads((d / "ui_meta.json").read_text(encoding="utf-8")).get("label", "")
            except Exception:
                pass
        try:
            c = yaml.safe_load(cfgp.read_text(encoding="utf-8"))
            wind = c["wind"]["mean"]["speed_mps"]
            wdir = c["wind"]["mean"]["from_deg"]
            turb = c["wind"]["turbulence"]["model"]
            pol = c["autonomy"]["policy"]["name"]
            cruise = c["mission"]["cruise"]["airspeed_mps"]
            nwp = len(c["mission"]["waypoints"])
        except Exception:
            wdir = turb = nwp = None
        return {"ref": ref_of(d), "run_id": s.get("run_id", d.name), "label": label,
                "mtime": d.stat().st_mtime, "status": s.get("status"), "termination": s.get("termination"),
                "flight_time_s": s.get("flight_time_s"), "E_batt_Wh": s.get("E_batt_Wh"),
                "Wh_per_km": s.get("Wh_per_km"), "soc_end": s.get("soc_end"), "dist_km": s.get("dist_ground_km"),
                "wind_mps": wind, "wind_from_deg": wdir, "turbulence": turb, "policy": pol, "cruise_mps": cruise,
                "waypoints": nwp, "decisions": s.get("decisions", []), "config_hash": s.get("config_hash")}

    @app.get("/api/runs")
    def list_runs(source: str = "runs"):
        try:
            base = safe_ref(source) if source != "runs" else ws / "runs"
        except HTTPException as e:
            if e.status_code == 404:          # e.g. no proof-of-concept results yet
                return []
            raise
        out = []
        for d in sorted(base.glob("*"), key=lambda p: -p.stat().st_mtime):
            if d.is_dir() and (d / "summary.json").exists():
                b = _run_brief(d)
                if b:
                    out.append(b)
        return _clean(out)

    @app.get("/api/run")
    def run_detail(ref: str):
        d = safe_ref(ref)
        out = {"ref": ref}
        for name in ("summary", "metadata"):
            p = d / f"{name}.json"
            out[name] = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
        for name in ("events", "legs", "phases"):
            p = d / f"{name}.csv"
            try:
                out[name] = pd.read_csv(p).to_dict("records") if p.exists() and p.stat().st_size > 2 else []
            except Exception:
                out[name] = []
        out["files"] = sorted(x.name for x in d.iterdir() if x.is_file())
        out["brief"] = _run_brief(d)
        return _clean(out)

    @lru_cache(maxsize=6)
    def _load_ts(path: str, mtime: float) -> pd.DataFrame:
        p = Path(path)
        return pd.read_parquet(p) if p.suffix == ".parquet" else pd.read_csv(p, low_memory=False)

    def _ts(d: Path) -> pd.DataFrame:
        for n in ("timeseries.parquet", "timeseries.csv"):
            if (d / n).exists():
                return _load_ts(str(d / n), (d / n).stat().st_mtime)
        raise HTTPException(404, "this run has no time-series file")

    @app.get("/api/run/columns")
    def run_columns(ref: str):
        df = _ts(safe_ref(ref))
        num = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
        return {"numeric": num, "all": list(df.columns), "rows": len(df)}

    @app.get("/api/run/series")
    def run_series(ref: str, cols: str = Query(...), max_points: int = 6000):
        df = _ts(safe_ref(ref))
        cols_l = [c for c in cols.split(",") if c in df.columns]
        step = max(1, int(math.ceil(len(df) / max_points)))
        sub = df.iloc[::step]
        out = {"t_s": sub["t_s"].tolist(), "mode": sub["mode"].astype(str).tolist() if "mode" in sub else []}
        for c in cols_l:
            out[c] = sub[c].tolist() if pd.api.types.is_numeric_dtype(sub[c]) else sub[c].astype(str).tolist()
        return _clean(out)

    @app.get("/api/run/config")
    def run_config(ref: str):
        d = safe_ref(ref)
        return _clean(yaml.safe_load((d / "config_resolved.yaml").read_text(encoding="utf-8")))

    @app.get("/api/file")
    def get_file(ref: str, name: str):
        d = safe_ref(ref)
        p = (d / name).resolve()
        if d not in p.parents or not p.is_file():
            raise HTTPException(404)
        return FileResponse(p, filename=p.name)

    @app.post("/api/run/label")
    def set_label(body: dict = Body(...)):
        d = safe_ref(body["ref"], write=True)
        meta = {}
        if (d / "ui_meta.json").exists():
            meta = json.loads((d / "ui_meta.json").read_text(encoding="utf-8"))
        meta["label"] = body.get("label", "")
        (d / "ui_meta.json").write_text(json.dumps(meta), encoding="utf-8")
        return {"ok": True}

    # ------------------------------------------------------------------ sweeps
    def _study_list(kind):
        out = []
        for d in sorted((ws / kind).glob("*"), key=lambda p: -p.stat().st_mtime):
            if not d.is_dir():
                continue
            st = {}
            if (d / "status.json").exists():
                try:
                    st = json.loads((d / "status.json").read_text(encoding="utf-8"))
                except Exception:
                    pass
            out.append({"name": d.name, "mtime": d.stat().st_mtime, **st})
        return out

    @app.get("/api/sweeps")
    def list_sweeps():
        return _clean(_study_list("sweeps"))

    @app.get("/api/sweep")
    def sweep_detail(name: str, legs: bool = False):
        d = safe_ref(f"sweeps/{name}")
        out = {"name": name, "spec": _load_yaml(d / "sweep_spec.yaml") if (d / "sweep_spec.yaml").exists() else {}}
        out["spec"].pop("base_config", None)
        p = d / "dataset_runs.csv"
        out["runs"] = pd.read_csv(p).to_dict("records") if p.exists() else []
        if legs and (d / "dataset_legs.csv").exists():
            out["legs"] = pd.read_csv(d / "dataset_legs.csv").to_dict("records")
        if (d / "failures.csv").exists():
            out["failures"] = pd.read_csv(d / "failures.csv").to_dict("records")
        out["files"] = sorted(x.name for x in d.iterdir() if x.is_file())
        return _clean(out)

    @app.get("/api/optimisations")
    def list_opts():
        return _clean(_study_list("optimisations"))

    @app.get("/api/optimisation")
    def opt_detail(name: str):
        d = safe_ref(f"optimisations/{name}")
        out = {"name": name}
        if (d / "spec.yaml").exists():
            out["spec"] = _load_yaml(d / "spec.yaml")
            out["spec"].pop("base_config", None)
        for n in ("generations", "evaluations"):
            p = d / f"{n}.csv"
            out[n] = pd.read_csv(p).to_dict("records") if p.exists() else []
        out["result"] = json.loads((d / "result.json").read_text(encoding="utf-8")) if (d / "result.json").exists() else None
        out["best_run_ref"] = f"optimisations/{name}/best_run" if (d / "best_run" / "summary.json").exists() else None
        return _clean(out)

    # ------------------------------------------------------------- performance
    @app.get("/api/performance")
    def performance():
        for d in (ws / "performance", ROOT / "validation_report" / "performance"):
            if (d / "performance.csv").exists():
                return _clean({"source": str(d), "rows": pd.read_csv(d / "performance.csv").to_dict("records"),
                               "fit": json.loads((d / "performance_fit.json").read_text(encoding="utf-8")),
                               "is_workspace": d == ws / "performance"})
        return {"rows": [], "fit": None}

    @app.get("/api/validation")
    def validation_summary():
        for d in (ws / "validation_report", ROOT / "validation_report"):
            p = d / "vv_results.json"
            if p.exists():
                js = json.loads(p.read_text(encoding="utf-8"))
                return _clean({"source": str(d), "meta": js["meta"], "passed": js["passed"], "total": js["total"],
                               "checks": [{k: c[k] for k in ("id", "title", "criterion", "value", "passed", "kind")}
                                          for c in js["checks"]]})
        return {"checks": []}

    return app


def _count(d):
    return sum(_count(v) if isinstance(v, dict) else 1 for v in d.values())


def serve(workspace=".", host="127.0.0.1", port=8050, open_browser=True):
    import threading
    import webbrowser

    import uvicorn
    app = create_app(workspace)
    url = f"http://{host}:{port}/"
    print(f"UAV Energy Lab UI  ->  {url}   (workspace: {Path(workspace).resolve()})")
    if open_browser:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host=host, port=port, log_level="warning")
