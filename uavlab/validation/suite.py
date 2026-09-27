"""Verification & Validation suite.

Every check states its criterion up front and records the measured value, so
the report shows evidence rather than assertions. Categories:

  VERIFICATION (is each model implemented correctly?)
    V1  atmosphere vs U.S. Standard Atmosphere 1976 tables
    V2  wind injection / wind triangle inside JSBSim
    V3  Dryden turbulence: variance and PSD vs MIL-F-8785C analytic spectra
    V4  discrete 1-cosine gust shape
    V5  battery: coulomb counting, energy conservation, step response
    V6  motor: no-load speed, peak-efficiency current, efficiency bound
    V7  powertrain network solver: KVL residual and power balance
    V8  propeller co-simulation: static equilibrium vs independent root-find
    V9  steady flight: full pipeline vs independent trim model (all blocks)
    V10 mechanical energy closure in flight (calm, shear, turbulence, gusts)
    V11 time-step convergence
    V12 reproducibility (seeding)
    V15 control-surface sign conventions
    V16 configuration validation rejects bad input
  VALIDATION / FITNESS FOR PURPOSE (does it behave as physics & practice say?)
    V13 closed-loop full flights across 8 wind scenarios (take-off to landing)
    V17 landing reliability over turbulence seeds
    U1  parameter sensitivity of cruise power (what to calibrate first)
    V14 wind-energy physics: per-leg energy in wind vs analytic prediction
    D1  demonstration: wind-aware speed policy vs fixed airspeed
"""
from __future__ import annotations

import base64
import copy
import io
import json
import math
import time
import traceback
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

from .. import __version__
from ..config import ConfigError, load_config

OUT = None


def _fig():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    return plt


def _check(cid, title, criterion, passed, value, details="", figure=None, kind="verification"):
    return {"id": cid, "title": title, "criterion": criterion, "passed": bool(passed), "value": value,
            "details": details, "figure": figure, "kind": kind}


# =============================================================================== V1
US1976 = [  # h (m), T (K), p (Pa), rho (kg/m^3) - U.S. Standard Atmosphere 1976, geopotential altitude
    (0.0, 288.150, 101325.0, 1.225000),
    (1000.0, 281.650, 89874.6, 1.111640),
    (2000.0, 275.150, 79495.2, 1.006490),
    (5000.0, 255.650, 54019.9, 0.736116),
    (11000.0, 216.650, 22632.1, 0.363918),
]


def v1_atmosphere(cfg):
    import jsbsim
    from ..units import FT, PSF, RANKINE, SLUG_FT3
    from ..fdm import FDM
    from ..models import build_model_dir
    import tempfile
    td = tempfile.mkdtemp()
    build_model_dir(cfg, td)
    worst = 0.0
    rows = []
    R_E = 6356766.0   # US1976 effective earth radius for geopotential altitude
    for h_gp, T, p, rho in US1976:
        f = FDM(td, 0.005)
        h_geom = R_E * h_gp / (R_E - h_gp)
        fd = f.fdm
        fd["ic/h-sl-ft"] = h_geom / FT
        fd["ic/vt-fps"] = 50.0
        fd["ic/lat-geod-deg"] = 0.0
        fd["ic/long-gc-deg"] = 0.0
        fd.run_ic()
        Tj = fd["atmosphere/T-R"] * RANKINE
        pj = fd["atmosphere/P-psf"] * PSF
        rj = fd["atmosphere/rho-slugs_ft3"] * SLUG_FT3
        e = max(abs(Tj / T - 1), abs(pj / p - 1), abs(rj / rho - 1))
        worst = max(worst, e)
        rows.append(f"h={h_gp:7.0f} m: T {Tj:8.3f}/{T:8.3f} K, p {pj:9.1f}/{p:9.1f} Pa, rho {rj:.5f}/{rho:.5f}")
    return _check("V1", "Atmosphere vs U.S. Standard Atmosphere 1976",
                  "max relative error of T, p, rho at 0-11 km < 0.2 %", worst < 2e-3,
                  f"{100 * worst:.4f} %", "<br>".join(rows))


# =============================================================================== V2
def v2_wind_injection(cfg):
    from ..fdm import FDM
    from ..models import build_model_dir
    import tempfile
    td = tempfile.mkdtemp()
    build_model_dir(cfg, td)
    f = FDM(td, 0.005)
    f.init_in_air(0, 0, 0, 100, 0, 17)
    mean, gust = np.array([3.0, -4.0, 0.5]), np.array([-1.0, 2.0, -0.3])
    f.set_wind(mean, gust)
    err = 0.0
    for _ in range(400):
        f.run()
        x = f.state()
        W = np.array([x["wind_tot_n"], x["wind_tot_e"], x["wind_tot_d"]])
        err = max(err, float(np.max(np.abs(W - (mean + gust)))))
        # |V_ground - W| must equal the true airspeed
        va = math.sqrt((x["vn"] - W[0]) ** 2 + (x["ve"] - W[1]) ** 2 + (x["vd"] - W[2]) ** 2)
        err = max(err, abs(va - x["tas"]))
    return _check("V2", "Wind injection and wind triangle in JSBSim",
                  "JSBSim total wind = mean + gust inputs and |V_ground - W| = TAS, error < 1e-6 m/s",
                  err < 1e-6, f"{err:.2e} m/s")


