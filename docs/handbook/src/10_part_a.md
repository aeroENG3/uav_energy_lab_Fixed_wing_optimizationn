# Part A: Software perspective

## A1 System overview

The lab is a **co-simulation built around JSBSim**. JSBSim integrates the six-degree-of-freedom rigid-body motion of the Rascal 110. It also computes the aerodynamic, gravity and ground-reaction forces and the propeller's thrust and torque. Every other part of the simulation is Python code in the `uavlab` package: the wind field, the mission and autonomy, the flight controllers, the servo dynamics, the electric powertrain and the energy accounting. The Python side drives JSBSim one integration step at a time through its property interface.

The package is divided into layers the same way a real UAV autopilot stack is. Every layer has one module, one configuration section and its own log columns. A result can therefore be traced to the layer that produced it, and a layer can be replaced without touching the others.

@@FIG:pipeline@@

### A1.1 Design principles

1. **One configuration object is the single source of truth.** A run is fully defined by one nested dictionary, the *resolved configuration*. It is built from `configs/defaults.yaml`, the scenario files and any overrides, and it is validated before anything runs. The simulation reads its parameters from nowhere else. The interface edits the same dictionary, the command line merges the same files, and the resolved dictionary is written into every run folder.
2. **SI units everywhere, except at the JSBSim boundary.** JSBSim works in English units: feet, slugs, pounds-force, Rankine. The conversions happen at that boundary, in `fdm.py` (the property interface) and `models.py` (the XML the lab generates). The only other English units are internal: the MIL-F-8785C turbulence formulas in `atmosphere.py` are written in feet and knots as the specification gives them, and crash detection uses the structural frame's inches. Everything else, and every log column, is SI, and each column name carries its unit (`_mps`, `_W`, `_Wh`, `_deg`).
3. **Determinism.** One integer seed (`sim.seed`) feeds a NumPy `SeedSequence`. It spawns independent streams for the wind, the sensors and the remaining random draws, and also seeds JSBSim's generator. The same configuration therefore always gives a bit-identical time series (V&V check V12). The run-to-run spread in turbulence is then a controlled experimental factor, not noise.
4. **Provenance by construction.** Every run writes the exact JSBSim XML files it flew with, the SHA-256 hash of each file, the resolved configuration, its hash, and the versions of every library. Any published number can be traced back to the model and parameters that produced it.
5. **Heavy work never runs in the interface process.** Simulations, parameter studies, optimisations and the V&V suite run in separate spawned processes. A crash or a long computation therefore never blocks the interface and never corrupts its state.
6. **Every model has a check.** Each physical block has a verification test against an analytic or independent result. The full pipeline is also validated against an independent trim model and against energy conservation (Part B14).

## A2 Package map

