"""Plug an adaptive controller into the autonomous layer and compare it with the
fixed-speed baseline on the same route, wind and seed (paired comparison).

    python examples/custom_policy.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from uavlab import load_config
from uavlab.policies import Policy, register
from uavlab.simulation import Simulation


@register("headwind_gain")
class HeadwindGain(Policy):
    """Toy adaptive law: add k * head-wind to the best-range speed (MacCready-style)."""

    def __init__(self, v0=14.5, k=0.45, v_min=12.0, v_max=24.0):
        self.v0, self.k, self.v_min, self.v_max = v0, k, v_min, v_max

    def update(self, obs):
        head = -obs["tailwind_mean"]
        return {"airspeed_mps": min(max(self.v0 + self.k * head, self.v_min), self.v_max)}


files = ["configs/missions/out_and_back.yaml", "configs/wind/steady_headwind_6.yaml"]
for name in ("fixed", "wind_aware_best_range", "headwind_gain"):
    cfg = load_config(*files, overrides={"autonomy.policy.name": name, "sim.seed": 11})
    s = Simulation(cfg, write_logs=False).run().summary
    print(f"{name:24s} {s['status']:7s} mission legs {s['mission_E_Wh']:6.2f} Wh   total {s['E_batt_Wh']:6.2f} Wh "
          f"  {s['flight_time_s']:6.0f} s")