# =============================================================================== V3
def v3_dryden(cfg, quick=False, out=None):
    from scipy.signal import welch
    from ..atmosphere import _DrydenFirstOrder, _DrydenSecondOrder, dryden_scales
    plt = _fig()
    V, h, w20, dt = 17.0, 100.0, 10.0, 0.02
    (Lu, Lv, Lw), (su, sv, sw) = dryden_scales(h, w20)
    n_seeds = 6 if quick else 24
    T = 3000.0
    N = int(T / dt)
    var = np.zeros(3)
    psd_acc = None
    for sd in range(n_seeds):
        rng = np.random.default_rng(1000 + sd)
        gu, gv, gw = _DrydenFirstOrder(), _DrydenSecondOrder(), _DrydenSecondOrder()
        X = np.empty((N, 3))
        for i in range(N):
            X[i] = (gu.step(rng, su, Lu, V, dt), gv.step(rng, sv, Lv, V, dt), gw.step(rng, sw, Lw, V, dt))
        var += X.var(0)
        f, P = welch(X, fs=1 / dt, nperseg=8192, axis=0)
        psd_acc = P if psd_acc is None else psd_acc + P
    var /= n_seeds
    psd = psd_acc / n_seeds
    w = 2 * np.pi * f
    # analytic one-sided PSD in Hz convention: Phi_Hz(f) = 2*pi*Phi_omega(omega)
    Phi_u = su ** 2 * 2 * Lu / (math.pi * V) / (1 + (Lu * w / V) ** 2) * 2 * math.pi
    def Phi_vw(s, L):
        return s ** 2 * L / (math.pi * V) * (1 + 3 * (L * w / V) ** 2) / (1 + (L * w / V) ** 2) ** 2 * 2 * math.pi
    Phis = [Phi_u, Phi_vw(sv, Lv), Phi_vw(sw, Lw)]
    band = (w > 0.05) & (w < 5.0)
    db = [float(np.mean(10 * np.log10(psd[band, i] / Phis[i][band]))) for i in range(3)]
    sig_err = [float(math.sqrt(var[i]) / s - 1) for i, s in enumerate((su, sv, sw))]
    ok = all(abs(e) < 0.05 for e in sig_err) and all(abs(d) < 0.5 for d in db)
    fig, axs = plt.subplots(1, 3, figsize=(15, 4), facecolor="#fcfcfb")
    from ..plotting import C, _style
    for i, (ax, name) in enumerate(zip(axs, ["u (along wind)", "v (cross wind)", "w (vertical)"])):
        ax.loglog(w[1:], psd[1:, i] / (2 * math.pi), color=C[0], lw=1.2, label="generated (Welch)")
        ax.loglog(w[1:], Phis[i][1:] / (2 * math.pi), color=C[1], lw=1.5, ls="--", label="MIL-F-8785C analytic")
        _style(ax, f"Dryden {name}", "PSD (m^2/s^2 per rad/s)", "frequency (rad/s)")
        ax.legend(fontsize=8, frameon=False)
    fig.tight_layout()
    fn = "v3_dryden_psd.png"
    fig.savefig(out / fn, dpi=100)
    plt.close(fig)
    det = (f"V={V} m/s, h={h} m, W20={w20} m/s, {n_seeds} seeds x {T:.0f} s. sigma target u/v/w "
           f"{su:.3f}/{sv:.3f}/{sw:.3f} m/s, errors {', '.join(f'{100 * e:+.2f}%' for e in sig_err)}; "
           f"mean PSD ratio in 0.05-5 rad/s: {', '.join(f'{d:+.2f} dB' for d in db)}")
    return _check("V3", "Dryden turbulence statistics (lab generator)",
                  "sigma within 5 % and mean PSD ratio within +-0.5 dB (0.05-5 rad/s) for u, v, w",
                  ok, f"max sigma err {100 * max(map(abs, sig_err)):.2f} %, max PSD {max(map(abs, db)):.2f} dB",
                  det, fn)


# =============================================================================== V4
def v4_gust(cfg):
    from ..atmosphere import WindField
    w = copy.deepcopy(cfg["wind"])
    w["mean"]["speed_mps"] = 0.0
    w["turbulence"]["model"] = "none"
    w["gusts"] = [{"t_s": 10.0, "duration_s": 4.0, "amplitude_mps": 5.0, "from_deg": 90.0, "shape": "one_minus_cos"}]
    wf = WindField(w, np.random.default_rng(0))
    err = 0.0
    for t in np.linspace(0, 20, 2001):
        g = wf.gust_wind(t)
        tau = t - 10.0
        ref = 2.5 * (1 - math.cos(2 * math.pi * tau / 4.0)) if 0 <= tau <= 4 else 0.0
        err = max(err, abs(-g[1] - ref), abs(g[0]) , abs(g[2]))
    return _check("V4", "Discrete 1-cosine gust", "max deviation from V = A/2 (1 - cos(2 pi t / T)) < 1e-9 m/s",
                  err < 1e-9, f"{err:.1e} m/s")


# =============================================================================== V5
def v5_battery(cfg):
    from ..energy.battery import Battery
    bc = dict(cfg["powertrain"]["battery"], soc_init=1.0)
    b = Battery(bc)
    I, dt = 10.0, 0.01
    for _ in range(int(1800 / dt)):
        b.step(I, dt)
    dsoc_exp = I * 0.5 / b.capacity_ah
    e1 = abs((1.0 - b.soc) - dsoc_exp)
    bal = b.e_chem - (b.e_term + b.e_r0 + b.e_r1 + b.stored_c1_energy())
    e2 = abs(bal) / b.e_chem
    # step response
    b2 = Battery(dict(bc, soc_init=0.6))
    v0 = b2.terminal_voltage(0.0)
    b2.step(20.0, 1e-6)
    dv_inst = v0 - b2.terminal_voltage(20.0)
    for _ in range(int(5 * b2.tau / 0.01)):
        b2.step(20.0, 0.01)
    ocv_now = b2.ocv()
    dv_ss = ocv_now - b2.terminal_voltage(20.0)
    e3 = abs(dv_inst / (20 * b2.r0) - 1)
    e4 = abs(dv_ss / (20 * (b2.r0 + b2.r1 * (1 - math.exp(-5)))) - 1)
    ok = e1 < 1e-9 and e2 < 1e-9 and e3 < 1e-3 and e4 < 1e-3
    return _check("V5", "Battery equivalent-circuit model",
                  "coulomb count exact (<1e-9); chem = terminal + R0 + R1 heat + C1 storage (<1e-9 rel.); "
                  "instantaneous drop = I R0 and 5-tau drop = I (R0 + R1(1-e^-5)) within 0.1 %",
                  ok, f"SOC err {e1:.1e}, energy balance {e2:.1e}, step {100 * e3:.3f}%/{100 * e4:.3f}%",
                  f"pack R0={b.r0 * 1000:.1f} mOhm, R1={b.r1 * 1000:.1f} mOhm, tau={b.tau:.1f} s, "
                  f"capacity {b.capacity_ah:.1f} Ah, energy {b.energy_capacity_wh():.1f} Wh")


