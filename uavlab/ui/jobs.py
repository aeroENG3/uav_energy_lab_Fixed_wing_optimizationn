"""Job manager for the UI: every experiment runs outside the web server process
(spawned processes, so a crash or a long computation never blocks the UI).

Job kinds: run (single simulation with live telemetry), sweep (DOE / Monte Carlo),
optimise (CEM), performance (steady-flight map), validate (V&V suite).
States: queued -> running -> done | failed | cancelled.
"""
from __future__ import annotations

import io
import json
import multiprocessing as mp
import queue
import sys
import threading
import time
import traceback
import uuid
from datetime import datetime
from pathlib import Path

CTX = mp.get_context("spawn")

TELEMETRY_KEYS = ["t_s", "mode", "leg", "n_m", "e_m", "alt_agl_m", "h_cmd_m", "tas_mps", "gs_mps", "v_cmd_mps",
                  "phi_deg", "theta_deg", "psi_deg", "P_batt_W", "soc", "v_bus_V", "i_batt_A", "rpm",
                  "wind_tot_n_mps", "wind_tot_e_mps", "wind_tot_d_mps", "E_batt_Wh", "xtrack_m", "act_thr",
                  "P_wind_W", "dist_ground_m"]


# ---------------------------------------------------------------- child processes
class _QueueWriter(io.TextIOBase):
    def __init__(self, q):
        self.q, self.buf = q, ""

    def write(self, s):
        self.buf += s
        while "\n" in self.buf:
            line, self.buf = self.buf.split("\n", 1)
            if line.strip():
                self.q.put(("log", line))
        return len(s)


def _child_run(cfg, run_dir, run_id, q):
    try:
        from ..plotting import run_dashboard
        from ..simulation import Simulation
        decim = max(1, int(round(float(cfg["sim"]["log_rate_hz"]) / 5.0)))
        n = [0]

        def on_row(r):
            n[0] += 1
            if n[0] % decim == 0:
                q.put(("row", {k: (r[k] if not isinstance(r[k], float) else round(r[k], 5)) for k in TELEMETRY_KEYS}))

        def on_event(ev):
            q.put(("event", ev))

        sim = Simulation(cfg, run_dir=run_dir, run_id=run_id, on_row=on_row, on_event=on_event,
                         keep_timeseries=False)
        q.put(("info", {"legs": len(sim.ap.legs), "run_dir": str(sim.run_dir)}))
        res = sim.run()
        try:
            run_dashboard(res.run_dir)
        except Exception:
            q.put(("log", "dashboard rendering failed:\n" + traceback.format_exc()))
        q.put(("done", {"summary": res.summary, "run_dir": str(res.run_dir)}))
    except Exception:
        q.put(("error", traceback.format_exc()))


def _child_call(fn_name, kwargs, q):
    """Run a library function with stdout streamed to the job log."""
    sys.stdout = _QueueWriter(q)
    try:
        if fn_name == "performance":
            from ..validation.performance import performance_map
            out = performance_map(**kwargs)
        elif fn_name == "validate":
            from ..validation.suite import run_suite
            ok = run_suite(**kwargs)
            out = {"all_passed": ok}
        else:
            raise ValueError(fn_name)
        q.put(("done", {"out": str(out)}))
    except Exception:
        q.put(("error", traceback.format_exc()))


# --------------------------------------------------------------------------- jobs
class Job:
    def __init__(self, kind, title, params=None):
        self.id = datetime.now().strftime("%H%M%S-") + uuid.uuid4().hex[:5]
        self.kind, self.title, self.params = kind, title, params or {}
        self.state = "queued"
        self.created = time.time()
        self.started = self.finished = None
        self.progress = 0.0
        self.message = ""
        self.log: list[str] = []
        self.telemetry: list[dict] = []
        self.events: list[dict] = []
        self.results: list[dict] = []     # sweep records / optimiser generations
        self.result: dict = {}
        self.error = ""
        self.proc = None
        self.config = None
        self._cancel = threading.Event()
        self.lock = threading.Lock()

    def cancelled(self) -> bool:
        return self._cancel.is_set()

    def add_log(self, line: str):
        with self.lock:
            self.log.append(f"{time.strftime('%H:%M:%S')}  {line}")
            self.message = line[:160]

    def brief(self):
        return {"id": self.id, "kind": self.kind, "title": self.title, "state": self.state,
                "progress": round(self.progress, 4), "message": self.message, "created": self.created,
                "started": self.started, "finished": self.finished, "result": self.result,
                "error": self.error[-4000:] if self.error else ""}

    def detail(self, since_row=0, since_event=0, since_log=0, since_result=0):
        d = self.brief()
        with self.lock:
            d["telemetry"] = self.telemetry[since_row:]
            d["events"] = self.events[since_event:]
            d["log"] = self.log[since_log:]
            d["results"] = self.results[since_result:]
            d["counts"] = {"rows": len(self.telemetry), "events": len(self.events), "log": len(self.log),
                           "results": len(self.results)}
        d["params"] = self.params
        return d