| Module | Layer | Responsibility | Main classes and functions |
|---|---|---|---|
| `config.py` | configuration | merge defaults, scenario files and overrides; validate; hash; diff | `load_config`, `config_from_dict`, `set_path`, `validate`, `config_hash`, `diff_from_defaults` |
| `atmosphere.py` | atmosphere | mean wind with shear, veer, schedule and slow variability; Dryden turbulence; discrete gusts | `WindField`, `WindSample`, `dryden_scales` |
| `mission.py` | mission | local frame, waypoints, runway selection, approach geometry, glide path | `Mission`, `Waypoint`, `Runway` |
| `geo.py` | mission | geodetic ↔ local NED conversion (WGS-84) | `LocalFrame` |
| `autonomy.py` | autonomy | flight-mode state machine, decisions D1–D9, landing logic, policy call | `Autopilot`, `Commands`, `Setpoints` |
| `policies.py` | autonomy | plug-in slot for adaptive and optimising controllers | `Policy`, `register`, `WindAwareBestRange`, `LinearWindPolicy` |
| `sensors.py` | autonomy | navigation-estimate errors; wind-triangle estimator | `Sensors`, `WindEstimator` |
| `control.py` | controller | L1 guidance, TECS, attitude loops, runway steering | `L1Guidance`, `TECS`, `AttitudeController`, `GroundSteering` |
| `actuators.py` | control surfaces | servo lag, rate limit, deadband; servo electrical power | `Actuator`, `ActuatorSet` |
| `models.py` | flight dynamics | generates the JSBSim aircraft, engine and propeller XML for each run | `build_model_dir`, `aircraft_xml`, `propeller_xml` |
| `fdm.py` | flight dynamics | thin JSBSim wrapper: initial conditions, inputs, state read-back, unit conversion | `FDM` |
| `energy/battery.py` | powertrain | 1-RC Thevenin LiPo pack with exact energy bookkeeping | `Battery` |
| `energy/motor.py` | powertrain | Drela first-order brushless DC motor | `Motor` |
| `energy/powertrain.py` | powertrain | ESC model and closed-form network solution; energy meters | `Powertrain`, `PowertrainSample` |
| `simulation.py` | orchestration | the step loop, energy ledger, crash detection, termination | `Simulation`, `RunResult` |
| `logger.py` | logging | time-series rows, events, output files, metadata | `RunLogger` |
| `metrics.py` | logging | per-leg and per-phase tables; summary KPIs | `leg_table`, `phase_table`, `summarize` |
| `plotting.py` | logging | run dashboard figure | `run_dashboard` |
| `batch.py` | studies | grid, Latin-hypercube and replicate sweeps; datasets | `run_sweep`, `build_jobs`, `run_one` |
| `optimize.py` | studies | cross-entropy method optimiser over any parameters | `run_optimisation` |
| `gym_env.py` | studies | Gymnasium environment for reinforcement learning | `UAVEnergyEnv` |
| `validation/performance.py` | assurance | steady-flight performance map and independent trim model | `performance_map`, `steady_flight_sim` |
| `validation/suite.py` | assurance | V&V suite and its HTML report | `run_suite`, `report_html` |
| `ui/server.py` | interface | FastAPI application: REST API and static files | `create_app`, `serve` |
| `ui/jobs.py` | interface | job manager: spawned worker processes, live telemetry | `JobManager`, `Job` |
| `ui/schema.py` | interface | parameter schema for the forms, parsed from `defaults.yaml` | `build_schema` |
| `cli.py` | interface | command line: `run`, `sweep`, `performance`, `validate`, `ui`, `config` | `main` |

Data files are in `uavlab/data/`: the original ArduPilot Rascal XML, the aircraft template, and the APC `PER3_18x8E.dat` propeller file. Configuration files are in `configs/`: `defaults.yaml`, `missions/`, `wind/` and `experiments/`.

## A3 The simulation step

`Simulation.step()` advances the whole pipeline by one physics step of `sim.dt_physics_s` (5 ms by default). The order is fixed. Each stage reads only values produced earlier in the same step, or at the end of the previous one.

@@FIG:step@@

1. **Wind.** `WindField.sample(t, h_agl, TAS, ψ, dt)` returns the mean, turbulence and gust vectors in NED. The mean goes into JSBSim's `atmosphere/wind-{north,east,down}-fps`. Turbulence plus gust goes into `atmosphere/gust-*`. JSBSim adds the two, so the aerodynamics see the total wind.
2. **Control tick** (every `n_ctrl = 1/(dt·f_ctrl)` steps; 4 at the defaults). The step converts the true state into local north/east and passes it through `Sensors.measure` (estimation errors). `Autopilot.update` then runs mode logic, decisions, the policy, guidance, TECS and the attitude loops. It returns `Commands` (aileron, elevator, rudder, steering, throttle) and `Setpoints` (for logging). Between control ticks the commands are held (zero-order hold).
3. **Actuators.** Every channel passes through saturation, deadband, first-order lag and rate limit, and goes to JSBSim as `fcs/*-cmd-norm`. Servo electrical power is computed from the surface rates.
4. **Powertrain.** The step reads the propeller speed ω from JSBSim and writes `blade-angle = clamp(RPM, 1000, 12000)/1000`, which selects the RPM column of the propeller tables (Section A6). It then solves the battery–ESC–motor network for the current throttle and writes the motor torque into JSBSim's engine input.
5. **JSBSim** `run()`. JSBSim integrates the rigid body, the aerodynamics, the landing gear and the rotor speed ODE, and computes thrust.
6. **Energy ledger.** The step integrates every mechanical power term with the trapezoidal rule at the physics rate and updates the air-relative energy balance (Section B8).
7. **Checks.** The crash check tests whether any structural point (prop tip, nose, wing tips, belly) is below the ground. The termination check looks for a terminal mode (LANDED, NO_GO, CRASHED) or the time limit.
8. **Log tick** (every `n_log` steps, and at termination). `RunLogger.row` builds one time-series row of about 110 columns from the state, the wind sample, the set-points, the powertrain sample and the ledger.

