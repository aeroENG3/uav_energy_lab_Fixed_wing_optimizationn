"""Standard run dashboard (matplotlib, PNG). One measure per axis; legends for
multi-series panels; a fixed categorical colour order."""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

C = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"]
SURF, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"
MODE_COLORS = {"TAKEOFF_ROLL": C[1], "ROTATE": C[1], "CLIMB_OUT": C[3], "MISSION": C[0],
               "APPROACH": C[2], "GO_AROUND": C[7], "FLARE": C[4], "ROLLOUT": C[6]}


def _style(ax, title, ylabel=None, xlabel="time (s)"):
    ax.set_facecolor(SURF)
    ax.set_title(title, loc="left", fontsize=10, color=INK, fontweight="bold")
    if ylabel:
        ax.set_ylabel(ylabel, color=INK2, fontsize=9)
    if xlabel:
        ax.set_xlabel(xlabel, color=INK2, fontsize=9)
    ax.grid(True, color=GRID, lw=0.6)
    ax.tick_params(colors=INK2, labelsize=8)
    for s in ax.spines.values():
        s.set_color(GRID)


def run_dashboard(run_dir: str | Path, out: str | Path | None = None) -> Path:
    run_dir = Path(run_dir)
    f = run_dir / "timeseries.csv"
    df = pd.read_csv(f, low_memory=False) if f.exists() else pd.read_parquet(run_dir / "timeseries.parquet")
    summ = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    ev = pd.read_csv(run_dir / "events.csv")
    t = df["t_s"]
    fig, axs = plt.subplots(4, 2, figsize=(15, 15), facecolor=SURF)
    fig.suptitle(f"Run {summ['run_id']}  -  status {summ['status']}  -  "
                 f"{summ.get('E_batt_Wh', 0):.1f} Wh, {summ.get('Wh_per_km') or float('nan'):.2f} Wh/km, "
                 f"SOC {summ.get('soc_start', 0):.2f} -> {summ.get('soc_end', 0):.2f}",
                 x=0.01, ha="left", fontsize=12, color=INK)

    ax = axs[0, 0]
    for mode, g in df.groupby((df["mode"] != df["mode"].shift()).cumsum()):
        md = g["mode"].iloc[0]
        if md in MODE_COLORS:
            ax.plot(g["e_m"], g["n_m"], color=MODE_COLORS[md], lw=1.6)
    for md in [m for m in MODE_COLORS if m in set(df["mode"])]:
        ax.plot([], [], color=MODE_COLORS[md], lw=2, label=md)
    try:
        cfg = __import__("yaml").safe_load((run_dir / "config_resolved.yaml").read_text(encoding="utf-8"))
        wps = [w for w in cfg["mission"]["waypoints"] if "n_m" in w]
        ax.scatter([w["e_m"] for w in wps], [w["n_m"] for w in wps], s=40, marker="s", color=INK,
                   zorder=5, label="waypoints")
        for w in wps:
            ax.annotate(w.get("name", ""), (w["e_m"], w["n_m"]), xytext=(4, 4), textcoords="offset points",
                        fontsize=8, color=INK2)
    except Exception:
        pass
    ax.set_aspect("equal", adjustable="datalim")
    _style(ax, "Ground track by flight mode", "north (m)", "east (m)")
    ax.legend(fontsize=7, frameon=False, loc="best")

    ax = axs[0, 1]
    ax.plot(t, df["alt_agl_m"], color=C[0], lw=1.5, label="altitude AGL")
    ax.plot(t, df["h_cmd_m"], color=C[1], lw=1.2, ls="--", label="commanded")
    _style(ax, "Altitude", "m AGL")
    ax.legend(fontsize=8, frameon=False)

    ax = axs[1, 0]
    ax.plot(t, df["tas_mps"], color=C[0], lw=1.5, label="true airspeed")
    ax.plot(t, df["gs_mps"], color=C[2], lw=1.2, label="ground speed")
    ax.plot(t, df["v_cmd_mps"], color=C[1], lw=1.2, ls="--", label="commanded airspeed")
    _style(ax, "Speed", "m/s")
    ax.legend(fontsize=8, frameon=False)

    ax = axs[1, 1]
    ax.plot(t, df["P_batt_W"], color=C[0], lw=1.2)
    _style(ax, "Battery output power", "W")

    ax = axs[2, 0]
    ax.plot(t, df["soc"] * 100, color=C[0], lw=1.5)
    _style(ax, "Battery state of charge", "%")

    ax = axs[2, 1]
    wt = np.hypot(df["wind_tot_n_mps"], df["wind_tot_e_mps"])
    ax.plot(t, wt, color=C[0], lw=0.8, label="total horizontal wind")
    ax.plot(t, df["wind_mean_speed_mps"], color=C[1], lw=1.5, label="mean wind at aircraft")
    ax.plot(t, np.hypot(df["wind_est_n_mps"], df["wind_est_e_mps"]), color=C[2], lw=1.2, label="autopilot estimate")
    _style(ax, "Wind", "m/s")
    ax.legend(fontsize=8, frameon=False)

    ax = axs[3, 0]
    ax.plot(t, df["phi_deg"], color=C[0], lw=1.2, label="roll")
    ax.plot(t, df["phi_cmd_deg"], color=C[1], lw=1.0, ls="--", label="roll command")
    _style(ax, "Roll attitude", "deg")
    ax.legend(fontsize=8, frameon=False)

    ax = axs[3, 1]
    eb = summ.get("energy_breakdown_Wh", {})
    keys = ["thrust_useful", "propeller_loss", "motor_copper_loss", "motor_iron_friction_loss", "esc_loss",
            "battery_internal_loss", "avionics_servos"]
    labels = ["thrust work (useful)", "propeller loss", "motor copper loss", "motor iron/friction",
              "ESC loss", "battery internal loss", "avionics + servos"]
    vals = [eb.get(k, 0.0) for k in keys]
    y = np.arange(len(keys))[::-1]
    ax.barh(y, vals, color=C[0], height=0.6)
    for yi, v in zip(y, vals):
        ax.text(v, yi, f"  {v:.2f} Wh", va="center", fontsize=8, color=INK)
    ax.set_yticks(y, labels)
    ax.set_xlim(0, max(vals + [1]) * 1.3)
    _style(ax, "Where the battery energy went", None, "Wh")
    fig.tight_layout(rect=(0, 0, 1, 0.97))
    out = Path(out) if out else run_dir / "dashboard.png"
    fig.savefig(out, dpi=110, facecolor=SURF)
    plt.close(fig)
    return out
