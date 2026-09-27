"""Figures of the proof of concept (called by run_poc.py; can be re-run on its own:
python poc/poc_figures.py [poc_results])."""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

C_BASE, C_OPT = "#2a78d6", "#eb6834"          # categorical slots 1 and 2 (validated palette)
INK, INK2, GRID = "#0b0b0b", "#52514e", "#e4e3df"
plt.rcParams.update({
    "font.size": 9, "axes.titlesize": 10, "axes.labelsize": 9, "axes.edgecolor": INK2, "axes.labelcolor": INK,
    "xtick.color": INK2, "ytick.color": INK2, "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6,
    "axes.spines.top": False, "axes.spines.right": False, "legend.frameon": False, "lines.linewidth": 1.6,
    "figure.dpi": 110, "savefig.bbox": "tight", "svg.fonttype": "none", "text.color": INK,
})


def _save(fig, out: Path, name: str):
    d = out / "figures"
    d.mkdir(parents=True, exist_ok=True)
    fig.savefig(d / f"{name}.svg")
    fig.savefig(d / f"{name}.png", dpi=200)
    plt.close(fig)


def _legs(df_legs):
    return df_legs[(df_legs["leg"] >= 0) & (df_legs["duration_s"] > 5)].reset_index(drop=True)


def make_figures(out):
    out = Path(out)
    res = json.loads((out / "poc_results.json").read_text(encoding="utf-8"))
    tb = pd.read_csv(out / "baseline" / "timeseries.csv", low_memory=False)
    to = pd.read_csv(out / "optimised" / "timeseries.csv", low_memory=False)
    lb, lo = _legs(pd.read_csv(out / "baseline" / "legs.csv")), _legs(pd.read_csv(out / "optimised" / "legs.csv"))

    # ---------------------------------------------------------------- 1 ground track
    fig, ax = plt.subplots(figsize=(7.2, 2.9))
    for t, c, lab in ((tb, C_BASE, "baseline, fixed 17 m/s"), (to, C_OPT, "optimised speed law")):
        ax.plot(t["e_m"] / 1000, t["n_m"] / 1000, color=c, lw=1.4, label=lab)
    cfg_wp = [(-2.5, 0.15, "W_END"), (2.5, 0.15, "E_END"), (-2.5, -0.15, "W_END2"), (1.2, -0.15, "E_END2")]
    for e, n, name in cfg_wp:
        ax.plot(e, n, marker="o", ms=5, color=INK, zorder=5)
        ax.annotate(name, (e, n), xytext=(0, 7 if n > 0 else -12), textcoords="offset points", ha="center",
                    fontsize=8, color=INK2)
    ax.annotate("", xy=(1.95, 0.55), xytext=(2.75, 0.55), arrowprops=dict(arrowstyle="-|>", color=INK, lw=1.4))
    ax.text(2.35, 0.62, "wind from the west, 8.3 m/s at 100 m", ha="center", fontsize=8, color=INK2)
    ax.set_xlabel("east (km)"); ax.set_ylabel("north (km)")
    ax.set_aspect("equal"); ax.set_ylim(-0.8, 0.85)
    ax.legend(loc="lower left", ncol=2, fontsize=8)
    ax.set_title("Ground track: take-off to the west, four 2.5-5 km legs, straight-in landing", loc="left")
    _save(fig, out, "fig1_track")

    # ---------------------------------------------------------------- 2 signals vs distance
    fig, axs = plt.subplots(4, 1, figsize=(7.2, 7.4), sharex=True)
    for t, c, lab in ((tb, C_BASE, "baseline"), (to, C_OPT, "optimised")):
        x = t["dist_ground_m"] / 1000
        axs[0].plot(x, t["tas_mps"], color=c, lw=1.2, label=lab)
        axs[1].plot(x, t["gs_mps"], color=c, lw=1.2, label=lab)
        axs[2].plot(x, t["P_batt_W"].rolling(20, min_periods=1).mean(), color=c, lw=1.2, label=lab)
        axs[3].plot(x, t["E_batt_Wh"], color=c, lw=1.6, label=lab)
    # shade up-wind legs (baseline distances; the optimised run flies the same route)
    for _, L in lb.iterrows():
        if L["tailwind_mean_mps"] < 0:
            d0 = tb.loc[tb["t_s"] >= L["t_start_s"], "dist_ground_m"].iloc[0] / 1000
            d1 = d0 + L["dist_ground_m"] / 1000
            for a in axs:
                a.axvspan(d0, d1, color="#f1efe8", zorder=0, lw=0)
            axs[0].text((d0 + d1) / 2, 23.2, "up-wind leg", ha="center", fontsize=8, color=INK2)
    axs[0].set_ylabel("true airspeed\n(m/s)"); axs[0].set_ylim(8, 25)
    axs[1].set_ylabel("ground speed\n(m/s)")
    axs[2].set_ylabel("battery power\n(W, 2 s mean)")
    axs[3].set_ylabel("battery energy\nused (Wh)")
    axs[3].set_xlabel("ground distance flown (km)")
    axs[0].legend(loc="lower right", ncol=2, fontsize=8)
    eb, eo = tb["E_batt_Wh"].iloc[-1], to["E_batt_Wh"].iloc[-1]
    axs[3].annotate(f"{eb:.1f} Wh", (tb["dist_ground_m"].iloc[-1] / 1000, eb), xytext=(4, 2),
                    textcoords="offset points", fontsize=8, color=INK)
    axs[3].annotate(f"{eo:.1f} Wh", (to["dist_ground_m"].iloc[-1] / 1000, eo), xytext=(4, -10),
                    textcoords="offset points", fontsize=8, color=INK)
    axs[0].set_title("Same route, same wind: the optimised law flies faster up-wind and slower down-wind", loc="left")
    fig.align_ylabels(axs)
    _save(fig, out, "fig2_signals")

    # ---------------------------------------------------------------- 3 energy per km per leg
    fig, ax = plt.subplots(figsize=(7.2, 3.0))
    n = min(len(lb), len(lo))
    xs = np.arange(n)
    w = 0.36
    for off, L, c, lab in ((-w / 2 - 0.01, lb, C_BASE, "baseline"), (w / 2 + 0.01, lo, C_OPT, "optimised")):
        bars = ax.bar(xs + off, L["Wh_per_km"][:n], w, color=c, label=lab, zorder=3)
        for b_, (_, r) in zip(bars, L.iloc[:n].iterrows()):
            ax.text(b_.get_x() + b_.get_width() / 2, b_.get_height() + 0.08, f"{r['Wh_per_km']:.2f}\n{r['tas_mean_mps']:.1f} m/s",
                    ha="center", va="bottom", fontsize=7.5, color=INK)
    labels = [f"leg {i + 1}: {r['leg_name']}\n{'up-wind' if r['tailwind_mean_mps'] < 0 else 'down-wind'} "
              f"({r['tailwind_mean_mps']:+.1f} m/s)" for i, (_, r) in enumerate(lb.iloc[:n].iterrows())]
    ax.set_xticks(xs, labels, fontsize=8)
    ax.set_ylabel("energy per ground km (Wh/km)")
    ax.set_ylim(0, max(lb["Wh_per_km"].max(), lo["Wh_per_km"].max()) * 1.32)
    ax.legend(loc="upper right", ncol=2, fontsize=8)
    ax.set_title("Energy per kilometre on each leg (labels: Wh/km and mean airspeed)", loc="left")
    _save(fig, out, "fig3_legs")

    # ---------------------------------------------------------------- 4 CEM search
    od = out / "optimisation"
    ev = pd.read_csv(od / "evaluations.csv")
    gens = pd.read_csv(od / "generations.csv")
    kv, kk = "autonomy.policy.params.v0", "autonomy.policy.params.k_head"
    base_E = res["summary"]["baseline"]["mission_E_Wh"]
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(7.2, 3.1), gridspec_kw={"width_ratios": [1.15, 1]})
    feas = ev[ev["violations"] == 0]
    sc = a1.scatter(feas[kv], feas[kk], c=feas["objective_kpi"], cmap="Blues_r", s=26, edgecolor=INK2, lw=0.4, zorder=3)
    bad = ev[ev["violations"] > 0]
    if len(bad):
        a1.scatter(bad[kv], bad[kk], marker="x", color=INK2, s=22, zorder=3, label="infeasible")
    a1.plot(gens[f"mu.{kv}"], gens[f"mu.{kk}"], color=INK, lw=1.0, marker="o", ms=3, zorder=4, label="mean per generation")
    bx = res["optimised"]
    a1.plot(bx["autonomy.policy.params.v0"], bx["autonomy.policy.params.k_head"], marker="*", ms=13, color=C_OPT,
            markeredgecolor="white", zorder=5, label="best design")
    a1.plot(17.0, 0.0, marker="D", ms=6, color=C_BASE, markeredgecolor="white", zorder=5, clip_on=False,
            label="baseline (17 m/s, k = 0)")
    a1.set_xlabel("v0 (m/s)"); a1.set_ylabel("k_head (–)")
    a1.set_xlim(11.8, 20.2); a1.set_ylim(-0.03, 1.23)
    cb = fig.colorbar(sc, ax=a1, pad=0.02); cb.set_label("mission energy (Wh)", fontsize=8); cb.ax.tick_params(labelsize=7)
    a1.legend(loc="upper left", fontsize=7)
    a1.set_title("Every evaluated design", loc="left")
    g = gens["generation"] + 1
    a2.plot(g, gens["best_objective"], color=C_OPT, marker="o", ms=4, label="best in generation")
    a2.plot(g, gens["mean_feasible_objective"], color=INK2, marker="o", ms=3, lw=1.0, label="mean of feasible")
    a2.axhline(base_E, color=C_BASE, lw=1.2, ls="--")
    a2.text(g.iloc[-1], base_E, " baseline", va="bottom", ha="right", fontsize=8, color=INK)
    a2.set_xlabel("generation"); a2.set_ylabel("mission-leg energy (Wh)")
    a2.set_xticks(g)
    a2.legend(loc="center right", fontsize=7)
    a2.set_title("Convergence", loc="left")
    fig.tight_layout()
    _save(fig, out, "fig4_cem")

    # ---------------------------------------------------------------- 5 speed-to-fly physics
    ph = res["physics"]
    a, b, c = ph["fit"]["a"], ph["fit"]["b"], ph["fit"]["c"]
    H = ph["wind_at_cruise_mps"]
    V = np.linspace(11.0, 26.0, 400)
    P = a * V ** 3 + b / V + c
    md = ph.get("map_diagnostic")
    gmap = None
    if md:
        from scipy.interpolate import PchipInterpolator
        gmap = PchipInterpolator(np.array(md["speeds"]), np.array(md["P_sim_W"]))
    fig, axs = plt.subplots(1, 2, figsize=(7.2, 3.1), sharey=False)
    for ax, h, title, law, pred, key in ((axs[0], H, f"Up-wind leg (head-wind {H:.1f} m/s)", ph["law_upwind_mps"], ph["pred_upwind_mps"], "up"),
                                         (axs[1], -H, f"Down-wind leg (tail-wind {H:.1f} m/s)", ph["law_downwind_mps"], ph["pred_downwind_mps"], "down")):
        e = P / (V - h) / 3.6
        ax.plot(V, e, color=INK, lw=1.6, label="fit aV³ + b/V + c")
        f = lambda v: (a * v ** 3 + b / v + c) / (v - h) / 3.6
        if gmap is not None:
            vm = np.linspace(11.0, max(md["speeds"]), 300)
            ax.plot(vm, gmap(vm) / (vm - h) / 3.6, color=INK2, lw=1.2, ls="--", label="measured map points")
            ax.plot(md["speeds"], np.array(md["P_sim_W"]) / (np.array(md["speeds"]) - h) / 3.6, ls="none", marker="o",
                    ms=3.5, mfc="white", mec=INK2, zorder=3)
            pm = md["sim"][key]
            if abs(pm - pred) > 0.3:
                ax.axvline(pm, color=INK2, lw=0.8, ls=":")
                ax.annotate(f"map optimum {pm:.1f}", (pm, 1.0), xycoords=("data", "axes fraction"), xytext=(3, -12),
                            textcoords="offset points", fontsize=7.5, color=INK2)
        ax.plot(pred, f(pred), marker="o", ms=6, color=INK, zorder=4)
        same = abs(law - pred) < 0.3
        ax.annotate("fit optimum = optimised\n(12 m/s lower limit)" if same else f"fit optimum {pred:.1f}",
                    (pred, f(pred)), xytext=(8, 14) if same else (0, -16), textcoords="offset points",
                    ha="left" if same else "center", fontsize=7.5, color=INK)
        ax.plot(17.0, f(17.0), marker="D", ms=6, color=C_BASE, markeredgecolor="white", zorder=5)
        ax.annotate("baseline 17", (17.0, f(17.0)), xytext=(6, 6), textcoords="offset points", fontsize=7.5, color=INK)
        ax.plot(law, f(law), marker="*", ms=12, color=C_OPT, markeredgecolor="white", zorder=5)
        if not same:
            ax.annotate(f"optimised {law:.1f}", (law, f(law)), xytext=(6, 10), textcoords="offset points", fontsize=7.5, color=INK)
        ax.set_title(title, loc="left"); ax.set_xlabel("airspeed (m/s)")
        lo_, hi_ = f(np.array([pred]))[0], max(f(np.array([11.0, 26.0])))
        ax.set_ylim(lo_ * 0.93, min(hi_, lo_ * 1.6))
    axs[0].set_ylabel("battery energy per ground km (Wh/km)")
    axs[0].legend(loc="center right", fontsize=7)
    fig.tight_layout()
    _save(fig, out, "fig5_physics")

    # ---------------------------------------------------------------- 6 robustness
    rb = res.get("robustness") or []
    if rb:
        fig, ax = plt.subplots(figsize=(7.2, 2.6))
        xs = np.arange(len(rb)); w = 0.36
        vb = [r["baseline_mission_E_Wh"] for r in rb]; vo = [r["optimised_mission_E_Wh"] for r in rb]
        ax.bar(xs - w / 2 - 0.01, vb, w, color=C_BASE, label="baseline", zorder=3)
        bars = ax.bar(xs + w / 2 + 0.01, vo, w, color=C_OPT, label="optimised", zorder=3)
        for bb, r in zip(bars, rb):
            ax.text(bb.get_x() + bb.get_width() / 2, bb.get_height() + 0.6, f"−{r['saving_pct']:.1f} %",
                    ha="center", fontsize=8, color=INK)
        ax.set_xticks(xs, [f"turbulence seed {r['seed']}" for r in rb])
        ax.set_ylabel("mission-leg energy (Wh)")
        ax.set_ylim(0, max(vb) * 1.18)
        ax.legend(loc="upper right", ncol=2, fontsize=8)
        ax.set_title("Robustness: the same two designs in light Dryden turbulence the optimiser never saw", loc="left")
        _save(fig, out, "fig6_robustness")


if __name__ == "__main__":
    make_figures(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).resolve().parents[1] / "poc_results")
