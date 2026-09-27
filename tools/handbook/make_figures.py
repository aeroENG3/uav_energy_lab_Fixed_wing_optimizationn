"""Generates the inline-SVG figures of the handbook (docs/handbook/figs/*.html).

Each figure is a <figure> with one <svg role="img" aria-label=...> and a <figcaption>.
Colours come from the page's CSS (currentColor + classes), so the figures follow the
light/dark theme. Run:  python tools/handbook/make_figures.py
"""
from __future__ import annotations

import html
import math
from pathlib import Path

OUT = Path(__file__).resolve().parents[2] / "docs" / "handbook" / "figs"


def esc(s):
    return html.escape(str(s), quote=True)


class Fig:
    def __init__(self, name, w, h, label, caption):
        self.name, self.w, self.h, self.label, self.caption = name, w, h, label, caption
        self.parts = []

    # ------------------------------------------------------------ primitives
    def add(self, s):
        self.parts.append(s)

    def text(self, x, y, s, cls="", anchor="start", rot=None):
        tr = f' transform="rotate({rot} {x:.1f} {y:.1f})"' if rot is not None else ""
        c = f' class="{cls}"' if cls else ""
        a = f' text-anchor="{anchor}"' if anchor != "start" else ""
        self.add(f'<text x="{x:.1f}" y="{y:.1f}"{c}{a}{tr}>{esc(s)}</text>')

    def box(self, x, y, w, h, title=None, lines=(), mono=None, cls="bx", align="left", rx=4, dash=False):
        d = ' stroke-dasharray="4 3"' if dash else ""
        self.add(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" class="{cls}"{d}/>')
        monos = [mono] if isinstance(mono, str) else list(mono or [])
        n = (1 if title else 0) + len(lines) + len(monos)
        lh = 15
        y0 = y + h / 2 - (n - 1) * lh / 2 + 4
        tx = x + 10 if align == "left" else x + w / 2
        anc = "start" if align == "left" else "middle"
        k = 0
        if title:
            self.text(tx, y0, title, "t", anc); k += 1
        for ln in lines:
            self.text(tx, y0 + k * lh, ln, "s", anc); k += 1
        for mo in monos:
            self.text(tx, y0 + k * lh, mo, "m", anc); k += 1

    def arrow(self, pts, cls="ln", accent=False, head=True, dash=False, both=False):
        p = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
        mk = f"a{'a' if accent else ''}-{self.name}"
        me = f' marker-end="url(#{mk})"' if head else ""
        ms = f' marker-start="url(#{mk})"' if both else ""
        c = cls + (" acc" if accent else "")
        d = ' stroke-dasharray="4 3"' if dash else ""
        self.add(f'<polyline points="{p}" class="{c}" fill="none"{d}{me}{ms}/>')

    def line(self, x1, y1, x2, y2, cls="ln", dash=False):
        d = ' stroke-dasharray="3 3"' if dash else ""
        self.add(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" class="{cls}"{d}/>')

    def render(self):
        defs = (f'<defs><marker id="a-{self.name}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" '
                f'markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" class="ah"/></marker>'
                f'<marker id="aa-{self.name}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" '
                f'markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" class="aha"/></marker></defs>')
        svg = (f'<svg viewBox="0 0 {self.w} {self.h}" role="img" aria-label="{esc(self.label)}" '
               f'xmlns="http://www.w3.org/2000/svg">{defs}' + "".join(self.parts) + "</svg>")
        return (f'<figure class="fig" id="fig-{self.name}"><div class="fig-scroll">{svg}</div>'
                f'<figcaption>{self.caption}</figcaption></figure>')

    def save(self):
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / f"{self.name}.html").write_text(self.render(), encoding="utf-8")


# ============================================================== 1 pipeline
def fig_pipeline():
    f = Fig("pipeline", 860, 716,
            "Layered simulation pipeline: configuration feeds every layer; atmosphere and mission feed the "
            "autonomous layer, controller, control surfaces and JSBSim; the powertrain exchanges rotor speed and "
            "motor torque with JSBSim; the energy ledger and logger feed studies, reinforcement learning and the interface.",
            "The simulation pipeline. Each layer is one module and one configuration section. Rotor speed and "
            "motor torque couple JSBSim and the powertrain every physics step. The <b>policy slot</b> "
            "(highlighted) is where an adaptive energy-optimising controller plugs in.")
    X0, W, RX, RW = 90, 420, 570, 270
    f.box(X0, 12, 750, 36, None, (), None, cls="bx2")
    f.text(X0 + 12, 35, "CONFIGURATION", "t")
    f.text(X0 + 135, 35, "defaults.yaml ← scenario files ← overrides → validate → hash  ·  one resolved dictionary, read by every layer", "s")
    rows = [70, 160, 250, 340, 430, 530, 640]
    H = 62
    f.box(X0, rows[0], 200, H, "ATMOSPHERE", ["mean wind · Dryden · gusts"], "atmosphere.py · US-1976")
    f.box(X0 + 220, rows[0], 200, H, "MISSION", ["waypoints · runway · approach"], "mission.py")
    f.box(X0, rows[1], W, H, "AUTONOMOUS LAYER", ["mode machine · decisions D1–D9 · sensor errors · wind estimator"],
          "autonomy.py · sensors.py")
    f.box(RX, rows[1], RW, H, "POLICY SLOT (adaptive optimiser)", ["fixed · wind_aware · linear_wind · RL"], "policies.py",
          cls="bxa")
    f.box(X0, rows[2], W, H, "CONTROLLER LAYER", ["L1 guidance · TECS · attitude PIDs · runway steering"], "control.py")
    f.box(X0, rows[3], W, H, "CONTROL SURFACES", ["servo lag · rate limit · deadband · servo power"], "actuators.py")
    f.box(X0, rows[4], W, H, "FLIGHT DYNAMICS (JSBSim 6-DoF, 200 Hz)", ["aerodynamics · gear · rotor ODE · thrust"],
          "fdm.py · models.py")
    f.box(RX, rows[4], RW, H, "ELECTRIC POWERTRAIN", ["battery 1-RC → ESC → motor (Drela)"], "energy/")
    f.box(X0, rows[5], 750, H, "ENERGY LEDGER & LOGGING",
          ["air-relative energy balance · electrical meters → timeseries · events · legs · phases · summary · metadata"],
          "simulation.py · logger.py · metrics.py")
    cw = 240
    for i, (t, m) in enumerate([("PARAMETER STUDIES · OPTIMISER", "batch.py · optimize.py"),
                                ("REINFORCEMENT LEARNING", "gym_env.py"),
                                ("INTERFACE · V&V", "ui/ · validation/")]):
        f.box(X0 + i * (cw + 15), rows[6], cw, H, t, [], m, align="center")
    # vertical stack arrows
    f.arrow([(X0 + 320, rows[0] + H), (X0 + 320, rows[1])]); f.text(X0 + 328, rows[1] - 9, "legs, approach points", "l")
    f.arrow([(X0 + 200, rows[1] + H), (X0 + 200, rows[2])]); f.text(X0 + 208, rows[2] - 9, "mode, path A→B, h_cmd, V_cmd", "l")
    f.arrow([(X0 + 200, rows[2] + H), (X0 + 200, rows[3])]); f.text(X0 + 208, rows[3] - 9, "δa, δe, δr, steer, δt", "l")
    f.arrow([(X0 + 200, rows[3] + H), (X0 + 200, rows[4])]); f.text(X0 + 208, rows[4] - 9, "surface positions (−1…1)", "l")
    # policy exchange
    f.arrow([(X0 + W, rows[1] + 20), (RX, rows[1] + 20)], accent=True); f.text(RX - 30, rows[1] + 14, "obs", "l", "middle")
    f.arrow([(RX, rows[1] + 44), (X0 + W, rows[1] + 44)], accent=True); f.text(RX - 30, rows[1] + 58, "V, h", "l", "middle")
    # throttle to powertrain
    f.arrow([(X0 + W, rows[3] + 31), (RX + 135, rows[3] + 31), (RX + 135, rows[4])])
    f.text(RX + 20, rows[3] + 25, "throttle d", "l")
    # coupling
    f.arrow([(X0 + W, rows[4] + 20), (RX, rows[4] + 20)]); f.text(RX - 30, rows[4] + 14, "ω", "l", "middle")
    f.arrow([(RX, rows[4] + 44), (X0 + W, rows[4] + 44)]); f.text(RX - 30, rows[4] + 58, "Q_m", "l", "middle")
    # to ledger
    f.arrow([(X0 + 210, rows[4] + H), (X0 + 210, rows[5])]); f.text(X0 + 218, rows[5] - 13, "forces, state", "l")
    f.arrow([(RX + 135, rows[4] + H), (RX + 135, rows[5])]); f.text(RX + 143, rows[5] - 13, "electrical powers", "l")
    for i in range(3):
        cx = X0 + i * (cw + 15) + cw / 2
        f.arrow([(cx, rows[5] + H), (cx, rows[6])])
    f.text(X0 + cw / 2 + 8, rows[6] - 16, "log files", "l")
    # left routes: wind (outer) and state feedback (inner)
    f.arrow([(X0, rows[0] + 31), (34, rows[0] + 31), (34, rows[4] + 46), (X0, rows[4] + 46)])
    f.text(28, (rows[0] + rows[4]) / 2 + 40, "wind W(t,h), NED → JSBSim", "l", "middle", rot=-90)
    f.arrow([(X0, rows[4] + 16), (58, rows[4] + 16), (58, rows[1] + 31), (X0, rows[1] + 31)])
    f.text(52, (rows[1] + rows[4]) / 2 + 30, "true state → sensors", "l", "middle", rot=-90)
    return f


# ============================================================== 2 step + timing
def fig_step():
    f = Fig("step", 860, 318,
            "Order of one 5 ms physics step and the multirate timing: control every 4th step, logging every 20th.",
            "One physics step (top) and the multirate schedule over 100 ms (bottom). Dashed stages run only on "
            "their tick. Commands are held between control ticks. Cumulative energies are integrated every step, "
            "whatever the log rate.")
    names = [("1  Wind", "WindField.sample", "→ wind, gust inputs"),
             ("2  Control", "sensors, autonomy", "every 4th step"),
             ("3  Actuators", "servo dynamics", "→ fcs/*-cmd-norm"),
             ("4  Powertrain", "read ω, solve", "→ motor torque"),
             ("5  JSBSim run()", "6-DoF + rotor", "→ state x"),
             ("6  Ledger", "energy terms", "crash, end checks"),
             ("7  Log", "RunLogger.row", "every 20th step")]
    bw, gap, x0, y0, bh = 110, 12, 9, 22, 76
    for i, (t, a, b) in enumerate(names):
        x = x0 + i * (bw + gap)
        f.box(x, y0, bw, bh, t, [a, b], None, align="center", dash=i in (1, 6))
        if i < 6:
            f.arrow([(x + bw, y0 + bh / 2), (x + bw + gap, y0 + bh / 2)])
    xe = x0 + 6 * (bw + gap) + bw / 2
    f.arrow([(xe, y0 + bh), (xe, y0 + bh + 18), (x0 + bw / 2, y0 + bh + 18), (x0 + bw / 2, y0 + bh)])
    f.text((xe + x0 + bw / 2) / 2, y0 + bh + 32, "next step: t + 5 ms", "l", "middle")
    # timeline
    tx0, tx1 = 150, 830
    px = (tx1 - tx0) / 20
    rows = [("physics 200 Hz", 184, 1), ("control 50 Hz", 222, 4), ("log 10 Hz", 260, 20)]
    for lab, y, every in rows:
        f.text(20, y + 4, lab, "s")
        f.line(tx0, y, tx1, y, "ln thin")
        for k in range(0, 21):
            if k % every:
                continue
            x = tx0 + k * px
            if every == 1:
                f.line(x, y - 6, x, y + 6, "ln")
            elif every == 4:
                f.add(f'<circle cx="{x:.1f}" cy="{y}" r="4.5" class="dot"/>')
                if k < 20:
                    f.add(f'<rect x="{x + 5:.1f}" y="{y - 3}" width="{4 * px - 10:.1f}" height="6" class="hold"/>')
            else:
                f.add(f'<rect x="{x - 5:.1f}" y="{y - 5}" width="10" height="10" class="dot"/>')
    f.text(tx0 + 2 * px, 212, "commands held (zero-order hold)", "l", "middle")
    for k in range(0, 21, 4):
        x = tx0 + k * px
        f.line(x, 280, x, 286, "ln")
        f.text(x, 300, f"{k * 5} ms", "l", "middle")
    f.line(tx0, 280, tx1, 280, "ln thin")
    return f


# ============================================================== 3 config chain
def fig_config():
    f = Fig("config", 860, 160,
            "Configuration resolution: defaults, then scenario files, then overrides, then validation, giving the resolved configuration and its hash.",
            "How a configuration is resolved. The interface and the optimiser enter with an in-memory dictionary "
            "(<code>config_from_dict</code>) and go through the same validation. A typo in a key is an error, never ignored.")
    items = [("defaults.yaml", ["every key, unit, tag"]),
             ("scenario files", ["deep-merge, in order"]),
             ("overrides", ["--set · UI edits · factors"]),
             ("validate()", ["all problems at once"]),
             ("resolved config", ["+ hash → metadata.json"])]
    bw, gap, x0, y0, bh = 148, 25, 12, 20, 60
    for i, (t, ls) in enumerate(items):
        x = x0 + i * (bw + gap)
        f.box(x, y0, bw, bh, t, ls, None, align="center", cls="bxa" if i == 4 else "bx")
        if i < 4:
            f.arrow([(x + bw, y0 + bh / 2), (x + bw + gap, y0 + bh / 2)])
    xo = x0 + 2 * (bw + gap)
    f.box(x0 + (bw + gap) - 20, 112, 2 * bw + gap + 40 - 60, 34, None, [], None, cls="bx2", dash=True)
    f.text(x0 + (bw + gap) - 8, 133, "interface / optimiser: config_from_dict(base, overrides)", "s")
    f.arrow([(xo + bw / 2, 112), (xo + bw / 2, y0 + bh)])
    return f


# ============================================================== 4 coupling
def fig_coupling():
    f = Fig("coupling", 860, 300,
            "Powertrain co-simulation: the lab solves battery, ESC and motor and passes motor torque to JSBSim's "
            "torque-source engine; JSBSim integrates the rotor with the propeller tables and returns rotor speed.",
            "Co-simulation of the electric powertrain with JSBSim, once per 5 ms step. The highlighted arrows "
            "are the coupling: motor torque in (encoded as power ÷ 10 kW), rotor speed back out with a one-step lag. "
            "The RPM also selects the column of the 2-D propeller tables through the blade-angle input.")
    f.box(10, 34, 390, 250, None, (), None, cls="grp", dash=True)
    f.text(22, 54, "LAB (Python) · energy/powertrain.py", "k")
    f.box(470, 34, 380, 250, None, (), None, cls="grp", dash=True)
    f.text(482, 54, "JSBSim", "k")
    f.box(24, 90, 110, 72, "Battery", ["OCV(SOC)", "R₀, R₁C₁"], None, align="center")
    f.box(158, 90, 100, 72, "ESC", ["duty d", "losses"], None, align="center")
    f.box(282, 90, 106, 72, "Motor", ["E = ω / Kv", "Q = (I − I₀) / Kv"], None, align="center")
    f.arrow([(134, 116), (158, 116)]); f.arrow([(158, 136), (134, 136)])
    f.text(146, 180, "V_bus, I_b", "l", "middle")
    f.arrow([(258, 126), (282, 126)])
    f.text(270, 180, "V_m, I_m", "l", "middle")
    f.arrow([(208, 66), (208, 90)]); f.text(216, 76, "throttle d", "l")
    f.box(24, 196, 364, 40, None, ["closed-form bus solve: one quadratic per ESC regime"], None, cls="bx2", align="center")
    f.box(490, 90, 150, 72, "Electric engine", ["torque source", "Q = P / ω"], None, align="center")
    f.box(676, 90, 156, 72, "Rotor", ["I_r dω/dt = Q_m − Q_p"], None, align="center")
    f.box(676, 190, 156, 58, "Propeller tables", ["C_T, C_P (J, RPM)", "→ T, Q_p"], None, align="center")
    f.box(490, 190, 150, 58, "6-DoF airframe", ["thrust → motion", "airspeed → J"], None, align="center")
    f.arrow([(640, 126), (676, 126)]); f.text(658, 118, "Q_m", "l", "middle")
    f.arrow([(736, 190), (736, 162)]); f.text(730, 180, "Q_p", "l", "end")
    f.arrow([(776, 162), (776, 190)]); f.text(782, 180, "ω", "l")
    f.arrow([(676, 208), (640, 208)]); f.text(658, 202, "T", "l", "middle")
    f.arrow([(640, 230), (676, 230)]); f.text(658, 244, "V", "l", "middle")
    f.arrow([(388, 116), (490, 116)], accent=True)
    f.text(439, 108, "P = Q_m·ω", "la", "middle")
    f.text(439, 134, "÷ 10 kW", "la", "middle")
    f.arrow([(756, 90), (756, 18), (335, 18), (335, 90)], accent=True)
    f.text(545, 12, "rotor speed ω (end of previous step)", "la", "middle")
    f.arrow([(370, 236), (370, 262), (800, 262), (800, 248)])
    f.text(585, 278, "RPM / 1000 → blade-angle (selects the table column)", "l", "middle")
    return f


# ============================================================== 5 studies
def fig_studies():
    f = Fig("studies", 860, 262,
            "Parameter studies expand a specification into jobs run by a spawn process pool into datasets; the "
            "cross-entropy optimiser loops sample, evaluate with common random numbers, score and update, reusing the same runner.",
            "The study engine. A parameter study expands its specification into independent jobs. The optimiser "
            "wraps the same runner in a loop: every candidate is flown on every condition with the <i>same</i> seeds "
            "(common random numbers), and infeasible designs are pushed down the ranking by a 10⁶ penalty.")
    f.text(15, 20, "PARAMETER STUDY  ·  batch.py", "k")
    bw, gap = 190, 22
    xs = [15 + i * (bw + gap) for i in range(4)]
    ya, yb, bh = 30, 150, 60
    f.box(xs[0], ya, bw, bh, "Specification", ["YAML file or interface form"], None, align="center")
    f.box(xs[1], ya, bw, bh, "build_jobs", ["grid × LHS × replicates"], None, align="center")
    f.box(xs[2], ya, bw, bh, "spawn process pool", ["run_one(job) × workers"], None, align="center", cls="bxa")
    f.box(xs[3], ya, bw, bh, "Datasets", ["per run and per leg (CSV)"], "runs/<id>/ full logs", align="center")
    for i in range(3):
        f.arrow([(xs[i] + bw, ya + bh / 2), (xs[i + 1], ya + bh / 2)])
    f.text(15, 138, "OPTIMISATION (cross-entropy method)  ·  optimize.py", "k")
    f.box(xs[0], yb, bw, bh, "Update μ, σ", ["smooth towards the elites"], None, align="center")
    f.box(xs[1], yb, bw, bh, "Sample population", ["N(μ, σ²) within bounds"], None, align="center")
    f.box(xs[2], yb, bw, bh, "Evaluate", ["conditions × seeds (CRN)"], None, align="center")
    f.box(xs[3], yb, bw, bh, "Score", ["mean objective + 10⁶ × violations"], None, align="center")
    f.arrow([(xs[0] + bw, yb + bh / 2), (xs[1], yb + bh / 2)])
    f.arrow([(xs[1] + bw, yb + bh / 2), (xs[2], yb + bh / 2)])
    f.arrow([(xs[2] + bw, yb + bh / 2), (xs[3], yb + bh / 2)])
    f.arrow([(xs[3] + bw / 2, yb + bh), (xs[3] + bw / 2, yb + bh + 18), (xs[0] + bw / 2, yb + bh + 18),
             (xs[0] + bw / 2, yb + bh)])
    f.text((xs[0] + xs[3] + bw) / 2, yb + bh + 34, "next generation · finally: best design flown again with full logs (best_run/)",
           "l", "middle")
    cx = xs[2] + bw / 2
    f.arrow([(cx - 30, yb), (cx - 30, ya + bh)]); f.text(cx - 36, 122, "jobs", "l", "end")
    f.arrow([(cx + 30, ya + bh), (cx + 30, yb)]); f.text(cx + 36, 122, "summaries", "l")
    return f


# ============================================================== 6 ui
def fig_ui():
    f = Fig("ui", 860, 330,
            "Interface architecture: the browser single-page app talks JSON to the FastAPI server; the server's job "
            "manager spawns worker processes that stream telemetry through queues and write results to the workspace folder.",
            "Interface architecture. The browser only edits a configuration and displays results. Every "
            "computation runs in a spawned process. Every result is a file in the workspace, readable by scripts and notebooks.")
    f.box(10, 30, 210, 190, None, (), None)
    f.text(22, 52, "BROWSER", "t"); f.text(22, 67, "single-page app, no build step", "s")
    for i, s in enumerate(["pages: overview · scenario · live ·", "results · compare · studies · V&V",
                           "edited configuration (local storage)", "charts: uPlot + canvas", "polls jobs every 1.5 s"]):
        f.text(22, 94 + i * 18, s, "s")
    f.box(300, 30, 240, 190, None, (), None)
    f.text(312, 52, "SERVER", "t"); f.text(312, 67, "FastAPI + uvicorn, 127.0.0.1:8050", "s")
    for i, s in enumerate(["REST API /api/* (OpenAPI at /api/docs)", "schema parsed from defaults.yaml",
                           "validate · resolve (config_from_dict)", "JobManager: one thread per job",
                           "static app · /handbook · reports"]):
        f.text(312, 94 + i * 18, s, "s")
    f.text(642, 22, "SPAWNED PROCESSES", "k")
    f.box(640, 30, 210, 56, "run", ["Simulation + on_row / on_event"], None)
    f.box(640, 97, 210, 56, "performance · V&V", ["one child process each"], None)
    f.box(640, 164, 210, 56, "sweep · optimise", ["spawn process pool (workers)"], None)
    f.arrow([(220, 96), (300, 96)]); f.text(260, 88, "JSON", "l", "middle")
    f.arrow([(300, 150), (220, 150)]); f.text(260, 166, "job state,", "l", "middle"); f.text(260, 179, "new rows only", "l", "middle")
    f.arrow([(540, 52), (640, 52)]); f.text(590, 45, "spawn", "l", "middle")
    f.arrow([(640, 74), (540, 74)], accent=True); f.text(590, 90, "queue: rows,", "la", "middle"); f.text(590, 103, "events, log", "la", "middle")
    f.arrow([(540, 125), (640, 125)]); f.arrow([(540, 192), (640, 192)])
    f.box(300, 260, 550, 56, None, (), None, cls="bx2")
    f.text(312, 282, "WORKSPACE FOLDER", "t")
    f.text(312, 300, "runs/ · sweeps/ · optimisations/ · performance/ · validation_report/ · scenarios/", "m")
    f.arrow([(745, 220), (745, 260)]); f.text(753, 244, "write results", "l")
    f.arrow([(420, 260), (420, 220)]); f.text(428, 244, "read · save scenarios", "l")
    return f


# ============================================================== 7 energy flow
def fig_energy():
    f = Fig("energy", 860, 312,
            "Energy flow from battery chemistry to the air: each stage passes power to the next and loses part of it; "
            "the wind adds or removes energy at the end of the chain. Typical cruise values at 17 m/s are shown.",
            "Where the battery energy goes, with typical values in steady cruise at 17 m/s. The loss boxes "
            "name the cumulative log columns. The wind term (highlighted) is the only input that does not come from "
            "the battery. It can be positive or negative, and it is what wind-exploiting strategies act on.")
    nodes = [("Chemical", "≈ 203 W", "E_chem_Wh"), ("Terminal", "201 W", "E_batt_Wh"),
             ("ESC input", "194 W", None), ("Motor input", "190 W", None), ("Shaft", "159 W", "E_shaft_Wh"),
             ("Thrust work", "123 W", "E_thrust_Wh"), ("Air energy", "½mV_a² + mgh", "E_air_J")]
    losses = [(["battery heat", "R₀, R₁: ≈ 2 W"], ["E_batt_loss_Wh"]),
              (["avionics, servos", "7 W"], ["E_avionics_Wh"]),
              (["ESC loss", "4 W"], ["E_esc_loss_Wh"]),
              (["copper + iron", "31 W"], ["E_copper_Wh", "E_iron_Wh"]),
              (["propeller loss", "36 W"], ["shaft − thrust"]),
              (["drag work D·V_a", "123 W"], ["E_drag_Wh"])]
    bw, gap, x0, y0, bh = 108, 14, 10, 70, 62
    for i, (t, v, m) in enumerate(nodes):
        x = x0 + i * (bw + gap)
        f.box(x, y0, bw, bh, t, [v], m, align="center", cls="bxa" if i == 6 else "bx")
        if i < 6:
            f.arrow([(x + bw, y0 + bh / 2), (x + bw + gap, y0 + bh / 2)])
            ls, ms = losses[i]
            f.box(x, 190, bw, 76, None, ls, ms, align="center", cls="bx2")
            f.arrow([(x + bw / 2, y0 + bh), (x + bw / 2, 190)])
    xw = x0 + 6 * (bw + gap) + bw / 2
    f.arrow([(xw, 26), (xw, y0)], accent=True, both=True)
    f.text(xw - 10, 22, "wind work P_wind (±)", "la", "end")
    f.text(xw - 10, 40, "E_wind_Wh", "ma", "end")
    f.text(10, 296, "Steady level cruise: thrust work = drag work, and the air-relative energy stays constant.", "s")
    return f


# ============================================================== 8 wind
def fig_wind():
    f = Fig("wind", 860, 256,
            "Wind model: mean wind, Dryden turbulence and discrete gusts are computed from time, height, airspeed and "
            "heading; the mean goes to JSBSim's wind input and turbulence plus gusts to its gust input.",
            "Composition of the wind. All three parts are logged exactly. JSBSim adds its two wind inputs and "
            "applies the total to the aerodynamics.")
    f.box(10, 98, 110, 64, "inputs", ["t, h_AGL, TAS, ψ"], "seeded stream", align="center")
    f.box(160, 20, 300, 64, "Mean wind", ["schedule(t) × shear f(h) + veer + OU"], "U_ref, χ_ref, α or z₀", align="center")
    f.box(160, 100, 300, 64, "Dryden turbulence", ["u: 1st order · v, w: 2nd order · exact"], "axes along the mean wind; σ, L from h, W₂₀",
          align="center")
    f.box(160, 180, 300, 64, "Discrete gusts", ["1-cosine · ramp-and-hold"], "t₀, T, amplitude, direction", align="center")
    for y in (52, 132, 212):
        f.arrow([(120, 130), (140, 130), (140, y), (160, y)])
    f.add('<circle cx="515" cy="172" r="13" class="bx"/>')
    f.text(515, 177, "+", "t", "middle")
    f.arrow([(460, 132), (515, 132), (515, 159)])
    f.arrow([(460, 212), (515, 212), (515, 185)])
    f.box(575, 20, 160, 64, "JSBSim", ["atmosphere/wind-*"], "mean wind", align="center")
    f.box(575, 140, 160, 64, "JSBSim", ["atmosphere/gust-*"], "turbulence + gusts", align="center")
    f.arrow([(460, 52), (575, 52)])
    f.arrow([(528, 172), (575, 172)])
    f.box(765, 70, 85, 84, "total", ["wind →", "α, β, q̄"], None, align="center", cls="bxa")
    f.arrow([(735, 52), (807, 52), (807, 70)])
    f.arrow([(735, 172), (807, 172), (807, 154)])
    return f


# ============================================================== 9 triangle + tangent
def fig_triangle():
    f = Fig("triangle", 860, 280,
            "Left: wind triangle with ground velocity along the track, air velocity crabbed into the wind and the wind "
            "vector split into tail- and cross-wind. Right: battery power against airspeed with tangent lines from the "
            "head-wind value on the speed axis; the tangent points are the energy-optimal airspeeds.",
            "(a) Wind triangle: the aircraft crabs into the cross-wind, and the ground speed along the track is "
            "√(V_a² − W_c²) + W_a. (b) Tangent construction on the measured power curve. A line from the head-wind "
            "value H on the speed axis touches P(V) at the energy-optimal airspeed. Shown for a 6 m/s tail-wind, still air "
            "and a 6 m/s head-wind (highlighted).")
    f.text(20, 22, "(a) wind triangle", "k")
    O = (60, 200); s = 16
    Wa, Wc, V = -3.0, 4.0, 14.0
    Vg = math.sqrt(V * V - Wc * Wc) + Wa
    G = (O[0] + Vg * s, O[1])
    A = (G[0] - Wa * s, G[1] - Wc * s)
    f.line(30, O[1], 400, O[1], "ln thin", dash=True); f.text(398, O[1] + 16, "track", "l", "end")
    f.arrow([O, G]); f.text((O[0] + G[0]) / 2, O[1] + 18, "V_g (ground)", "l", "middle")
    f.arrow([O, A]); f.text((O[0] + A[0]) / 2 - 6, (O[1] + A[1]) / 2 - 10, "V_a (air)", "l", "end")
    f.arrow([A, G], accent=True); f.text(A[0] + 12, (A[1] + G[1]) / 2 + 4, "W (wind)", "la")
    f.line(A[0], A[1], A[0] + Wa * s, A[1], "ln thin", dash=True)
    f.line(A[0] + Wa * s, A[1], G[0], G[1], "ln thin", dash=True)
    f.text(A[0] + Wa * s / 2, A[1] - 8, "W_a", "l", "middle")
    f.text(A[0] + Wa * s - 8, (A[1] + G[1]) / 2 + 4, "W_c", "l", "end")
    ang = math.atan2(A[1] - O[1], A[0] - O[0])
    r = 46
    f.add(f'<path d="M {O[0] + r:.1f} {O[1]:.1f} A {r} {r} 0 0 0 {O[0] + r * math.cos(ang):.1f} {O[1] + r * math.sin(ang):.1f}" class="ln thin" fill="none"/>')
    f.text(O[0] + r + 6, O[1] - 6, "crab", "l")
    f.text(20, 250, "V_g = √(V_a² − W_c²) + W_a", "s")
    f.text(20, 268, "here: V_a = 14, W_a = −3 (head), W_c = 4 m/s → V_g = 10.4 m/s", "s")
    # (b) tangent construction
    a, b, c = 0.020294584076565494, 177.79307385567887, 88.53536678025206
    px0, px1, py0, py1 = 480, 840, 232, 40
    vmin, vmax, pmax = -8.0, 26.0, 360.0
    X = lambda v: px0 + (v - vmin) / (vmax - vmin) * (px1 - px0)
    Y = lambda p: py0 - p / pmax * (py0 - py1)
    f.text(470, 22, "(b) speed-to-fly: tangent construction", "k")
    f.line(px0, py0, px1, py0, "ln"); f.line(X(0), py0, X(0), py1, "ln")
    for v in (-5, 0, 5, 10, 15, 20, 25):
        f.line(X(v), py0, X(v), py0 + 5, "ln"); f.text(X(v), py0 + 18, str(v), "l", "middle")
    for p in (100, 200, 300):
        f.line(X(0) - 5, Y(p), X(0), Y(p), "ln"); f.text(X(0) - 8, Y(p) + 4, str(p), "l", "end")
    f.text((px0 + px1) / 2 + 60, py0 + 34, "airspeed V (m/s); head-wind H on the same axis", "l", "middle")
    f.text(X(0) + 6, py1 + 2, "battery power P (W)", "l")
    pts = []
    v = 11.0
    while v <= 25.0 + 1e-9:
        pts.append(f"{X(v):.1f},{Y(a * v ** 3 + b / v + c):.1f}")
        v += 0.5
    f.add(f'<polyline points="{" ".join(pts)}" class="ln thick" fill="none"/>')
    f.text(X(22.8) - 8, Y(a * 22.8 ** 3 + b / 22.8 + c) + 4, "P(V)", "t", "end")
    for H, vs, acc in ((-6, 12.09, False), (0, 14.10, False), (6, 17.49, True)):
        ps = a * vs ** 3 + b / vs + c
        ve = vs + 3.5
        pe = ps / (vs - H) * (ve - H)
        f.add(f'<line x1="{X(H):.1f}" y1="{Y(0):.1f}" x2="{X(ve):.1f}" y2="{Y(pe):.1f}" class="ln{" acc" if acc else ""}" stroke-dasharray="5 3"/>')
        f.add(f'<circle cx="{X(vs):.1f}" cy="{Y(ps):.1f}" r="4" class="{"dota" if acc else "dot"}"/>')
        f.add(f'<circle cx="{X(H):.1f}" cy="{Y(0):.1f}" r="3.5" class="{"dota" if acc else "dot"}"/>')
    f.text(X(12.09) - 4, Y(a * 12.09 ** 3 + b / 12.09 + c) - 12, "12.1 (tail 6)", "l", "end")
    f.text(X(14.1) + 8, Y(a * 14.1 ** 3 + b / 14.1 + c) + 18, "14.1 (still air)", "l")
    f.text(X(17.49) - 8, Y(a * 17.49 ** 3 + b / 17.49 + c) - 8, "17.5 (head 6)", "la", "end")
    return f


# ============================================================== 10 L1
def fig_l1():
    f = Fig("l1", 860, 250,
            "L1 guidance geometry: the aircraft is off the path by the cross-track error; a reference point on the path "
            "lies L1 ahead; the angle eta between the ground velocity and the line to the reference point sets the "
            "lateral acceleration that follows a circular arc to that point.",
            "L1 guidance. The reference point R lies on the path at distance L₁ from the aircraft. Commanding "
            "a = K V_g² sin η / L₁ puts the aircraft on the circular arc (dotted) tangent to its velocity that passes "
            "through R. The law uses ground velocity, so it corrects for wind drift without a separate wind estimate.")
    yp = 190
    f.line(40, yp, 560, yp, "ln thick")
    f.add(f'<circle cx="70" cy="{yp}" r="4" class="dot"/>'); f.text(70, yp + 20, "A", "t", "middle")
    f.add(f'<circle cx="540" cy="{yp}" r="4" class="dot"/>'); f.text(540, yp + 20, "B", "t", "middle")
    f.text(300, yp + 36, "desired path A → B", "s", "middle")
    P = (240.0, 110.0)
    L1 = 150.0
    R = (P[0] + math.sqrt(L1 ** 2 - (yp - P[1]) ** 2), yp)
    th = math.radians(-12)
    Vend = (P[0] + 110 * math.cos(th), P[1] + 110 * math.sin(th))
    f.add(f'<circle cx="{P[0]}" cy="{P[1]}" r="5" class="dot"/>')
    f.text(P[0] - 10, P[1] - 10, "aircraft", "l", "end")
    f.arrow([P, Vend]); f.text(Vend[0] + 4, Vend[1] - 6, "V_g", "l")
    f.line(P[0], P[1], R[0], R[1], "ln", dash=True)
    f.text((P[0] + R[0]) / 2 + 10, (P[1] + R[1]) / 2 - 6, "L₁", "l")
    f.add(f'<circle cx="{R[0]:.1f}" cy="{R[1]}" r="4.5" class="dota"/>'); f.text(R[0] + 8, R[1] - 8, "R (reference point)", "la")
    f.line(P[0], P[1], P[0], yp, "ln thin", dash=True); f.text(P[0] - 6, (P[1] + yp) / 2 + 4, "y (cross-track)", "l", "end")
    phi_pr = math.atan2(R[1] - P[1], R[0] - P[0])
    eta = phi_pr - th
    r = 44
    f.add(f'<path d="M {P[0] + r * math.cos(th):.1f} {P[1] + r * math.sin(th):.1f} A {r} {r} 0 0 1 '
          f'{P[0] + r * math.cos(phi_pr):.1f} {P[1] + r * math.sin(phi_pr):.1f}" class="ln thin" fill="none"/>')
    mid = (th + phi_pr) / 2
    f.text(P[0] + (r + 12) * math.cos(mid), P[1] + (r + 12) * math.sin(mid) + 4, "η", "t", "middle")
    Rc = L1 / (2 * math.sin(eta))
    cdir = th + math.pi / 2
    C = (P[0] + Rc * math.cos(cdir), P[1] + Rc * math.sin(cdir))
    f.add(f'<path d="M {P[0]:.1f} {P[1]:.1f} A {Rc:.1f} {Rc:.1f} 0 0 1 {R[0]:.1f} {R[1]:.1f}" class="ln acc" fill="none" stroke-dasharray="2 3"/>')
    aend = (P[0] + 46 * math.cos(cdir), P[1] + 46 * math.sin(cdir))
    f.arrow([P, aend], accent=True); f.text(aend[0] + 6, aend[1] + 2, "a_cmd", "la")
    x = 610
    for i, s in enumerate(["a_cmd = K_L1 · V_g² / L₁ · sin η", "η = η₁ + η₂,  η₁ = asin(y / L₁)",
                           "L₁ = ζ · T · V_g / π  (≥ 15 m)", "K_L1 = 4 ζ²", "φ_cmd = atan(a_cmd / g)",
                           "T = 18 s, ζ = 0.75 → L₁ ≈ 73 m at 17 m/s"]):
        f.text(x, 60 + i * 24, s, "s")
    return f


# ============================================================== 11 control
def fig_control():
    f = Fig("control", 860, 300,
            "Controller layer: L1 turns the path into a roll command for the roll loop; TECS turns height and speed "
            "set-points into a pitch command and a throttle command; a yaw loop coordinates turns; all outputs go to the actuators.",
            "Controller layer. The highlighted inputs are the set-points an adaptive policy changes: airspeed and "
            "height. Attitude-loop gains are scaled by s(V) = clamp((V_ref/V)², 0.4, 2).")
    f.box(10, 30, 140, 250, None, (), None, cls="bx2")
    f.text(22, 54, "AUTONOMY", "t")
    for i, s in enumerate(["mode", "path A → B", "h_cmd, V_cmd", "(policy)"]):
        f.text(22, 78 + i * 17, s, "s")
    rows = {"l1": 36, "tecs": 116, "thr": 186, "yaw": 238}
    f.box(200, rows["l1"], 140, 50, "L1 guidance", [], "pos, V_g", align="center")
    f.box(200, rows["tecs"], 140, 110, "TECS", ["energy rate → δt", "energy balance → θ"], "h, dh/dt, TAS, a_x", align="center",
          cls="bxa")
    f.box(410, rows["l1"], 150, 50, "Roll PID × s(V)", [], "φ, p", align="center")
    f.box(410, rows["tecs"], 150, 50, "Pitch PID × s(V)", [], "θ, q, turn comp.", align="center")
    f.box(410, rows["thr"], 150, 40, "Throttle shaping", ["τ 0.15 s · slew 1 /s"], None, align="center")
    f.box(410, rows["yaw"], 150, 50, "Yaw loop × s(V)", [], "β, r, φ, −k_ff δa", align="center")
    f.box(730, 30, 120, 258, None, (), None, cls="bx2")
    f.text(790, 158, "ACTUATORS", "t", "middle")
    f.arrow([(150, 61), (200, 61)]); f.text(175, 55, "A→B", "l", "middle")
    f.arrow([(150, 150), (200, 150)], accent=True); f.text(175, 144, "h, V", "la", "middle")
    f.arrow([(340, 61), (410, 61)]); f.text(375, 55, "φ_cmd", "l", "middle")
    f.arrow([(340, 141), (410, 141)]); f.text(375, 135, "θ_cmd", "l", "middle")
    f.arrow([(340, 206), (410, 206)]); f.text(375, 200, "δt", "l", "middle")
    for y, lab in ((61, "δa"), (141, "δe"), (206, "δt"), (263, "δr")):
        f.arrow([(560, y), (730, y)]); f.text(645, y - 6, lab, "l", "middle")
    return f


# ============================================================== 12 modes
def fig_modes():
    f = Fig("modes", 860, 340,
            "Flight-mode state machine from pre-flight through take-off, climb-out, mission, approach, flare and roll-out "
            "to landed, with go-around and no-go branches and the decisions that trigger them.",
            "Flight modes and the transitions between them. Energy and safety decisions (D4, D5, D6, D8) end the "
            "mission early by switching to APPROACH. Go-around (D7) loops back to the approach. Terminal states are LANDED, "
            "NO_GO, CRASHED and TIMEOUT.")
    bw, bh = 110, 44
    xs = [20, 185, 350, 515, 690]
    y1, y2, y3 = 44, 180, 276
    names1 = [("PREFLIGHT", "settle 2 s"), ("TAKEOFF_ROLL", "steer, tail up"), ("ROTATE", "to 9° pitch"),
              ("CLIMB_OUT", "full power, 14 m/s"), ("MISSION", "legs · policy")]
    for x, (n, s) in zip(xs, names1):
        f.box(x, y1, bw, bh, n, [s], None, align="center")
    labs = ["armed", "V ≥ 13 m/s", "h > 3 m", "h ≥ 25 m"]
    for i in range(4):
        f.arrow([(xs[i] + bw, y1 + bh / 2), (xs[i + 1], y1 + bh / 2)])
        f.text((xs[i] + bw + xs[i + 1]) / 2, y1 - 8, labs[i], "l", "middle")
    f.box(xs[0], y2, bw, bh, "NO_GO", ["terminal"], None, align="center", cls="bxbad")
    f.box(xs[1], y2, bw, bh, "LANDED", ["GS < 0.5 m/s"], None, align="center", cls="bxok")
    f.box(xs[2], y2, bw, bh, "ROLLOUT", ["wheel landing"], None, align="center")
    f.box(xs[3], y2, bw, bh, "FLARE", ["exponential, h < 3 m"], None, align="center")
    f.box(xs[4], y2, bw + 40, bh, "APPROACH", ["to_align → align → final"], None, align="center")
    f.box(xs[4], y3, bw + 40, bh, "GO_AROUND", ["climb to pattern + 15 m"], None, align="center")
    # mission -> approach
    f.arrow([(xs[4] + 55, y1 + bh), (xs[4] + 55, y2)], accent=True)
    f.text(xs[4] + 63, 118, "complete ·", "la"); f.text(xs[4] + 63, 132, "D4 D5 D6 D8", "la")
    f.arrow([(xs[4], y2 + bh / 2), (xs[3] + bw, y2 + bh / 2)]); f.text((xs[3] + bw + xs[4]) / 2, y2 - 8, "flare height", "l", "middle")
    f.arrow([(xs[3], y2 + 14), (xs[2] + bw, y2 + 14)]); f.text((xs[2] + bw + xs[3]) / 2, y2 - 8, "touchdown", "l", "middle")
    f.arrow([(xs[2] + bw, y2 + 32), (xs[3], y2 + 32)]); f.text((xs[2] + bw + xs[3]) / 2, y2 + bh + 16, "re-flare", "l", "middle")
    f.arrow([(xs[2], y2 + bh / 2), (xs[1] + bw, y2 + bh / 2)]); f.text((xs[1] + bw + xs[2]) / 2, y2 - 8, "stopped", "l", "middle")
    # go-around
    f.arrow([(xs[4] + 50, y2 + bh), (xs[4] + 50, y3)]); f.text(xs[4] + 44, y3 - 20, "D7", "l", "end")
    f.arrow([(xs[4] + 100, y3), (xs[4] + 100, y2 + bh)]); f.text(xs[4] + 106, y3 - 20, "climbed", "l")
    f.arrow([(xs[2] + bw / 2, y2 + bh), (xs[2] + bw / 2, y3 + 30), (xs[4], y3 + 30)])
    f.text((xs[2] + bw / 2 + xs[4]) / 2, y3 + 24, "bounce > 2 m (D7)", "l", "middle")
    # no-go
    f.arrow([(xs[0] + 40, y1 + bh), (xs[0] + 40, y2)]); f.text(xs[0] + 46, 128, "D2 no-go", "l")
    f.arrow([(xs[1] + 55, y1 + bh), (xs[1] + 55, 146), (xs[0] + 85, 146), (xs[0] + 85, y2)])
    f.text(xs[1] + 61, 128, "abort (D2)", "l")
    f.text(20, 300, "Any mode → CRASHED (structure contact)", "s")
    f.text(20, 318, "Any mode → TIMEOUT (t_max)", "s")
    return f


# ============================================================== 13 approach
def fig_approach():
    f = Fig("approach", 860, 262,
            "Side view of the straight-in approach: level at pattern altitude from the align point through the entry "
            "point to the final approach fix, then down the glide path to the touchdown point on the runway.",
            "Approach geometry (side view; vertical scale exaggerated). The glide path starts at the final approach fix, "
            "h_pattern/tan γ before the touchdown point. The flare starts at 3 m, too small to see at this scale.")
    yg = 200
    sx = 0.673
    xa = 30
    xe = xa + 250 * sx; xf = xe + 350 * sx; xt = xf + 428 * sx
    xth = xt - 40 * sx; xre = xth + 200 * sx
    hp = 110
    f.line(10, yg, 850, yg, "ln")
    f.add(f'<rect x="{xth:.1f}" y="{yg - 3}" width="{xre - xth:.1f}" height="6" class="bx2"/>')
    f.text((xth + xre) / 2, yg - 10, "runway", "s", "middle")
    f.arrow([(10, yg - hp), (xa, yg - hp)], dash=True)
    f.add(f'<polyline points="{xa:.1f},{yg - hp} {xf:.1f},{yg - hp} {xt:.1f},{yg}" class="ln thick" fill="none"/>')
    f.arrow([(xt, yg), (xt + 40, yg)], cls="ln")
    for x, lab in ((xa, "align"), (xe, "entry"), (xf, "FAF"), (xt, "TD")):
        f.line(x, yg - hp - 8, x, yg + 4, "ln thin", dash=True)
        f.text(x, yg - hp - 14, lab, "t", "middle")
    f.text(xa + 6, yg - hp + 18, "pattern altitude 45 m", "s")
    f.text((xa + xf) / 2, yg - hp - 32, "L1 on the extended centre line", "l", "middle")
    f.text(592, 118, "glide path γ = 6°", "la")
    f.text(592, 134, "D9: + gust additive on final", "l")
    f.add(f'<circle cx="{xt - 18:.1f}" cy="{yg - 8}" r="3" class="dota"/>')
    f.line(644, yg - 10, xt - 21, yg - 8, "ln thin")
    f.text(640, yg - 7, "flare starts at 3 m", "la", "end")
    for x1, x2, lab in ((xa, xe, "250 m"), (xe, xf, "final_length 350 m"), (xf, xt, "h_pattern / tan γ = 428 m"),
                        (xth, xt, "40 m")):
        yy = 222 if lab != "40 m" else 244
        f.line(x1, yy, x2, yy, "ln thin"); f.line(x1, yy - 4, x1, yy + 4, "ln thin"); f.line(x2, yy - 4, x2, yy + 4, "ln thin")
        f.text((x1 + x2) / 2, yy + 14 if lab != "40 m" else yy - 6, lab, "l", "middle")
    f.text(xre + 4, yg + 18, "", "l")
    f.text(640, 30, "D7 go-around on final if:", "s")
    f.text(640, 46, "> 12 m off the centre line below 15 m,", "s")
    f.text(640, 62, "> 6 m low below 8 m, or long", "s")
    return f


FIGS = [fig_pipeline, fig_step, fig_config, fig_coupling, fig_studies, fig_ui, fig_energy, fig_wind,
        fig_triangle, fig_l1, fig_control, fig_modes, fig_approach]

if __name__ == "__main__":
    for fn in FIGS:
        fig = fn()
        fig.save()
        print("wrote", OUT / f"{fig.name}.html")