> **Why 200 Hz?** The fastest dynamics in the loop are the propeller rotor (time constant about 40 ms), the servo lag (30 ms) and the landing-gear springs. JSBSim's explicit integrators need a step well below all three. The time-step convergence check (V11) shows that halving the step changes the mission energy by less than 1 %. A larger step saves CPU but makes the gear stiff, and the configuration validator rejects steps above 20 ms.

### A3.1 Multirate timing

| Rate | Default | Configuration key | What runs |
|---|---|---|---|
| physics | 200 Hz (5 ms) | `sim.dt_physics_s` | wind sample, actuators, powertrain, JSBSim, energy ledger, crash check |
| control | 50 Hz (20 ms) | `sim.control_rate_hz` | sensors, autonomy, policy, guidance, TECS, attitude loops |
| decisions | 1 Hz | fixed | energy-reserve, geofence and energy-feasibility decisions (D4–D6) |
| logging | 10 Hz (100 ms) | `sim.log_rate_hz` | one time-series row (cumulative energies stay exact at 200 Hz) |

The control rate must divide the physics rate exactly. The validator enforces this. Cumulative energies in the log are integrated at the physics rate, so reducing the log rate (for example to 2 Hz in large studies) loses time resolution but no energy accuracy.

### A3.2 Life cycle of a run

`Simulation.__init__` → `_setup()` does the following in order:

1. It computes the step counts from the rates and spawns the random streams.
2. It writes the JSBSim model directory for this run (`build_model_dir`), loads it and sets the atmosphere (ΔT, sea-level pressure, humidity).
3. It builds `WindField`, `Mission`, `Powertrain`, `ActuatorSet`, `Sensors`, `RunLogger` and `Autopilot`, and resets the policy.
4. It makes the pre-flight decision on the 10 m surface wind: runway into wind (D1), then go or no-go (D2).
5. It places the aircraft on the runway centre line 5 m past the threshold, tail down, with the initial wind already applied.

`run()` calls `step()` until it returns `False`, then `finish()` writes the output files (Section A7) and returns a `RunResult` with the summary, status, time series and events.

```python
from uavlab import load_config
from uavlab.simulation import Simulation

cfg = load_config("configs/missions/out_and_back.yaml", "configs/wind/steady_headwind_6.yaml",
                  overrides={"mission.cruise.airspeed_mps": 18.0, "sim.seed": 3})
res = Simulation(cfg).run()               # full flight, logs in runs/<run_id>/
print(res.status, res.summary["E_batt_Wh"], res.summary["Wh_per_km"])
```

`Simulation` takes these optional arguments: `run_dir` (output folder), `policy` (a policy object that replaces the configured one), `write_logs=False` (no files, used inside optimisers), `keep_timeseries`, and the hooks `on_row(row)` and `on_event(event)`. The interface uses the hooks to stream live telemetry.

## A4 Configuration system

### A4.1 Resolution chain

@@FIG:config@@

`load_config(*files, overrides=...)` applies these steps in order:

1. **Defaults.** It reads `configs/defaults.yaml`. This file defines every key the simulation knows. A key missing from it does not exist.
2. **Scenario files**, in the order given. They are deep-merged: nested dictionaries merge key by key, and lists replace the old list. A file may `include:` other files relative to itself.
3. **Overrides.** It applies dotted-path overrides such as `{"wind.mean.speed_mps": 6}`. An unknown path raises `ConfigError`, so a typo can never be silently ignored. The only exception is keys under `*.params` (policy parameters), which are free-form.
4. **Validation.** `validate()` checks physical ranges and consistency. For example: the control rate divides the physics rate; the cruise speed is above 1.3 × the stall speed; the OCV table is monotonic; every waypoint has a position. Every problem is reported at once.
5. **Hash.** `config_hash` is the first 16 hexadecimal digits of the SHA-256 of the canonical JSON of the resolved dictionary. Two runs with the same hash flew the same configuration.

`config_from_dict(base, overrides)` does the same starting from an in-memory dictionary. The interface and the optimiser use it. `diff_from_defaults(cfg)` returns only the values that differ from the defaults, and that is what a saved scenario file contains.

### A4.2 Anatomy of `defaults.yaml`

