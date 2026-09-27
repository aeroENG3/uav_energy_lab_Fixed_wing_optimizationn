"""Command line interface.

  python -m uavlab run configs/missions/survey_box.yaml configs/wind/gusty.yaml --set sim.seed=7
  python -m uavlab sweep configs/experiments/wind_speed_direction.yaml --workers 4
  python -m uavlab performance            # power-required / best-range / endurance map
  python -m uavlab validate [--quick]     # verification & validation suite + report
  python -m uavlab config <files> --set k=v   # print the resolved configuration
  python -m uavlab ui                     # graphical interface in the browser (http://127.0.0.1:8050)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml


def _parse_sets(items):
    out = {}
    for it in items or []:
        if "=" not in it:
            raise SystemExit(f"--set expects key=value, got '{it}'")
        k, v = it.split("=", 1)
        out[k.strip()] = yaml.safe_load(v)
    return out


def main(argv=None):
    # Windows consoles and redirected output may not be UTF-8: never crash on a symbol
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(prog="uavlab", description="UAV Energy Lab (JSBSim Rascal 110 electric)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="run one simulation")
    r.add_argument("scenario", nargs="*", help="scenario YAML files merged over configs/defaults.yaml")
    r.add_argument("--set", action="append", help="override, e.g. --set wind.mean.speed_mps=6")
    r.add_argument("--out", default=None, help="run directory (default runs/<run_id>)")
    r.add_argument("--no-plot", action="store_true")
    s = sub.add_parser("sweep", help="batch / Monte-Carlo sweep -> dataset")
    s.add_argument("spec")
    s.add_argument("--out", default="sweeps")
    s.add_argument("--workers", type=int, default=None)
    p = sub.add_parser("performance", help="steady-flight performance map of the aircraft + powertrain")
    p.add_argument("--out", default="validation_report/performance")
    p.add_argument("--set", action="append")
    v = sub.add_parser("validate", help="run the V&V suite and write the report")
    v.add_argument("--out", default="validation_report")
    v.add_argument("--quick", action="store_true", help="shorter statistical tests")
    u = sub.add_parser("ui", help="start the graphical user interface (local web app)")
    u.add_argument("--workspace", default=".", help="folder for runs/, sweeps/, scenarios/ ... (default: current)")
    u.add_argument("--host", default="127.0.0.1", help="use 0.0.0.0 to share on a lab network")
    u.add_argument("--port", type=int, default=8050)
    u.add_argument("--no-browser", action="store_true")
    c = sub.add_parser("config", help="print the resolved configuration")
    c.add_argument("scenario", nargs="*")
    c.add_argument("--set", action="append")
    a = ap.parse_args(argv)

    if a.cmd == "run":
        from .config import load_config
        from .simulation import Simulation
        cfg = load_config(*a.scenario, overrides=_parse_sets(a.set))
        sim = Simulation(cfg, run_dir=a.out)
        res = sim.run()
        if not a.no_plot and res.run_dir:
            from .plotting import run_dashboard
            run_dashboard(res.run_dir)
        keep = ("status", "termination", "flight_time_s", "E_batt_Wh", "Wh_per_km", "soc_end", "decisions",
                "touchdown", "energy_closure")
        print(json.dumps({k: res.summary.get(k) for k in keep}, indent=2, default=str))
        print(f"logs: {res.run_dir}")
        return 0 if res.status in ("LANDED", "NO_GO") else 1
    if a.cmd == "sweep":
        from .batch import run_sweep
        out = run_sweep(a.spec, a.out, a.workers)
        print(f"dataset: {out}")
        return 0
    if a.cmd == "performance":
        from .validation.performance import performance_map
        out = performance_map(Path(a.out), overrides=_parse_sets(a.set))
        print(f"performance map: {out}")
        return 0
    if a.cmd == "validate":
        from .validation.suite import run_suite
        ok = run_suite(Path(a.out), quick=a.quick)
        return 0 if ok else 1
    if a.cmd == "ui":
        from .ui.server import serve
        serve(a.workspace, a.host, a.port, not a.no_browser)
        return 0
    if a.cmd == "config":
        from .config import load_config
        cfg = load_config(*a.scenario, overrides=_parse_sets(a.set))
        print(yaml.safe_dump(cfg, sort_keys=False))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