# =============================================================================== V6
def v6_motor(cfg):
    from ..energy.motor import Motor
    m = Motor(cfg["powertrain"]["motor"])
    V = 22.0
    # no-load: (I - I0)/Kv = 0 -> I = I0 -> omega = Kv (V - I0 R)
    om = m.no_load_speed_rad_s(V)
    I = (V - m.back_emf(om)) / m.r
    e1 = abs(m.torque(I, om))
    # efficiency scan at fixed terminal voltage
    oms = np.linspace(0.05, 0.999, 4000) * m.kv * V
    Is = (V - oms / m.kv) / m.r
    eta = np.array([m.torque(i, o) * o / (V * i) for i, o in zip(Is, oms)])
    i_best = Is[int(np.argmax(eta))]
    i_th = m.max_efficiency_current(V)
    e2 = abs(i_best / i_th - 1)
    ok = e1 < 1e-9 and e2 < 0.01 and eta.max() < 1.0
    return _check("V6", "Motor model (Drela first-order)",
                  "zero torque at analytic no-load speed; peak-efficiency current = sqrt(I0 V / R) within 1 %; "
                  "efficiency < 1", ok,
                  f"no-load torque {e1:.1e} Nm, I_best {i_best:.2f} A vs {i_th:.2f} A, eta_max {eta.max():.3f}")


# =============================================================================== V7
def v7_powertrain(cfg):
    from ..energy.powertrain import Powertrain
    rng = np.random.default_rng(3)
    worst_kvl, worst_bal = 0.0, 0.0
    regimes = set()
    for k in range(3000):
        pc = copy.deepcopy(cfg["powertrain"])
        pc["battery"]["soc_init"] = float(rng.uniform(0.1, 1.0))
        pt = Powertrain(pc)
        pt.p_avionics_extra = float(rng.uniform(0, 5))
        d = float(rng.uniform(0, 1))
        om = float(rng.uniform(0, 900))
        pt.step(d, om, 0.005)
        s = pt.s
        regimes.add(s.regime)
        worst_kvl = max(worst_kvl, abs(pt.solve_residual))
        bal = [s.p_batt_term - (s.p_esc_in + s.p_avionics), s.p_esc_in - (s.p_motor_in + s.p_esc_loss),
               s.p_motor_in - (s.p_shaft + s.p_copper + s.p_iron) if s.i_motor > 0 else 0.0]
        worst_bal = max(worst_bal, max(abs(x) for x in bal) / max(s.p_batt_term, 1.0))
    ok = worst_kvl < 1e-9 and worst_bal < 1e-9 and {"normal", "limited", "freewheel"} <= regimes
    return _check("V7", "Powertrain network solver",
                  "3000 random operating points (all 3 ESC regimes): KVL residual < 1e-9 V, power balance "
                  "battery = ESC + avionics, ESC = motor + loss, motor = shaft + copper + iron (<1e-9 rel.)",
                  ok, f"KVL {worst_kvl:.1e} V, balance {worst_bal:.1e}, regimes {sorted(regimes)}")


# =============================================================================== V8
def v8_static_prop(cfg):
    from scipy.optimize import brentq
    from ..energy.powertrain import Powertrain
    from ..fdm import FDM
    from ..models import build_model_dir
    from ..units import RPM
    from .performance import IndependentModel
    import tempfile
    td = tempfile.mkdtemp()
    build_model_dir(cfg, td)
    rows, worst = [], 0.0
    for duty in (0.3, 0.6, 1.0):
        f = FDM(td, 0.005)
        f.init_on_ground(0, 0, 0, 0)
        f.fdm["forces/hold-down"] = 1
        pc = copy.deepcopy(cfg["powertrain"])
        pt = Powertrain(pc)
        for _ in range(int(8 / 0.005)):
            rpm = f.prop_rpm()
            om = rpm * RPM
            f.set_prop_krpm(min(max(rpm, 1000.0), 12000.0) / 1000.0)
            q = pt.step(duty, om, 0.005)
            f.set_motor_torque(q, om)
            f.run()
        x = f.state()
        rpm_sim, T_sim, vbus = x["rpm"], x["thrust"], pt.s.v_bus
        # independent: motor torque at fixed bus voltage = propeller torque CP rho n^2 D^5 / (2 pi)
        im = IndependentModel(cfg, 36.4, 3.56, 6.15, 9.81)
        m = pt.motor
        R = m.r + pt.r_esc
        rho = x["rho"]
        def resid(n):
            om = 2 * math.pi * n
            i = (duty * vbus - om / m.kv) / R
            Qm = (i - m.i0(om)) / m.kv
            cp = im._bilinear(im.CP, 0.0, n * 60 / 1000)
            return Qm - cp * rho * n * n * im.D ** 5 / (2 * math.pi)
        n = brentq(resid, 1.0, m.kv * vbus / (2 * math.pi) * 0.999)
        ct = im._bilinear(im.CT, 0.0, n * 60 / 1000)
        T_mod = ct * rho * n * n * im.D ** 4
        e = max(abs(rpm_sim / (n * 60) - 1), abs(T_sim / T_mod - 1))
        worst = max(worst, e)
        rows.append(f"duty {duty:.1f}: rpm {rpm_sim:7.1f} vs {n * 60:7.1f}, thrust {T_sim:6.2f} vs {T_mod:6.2f} N, "
                    f"I_batt {pt.s.i_batt:5.1f} A")
    return _check("V8", "Propeller/motor co-simulation, static run-up",
                  "steady RPM and thrust from JSBSim+powertrain vs independent torque-balance root-find within 0.5 %",
                  worst < 5e-3, f"{100 * worst:.3f} %", "<br>".join(rows))


# =============================================================================== V9
def v9_performance(cfg, out, quick=False):
    from .performance import performance_map
    pdir = out / "performance"
    performance_map(pdir, quick=quick)
    df = pd.read_csv(pdir / "performance.csv")
    fit = json.loads((pdir / "performance_fit.json").read_text(encoding="utf-8"))
    ep = df["err_P_batt_pct"].abs().max()
    er = df["err_rpm_pct"].abs().max()
    ea = df["err_alpha_deg"].abs().max()
    # sign/magnitude of the logged aerodynamic forces: lift ~ weight in level flight
    el = float((df["sim_lift_N"] / (df["sim_mass_kg"] * df["sim_g"]) - 1).abs().max())
    ok = ep < 3.0 and er < 1.0 and ea < 0.3 and el < 0.02
    tbl = "<br>".join(f"V={r.sim_tas:5.1f} m/s: P_batt {r.sim_P_batt_W:6.1f} W (model {r.model_P_batt_W:6.1f}, "
                      f"{r.err_P_batt_pct:+.2f}%), rpm {r.sim_rpm:6.0f} ({r.err_rpm_pct:+.2f}%), alpha "
                      f"{r.sim_alpha_deg:5.2f} deg ({r.err_alpha_deg:+.3f}), L/D {r.L_over_D:5.2f}, "
                      f"eta prop/motor/esc {r.eta_prop:.3f}/{r.eta_motor:.3f}/{r.eta_esc:.3f}"
                      for r in df.itertuples())
    det = (tbl + f"<br>Best-endurance speed {fit['v_best_endurance_mps']:.1f} m/s, best-range speed "
           f"{fit['v_best_range_mps']:.1f} m/s, minimum {fit['Wh_per_km_min']:.2f} Wh/km (still air, "
           f"rho={fit['density_kgm3']:.3f}). Remaining differences come from lateral-directional trim drag "
           f"(sideslip/rudder for the yaw-trim term and propeller torque), which the independent model omits.")
    return _check("V9", "Steady flight: full pipeline vs independent trim model",
                  "battery power within 3 %, RPM within 1 %, angle of attack within 0.3 deg at every speed; "
                  "logged lift within 2 % of weight",
                  ok, f"max errors: P {ep:.2f} %, rpm {er:.2f} %, alpha {ea:.3f} deg, lift/weight {100 * el:.2f} %", det,
                  "performance/performance.png")


