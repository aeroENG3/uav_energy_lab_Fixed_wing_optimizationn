# Architecture

```
 configs/*.yaml ──► config.py (merge, validate, hash)
                          │
 ┌────────────────────────┴─────────────────────────────────────────────────────────┐
 │ simulation.py  (one physics step = 5 ms; control every 20 ms; log every 100 ms)  │
 │                                                                                  │
 │  ATMOSPHERE LAYER      atmosphere.py  WindField: mean(t,h) + Dryden + gusts ───┐ │
 │                        JSBSim US-1976 atmosphere (ΔT, p_sl, RH)                │ │
 │                                                                                ▼ │
 │  MISSION LAYER         mission.py     waypoints, runway, approach geometry       │
 │         │                                                                        │
 │  AUTONOMOUS LAYER      autonomy.py    flight-mode state machine, decisions D1-D9,│
 │         │              policies.py    policy plug-in (online optimiser / RL)     │
 │         │              sensors.py     nav-estimate errors, wind estimator        │
 │         ▼                                                                        │
 │  CONTROLLER LAYER      control.py     L1 guidance, TECS, attitude PIDs, steering │
 │         │                                                                        │
 │  CONTROL SURFACES      actuators.py   servo lag/rate/deadband + servo power      │
 │         ▼                                                                        │
 │  FLIGHT DYNAMICS       fdm.py ─► JSBSim 6-DoF (Rascal 110e, models.py builds XML)│
 │         ▲   ω                     ▲ torque                                       │
 │         └── energy/powertrain.py ─┘  battery (1-RC) ─ ESC ─ motor (Drela)        │
 │                                                                                  │
 │  ENERGY LEDGER         electrical meters + mechanical/wind energy balance        │
 │  LOGGING               logger.py, metrics.py ─► timeseries / events / legs /     │
 │                                                  phases / summary / metadata     │
 └──────────────────────────────────────────────────────────────────────────────────┘
        │                         │                               │                         │
   batch.py (sweeps,         gym_env.py (Gymnasium,         validation/ (V&V suite,     ui/ (FastAPI server,
   Monte Carlo datasets)     RL at the autonomy layer)       performance map)            job manager, web app)
   optimize.py (CEM over
   any parameters)
```

The full explanation, with figures, equations and the per-step data flow, is in the handbook: `docs/handbook/handbook.html` (Part A for software, Part B for the engineering basis).

## Step order (simulation.py `Simulation.step`)

1. **Wind**: `WindField.sample(t, h, TAS, ψ)` gives the mean, turbulence and gust vectors. The mean goes to JSBSim `atmosphere/wind-*`, turbulence plus gust to `atmosphere/gust-*`.
2. **Control tick** (every `n_ctrl` steps): state → `Sensors.measure` → `Autopilot.update` (mode logic, decisions, policy, guidance, TECS, inner loops) → surface, steering and throttle commands.
3. **Actuators**: first-order lag + rate limit + deadband → `fcs/*-cmd-norm`.
4. **Powertrain**: read propeller RPM, write `blade-angle = RPM/1000` (selects the RPM column of the propeller tables), solve battery–ESC–motor for this throttle, write motor torque as JSBSim engine power.
5. **JSBSim** `run()` — 6-DoF integration, aerodynamics, ground reactions, propeller ODE and thrust.
6. **Energy ledger** (trapezoidal, every step), crash check, termination, log row.

## Where to change things

| You want to… | Edit |
|---|---|
| change aircraft mass, CG, calibration | `aircraft:` in the scenario YAML |
| use your motor / battery / ESC | `powertrain:` (Kv, R, I0, cells, capacity, R0, OCV curve …) |
| use measured propeller data | drop a PER3-format file in `uavlab/data/`, set `powertrain.propeller.data_file` |
| add a wind phenomenon | `atmosphere.py` → add to `WindField.sample` (log it in `logger.py`) |
| add an autonomous decision | `autonomy.py` → `Autopilot.update` (log with `self.ev(...)`) |
| plug in an adaptive controller | subclass `policies.Policy`, `@register("name")`, set `autonomy.policy.name` |
| change the controller | `control.py` (gains in `controller:`) |
| new KPI | `metrics.py` |
| new V&V check | `validation/suite.py` |
| run experiments without code | `python -m uavlab ui` (see the handbook, Part C) |
| add an interface page | `uavlab/ui/static/js/pages/<name>.js` exporting `render(main, params)`; register it in `app.js` |
| add a configuration key | add it to `configs/defaults.yaml` with a `# unit, meaning [TAG]` comment: the forms and the handbook's parameter table pick it up |
