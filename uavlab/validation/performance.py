"""Steady-flight performance map and an independent trim model.

Two independent ways to get battery power in steady level flight at airspeed V:

  1. SIMULATION: the full pipeline (JSBSim 6-DoF + powertrain co-simulation +
     TECS/attitude loops) flies straight and level; values are averaged after
     the transients (incl. battery polarisation) have settled.
  2. INDEPENDENT MODEL: a separate re-implementation that reads the same
     coefficients and solves the algebraic trim (lift, drag, pitching-moment
     and thrust balance), then the propeller (bilinear CT/CP tables), motor,
     ESC and battery equations in closed form.

Agreement verifies the implementation of every block in the chain (V&V check
V9). The map also yields best-endurance / best-range speeds and the P(V) fit
used by the wind-aware policy.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import brentq, fsolve

from ..actuators import ActuatorSet
from ..config import load_config
from ..control import TECS, AttitudeController, L1Guidance
from ..energy.powertrain import Powertrain
from ..fdm import FDM
from ..models import build_model_dir, build_prop_tables, read_apc_per3, DATA
from ..units import DEG, FT, IN, LBF, RPM

G0 = 9.80665


# ------------------------------------------------------------------ simulation
def steady_flight_sim(cfg: dict, v: float, h_agl: float = 100.0, settle_s: float = 100.0, avg_s: float = 30.0,
                      soc: float = 0.8, model_root: Path | None = None) -> dict:
    import tempfile
    tmp = None
    if model_root is None:
        tmp = tempfile.TemporaryDirectory(prefix="uavlab_perf_", ignore_cleanup_errors=True)
        model_root = Path(tmp.name)
    build_model_dir(cfg, model_root)
    dt = float(cfg["sim"]["dt_physics_s"])
    n_ctrl = int(round(1.0 / (dt * cfg["sim"]["control_rate_hz"])))
    f = FDM(model_root, dt)
    a = cfg["atmosphere"]
    f.set_atmosphere(a["delta_T_K"], a["sl_pressure_pa"], a["relative_humidity_pct"])
    home = cfg["mission"]["home"]
    f.init_in_air(home["lat_deg"], home["lon_deg"], home["alt_msl_m"], h_agl, 0.0, v)
    f.set_wind(np.zeros(3), np.zeros(3))
    pcfg = dict(cfg["powertrain"])
    pcfg["battery"] = dict(pcfg["battery"], soc_init=soc)
    pt = Powertrain(pcfg)
    act = ActuatorSet(cfg["actuators"], cfg["powertrain"]["avionics"])
    cc = cfg["controller"]
    tecs = TECS(cc["tecs"], cc["pitch_limit_deg"])
    att = AttitudeController(cc, v_ref=cfg["mission"]["cruise"]["airspeed_mps"])
    l1 = L1Guidance(cc["l1"]["period_s"], cc["l1"]["damping"], cc["roll_limit_deg"])
    x = f.state()
    tecs.reset(x["h_agl"], x["tas"])
    # warm start the rotor and throttle so the transient is short
    thr = 0.6
    cmd = [0.0, cfg["controller"]["pitch"]["trim_elev"], 0.0, thr]
    rows = []
    k = 0
    n_total = int((settle_s + avg_s) / dt)
    A, B = np.array([0.0, 0.0]), np.array([1e5, 0.0])
    pos0 = None
    from ..geo import LocalFrame
    frame = LocalFrame(home["lat_deg"], home["lon_deg"], home["alt_msl_m"])
    for k in range(n_total):
        if k % n_ctrl == 0:
            x = f.state()
            ne = frame.to_ned(x["lat"], x["lon"], x["h_msl"])[:2]
            cdt = dt * n_ctrl
            phi_c = l1.line(ne, [x["vn"], x["ve"]], A, B)
            t_c, th_c = tecs.update(cdt, x["h_agl"], -x["vd"], x["tas"], h_agl, v, ax=x["ax"], theta=x["theta"])
            ail = att.roll(cdt, phi_c, x["phi"], x["p"], x["tas"])
            elev = att.pitch(cdt, th_c, x["theta"], x["q"], x["phi"], x["tas"])
            rud = att.yaw(x["beta"], x["r"], x["phi"], x["tas"], ail)
            thr += cdt / (0.15 + cdt) * (t_c - thr)
            cmd = [ail, elev, rud, thr]
        a_, e_, r_, t_ = act.step(*cmd, dt)
        f.set_surfaces(a_, e_, r_, 0.0)
        rpm = f.prop_rpm()
        om = rpm * RPM
        f.set_prop_krpm(min(max(rpm, 1000.0), 12000.0) / 1000.0)
        pt.p_avionics_extra = act.servo_power()
        q = pt.step(t_, om, dt)
        f.set_motor_torque(q, om)
        f.run()
        if k * dt >= settle_s:
            x = f.state()
            s = pt.s
            rows.append({"tas": x["tas"], "h": x["h_agl"], "alpha": x["alpha"], "theta": x["theta"],
                         "elev": x["elev_pos"], "rpm": x["rpm"], "J": x["J"], "thrust": x["thrust"],
                         "drag": x["drag"], "lift": x["lift"], "qbar": x["qbar"], "rho": x["rho"],
                         "p_batt": s.p_batt_term, "p_shaft": s.p_shaft, "p_motor_in": s.p_motor_in,
                         "p_esc_in": s.p_esc_in, "p_av": s.p_avionics, "i_batt": s.i_batt, "i_motor": s.i_motor,
                         "v_bus": s.v_bus, "duty": s.duty_eff, "soc": pt.battery.soc, "u_air": x["u_air"],
                         "mass": x["mass"], "g": x["g"], "vd": x["vd"]})
    df = pd.DataFrame(rows)
    m = df.mean()
    out = {"v_cmd": v, "tas": m["tas"], "alt_std": df["h"].std(), "tas_std": df["tas"].std(),
           "alpha_deg": m["alpha"] / DEG, "elev_norm": m["elev"], "rpm": m["rpm"], "J": m["J"],
           "thrust_N": m["thrust"], "drag_N": m["drag"], "lift_N": m["lift"],
           "CL": m["lift"] / (m["qbar"] * 10.57 * FT * FT), "CD": m["drag"] / (m["qbar"] * 10.57 * FT * FT),
           "P_batt_W": m["p_batt"], "P_shaft_W": m["p_shaft"], "P_thrust_W": (df["thrust"] * df["u_air"]).mean(),
           "P_motor_in_W": m["p_motor_in"], "P_esc_in_W": m["p_esc_in"], "P_avionics_W": m["p_av"],
           "I_batt_A": m["i_batt"], "V_bus_V": m["v_bus"], "duty": m["duty"], "soc": m["soc"],
           "rho": m["rho"], "mass_kg": m["mass"], "g": m["g"], "climb_mps": -m["vd"]}
    if tmp is not None:
        tmp.cleanup()
    return out


# -------------------------------------------------------------- independent model
class IndependentModel:
    """Algebraic steady-level-flight model written separately from the simulator.
    Reads coefficient values from the config (calibration factors) and the
    constants of the Rascal aircraft file; does not call JSBSim."""

    S = 10.57 * FT * FT
    b = 9.17 * FT
    c = 1.15 * FT

    def __init__(self, cfg: dict, cg_x_in: float, cg_z_in: float, mass: float, g: float):
        cal = cfg["aircraft"].get("aero_calibration", {})
        self.cd0s = float(cal.get("cd0_scale", 1.0))
        self.k = 0.04 * float(cal.get("cdi_scale", 1.0))
        self.cls = float(cal.get("cl_scale", 1.0))
        self.m, self.g = mass, g
        # AERORP (37.4, 0, 0) and prop (1, 0, 0) relative to the CG, body axes (x fwd, z down), m
        self.r_aero = np.array([-(37.4 - cg_x_in), 0.0, -(0.0 - cg_z_in)]) * IN
        self.r_prop = np.array([-(1.0 - cg_x_in), 0.0, -(0.0 - cg_z_in)]) * IN
        pp = cfg["powertrain"]["propeller"]
        self.D = float(pp["diameter_in"]) * IN
        apc = read_apc_per3(DATA / pp.get("data_file", "PER3_18x8E.dat"))
        self.jg = np.round(np.concatenate([np.arange(0.0, 0.64 + 1e-9, 0.02), [0.68, 0.72, 0.76, 0.80, 0.90]]), 3)
        self.rpms, self.CT, self.CP, _ = build_prop_tables(apc, self.jg)
        self.krpm = np.array(self.rpms) / 1000.0
        self.cts, self.cps = float(pp.get("ct_scale", 1.0)), float(pp.get("cp_scale", 1.0))
        self.pt_cfg = cfg["powertrain"]

    @staticmethod
    def _interp1(x, xs, ys):
        return float(np.interp(x, xs, ys))

    def CL_alpha(self, a):
        return self.cls * self._interp1(a, [-0.2, 0.0, 0.23, 0.6], [-0.75, 0.25, 1.4, 0.71])

    def CD0(self, a):
        return self.cd0s * self._interp1(a, [-1.57, -0.26, 0.0, 0.26, 1.57], [1.5, 0.056, 0.028, 0.056, 1.5])

    def aero(self, a, de_rad, qbar, mach):
        CL = self.CL_alpha(a) + 0.2 * de_rad
        de_norm = max(min(de_rad / 0.3, 1.0), -1.0)
        CD = self.CD0(a) + self.k * CL * CL + 0.03 * abs(de_norm)
        cmde = -0.5 + (-0.275 + 0.5) * mach / 2.0
        Cm = -0.5 * a + cmde * de_rad
        return CL, CD, Cm

    def _bilinear(self, M, J, krpm):
        J = min(max(J, self.jg[0]), self.jg[-1])
        kr = min(max(krpm, self.krpm[0]), self.krpm[-1])
        i = min(np.searchsorted(self.jg, J) - 1, len(self.jg) - 2)
        i = max(i, 0)
        j = min(max(np.searchsorted(self.krpm, kr) - 1, 0), len(self.krpm) - 2)
        tj = (J - self.jg[i]) / (self.jg[i + 1] - self.jg[i])
        tk = (kr - self.krpm[j]) / (self.krpm[j + 1] - self.krpm[j])
        return ((1 - tj) * (1 - tk) * M[i, j] + tj * (1 - tk) * M[i + 1, j]
                + (1 - tj) * tk * M[i, j + 1] + tj * tk * M[i + 1, j + 1])

    def trim(self, v, rho, mach):
        qbar = 0.5 * rho * v * v
        W = self.m * self.g

        def eqs(z):
            a, de, T = z
            CL, CD, Cm = self.aero(a, de, qbar, mach)
            L, D = qbar * self.S * CL, qbar * self.S * CD
            # body-axis aero force (theta = alpha in level flight)
            Fx = -D * math.cos(a) + L * math.sin(a)
            Fz = -D * math.sin(a) - L * math.cos(a)
            My_aero = Cm * qbar * self.S * self.c + (self.r_aero[2] * Fx - self.r_aero[0] * Fz)
            My_prop = self.r_prop[2] * T
            # force balance in earth axes with theta = alpha, gamma = 0
            fx_e = (Fx + T) * math.cos(a) + Fz * math.sin(a)
            fz_e = -(Fx + T) * math.sin(a) + Fz * math.cos(a) + W
            return [fx_e, fz_e, My_aero + My_prop]

        a, de, T = fsolve(eqs, [0.02, -0.05, 6.0], xtol=1e-12)
        CL, CD, Cm = self.aero(a, de, qbar, mach)
        return {"alpha": a, "de_rad": de, "thrust": T, "CL": CL, "CD": CD, "drag": qbar * self.S * CD,
                "lift": qbar * self.S * CL}

    def propeller(self, T, v_axial, rho):
        """Propeller speed giving thrust T at axial speed v (J and kRPM coupled)."""
        def f(n):
            J = v_axial / (n * self.D)
            ct = self.cts * self._bilinear(self.CT, J, n * 60 / 1000.0)
            return ct * rho * n * n * self.D ** 4 - T
        n = brentq(f, 20.0, 200.0, xtol=1e-10)
        J = v_axial / (n * self.D)
        cp = self.cps * self._bilinear(self.CP, J, n * 60 / 1000.0)
        P = cp * rho * n ** 3 * self.D ** 5
        return {"n": n, "rpm": n * 60, "J": J, "P_shaft": P}

    def electrical(self, P_shaft, rpm, soc, p_aux):
        m, e, b = self.pt_cfg["motor"], self.pt_cfg["esc"], self.pt_cfg["battery"]
        kv = m["kv_rpm_per_v"] * math.pi / 30
        om = rpm * RPM
        Q = P_shaft / om
        I = Q * kv + m["no_load_current_a"]
        E = om / kv
        Vm = E + I * m["resistance_ohm"]
        ns, npar = b["cells_series"], b["cells_parallel"]
        ocv = ns * float(np.interp(soc, b["ocv_table"]["soc"], b["ocv_table"]["v"]))
        R0 = ns * b["r0_cell_ohm"] / npar + b.get("wiring_resistance_ohm", 0.0)
        R1 = ns * b["r1_cell_ohm"] / npar
        # steady state: polarisation voltage = I_b * R1
        def g(V):
            d = (Vm + I * e["resistance_ohm"]) / V
            Ib = d * I + (e["switching_loss_frac"] * V * I + e["quiescent_power_w"] + p_aux) / V
            return V - (ocv - Ib * (R0 + R1)), d, Ib
        V = brentq(lambda V: g(V)[0], 5.0, ocv)
        _, d, Ib = g(V)
        return {"P_batt": V * Ib, "I_batt": Ib, "V_bus": V, "duty": d, "I_motor": I, "P_motor_in": Vm * I}

    def point(self, v, rho, mach, soc, p_aux):
        tr = self.trim(v, rho, mach)
        pr = self.propeller(tr["thrust"], v * math.cos(tr["alpha"]) * 1.0, rho)
        el = self.electrical(pr["P_shaft"], pr["rpm"], soc, p_aux)
        return {**tr, **pr, **el}


# -------------------------------------------------------------------- the map
def performance_map(out: Path, overrides: dict | None = None, speeds=None, quick: bool = False,
                    base_config: dict | None = None) -> Path:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from ..plotting import C, GRID, INK, INK2, SURF, _style
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    if base_config is not None:
        from ..config import config_from_dict
        cfg = config_from_dict(base_config, overrides or {})
    else:
        cfg = load_config(overrides=overrides or {})
    cfg["sensors"]["noise_enabled"] = False
    speeds = speeds or ([11, 13, 15, 17, 19, 21, 23, 25] if not quick else [12, 17, 22])
    rows = []
    for v in speeds:
        sim = steady_flight_sim(cfg, float(v), settle_s=60.0 if quick else 100.0, avg_s=20.0 if quick else 30.0)
        # independent model at the same density, mass, SOC and auxiliary power
        im = IndependentModel(cfg, 36.4, _cg_z(cfg), sim["mass_kg"], sim["g"])
        mach = sim["tas"] / math.sqrt(1.4 * 287.05 * 288.15)
        mod = im.point(sim["tas"], sim["rho"], mach, sim["soc"], sim["P_avionics_W"])
        e_use = _usable_wh(cfg)
        rows.append({**{f"sim_{k}": val for k, val in sim.items()},
                     "model_alpha_deg": mod["alpha"] / DEG, "model_rpm": mod["rpm"], "model_thrust_N": mod["thrust"],
                     "model_P_shaft_W": mod["P_shaft"], "model_P_batt_W": mod["P_batt"], "model_CL": mod["CL"],
                     "model_CD": mod["CD"], "model_duty": mod["duty"],
                     "err_P_batt_pct": 100 * (sim["P_batt_W"] - mod["P_batt"]) / mod["P_batt"],
                     "err_rpm_pct": 100 * (sim["rpm"] - mod["rpm"]) / mod["rpm"],
                     "err_alpha_deg": sim["alpha_deg"] - mod["alpha"] / DEG,
                     "L_over_D": sim["lift_N"] / sim["drag_N"],
                     "eta_prop": sim["P_thrust_W"] / sim["P_shaft_W"],
                     "eta_motor": sim["P_shaft_W"] / sim["P_motor_in_W"],
                     "eta_esc": sim["P_motor_in_W"] / sim["P_esc_in_W"],
                     "Wh_per_km": sim["P_batt_W"] / sim["tas"] / 3.6,
                     "endurance_min_usable": 60 * e_use / sim["P_batt_W"],
                     "range_km_usable": e_use / (sim["P_batt_W"] / sim["tas"] / 3.6)})
        print(f"  V={v:5.1f}  P_batt sim {sim['P_batt_W']:7.1f} W  model {mod['P_batt']:7.1f} W  "
              f"err {rows[-1]['err_P_batt_pct']:+5.2f}%  rpm err {rows[-1]['err_rpm_pct']:+5.2f}%  "
              f"alpha err {rows[-1]['err_alpha_deg']:+.2f} deg")
    df = pd.DataFrame(rows)
    df.to_csv(out / "performance.csv", index=False, float_format="%.6g")
    V = df["sim_tas"].to_numpy()
    P = df["sim_P_batt_W"].to_numpy()
    A = np.c_[V ** 3, 1.0 / V, np.ones_like(V)]
    # non-negative least squares: parasite (a), induced (b) and fixed-load (c) terms stay physical
    from scipy.optimize import nnls
    coef, _ = nnls(A, P)
    vv = np.linspace(V.min(), V.max(), 400)
    pf = coef[0] * vv ** 3 + coef[1] / vv + coef[2]
    fit = {"model": "P_batt(V) = a V^3 + b / V + c  (W, V in m/s TAS)",
           "a": float(coef[0]), "b": float(coef[1]), "c": float(coef[2]),
           "rms_residual_W": float(np.sqrt(np.mean((A @ coef - P) ** 2))),
           "v_best_endurance_mps": float(vv[np.argmin(pf)]),
           "v_best_range_mps": float(vv[np.argmin(pf / vv)]),
           "p_min_W": float(pf.min()), "Wh_per_km_min": float((pf / vv / 3.6).min()),
           "density_kgm3": float(df["sim_rho"].mean()), "mass_kg": float(df["sim_mass_kg"].mean())}
    (out / "performance_fit.json").write_text(json.dumps(fit, indent=2), encoding="utf-8")
    fig, axs = plt.subplots(1, 3, figsize=(16, 4.8), facecolor=SURF)
    ax = axs[0]
    ax.plot(vv, pf, color=C[0], lw=1.5, label="fit a V^3 + b/V + c")
    ax.scatter(V, P, color=C[0], s=36, zorder=5, label="simulation (closed loop)")
    ax.scatter(df["sim_tas"], df["model_P_batt_W"], marker="x", color=C[1], s=50, zorder=6, label="independent model")
    _style(ax, "Battery power in level flight", "W", "true airspeed (m/s)")
    ax.legend(fontsize=8, frameon=False)
    ax = axs[1]
    ax.plot(vv, pf / vv / 3.6, color=C[0], lw=1.5)
    ax.scatter(V, df["Wh_per_km"], color=C[0], s=36, zorder=5)
    ax.axvline(fit["v_best_range_mps"], color=INK2, lw=0.8, ls="--")
    ax.annotate(f"best range {fit['v_best_range_mps']:.1f} m/s", (fit["v_best_range_mps"], ax.get_ylim()[1]),
                xytext=(4, -14), textcoords="offset points", fontsize=8, color=INK2)
    _style(ax, "Energy per km (still air)", "Wh/km", "true airspeed (m/s)")
    ax = axs[2]
    for i, (k, lab) in enumerate([("eta_prop", "propeller"), ("eta_motor", "motor"), ("eta_esc", "ESC")]):
        ax.plot(V, df[k], color=C[i], lw=1.5, marker="o", ms=4, label=lab)
    _style(ax, "Component efficiency", "efficiency (-)", "true airspeed (m/s)")
    ax.set_ylim(0.4, 1.0)
    ax.legend(fontsize=8, frameon=False)
    fig.tight_layout()
    fig.savefig(out / "performance.png", dpi=110, facecolor=SURF)
    plt.close(fig)
    return out


def _cg_z(cfg):
    """CG height (structural z, in) including the battery/payload point masses."""
    ac, b = cfg["aircraft"], cfg["powertrain"]["battery"]
    m0, mb, mp = float(ac["airframe_mass_kg"]), float(b["mass_kg"]), float(ac.get("payload_mass_kg", 0.0))
    return (m0 * 4.0 + mb * 2.0 + mp * 2.0) / (m0 + mb + mp)


def _usable_wh(cfg):
    """Energy available between full charge and the RTL reserve (Wh)."""
    from ..energy.battery import Battery
    b = Battery(cfg["powertrain"]["battery"])
    rsoc = float(cfg["mission"]["reserve"]["rtl_soc"])
    s = np.linspace(rsoc, 1.0, 500)
    v = np.interp(s, b._soc_tab, b._v_tab) * b.ns
    return float(np.trapezoid(v, s) * b.capacity_ah)