# ======================================================================= mission runs
def _run(args):
    files, ov, tag, outdir = args
    from ..simulation import Simulation
    cfg = load_config(*files, overrides=ov)
    cfg["logging"]["out_dir"] = str(outdir)
    sim = Simulation(cfg, run_dir=Path(outdir) / tag, run_id=tag, keep_timeseries=False)
    res = sim.run()
    return tag, res.summary


WIND_SCENARIOS = ["calm", "steady_headwind_6", "crosswind_6", "turbulent_light", "gusty", "time_varying",
                  "turbulent_jsbsim", "strong_wind"]


def mission_runs(out, workers):
    runs = out / "runs"
    jobs = [(["configs/missions/survey_box.yaml", f"configs/wind/{w}.yaml"], {}, f"survey_{w}", runs)
            for w in WIND_SCENARIOS]
    jobs += [(["configs/missions/survey_box.yaml", "configs/wind/calm.yaml"], {"sim.dt_physics_s": 0.0025},
              "survey_calm_dt2.5ms", runs)]
    jobs += [(["configs/missions/survey_box.yaml", "configs/wind/turbulent_light.yaml"],
              {"sim.t_max_s": 120.0, "sim.seed": 42}, f"repro_{k}", runs) for k in ("a", "b")]
    jobs += [(["configs/missions/survey_box.yaml", "configs/wind/turbulent_light.yaml"],
              {"sim.t_max_s": 120.0, "sim.seed": 43}, "repro_c", runs)]
    jobs += [(["configs/missions/survey_box.yaml", "configs/wind/turbulent_light.yaml"], {"sim.seed": 100 + k},
              f"landing_mc_{k}", runs) for k in range(N_LANDING_MC)]
    ob = ["configs/missions/out_and_back.yaml", "configs/wind/steady_headwind_6.yaml"]
    jobs += [(ob, {}, "wind_legs_fixed", runs)]
    jobs += [(ob, {"autonomy.policy.name": "wind_aware_best_range"}, "wind_legs_policy", runs)]
    res = {}
    with ProcessPoolExecutor(max_workers=workers) as ex:
        for tag, s in ex.map(_run, jobs):
            res[tag] = s
            print(f"    run {tag:32s} {s['status']:8s} {s.get('E_batt_Wh', 0):6.2f} Wh")
    return res


N_LANDING_MC = 8


def v17_landing_mc(res):
    sinks, bounces, rows, ok = [], [], [], True
    for k in range(N_LANDING_MC):
        s = res[f"landing_mc_{k}"]
        td = s.get("touchdown") or {}
        nb = sum(d == "D7_reflare" for d in s.get("decisions", []))
        on_rw = td.get("along_runway_m") is not None and 0 <= td["along_runway_m"] < 150 and abs(td.get("xtrack_m", 99)) < 10
        ok = ok and s["status"] == "LANDED" and on_rw
        if td.get("sink_mps") is not None:
            sinks.append(td["sink_mps"])
        bounces.append(nb)
        rows.append(f"seed {100 + k}: {s['status']}, sink {td.get('sink_mps')} m/s, touchdown {td.get('along_runway_m')} m / "
                    f"{td.get('xtrack_m')} m, bounces {nb}, energy {s.get('E_batt_Wh', 0):.2f} Wh")
    p95 = float(np.percentile(sinks, 95)) if sinks else 99.0
    ok = ok and p95 < 2.5
    det = "<br>".join(rows) + (f"<br>Touchdown sink mean {np.mean(sinks):.2f} m/s, 95th percentile {p95:.2f} m/s; "
                               f"bounces per landing mean {np.mean(bounces):.1f} (each recovered by the re-flare logic). "
                               f"Mission energy spread across seeds {np.std([res[f'landing_mc_{k}'].get('E_batt_Wh', 0) for k in range(N_LANDING_MC)]):.2f} Wh (1 sigma).")
    return _check("V17", f"Landing reliability in light turbulence ({N_LANDING_MC} seeds)",
                  "every flight lands on the runway; 95th-percentile touchdown sink < 2.5 m/s", ok,
                  f"{sum(r.split(': ')[1].startswith('LANDED') for r in rows)}/{N_LANDING_MC} landed, sink P95 {p95:.2f} m/s",
                  det, kind="validation")


def v10_closure(res):
    rows, worst = [], 0.0
    for w in WIND_SCENARIOS:
        s = res[f"survey_{w}"]
        rel = abs(s["energy_closure"]["relative"])
        lim = 2e-3 if "jsbsim" in w else 1e-3   # JSBSim turbulence adds rotational gust terms
        worst = max(worst, rel / lim)
        rows.append(f"{w}: residual {s['energy_closure']['residual_J']:+.2f} J ({rel:.1e} of gross work), "
                    f"wind work {s['energy_breakdown_Wh']['wind_work']:+.3f} Wh")
    return _check("V10", "Mechanical energy closure in flight",
                  "|dE_air - (aero + propulsive + gear + wind work)| < 0.1 % of gross work for the lab's wind "
                  "models (0.2 % with JSBSim's turbulence, whose rotational gust terms are not in the closure)",
                  worst < 1.0, f"worst {worst:.2f} of limit", "<br>".join(rows))


