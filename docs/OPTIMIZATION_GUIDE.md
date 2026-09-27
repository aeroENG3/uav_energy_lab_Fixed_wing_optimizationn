# Using the lab for wind-adaptive energy optimisation

The lab supports four routes into the adaptive controller, and all four share the same simulation core and logs. Every route is also available in the graphical interface (`python -m uavlab ui`); the handbook (`docs/handbook/handbook.html`, Part B9) derives the speed-to-fly theory behind them.

## 1. Offline: datasets → models → optimised settings

```bash
python -m uavlab sweep configs/experiments/airspeed_vs_wind.yaml      # 15 full flights
python -m uavlab sweep configs/experiments/monte_carlo_wind.yaml      # 40 LHS samples
```

- `dataset_runs.csv` (one row per flight) → surrogate models (GP, gradient boosting) and Bayesian optimisation of mission-level settings: cruise airspeed, altitude, TECS weights, route direction.
- `dataset_legs.csv` (one row per leg) is the most useful table for wind adaptation. Each row maps (tail-wind, cross-wind, turbulence RMS, altitude, commanded airspeed) → Wh/km. Fit `Wh/km = f(V_air, W_along, W_cross, σ_turb, h)`, then minimise it over V_air for the wind you estimate. `examples/fit_speed_to_fly.py` shows the full workflow.
- Any configuration key can be swept (`grid:` full factorial, `random:` Latin hypercube, `replicates:` for turbulence seeds). Every run keeps its full logs, config and model hash, so a dataset can be audited run by run.

**Experiment design tips**
- Use `replicates ≥ 3` when turbulence is on. Energy differences between strategies are often 2–8 %, the same order as the run-to-run spread in turbulence. Compare strategies with the *same seeds* (paired design); the seed is a column of the dataset.
- Compare legs, not whole flights, when the question is about wind. Take-off, climb and landing add a large, mostly wind-independent share.
- Keep `sensors.noise_enabled: true` for realism. Switch it off to isolate the physics.

## 2. Online: the policy slot in the autonomous layer

`autonomy.policy` is called at 50 Hz in MISSION mode with an observation. It includes SOC, battery power, TAS and ground speed, fast and slow wind estimates, tail- and cross-wind on the current leg, gust level and distance to the waypoint. The policy returns airspeed and/or altitude set-points, which TECS and L1 then fly.

```python
from uavlab.policies import Policy, register

@register("my_adaptive")
class MyAdaptive(Policy):
    def __init__(self, gain=1.0): self.gain = gain
    def update(self, obs):
        v = 15.0 - self.gain * obs["tailwind_mean"] * 0.4
        return {"airspeed_mps": v}
```

```yaml
autonomy:
  policy: {name: my_adaptive, params: {gain: 1.2}}
```

The built-in `wind_aware_best_range` policy is a physics baseline. It is the classical speed-to-fly for range in wind: `V* = argmin P(V)/V_g(V)`, where `P(V)` is the still-air battery-power fit from `python -m uavlab performance`, with optional recursive-least-squares adaptation (`online_rls: true`). Any learned or model-predictive controller should beat this baseline, not only the fixed-speed one.

## 3. Reinforcement learning

```python
from uavlab.gym_env import UAVEnergyEnv
env = UAVEnergyEnv(decision_dt_s=2.0,
                   randomize={"wind.mean.speed_mps": {"uniform": [0, 9]},
                              "wind.mean.from_deg": {"uniform": [0, 360]},
                              "wind.turbulence.model": {"choice": ["none", "dryden"]}})
```

- The action is (airspeed, altitude offset) at the autonomy layer. Take-off, approach and landing remain with the autopilot, so exploration cannot crash the aircraft through its inner loops.
- The reward is the negative battery energy per step, plus a completion bonus and an abort/crash penalty. Maximising the return minimises the energy to fly the route.
- About 20× real time per core. `examples/train_rl_sb3.py` shows PPO with Stable-Baselines3 (`pip install stable-baselines3`).

## 4. Design optimisation without code (`optimize.py`, interface page *Optimisation*)

The cross-entropy method (CEM) searches any numeric configuration keys, policy parameters included, to minimise or maximise any summary KPI. The objective is averaged over several flight conditions (for example calm, a 6 m/s westerly and a 6 m/s northerly) and seeds. Every candidate flies with the same seeds (common random numbers), so candidates are compared on identical turbulence. Constraints (`status == LANDED`, `soc_end >= 0.3`, …) add a 10⁶ penalty per violation, so feasible designs always rank first.

```python
from uavlab.optimize import run_optimisation
spec = {
  "name": "speed_law",
  "scenario": ["configs/missions/out_and_back.yaml"],
  "fixed": {"autonomy.policy.name": "linear_wind", "sim.log_rate_hz": 2},
  "variables": [{"path": "autonomy.policy.params.v0", "lo": 12, "hi": 20},
                {"path": "autonomy.policy.params.k_head", "lo": 0.0, "hi": 1.2}],
  "objective": {"kpi": "mission_Wh_per_km", "sense": "min"},
  "constraints": [{"kpi": "status", "op": "==", "value": "LANDED"}],
  "conditions": [{"label": "calm", "overrides": {"wind.mean.speed_mps": 0}},
                 {"label": "west6", "overrides": {"wind.mean.speed_mps": 6, "wind.mean.from_deg": 270}}],
  "seeds": [1, 2],
  "algorithm": {"population": 8, "elite_frac": 0.25, "iterations": 5},
  "workers": 4,
}
run_optimisation(spec)   # -> optimisations/speed_law/{evaluations.csv, generations.csv, result.json, best_run/}
```

`linear_wind` (V = v₀ + k_head·head-wind + k_cross·|cross-wind| + k_gust·σ_gust, optional altitude offset) is a parametric law made for this: the speed-to-fly theory predicts k_head ≈ 0.5–0.6 for this aircraft, and the optimiser finds it from full flights. Compare the result with `wind_aware_best_range` on the same seeds.

## Signals that matter for wind-energy work

| Signal | Column |
|---|---|
| energy per ground distance | legs `Wh_per_km`, runs `kpi.Wh_per_km` |
| wind along / across the track | `tailwind_mps`, `crosswind_mps`, legs `tailwind_mean_mps` |
| energy the wind added or removed | `P_wind_W`, `E_wind_Wh` (air-relative mechanical energy balance) |
| where the battery energy went | `P_*` loss columns and `summary.energy_breakdown_Wh` |
| propulsive efficiency at the operating point | legs `eta_prop`, `eta_drive` |
| energy-feasibility prediction | `pred_soc_landing` (decision D5) |

## Calibrating against flight data (recommended before quoting absolute numbers)

1. Fly 4–6 steady, level, constant-speed segments in calm air across the speed range. Log battery voltage and current, airspeed and altitude.
2. Run `python -m uavlab performance` with your mass, battery and motor data.
3. Adjust `aircraft.aero_calibration.cd0_scale` (high-speed power) and `cdi_scale` (low-speed power), then `powertrain.propeller.cp_scale` if the RPM disagrees, until the power curves match.
4. Commit the calibrated YAML. Every later run records its hash.