Each key has a trailing comment that states its unit, meaning and provenance tag. The interface's schema builder (`ui/schema.py`) parses these comments. The parameter forms, units, tooltips and Appendix A of this handbook are all generated from the same file, so the documentation cannot drift from the code.

| Section | Contents |
|---|---|
| `sim` | physics step, control and log rates, time limit, seed, settle time |
| `aircraft` | masses and CG positions, inertia scale, tail-wheel steering, gear damping, aerodynamic calibration factors, limits |
| `powertrain` | propeller data and calibration, motor constants, ESC losses, battery cells and OCV table, avionics loads |
| `atmosphere` | ISA temperature offset, sea-level pressure, humidity |
| `wind` | mean wind (speed, direction, shear, veer, vertical, time schedule, slow variability), turbulence model and intensity, discrete gusts |
| `mission` | home, runway, take-off, cruise, waypoints, repeats, landing pattern, energy reserves, geofence |
| `autonomy` | policy name and parameters, wind limits, wind-estimator time constants |
| `controller` | L1, TECS, attitude and steering gains, limits |
| `actuators` | servo time constants, rate limits, deadbands |
| `sensors` | noise switch and error standard deviations |
| `logging` | output folder, CSV or Parquet, whether to keep the JSBSim files |

Provenance tags: **[SPEC]** from a standard, **[DATA]** from a manufacturer's data file, **[REP]** representative of the aircraft class (replace with your hardware), **[TUNE]** controller tuning.

### A4.3 Presets

| Folder | Kind | What loading it does in the interface |
|---|---|---|
| `configs/missions/` | mission preset | replaces the `mission` section, keeps everything else |
| `configs/wind/` | wind preset | replaces the `wind` section, keeps everything else |
| `configs/experiments/` | study specification | fills the Parameter-study form |
| `<workspace>/scenarios/` | saved scenario | replaces the whole configuration |

## A5 JSBSim integration

### A5.1 Model generation (`models.py`)

The lab does not ship a fixed aircraft file. For every run, `build_model_dir` writes a complete JSBSim model directory into `<run_dir>/jsbsim/`:

- `aircraft/rascal110_e/rascal110_e.xml`. This is the Rascal airframe filled in from the template with the configured masses, CG, inertia scale, calibration factors, gear damping and tail-wheel steering limit. The header comment lists the changes M1–M10 from the ArduPilot original (Part B3).
- `engine/lab_motor_torque_source.xml`. A JSBSim `<electric_engine>` with a nominal 10 kW rating. It is used only as a torque source (Section A6).
- `engine/lab_propeller.xml`. The propeller, whose CT and CP tables are two-dimensional in advance ratio J and RPM. They are built from the APC PER3 file with the configured `ct_scale` and `cp_scale`.

The SHA-256 of each file goes into `metadata.json`. Changing any aircraft parameter changes the XML, and so it changes the hash.

### A5.2 The property interface (`fdm.py`)

`FDM` is the only class that talks to JSBSim. It converts units on the way in and out.

| Direction | JSBSim property | Lab quantity |
|---|---|---|
| write | `atmosphere/delta-T`, `atmosphere/P-sl-psf`, `atmosphere/RH` | ISA offset (K), sea-level pressure (Pa), humidity (%) |
| write | `atmosphere/wind-{north,east,down}-fps` | mean wind, NED (m/s) |
| write | `atmosphere/gust-{north,east,down}-fps` | turbulence + gusts, NED (m/s) |
| write | `fcs/{aileron,elevator,rudder,steer}-cmd-norm` | actuator positions (−1…1) |
| write | `fcs/throttle-cmd-norm[0]` | motor power as a fraction of 10 kW (torque source) |
| write | `propulsion/engine[0]/blade-angle` | propeller speed in thousands of RPM (table column) |
| read | `position/*`, `attitude/*`, `velocities/*` | position, attitude, body rates, NED and air-relative velocity |
| read | `aero/alpha-rad`, `aero/beta-rad`, `aero/qbar-psf` | angle of attack, sideslip, dynamic pressure |
| read | `forces/fb{x,y,z}-{aero,prop,gear}-lbs` | body-axis forces per source (energy ledger) |
| read | `forces/fw{x,y,z}-aero-lbs` | drag, side force, lift (wind axes, drag and lift positive) |
| read | `propulsion/engine[0]/{propeller-rpm, thrust-lbs, advance-ratio, …}` | rotor speed, thrust, J, CT, propeller power |
| read | `atmosphere/{rho,T,P}`, `atmosphere/total-wind-*` | air state and the wind JSBSim actually applied |
| read | `gear/unit[i]/WOW` | weight on wheels per gear and structure point |