def v11_dt(res):
    a, b = res["survey_calm"], res["survey_calm_dt2.5ms"]
    e = abs(a["E_batt_Wh"] / b["E_batt_Wh"] - 1)
    t = abs(a["flight_time_s"] / b["flight_time_s"] - 1)
    return _check("V11", "Time-step convergence", "total battery energy and flight time change < 1 % when "
                  "the physics step is halved (5 ms -> 2.5 ms)", e < 0.01 and t < 0.01,
                  f"energy {100 * e:.3f} %, time {100 * t:.3f} %",
                  f"5 ms: {a['E_batt_Wh']:.3f} Wh / {a['flight_time_s']:.1f} s; 2.5 ms: {b['E_batt_Wh']:.3f} Wh / "
                  f"{b['flight_time_s']:.1f} s")


def v12_repro(out):
    d = out / "runs"
    A = pd.read_csv(d / "repro_a" / "timeseries.csv")
    B = pd.read_csv(d / "repro_b" / "timeseries.csv")
    Cc = pd.read_csv(d / "repro_c" / "timeseries.csv")
    num = A.select_dtypes("number").columns
    same = A[num].equals(B[num])
    diff = not np.allclose(A["wind_turb_n_mps"].to_numpy()[:len(Cc)], Cc["wind_turb_n_mps"].to_numpy()[:len(A)])
    return _check("V12", "Reproducibility", "identical seed -> bit-identical time series; different seed -> "
                  "different turbulence realisation", same and diff, f"identical={same}, differs={diff}")


def v13_robustness(res):
    rows, ok = [], True
    for w in WIND_SCENARIOS:
        s = res[f"survey_{w}"]
        td = s.get("touchdown") or {}
        tr = s.get("tracking") or {}
        severe = w == "strong_wind"
        turbulent = w not in ("calm", "steady_headwind_6")
        landed = s["status"] == "LANDED"
        sink_ok = td.get("sink_mps", 9) < (2.5 if turbulent else 1.6)
        rw_ok = td.get("along_runway_m") is not None and 0 <= td["along_runway_m"] < 150 and \
            abs(td.get("xtrack_m", 99)) < 10
        trk_ok = (tr.get("xtrack_rms_steady_m") or 99) < (80 if severe else 6.0)
        this = landed and sink_ok and trk_ok and rw_ok
        ok = ok and this
        rows.append(f"{'PASS' if this else 'FAIL'} {w}: {s['status']}, {s.get('E_batt_Wh', 0):.2f} Wh, "
                    f"{s.get('Wh_per_km') or 0:.2f} Wh/km, touchdown sink {td.get('sink_mps')} m/s at "
                    f"{td.get('along_runway_m')} m / {td.get('xtrack_m')} m, steady xtrack RMS "
                    f"{(tr.get('xtrack_rms_steady_m') or 0):.2f} m, decisions {s.get('decisions')}")
    return _check("V13", f"Closed-loop full flights, {len(WIND_SCENARIOS)} wind scenarios (take-off to full stop)",
                  "all land on the runway (touchdown 0-150 m past the threshold, < 10 m off the centre line); "
                  "touchdown sink < 1.6 m/s in smooth air, < 2.5 m/s in turbulence; steady cross-track RMS < 6 m "
                  "(strong-wind stress case, wind close to the cruise airspeed on up-wind legs: tracking not required)",
                  ok, f"{sum(r.startswith('PASS') for r in rows)}/{len(rows)} pass", "<br>".join(rows),
                  kind="validation")


def v14_wind_legs(res, out):
    """Energy on head-wind / tail-wind legs in a steady sheared wind vs the analytic
    prediction E = P(V_a) * d / V_g, with P(V) the still-air performance-map fit
    and V_g from the configured wind profile (neither uses the leg data).
    Compared on the steady part of each leg (entry turn and level-off excluded)."""
    from ..atmosphere import shear_factor, wind_vector_ned
    fit = json.loads((out / "performance" / "performance_fit.json").read_text(encoding="utf-8"))
    cfg = load_config("configs/missions/out_and_back.yaml", "configs/wind/steady_headwind_6.yaml")
    ts = pd.read_csv(out / "runs" / "wind_legs_fixed" / "timeseries.csv", low_memory=False)
    P = lambda v: fit["a"] * v ** 3 + fit["b"] / v + fit["c"]
    rows, worst = [], 0.0
    head_e = tail_e = None
    mis = ts[ts["mode"] == "MISSION"]
    for leg, g in mis.groupby("leg"):
        g = g[(g["t_s"] > g["t_s"].min() + 30.0)]
        g = g[(g["alt_agl_m"] - g["h_cmd_m"]).abs() < 3.0]
        if len(g) < 300:
            continue
        a, b = g.iloc[0], g.iloc[-1]
        d = b["dist_ground_m"] - a["dist_ground_m"]
        e_sim = b["E_batt_Wh"] - a["E_batt_Wh"]
        h = g["alt_agl_m"].mean()
        W = wind_vector_ned(cfg["wind"]["mean"]["speed_mps"] * shear_factor(h, cfg["wind"]["mean"]),
                            cfg["wind"]["mean"]["from_deg"])
        trk = math.atan2(g["ve_mps"].mean(), g["vn_mps"].mean())
        wa = W[0] * math.cos(trk) + W[1] * math.sin(trk)
        wc = -W[0] * math.sin(trk) + W[1] * math.cos(trk)
        va = 17.0
        vg = math.sqrt(va * va - wc * wc) + wa
        e_pred = P(va) * d / vg / 3600.0
        err = e_sim / e_pred - 1
        worst = max(worst, abs(err))
        whkm = e_sim / (d / 1000)
        if wa < -3:
            head_e = whkm
        if wa > 3:
            tail_e = whkm
        rows.append(f"leg {g['leg_name'].iloc[0]} (steady {b['t_s'] - a['t_s']:.0f} s, {d / 1000:.2f} km): tail-wind "
                    f"{wa:+.2f} m/s, ground speed {d / (b['t_s'] - a['t_s']):.2f} (pred {vg:.2f}) m/s, energy "
                    f"{e_sim:.2f} Wh vs predicted {e_pred:.2f} Wh ({100 * err:+.2f} %), {whkm:.2f} Wh/km")
    legs = pd.read_csv(out / "runs" / "wind_legs_fixed" / "legs.csv")
    rows.append("Whole legs (incl. turns/climb), from legs.csv: " + "; ".join(
        f"{r.leg_name} {r.Wh_per_km:.2f} Wh/km" for r in legs.itertuples()))
    ok = worst < 0.03 and head_e is not None and tail_e is not None and head_e > 2 * tail_e
    return _check("V14", "Wind-energy physics on head-wind / tail-wind legs",
                  "steady-leg battery energy within 3 % of E = P(V_a) d / V_g (still-air performance map + "
                  "configured wind profile), and head-wind legs cost > 2x tail-wind legs per km",
                  ok, f"worst {100 * worst:.2f} %", "<br>".join(rows), kind="validation")


