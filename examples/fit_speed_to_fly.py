"""Offline optimisation from a sweep dataset: learn Wh/km as a function of airspeed
and wind along the track from dataset_legs.csv, then find the energy-optimal
airspeed for each head/tail-wind.

    python examples/fit_speed_to_fly.py        # uses the shipped sample dataset
    # or regenerate it:  python -m uavlab sweep configs/experiments/airspeed_vs_wind.yaml
    #                    python examples/fit_speed_to_fly.py sweeps/airspeed_vs_wind/dataset_legs.csv
"""
import sys

import numpy as np
import pandas as pd

path = sys.argv[1] if len(sys.argv) > 1 else "examples/sample_dataset/airspeed_vs_wind/dataset_legs.csv"
legs = pd.read_csv(path)
legs = legs[legs["duration_s"] > 60]                      # drop short legs (mostly turns)
V, W = legs["tas_mean_mps"].to_numpy(), legs["tailwind_mean_mps"].to_numpy()
P = legs["P_batt_mean_W"].to_numpy()

# physics-shaped model: battery power depends on airspeed only (still-air polar),
# ground speed = V + W_along  ->  Wh/km = P(V) / (V + W) / 3.6
A = np.c_[V ** 3, 1 / V, np.ones_like(V)]
# non-negative least squares keeps the parasite, induced and fixed-load terms physical
from scipy.optimize import nnls
coef, _ = nnls(A, P)
pred = A @ coef
print(f"P(V) = {coef[0]:.4f} V^3 + {coef[1]:.1f}/V + {coef[2]:.1f}   (RMS {np.sqrt(np.mean((pred - P) ** 2)):.1f} W, "
      f"{len(P)} legs)")
vv = np.linspace(11, 26, 301)
Pv = coef[0] * vv ** 3 + coef[1] / vv + coef[2]
print("\n tail-wind (m/s)   optimal airspeed (m/s)   Wh/km at optimum   Wh/km at 17 m/s")
for w in (-8, -6, -4, -2, 0, 2, 4, 6, 8):
    whkm = Pv / np.maximum(vv + w, 0.5) / 3.6
    i = int(np.argmin(whkm))
    w17 = (coef[0] * 17 ** 3 + coef[1] / 17 + coef[2]) / (17 + w) / 3.6
    print(f"   {w:+5.1f}              {vv[i]:5.1f}                    {whkm[i]:5.2f}             {w17:5.2f}")