Two initialisers exist. `init_on_ground` is used for full flights: tail-dragger attitude of 14°, 1.2 ft above the gear, settled for `sim.settle_time_s` before take-off. `init_in_air` is used by the performance map and the V&V steady-flight checks. JSBSim's own milspec turbulence can be selected instead of the lab's generator through `set_jsbsim_turbulence`.

## A6 Powertrain co-simulation coupling

JSBSim's built-in electric engine turns a throttle setting into a fixed fraction of rated power. It has no battery, no motor constants, no ESC losses and no voltage sag. The lab therefore keeps JSBSim for what it does well (the propeller aerodynamics and the rotor dynamics) and computes the electrical side itself.

@@FIG:coupling@@

Each physics step runs the loop in the figure:

1. The lab reads the rotor speed ω at the end of the previous step.
2. `Powertrain.step(throttle, ω, dt)` solves battery, ESC and motor in closed form for that ω and returns the motor shaft torque Q_m (Part B5).
3. `FDM.set_motor_torque(Q_m, ω)` writes `throttle = Q_m·ω / 10 000 W`. JSBSim's electric engine converts power back to torque as P/ω, so the torque JSBSim applies is exactly Q_m. Below ω = 0.01 rad/s JSBSim divides by 1 instead of ω, and the wrapper uses the same rule.
4. `FDM.set_prop_krpm(RPM/1000)`, with the RPM clamped to the table range 1000–12000, writes the propeller's `blade-angle`. The propeller is declared variable-pitch with manual pitch, and its CT and CP tables use blade angle as the second table axis. This turns the pitch axis into an RPM axis, so JSBSim interpolates the APC data in both J and RPM. APC's coefficients do depend on RPM (Reynolds and Mach effects).
5. JSBSim integrates the rotor, I_rotor·dω/dt = Q_m − Q_prop(J, RPM), together with the airframe, and computes thrust.

The coupling is **explicit with a one-step lag**: the electrical solution uses ω from the start of the step. The rotor time constant (about 40 ms) is eight times the step, so the lag has no measurable effect. V8 checks the static run-up against an independent root-find, and V11 checks time-step convergence.

## A7 Logging and outputs

### A7.1 What a run writes

| File | Content | Produced by |
|---|---|---|
| `timeseries.csv` (or `.parquet`) | one row per log tick, about 110 columns: state, wind components, set-points, commands, electrical and mechanical powers, cumulative energies | `RunLogger.row` |
| `events.csv` | every mode change, decision (D1–D9), waypoint and terminal event, with its data as JSON | `RunLogger.event` |
| `legs.csv` | one row per mission leg: energy, Wh/km, wind along and across the track, turbulence, efficiencies, tracking errors | `metrics.leg_table` |
| `phases.csv` | the same statistics per flight phase (ground, take-off, climb, mission, approach, landing) | `metrics.phase_table` |
| `summary.json` | status, KPIs, full energy breakdown, efficiencies, touchdown, wind statistics, energy-closure residual | `metrics.summarize` |
| `metadata.json` | run id, UTC time, library versions, seed, configuration hash, model-file hashes, rates, base-model provenance | `RunLogger.metadata` |
| `config_resolved.yaml` | the full resolved configuration | `RunLogger.finish` |
| `jsbsim/` | the exact model files the run flew with | `models.build_model_dir` |
| `dashboard.png` | overview figure of the flight (runs started with `uavlab run` or from the interface) | `plotting.run_dashboard` |
| `ui_meta.json` | label and origin of runs started from the interface | `ui/jobs.py` |

Appendix B lists every time-series column. Sign conventions: NED frame; wind vectors point where the air moves *to*; `*_from_deg` is meteorological (where it blows *from*); `tailwind_mps` is positive along the ground track; `crosswind_mps` is positive when it pushes the aircraft to the right.

### A7.2 Reading outputs

```python
import json, pandas as pd
run = "runs/20260924-101500-a1b2c3"
ts   = pd.read_csv(f"{run}/timeseries.csv")
legs = pd.read_csv(f"{run}/legs.csv")
ev   = pd.read_csv(f"{run}/events.csv")
summ = json.load(open(f"{run}/summary.json"))

# energy of any segment = difference of the cumulative columns at its ends
seg = ts[(ts.t_s > 200) & (ts.t_s < 260)]
print(seg.E_batt_Wh.iloc[-1] - seg.E_batt_Wh.iloc[0], "Wh")
```