def d1_policy(res):
    a, b = res["wind_legs_fixed"], res["wind_legs_policy"]
    ea, eb = a.get("mission_E_Wh"), b.get("mission_E_Wh")
    sav = 100 * (1 - eb / ea) if ea and eb else float("nan")
    return _check("D1", "Demonstration: wind-aware speed-to-fly policy (online optimiser slot)",
                  "informative: same route and wind, fixed 17 m/s vs wind_aware_best_range policy",
                  a["status"] == "LANDED" and b["status"] == "LANDED",
                  f"mission-leg energy {ea:.2f} -> {eb:.2f} Wh ({sav:+.1f} % saving)",
                  f"fixed: total {a['E_batt_Wh']:.2f} Wh, {a['flight_time_s']:.0f} s; policy: total "
                  f"{b['E_batt_Wh']:.2f} Wh, {b['flight_time_s']:.0f} s", kind="demonstration")


def v15_signs(cfg):
    from ..fdm import FDM
    from ..models import build_model_dir
    import tempfile
    td = tempfile.mkdtemp()
    build_model_dir(cfg, td)
    res = {}
    for ch in ("ail", "elev", "rud"):
        f = FDM(td, 0.005)
        f.init_in_air(0, 0, 0, 100, 0, 17)
        u = {"ail": 0, "elev": 0, "rud": 0}
        base = {}
        for s_ in (0.0, 0.3):
            f = FDM(td, 0.005)
            f.init_in_air(0, 0, 0, 100, 0, 17)
            u = {"ail": 0.0, "elev": 0.0, "rud": 0.0}
            u[ch] = s_
            for _ in range(40):
                f.set_surfaces(u["ail"], u["elev"], u["rud"], 0.0)
                f.run()
            base[s_] = f.state()
        d = {k: base[0.3][k] - base[0.0][k] for k in ("p", "q", "r")}
        res[ch] = d
    ok = res["ail"]["p"] > 0 and res["elev"]["q"] < 0 and res["rud"]["r"] < 0
    return _check("V15", "Control-surface sign conventions",
                  "+aileron -> +roll rate, +elevator -> nose-down, +rudder -> nose-left (as the controllers assume)",
                  ok, f"dp={res['ail']['p']:+.3f}, dq={res['elev']['q']:+.3f}, dr={res['rud']['r']:+.3f} rad/s")


def v16_config():
    bad = {"powertrain.battery.soc_init": 1.5, "wind.turbulence.model": "vonkarman", "sim.control_rate_hz": 33}
    caught = 0
    for k, v in bad.items():
        try:
            load_config(overrides={k: v})
        except ConfigError:
            caught += 1
    try:
        load_config(overrides={"wind.mean.speedd": 3})
    except ConfigError:
        caught += 1
    return _check("V16", "Configuration validation", "invalid values and unknown keys are rejected",
                  caught == 4, f"{caught}/4 rejected")


# ======================================================================= U1
def u1_sensitivity(cfg, out, quick=False):
    """One-at-a-time sensitivity of cruise battery power (17 m/s, level) to the
    parameters that are least certain. Tells you what to calibrate first."""
    from .performance import steady_flight_sim
    plt = _fig()
    from ..plotting import C, _style
    base_cfg = load_config()
    base_cfg["sensors"]["noise_enabled"] = False
    st, av = (40.0, 10.0) if quick else (70.0, 20.0)
    p0 = steady_flight_sim(base_cfg, 17.0, settle_s=st, avg_s=av)["P_batt_W"]
    cases = [("CD0 +-10 %", "aircraft.aero_calibration.cd0_scale", 1.0, 0.10),
             ("induced drag K +-10 %", "aircraft.aero_calibration.cdi_scale", 1.0, 0.10),
             ("propeller CP +-5 % (CT fixed)", "powertrain.propeller.cp_scale", 1.0, 0.05),
             ("all-up mass +-10 %", "aircraft.airframe_mass_kg", 4.80, 0.128),
             ("motor I0 +-30 %", "powertrain.motor.no_load_current_a", 1.8, 0.30),
             ("motor R +-30 %", "powertrain.motor.resistance_ohm", 0.025, 0.30),
             ("battery R0 +-30 %", "powertrain.battery.r0_cell_ohm", 0.0025, 0.30),
             ("avionics power +-30 %", "powertrain.avionics.base_power_w", 6.0, 0.30)]
    rows = []
    for lab, key, nom, rel in cases:
        vals = []
        for sgn in (-1, 1):
            c = load_config(overrides={key: nom * (1 + sgn * rel)})
            c["sensors"]["noise_enabled"] = False
            vals.append(100 * (steady_flight_sim(c, 17.0, settle_s=st, avg_s=av)["P_batt_W"] / p0 - 1))
        rows.append((lab, vals[0], vals[1]))
    rows.sort(key=lambda r: max(abs(r[1]), abs(r[2])))
    fig, ax = plt.subplots(figsize=(9, 4.5), facecolor="#fcfcfb")
    y = np.arange(len(rows))
    ax.barh(y, [r[1] for r in rows], color=C[0], height=0.6, label="parameter decreased")
    ax.barh(y, [r[2] for r in rows], color=C[1], height=0.6, label="parameter increased")
    ax.set_yticks(y, [r[0] for r in rows])
    ax.axvline(0, color="#52514e", lw=0.8)
    _style(ax, f"Sensitivity of cruise battery power (17 m/s, {p0:.0f} W nominal)", None, "change in battery power (%)")
    ax.legend(fontsize=8, frameon=False, loc="lower right")
    fig.tight_layout()
    fig.savefig(out / "u1_sensitivity.png", dpi=100)
    plt.close(fig)
    det = "<br>".join(f"{r[0]}: {r[1]:+.2f} % / {r[2]:+.2f} %" for r in rows[::-1])
    top = rows[-1]
    return _check("U1", "Uncertainty: parameter sensitivity of cruise power",
                  "informative: one-at-a-time perturbation of uncertain [REP] parameters", True,
                  f"largest: {top[0]} ({top[1]:+.1f} / {top[2]:+.1f} %)", det, "u1_sensitivity.png",
                  kind="uncertainty")