MODE_PROGRESS = {"PREFLIGHT": 0.0, "TAKEOFF_ROLL": 0.02, "ROTATE": 0.03, "CLIMB_OUT": 0.04, "MISSION": 0.06,
                 "APPROACH": 0.86, "GO_AROUND": 0.86, "FLARE": 0.96, "ROLLOUT": 0.97}


class JobManager:
    def __init__(self, workspace: Path):
        self.ws = Path(workspace)
        self.jobs: dict[str, Job] = {}

    def list(self):
        return [j.brief() for j in sorted(self.jobs.values(), key=lambda j: -j.created)]

    def get(self, jid) -> Job:
        return self.jobs[jid]

    def cancel(self, jid):
        j = self.jobs[jid]
        j._cancel.set()
        if j.proc is not None and j.proc.is_alive():
            j.proc.terminate()
        j.add_log("cancel requested")
        return j.brief()

    # ------------------------------------------------------------------ helpers
    def _start(self, job: Job, target):
        self.jobs[job.id] = job
        th = threading.Thread(target=self._wrap, args=(job, target), daemon=True)
        th.start()
        return job

    def _wrap(self, job, target):
        job.state, job.started = "running", time.time()
        try:
            target(job)
            if job.state == "running":
                job.state = "cancelled" if job.cancelled() else "done"
                if job.state == "done":
                    job.progress = 1.0
        except Exception:
            job.error = traceback.format_exc()
            job.state = "cancelled" if job.cancelled() else "failed"
            job.add_log("FAILED: " + job.error.strip().splitlines()[-1])
        job.finished = time.time()

    def _pump(self, job: Job, q, proc, on_msg):
        """Read messages from a child process until it finishes."""
        done = False
        while True:
            try:
                kind, payload = q.get(timeout=0.3)
                if kind in ("done", "error"):
                    done = True
                on_msg(kind, payload)
            except queue.Empty:
                if not proc.is_alive():
                    # drain what is left
                    while True:
                        try:
                            kind, payload = q.get_nowait()
                            if kind in ("done", "error"):
                                done = True
                            on_msg(kind, payload)
                        except queue.Empty:
                            break
                    break
        proc.join(timeout=2)
        if not done and not job.cancelled():
            raise RuntimeError(f"worker process ended unexpectedly (exit code {proc.exitcode})")

    # ---------------------------------------------------------------------- run
    def submit_run(self, cfg: dict, label: str = "") -> Job:
        run_id = datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:4]
        run_dir = self.ws / "runs" / run_id
        job = Job("run", label or f"Run {run_id}", {"run_id": run_id, "ref": f"runs/{run_id}"})
        cfg = json.loads(json.dumps(cfg))
        job.config = cfg
        cfg["logging"]["out_dir"] = str(self.ws / "runs")

        def target(job):
            (run_dir).mkdir(parents=True, exist_ok=True)
            (run_dir / "ui_meta.json").write_text(json.dumps({"label": label, "created": time.time()}), encoding="utf-8")
            q = CTX.Queue()
            proc = CTX.Process(target=_child_run, args=(cfg, str(run_dir), run_id, q), daemon=True)
            job.proc = proc
            proc.start()
            job.add_log(f"simulation started: {run_id}")
            n_legs = [1]

            def on_msg(kind, p):
                if kind == "row":
                    with job.lock:
                        job.telemetry.append(p)
                    base = MODE_PROGRESS.get(p["mode"], job.progress)
                    if p["mode"] == "MISSION" and n_legs[0]:
                        base = 0.06 + 0.80 * min(max(p["leg"], 0) / n_legs[0], 1.0)
                    job.progress = max(job.progress, base)
                    job.message = f"t = {p['t_s']:.0f} s  {p['mode']}  SOC {100 * p['soc']:.1f} %"
                elif kind == "event":
                    with job.lock:
                        job.events.append(p)
                    if p["kind"] in ("decision", "mode", "terminal"):
                        job.add_log(f"t={p['t_s']:.1f}s {p['kind']}: {p['name']} {p['data'] if p['data'] != '{}' else ''}")
                elif kind == "info":
                    n_legs[0] = max(p["legs"], 1)
                elif kind == "log":
                    job.add_log(p)
                elif kind == "done":
                    job.result = {"ref": f"runs/{run_id}", "status": p["summary"]["status"],
                                  "E_batt_Wh": p["summary"].get("E_batt_Wh"),
                                  "Wh_per_km": p["summary"].get("Wh_per_km")}
                    job.add_log(f"finished: {p['summary']['status']}, {p['summary'].get('E_batt_Wh', 0):.2f} Wh")
                elif kind == "error":
                    job.error = p
                    job.state = "failed"
                    job.add_log("FAILED: " + p.strip().splitlines()[-1])

            self._pump(job, q, proc, on_msg)
            if job.cancelled():
                job.state = "cancelled"
        return self._start(job, target)

    # -------------------------------------------------------------------- sweep
    def submit_sweep(self, spec: dict) -> Job:
        from ..batch import build_jobs, run_sweep
        name = spec["name"]
        n = len(build_jobs(spec, self.ws / "sweeps" / name))
        job = Job("sweep", f"Sweep {name}", {"name": name, "n_runs": n})

        def target(job):
            done = [0]

            def on_result(rec):
                done[0] += 1
                with job.lock:
                    job.results.append(rec)
                job.progress = done[0] / max(n, 1)

            run_sweep(spec, self.ws / "sweeps", spec.get("workers"), progress=job.add_log, on_result=on_result,
                      cancel=job.cancelled)
            job.result = {"name": name, "runs": done[0]}
        return self._start(job, target)

    # ----------------------------------------------------------------- optimise
    def submit_optimise(self, spec: dict) -> Job:
        from ..optimize import run_optimisation
        name = spec["name"]
        iters = int((spec.get("algorithm") or {}).get("iterations", 5))
        job = Job("optimise", f"Optimisation {name}", {"name": name, "iterations": iters})

        def target(job):
            def on_gen(g):
                with job.lock:
                    job.results.append(g)
                job.progress = len(job.results) / max(iters, 1) * 0.95

            run_optimisation(spec, self.ws / "optimisations", progress=job.add_log, on_generation=on_gen,
                             cancel=job.cancelled)
            job.result = {"name": name}
        return self._start(job, target)

    # --------------------------------------------------------- performance / V&V
    def _submit_call(self, kind, title, fn, kwargs, n_expected):
        job = Job(kind, title, dict(kwargs))

        def target(job):
            q = CTX.Queue()
            proc = CTX.Process(target=_child_call, args=(fn, kwargs, q), daemon=True)
            job.proc = proc
            proc.start()

            def on_msg(kind_, p):
                if kind_ == "log":
                    job.add_log(p)
                    if p.lstrip().startswith(("V=", "[V&V]", "run ")):
                        job.progress = min(job.progress + 1.0 / n_expected, 0.97)
                elif kind_ == "done":
                    job.result = p
                elif kind_ == "error":
                    job.error = p
                    job.state = "failed"
            self._pump(job, q, proc, on_msg)
        return self._start(job, target)

    def submit_performance(self, cfg: dict, quick: bool) -> Job:
        out = self.ws / "performance"
        return self._submit_call("performance", "Performance map", "performance",
                                 {"out": str(out), "quick": quick, "base_config": cfg}, 3 if quick else 8)

    def submit_validate(self, quick: bool) -> Job:
        return self._submit_call("validate", "Verification & validation suite", "validate",
                                 {"out": str(self.ws / "validation_report"), "quick": quick}, 60)