### A7.3 Hooks

`RunLogger.event` and `RunLogger.row` call `sim.on_event(event)` and `sim.on_row(row)` whenever those are set. The interface's worker process uses them to push a subset of each row (`TELEMETRY_KEYS` in `ui/jobs.py`) into a queue for the live view. The same hooks can feed a notebook plot or an external visualiser without touching the simulation code.

## A8 Studies: sweeps, optimisation, performance map, reinforcement learning

@@FIG:studies@@

### A8.1 Parameter sweeps (`batch.py`)

A sweep specification (YAML or a dictionary) names a base scenario, `fixed` overrides, a full-factorial `grid`, a Latin-hypercube `random` block (`uniform` ranges or `choice` lists) and a number of `replicates`. `build_jobs` expands it into one job per run: every grid point is combined with every random sample, and every combination is repeated `replicates` times with the seed `sim.seed = 1000·point + r + 1` (unless the specification sets `sim.seed` itself, in which case every replicate uses that seed). `run_sweep` runs the jobs on a `ProcessPoolExecutor` with the *spawn* start method. Each worker imports a fresh interpreter and JSBSim instance, so runs are independent and the results do not depend on the number of workers.

`run_one` never raises. A failed run becomes a row in `failures.csv`. Outputs:

- `runs/<run_id>/`: the full logs of every run.
- `dataset_runs.csv`: one row per run, with `param.*` for the swept values and `kpi.*` for every summary field, flattened with dots.
- `dataset_legs.csv`: one row per mission leg of every run, carrying the run parameters. This is the main table for wind–energy models.
- `sweep_spec.yaml` and `status.json`.

### A8.2 Optimisation (`optimize.py`)

The optimiser searches numeric configuration parameters, including policy parameters, to minimise or maximise any summary KPI. It uses the **cross-entropy method** (CEM):

1. Sample a population of candidates from a Gaussian N(μ, σ²) clipped to the bounds. Candidate 0 is always the current mean.
2. Evaluate every candidate on every *condition* (for example calm, 6 m/s west wind, 9 m/s north wind) and every seed. The seeds are the same for all candidates (**common random numbers**), so candidates are compared on identical turbulence and the comparison noise largely cancels.
3. The score is the mean objective over conditions and seeds, plus 10⁶ for every violated constraint or failed run. A feasible design therefore always ranks above an infeasible one.
4. Take the best `elite_frac` of the population and smooth the mean and standard deviation towards the elite statistics: μ ← (1−a)μ + a·mean(elite), σ ← max((1−a)σ + a·std(elite), σ_min).
5. Repeat for `iterations` generations, then fly the best design once more with full logs (`best_run/`).

CEM needs no gradients. It tolerates the noise turbulence puts on every evaluation, and it parallelises a whole generation at once. Outputs: `evaluations.csv` (every run), `generations.csv` (μ, σ, best and mean feasible objective per generation), `result.json` and `best_run/`.

### A8.3 Performance map (`validation/performance.py`)

`performance_map` flies the aircraft straight and level at a set of airspeeds with the real controllers and the full powertrain. It averages each speed after the transients have settled. It then solves the same operating points with an **independent algebraic trim model** that shares only the coefficient data. The outputs are the battery-power curve P(V), the fit a·V³ + b/V + c (non-negative least squares), the best-endurance and best-range speeds, and a component-efficiency table. The fit coefficients can be copied into the `wind_aware_best_range` policy (Part B9; *Performance map → Use fit in wind-aware policy* in the interface). The policy's built-in defaults come from an earlier fit of the same map and differ from the shipped fit by less than 1 %.

### A8.4 Policies and the autonomy-layer interface (`policies.py`)

A policy is a class with `update(obs) → {"airspeed_mps": …, "alt_agl_m": …}`. It is called at the control rate in MISSION mode. Missing keys leave the mission defaults unchanged. The autonomy layer clamps the outputs to safe limits: airspeed between 1.3 × stall and 0.85 × V_NE, altitude between 20 m and the geofence ceiling. Policies are registered by name with `@register("name")` and selected with `autonomy.policy.name`. Their constructor arguments become `autonomy.policy.params` and appear automatically in the interface and the optimiser.