# ============================================================================ report
def _img(path: Path) -> str:
    return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode()


KIND_LABEL = {"verification": "Verification", "validation": "Validation", "uncertainty": "Uncertainty",
              "demonstration": "Demonstration"}


def _html_escape(s):
    return str(s).replace("&", "&amp;").replace("<br>", "\x00").replace("<", "&lt;").replace(">", "&gt;") \
        .replace("\x00", "<br>")


def write_report(out: Path, checks: list, meta: dict):
    n_pass = sum(c["passed"] for c in checks)
    js = {"meta": meta, "checks": checks, "passed": n_pass, "total": len(checks)}
    (out / "vv_results.json").write_text(json.dumps(js, indent=2, default=str), encoding="utf-8")
    md = [f"# UAV Energy Lab - Verification & Validation report", "",
          f"uavlab {meta['uavlab']}, JSBSim {meta['jsbsim']}, generated {meta['date']}, wall time "
          f"{meta['wall_s']:.0f} s. **{n_pass}/{len(checks)} checks passed.**", "",
          "| ID | Check | Criterion | Result | Pass |", "|---|---|---|---|---|"]
    for c in checks:
        md.append(f"| {c['id']} | {c['title']} | {c['criterion']} | {c['value']} | {'PASS' if c['passed'] else 'FAIL'} |")
    md.append("")
    for c in checks:
        md += [f"## {c['id']} {c['title']}", "", f"*Criterion:* {c['criterion']}", "",
               f"*Result:* {c['value']} - **{'PASS' if c['passed'] else 'FAIL'}**", ""]
        if c["details"]:
            md += [c["details"].replace("<br>", "  \n"), ""]
        if c["figure"]:
            md += [f"![{c['id']}]({c['figure']})", ""]
    (out / "VV_REPORT.md").write_text("\n".join(md), encoding="utf-8")
    (out / "VV_REPORT.html").write_text(report_html(out, checks, meta), encoding="utf-8")


def report_html(out: Path, checks: list, meta: dict, extra_figures: list | None = None) -> str:
    """Self-contained, theme-aware HTML report (content-only document: browsers add
    the html/head/body wrapper; also valid as a published page)."""
    n_pass = sum(c["passed"] for c in checks)
    groups = {}
    for c in checks:
        groups.setdefault(c.get("kind", "verification"), []).append(c)
    rows = ""
    for kind in ("verification", "validation", "uncertainty", "demonstration"):
        if kind not in groups:
            continue
        rows += f"<tr class='grp'><th colspan='4'>{KIND_LABEL[kind]}</th></tr>"
        for c in groups[kind]:
            state = "pass" if c["passed"] else "fail"
            label = ("PASS" if c["passed"] else "FAIL") if kind in ("verification", "validation") else \
                ("INFO" if c["passed"] else "FAIL")
            rows += (f"<tr><td class='id'><a href='#{c['id']}'>{c['id']}</a></td><td>{_html_escape(c['title'])}"
                     f"<div class='crit'>{_html_escape(c['criterion'])}</div></td><td class='val'>"
                     f"{_html_escape(c['value'])}</td><td><span class='chip {state}'>{label}</span></td></tr>")
    secs = ""
    for c in checks:
        fig = ""
        if c["figure"] and (out / c["figure"]).exists():
            fig = f"<figure><img src='{_img(out / c['figure'])}' alt='{c['id']}: {_html_escape(c['title'])}'></figure>"
        det = f"<details><summary>Measured values</summary><p class='det'>{_html_escape(c['details'])}</p></details>" \
            if c["details"] else ""
        state = "pass" if c["passed"] else "fail"
        secs += (f"<section id='{c['id']}'><h3><span class='chip {state}'>{'PASS' if c['passed'] else 'FAIL'}</span> "
                 f"{c['id']} &middot; {_html_escape(c['title'])}</h3><p><b>Criterion.</b> {_html_escape(c['criterion'])}</p>"
                 f"<p><b>Result.</b> <span class='mono'>{_html_escape(c['value'])}</span></p>{det}{fig}</section>")
    extra = ""
    for title, path in extra_figures or []:
        if Path(path).exists():
            extra += f"<figure><figcaption>{_html_escape(title)}</figcaption><img src='{_img(Path(path))}' alt='{_html_escape(title)}'></figure>"
    return f"""<title>Rascal Energy Lab V&amp;V</title>
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans+Condensed:wght@500;600&family=IBM+Plex+Sans:wght@400;500;600&display=swap">
<style>
:root{{--bg:#f4f6f5;--panel:#ffffff;--ink:#17201d;--ink2:#4c5954;--rule:#d7deda;--accent:#1d6a86;
--pass:#1f7a3a;--pass-bg:#e3f1e7;--fail:#b3261e;--fail-bg:#f8e1df;--info:#1d6a86;--info-bg:#e1eef3;
--sans:"IBM Plex Sans",system-ui,-apple-system,"Segoe UI",sans-serif;--cond:"IBM Plex Sans Condensed","IBM Plex Sans",system-ui,sans-serif;
--mono:"IBM Plex Mono",ui-monospace,Menlo,Consolas,monospace}}
@media (prefers-color-scheme:dark){{:root:not([data-theme="light"]){{color-scheme:dark;--bg:#111715;--panel:#18201d;--ink:#e4ebe8;
--ink2:#a3b1ab;--rule:#2c3733;--accent:#6cb6d3;--pass:#7fd39a;--pass-bg:#173424;--fail:#f19a92;--fail-bg:#3d1f1c;--info:#8cc6de;--info-bg:#15313d}}}}
:root[data-theme="dark"]{{color-scheme:dark;--bg:#111715;--panel:#18201d;--ink:#e4ebe8;--ink2:#a3b1ab;--rule:#2c3733;
--accent:#6cb6d3;--pass:#7fd39a;--pass-bg:#173424;--fail:#f19a92;--fail-bg:#3d1f1c;--info:#8cc6de;--info-bg:#15313d}}
body{{background:var(--bg);color:var(--ink);font:15px/1.55 var(--sans);margin:0}}
.wrap{{max-width:1040px;margin:0 auto;padding-inline:16px;padding-block:28px 64px}}
h1,h2,h3{{font-family:var(--cond);text-wrap:balance;line-height:1.2}}
h1{{font-size:30px;margin:0 0 6px}} h2{{font-size:21px;margin:36px 0 10px}} h3{{font-size:17px;margin:0 0 8px}}
.eyebrow{{font:500 12px/1 var(--mono);letter-spacing:.08em;text-transform:uppercase;color:var(--accent)}}
.lede{{color:var(--ink2);max-width:68ch}}
.mono,.val,.id{{font-family:var(--mono);font-variant-numeric:tabular-nums}}
.stats{{display:flex;flex-wrap:wrap;gap:12px;margin:20px 0 4px}}
.stat{{background:var(--panel);border:1px solid var(--rule);border-radius:6px;padding:12px 16px;min-width:0;flex:1 1 140px}}
.stat b{{display:block;font:600 22px/1.2 var(--mono)}} .stat span{{color:var(--ink2);font-size:13px}}
.tablewrap{{overflow-x:auto;background:var(--panel);border:1px solid var(--rule);border-radius:6px}}
table{{border-collapse:collapse;width:100%;font-size:13.5px}}
td,th{{padding:9px 12px;border-bottom:1px solid var(--rule);text-align:left;vertical-align:top}}
tr.grp th{{font:600 12px/1 var(--mono);letter-spacing:.07em;text-transform:uppercase;color:var(--ink2);background:var(--bg)}}
.crit{{color:var(--ink2);font-size:12.5px;margin-top:2px}} .val{{font-size:12.5px;min-width:14ch}}
.id a{{color:var(--accent);text-decoration:none}} .id a:focus-visible{{outline:2px solid var(--accent)}}
.chip{{display:inline-block;font:600 11px/1 var(--mono);letter-spacing:.06em;padding:4px 7px;border-radius:4px;white-space:nowrap}}
.chip.pass{{color:var(--pass);background:var(--pass-bg)}} .chip.fail{{color:var(--fail);background:var(--fail-bg)}}
section{{border-top:1px solid var(--rule);padding-top:18px;margin-top:22px}}
section p{{margin:6px 0;max-width:80ch}} .det{{color:var(--ink2);font:12.5px/1.6 var(--mono);overflow-wrap:anywhere}}
details summary{{cursor:pointer;color:var(--accent);font-size:13.5px}}
figure{{margin:14px 0 0;background:#fcfcfb;border:1px solid var(--rule);border-radius:6px;padding:8px}}
figure img{{display:block;max-width:100%;height:auto;margin:0 auto}} figcaption{{color:#4c5954;font-size:13px;margin-bottom:6px}}
</style>
<div class="wrap">
<div class="eyebrow">JSBSim Rascal 110 electric &middot; uavlab {meta['uavlab']}</div>
<h1>Verification &amp; validation report</h1>
<p class="lede">Every model block of the UAV energy lab is checked against a published reference, an analytic
solution or an independent re-implementation. It is then flown end to end in wind from take-off to full stop.
Each criterion is fixed before the run, and the measured value is shown next to it.</p>
<div class="stats"><div class="stat"><b>{n_pass}/{len(checks)}</b><span>checks passed</span></div>
<div class="stat"><b>JSBSim {meta['jsbsim']}</b><span>flight-dynamics core</span></div>
<div class="stat"><b>{meta['wall_s'] / 60:.0f} min</b><span>suite run time (2 cores)</span></div>
<div class="stat"><b>{meta['date'][:10]}</b><span>generated</span></div></div>
<h2>Checks</h2>
<div class="tablewrap"><table><thead><tr><th>ID</th><th>Check and criterion</th><th>Result</th><th>Status</th></tr></thead>
<tbody>{rows}</tbody></table></div>
{('<h2>Example flight</h2>' + extra) if extra else ''}
<h2>Evidence</h2>
{secs}
<p class="crit" style="margin-top:32px">Reproduce: <span class="mono">python -m uavlab validate</span> from the repository root.
The per-run logs behind V10-V14 and D1 are in <span class="mono">validation_report/runs/</span>.</p>
</div>
"""


