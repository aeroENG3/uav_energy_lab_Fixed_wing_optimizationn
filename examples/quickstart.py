"""Run one full flight (take-off -> survey -> landing) in gusty wind and print the energy summary.

    python examples/quickstart.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from uavlab import load_config
from uavlab.plotting import run_dashboard
from uavlab.simulation import Simulation

cfg = load_config("configs/missions/survey_box.yaml", "configs/wind/gusty.yaml",
                  overrides={"sim.seed": 7})
res = Simulation(cfg).run()
run_dashboard(res.run_dir)
s = res.summary
print(json.dumps({k: s.get(k) for k in ("status", "flight_time_s", "E_batt_Wh", "Wh_per_km", "soc_end",
                                        "energy_breakdown_Wh", "touchdown", "decisions")}, indent=2))
print("logs and dashboard.png in", res.run_dir)