| Policy | Purpose |
|---|---|
| `fixed` | baseline: the mission's airspeed and altitude |
| `external` | set-points written from outside, used by the Gymnasium environment and notebooks |
| `wind_aware_best_range` | physics baseline: speed-to-fly for minimum energy per ground distance, optional online RLS adaptation of P(V) |
| `linear_wind` | parametric law V = v₀ + k_head·headwind + k_cross·\|crosswind\| + k_gust·σ_gust, made for tuning with the optimiser |

Observation keys: `t, tas, gs, h, soc, p_batt, wind_ne, wind_mean_ne, gust_sigma, tailwind, crosswind, tailwind_mean, crosswind_mean, leg, leg_track, dist_to_wp, v_default, h_default`.

### A8.5 Reinforcement learning (`gym_env.py`)

`UAVEnergyEnv` is a Gymnasium environment around the full pipeline. `reset()` flies the take-off and climb, and the agent takes over at the first mission leg. Each `step(action)` advances `decision_dt_s` of simulated time (2 s by default).

- **Action:** airspeed and altitude offset, both scaled to [−1, 1].
- **Observation:** 12 normalised values: SOC, TAS, ground speed, height, mean tail- and crosswind, mean wind speed, gust level, distance to the waypoint, route fraction, battery power, current command.
- **Reward:** the negative battery energy used in the step, plus a completion bonus and a penalty for a crash or an abort.

Take-off and landing stay with the autopilot, so exploration cannot crash the aircraft through its inner loops. Wind parameters can be randomised per episode (domain randomisation).

## A9 User-interface architecture

@@FIG:ui@@

### A9.1 Server

`python -m uavlab ui` starts a FastAPI application under uvicorn, bound to `127.0.0.1:8050` by default. The server is stateless apart from the job list. Everything it produces lives in the **workspace** folder:

```text
<workspace>/
  runs/<run_id>/            single runs (same layout as the command line) + ui_meta.json
  sweeps/<name>/            parameter studies (dataset_runs.csv, dataset_legs.csv, runs/)
  optimisations/<name>/     optimisations (evaluations.csv, generations.csv, result.json, best_run/)
  performance/              latest performance map
  validation_report/        latest V&V report run from the interface
  scenarios/<name>.yaml     saved scenarios (only values that differ from the defaults)
```

A path sent by the browser is resolved against the workspace and rejected if it points outside it. Appendix D lists the REST endpoints. The interactive OpenAPI page is at `/api/docs`.

### A9.2 Job manager

Each job gets a supervising thread in the server, and the computation itself always runs in processes started with the multiprocessing *spawn* method:

| Job kind | Where the work runs | Live data |
|---|---|---|
| `run` | one child process: `Simulation(...).run()` with the `on_row` and `on_event` hooks | telemetry rows, events |
| `performance` | one child process: `validation.performance.performance_map` | log lines |
| `validate` | one child process: `validation.suite.run_suite` | log lines |
| `sweep` | `batch.run_sweep` in the supervising thread, with a spawn process pool of `workers` processes | one result row per finished run |
| `optimise` | `optimize.run_optimisation` in the supervising thread, with a spawn process pool | one row per generation |

A single-process job's child sends `("row", …)`, `("event", …)`, `("log", …)`, `("done", …)` and `("error", …)` messages through a queue. For performance and V&V jobs, the child's printed output is also redirected into the queue as log lines. The supervising thread appends the messages to the job's buffers. The browser polls `GET /api/jobs/{id}?since_row=…&since_event=…&since_log=…`, so each poll moves only new data.

A job ends as `done`, `failed` or `cancelled`. Cancelling a single-process job terminates its child. Sweeps and optimisations check a cancel flag between runs or generations, so completed work is kept.

### A9.3 Front end

The front end is a single-page application in plain JavaScript modules with no build step. It is served from `uavlab/ui/static/` and makes no calls to the internet. uPlot 1.6.31 (MIT licence) is vendored for time-series charts. Other plots (XY plots, the mission map, previews) are drawn on canvas by `charts.js` and `map.js`.