def run_suite(out: Path, quick: bool = False, workers: int | None = None) -> bool:
    import os
    import jsbsim
    from datetime import datetime
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    cfg = load_config()
    workers = workers or max(1, (os.cpu_count() or 2))
    checks = []

    def do(fn, *a):
        name = fn.__name__
        print(f"[V&V] {name} ...", flush=True)
        try:
            c = fn(*a)
        except Exception as e:
            c = _check(name.upper().split("_")[0], name, "ran without error", False, f"ERROR {e}",
                       traceback.format_exc().replace("\n", "<br>"))
        print(f"      {c['id']}: {'PASS' if c['passed'] else 'FAIL'}  {c['value']}", flush=True)
        checks.append(c)

    do(v1_atmosphere, cfg)
    do(v2_wind_injection, cfg)
    do(v3_dryden, cfg, quick, out)
    do(v4_gust, cfg)
    do(v5_battery, cfg)
    do(v6_motor, cfg)
    do(v7_powertrain, cfg)
    do(v8_static_prop, cfg)
    do(v15_signs, cfg)
    do(v16_config)
    do(v9_performance, cfg, out, quick)
    print("[V&V] mission runs ...", flush=True)
    res = mission_runs(out, workers)
    do(v10_closure, res)
    do(v11_dt, res)
    do(v12_repro, out)
    do(v13_robustness, res)
    do(v17_landing_mc, res)
    do(v14_wind_legs, res, out)
    do(d1_policy, res)
    do(u1_sensitivity, cfg, out, quick)
    order = ["V1", "V2", "V3", "V4", "V5", "V6", "V7", "V8", "V9", "V10", "V11", "V12", "V13", "V14", "V15",
             "V16", "V17", "U1", "D1"]
    checks.sort(key=lambda c: order.index(c["id"]) if c["id"] in order else 99)
    meta = {"uavlab": __version__, "jsbsim": jsbsim.__version__, "date": datetime.now().isoformat(timespec="seconds"),
            "wall_s": time.time() - t0, "quick": quick}
    write_report(out, checks, meta)
    n = sum(c["passed"] for c in checks)
    print(f"[V&V] {n}/{len(checks)} passed -> {out / 'VV_REPORT.html'}")
    return n == len(checks)


def rebuild_report(out: Path, extra_figures: list | None = None) -> Path:
    """Re-render VV_REPORT.html from vv_results.json (e.g. after editing the template)."""
    out = Path(out)
    js = json.loads((out / "vv_results.json").read_text(encoding="utf-8"))
    html = report_html(out, js["checks"], js["meta"], extra_figures)
    (out / "VV_REPORT.html").write_text(html, encoding="utf-8")
    return out / "VV_REPORT.html"