| Module | Role |
|---|---|
| `core.js` | DOM helper, API client, shared state (the configuration being edited, schema, defaults, jobs), formatting, toasts, dialogs |
| `widgets.js` | schema-driven property grid, editable tables, sortable data tables |
| `charts.js`, `map.js` | time-series and XY charts; mission map with waypoints, runway, approach and flown track |
| `app.js` | shell: navigation, toolbar (Open, Save, Validate, Run), status bar, job polling, theme |
| `pages/*.js` | one module per page: overview, scenario, live, results, compare, doe, optimise, performance, validation, jobs, handbook |

The configuration being edited is kept in the browser's local storage, so a page reload does not lose work. It is sent to the server with every run request, validated there and resolved with `config_from_dict`.

### A9.4 Interface standards

The layout follows the principles of **ISA-101** (high-performance HMI) and **ISO 9241-110** (interaction principles). It follows their principles; it is not certified against them.

- Neutral grey surfaces. Colour is reserved for status and abnormal states: green for passed or landed, amber for a warning or a modified value, red for an alarm, failure or crash, blue for running or selected. The status is always also written as text.
- Every numeric field shows its unit. A modified value is marked in the margin and can be reset to its default with one click. Values outside their limits are rejected at entry, and the message says why.
- Every parameter has the description and provenance tag from `defaults.yaml`.
- The toolbar and status bar sit in the same place on every page. The status bar shows the server connection, versions, CPU count, the running job and the workspace.
- Every long action can be cancelled, and its progress and log are visible on the Jobs page.
- Light and dark themes. Keyboard access and visible focus; Ctrl+Enter runs the scenario.

## A10 Extending the lab

| To… | Do this |
|---|---|
| add an adaptive controller | Subclass `policies.Policy`, decorate it with `@register("name")` and import it in `policies.py` or in a module imported at start-up. Its constructor parameters appear in the interface and can be optimised. |
| add a wind phenomenon | Extend `WindField.sample` in `atmosphere.py` and return it in `WindSample` (mean, turbulence or gust). Add configuration keys to `defaults.yaml` with a comment and a validation rule, and log the component in `logger.py`. |
| add an autonomous decision | Add the rule in `Autopilot.update` (`autonomy.py`). Log it with `self.ev(t, "decision", "Dn_name", **data)` so it appears in `events.csv` and the interface. |
| use your motor, battery or ESC | Change the `powertrain` values: Kv, R, I₀, cells, capacity, R₀, R₁, C₁, the OCV table, ESC losses. No code change is needed. |
| use measured propeller data | Put a PER3-format file in `uavlab/data/` and set `powertrain.propeller.data_file`. Alternatively, keep the APC data and use `ct_scale` and `cp_scale`. |
| calibrate the airframe | Set `aircraft.aero_calibration.cd0_scale`, `cdi_scale` and `cl_scale` (Section B14.4). |
| add a KPI | Compute it in `metrics.summarize`. It then appears in `summary.json`, `dataset_runs.csv` and the optimiser's objective list. |
| add a V&V check | Write a function in `validation/suite.py` that returns `_check(id, title, criterion, passed, value, …)`, call it with `do(...)` in `run_suite`, and add its id to the `order` list that sorts the report. |
| add a configuration key | Add it with a unit and description comment to `defaults.yaml`. The schema, forms and Appendix A pick it up automatically. Add labels, choices or limits in `ui/schema.py` if needed. |
| add an interface page | Add `pages/<name>.js` exporting `render(main, params)`, then register it in `PAGES` and `loaders` in `app.js`. |

## A11 Quality: tests, V&V and reproducibility

- **Unit and flight tests** (`python -m pytest -q`) cover the individual models, the control-surface sign conventions, configuration validation, a short closed-loop flight, and the interface's REST API (`tests/test_ui.py`).
- **The V&V suite** (`python -m uavlab validate`, or the Verification page) runs 19 checks, each with a pre-stated criterion (Part B14). It writes `VV_REPORT.html` with every measured value and figure.
- **Reproducibility.** A run folder holds everything needed to repeat it: `config_resolved.yaml`, the seed, the model files and their hashes, and the library versions. The command below reproduces a run bit-for-bit, and V12 checks this on every V&V run.

  ```bash
  python -m uavlab run runs/<id>/config_resolved.yaml
  ```

- **Statistics.** With turbulence on, one run is one sample. Use replicates (sweeps) or several seeds (optimiser), and compare strategies on the *same* seeds (a paired design). Energy differences between strategies are often 2–8 %, the same order as the seed-to-seed spread in moderate turbulence.
