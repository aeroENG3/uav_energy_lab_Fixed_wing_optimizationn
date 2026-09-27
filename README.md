# UAV Energy Lab (`uavlab`)

A Python simulation lab for **energy-consumption studies and wind-adaptive optimisation** of a
fixed-wing electric UAV. The flight dynamics come from **JSBSim** (Rascal 110). An electric powertrain
co-simulation (battery → ESC → motor → propeller) sits around it, together with a full autonomy stack
that flies complete missions from take-off to full stop. Every run produces audit-ready logs made for
optimisation work.

```
ATMOSPHERE  ─►  MISSION  ─►  AUTONOMY (decisions, policy)  ─►  CONTROLLER  ─►  CONTROL SURFACES  ─►  JSBSim 6-DoF
 ISA+ΔT, RH     waypoints     modes, reserve / wind / go-around   L1 + TECS +      servo lag, rate,       Rascal 110e
 shear, veer    runway,       energy-feasibility prediction,      attitude PIDs    deadband, power         ▲  ω │ torque
 schedule, OU   approach      plug-in adaptive policy / RL                                                 │    ▼
 Dryden, gusts                                                                          battery (1-RC) ─ ESC ─ motor (Drela)
                                  ──►  logs: time series · events · per-leg · per-phase · summary · metadata  ──►  optimisation
```

## Graphical interface (every experiment without touching code)

```bash
python -m pip install -r requirements.txt
python -m uavlab ui
```

It opens `http://127.0.0.1:8050` in your browser. `python -m uavlab ui --workspace <folder>` keeps runs, studies and scenarios in another folder.

| Page | What you do there |
|---|---|
| Overview | start from a template (calm survey, gusty wind, head-/tail-wind legs, strengthening wind, endurance, strong wind) |
| Scenario | edit every parameter with units, limits, provenance tags and reset-to-default: mission map with drag-and-drop waypoints, wind profile preview, battery curve, policy and its parameters |
| Live run | watch the flight: mode, track, altitude/speed against command, battery power, SOC, decisions |
| Results / Compare | KPIs, where the battery energy went, signals, legs, events, files; side-by-side comparison with differences |
| Parameter study | grid and Latin-hypercube designs with replicates, run in parallel, response charts, CSV datasets |
| Optimisation | minimise or maximise any KPI over several wind conditions with constraints (cross-entropy method, common random numbers) |
| Performance map | power curve, best-endurance and best-range speeds, component efficiencies, fit for the wind-aware policy |
| Verification & validation | run the V&V suite and read the report |
| Handbook | the engineering handbook (below) |

The interface follows ISA-101 / ISO 9241-110 principles: neutral surfaces, colour only for status, units on every value, visible modified values, cancellable long jobs. Every result is an ordinary file in the workspace, and a saved scenario runs unchanged from the command line.

## Proof of concept: optimisation in a head-wind

`python poc/run_poc.py` (or open `poc/run_poc.py` in an IDE and press Run) runs the complete proof of concept:
1. a baseline flight at a fixed 17 m/s in a 6 m/s westerly;
2. the cross-entropy optimiser tuning a wind-adaptive speed law $V = v_0 + k_{head} H$ in exactly the same condition;
3. the optimised flight;
4. a robustness check in unseen turbulence;
5. a physics cross-check;
6. six pre-stated pass/fail criteria.

Results go to `poc_results/`. The step-by-step guide, which explains the autonomy, the flight-dynamics model, the logs and criteria, the simulation process and the optimisation, is **`docs/poc/POC_GUIDE.pdf`**. `--quick` runs a smaller search, and `--resume` completes an interrupted run.

## Handbook

`docs/handbook/handbook.html` (also at `/handbook` in the interface) explains the lab from three sides:
- **software**: architecture, per-step data flow and timing, configuration, JSBSim coupling, logs, studies, interface;
- **aerospace engineering**: frames, 6-DoF, aerodynamics, propeller, motor/ESC/battery, atmosphere, wind and turbulence, energy equations, speed-to-fly in wind, L1, TECS, autonomy and landing, V&V and limits;
- **interface workflows**, plus the full parameter reference, log signals, CLI and REST references.

Sources are in `docs/handbook/src/*.md`; rebuild with `cd tools/handbook && npm install && npm run build`.

## Quick start (command line)

Run the commands **one at a time**, from the repository folder, in this order. Each line is a complete
command (no line continuations), so the same lines work in PowerShell, cmd and bash.

**Windows (PowerShell), first time:**

```powershell
cd $HOME\Documents\uav_energy_lab
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m pytest -q
python -m uavlab ui
```

If `Activate.ps1` is blocked, run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once, or skip the
virtual environment and install into your normal Python. Use `python -m pytest`, not `pytest`: it works even
when the Scripts folder is not on your PATH. Python 3.10 to 3.13 (64-bit) is supported.

**Linux / macOS:** the same commands, with `source .venv/bin/activate` to activate the environment.

**From an IDE (PyCharm, VS Code, Spyder):** open **`run_ui.py`** and press Run; the interface opens in the
browser. For command-line tasks, run **`run_lab.py`** with the command in the run configuration's
*Parameters* field (for example `run configs/missions/survey_box.yaml configs/wind/gusty.yaml`). Do not press
Run on files inside `uavlab/`: they are parts of a package, and running one alone fails with
*"attempted relative import with no known parent package"*. In PyCharm you can also create a run
configuration with *Module name* `uavlab`, *Parameters* `ui` and the repository as working directory.

**Other commands** (the interface runs all of them too):

| Command | What it does | Time (4 cores) |
|---|---|---|
| `python -m uavlab run configs/missions/survey_box.yaml configs/wind/gusty.yaml` | one full flight → `runs/<run_id>/` (time series, events, legs, phases, summary, metadata, dashboard.png) | ≈ 30 s |
| `python -m uavlab run configs/missions/out_and_back.yaml configs/wind/steady_headwind_6.yaml --set autonomy.policy.name=wind_aware_best_range --set sim.seed=3` | the same with the wind-aware policy; every `--set path=value` overrides one parameter | ≈ 1 min |
| `python -m uavlab sweep configs/experiments/airspeed_vs_wind.yaml` | 15 full flights → dataset for offline optimisation in `sweeps/` | ≈ 5 min |
| `python -m uavlab performance` | power curve, best-range and best-endurance speeds | ≈ 2 min |
| `python -m uavlab validate --quick` | V&V suite with shorter statistics (`validate` alone: full suite, ≈ 10–25 min) → `validation_report/VV_REPORT.html` | ≈ 5–7 min |
| `python -m pytest -q` | automated tests | ≈ 30 s |

A 7-minute mission simulates in about 20–30 s (≈ 20× real time per core).

## What is modelled

| Layer | Implementation | Details |
|---|---|---|
| Atmosphere | JSBSim US-1976 (ΔT, sea-level pressure, humidity) | `atmosphere:` |
| Wind | mean wind + power/log shear + veer + time schedule + Ornstein–Uhlenbeck variability; Dryden turbulence (MIL-F-8785C, the lab's exact discrete generator or JSBSim's); 1-cosine / ramp gusts; vertical wind | `wind:`, `configs/wind/*.yaml` |
| Mission | waypoints (local N/E or lat/lon, per-waypoint altitude/speed), repeats, runway, straight-in approach with glide path, reserves, geofence | `mission:`, `configs/missions/*.yaml` |
| Autonomy | mode machine PREFLIGHT → TAKEOFF_ROLL → ROTATE → CLIMB_OUT → MISSION → APPROACH → FLARE → ROLLOUT → LANDED (+ GO_AROUND); decisions D1–D9 (runway into wind, go/no-go, reserve RTL, **wind-aware energy-feasibility prediction**, geofence, go-around/bounce, battery cut-off, gust-corrected approach speed); **policy plug-in** | `autonomy.py`, `policies.py` |
| Controller | L1 path following, TECS energy control with complementary airspeed filter, PID attitude loops with airspeed scheduling, turn coordination, runway steering, turn anticipation | `controller:` |
| Control surfaces | servo lag, rate limit, deadband, saturation; servo electrical power | `actuators:` |
| Flight dynamics | JSBSim 6-DoF, Rascal 110 (ArduPilot/FlightGear model, changes documented M1–M10) | `docs/MODEL_CARD.md` |
| Energy | APC 18x8E propeller data CT/CP(J, RPM); Drela motor model; averaged ESC with losses, current limit, freewheeling; 1-RC LiPo with OCV(SOC), polarisation, cut-off; avionics and servo loads; **complete energy ledger**, including the wind-power term | `powertrain:` |

## Outputs (per run)

`timeseries` (≈110 columns: state, wind components, set-points, electrical and mechanical power, cumulative energies), `events` (every mode change and decision with the reason and data behind it), `legs` (energy and wind per mission leg, the main table for wind–energy models), `phases`, `summary.json` (KPIs and energy breakdown), `metadata.json` (versions, seed, config hash, SHA-256 of the JSBSim files), `config_resolved.yaml`, `jsbsim/` (exact model files). Any run can be reproduced bit-for-bit. See `docs/LOG_SCHEMA.md`.

## Interfaces for optimisation (`docs/OPTIMIZATION_GUIDE.md`)

1. **Offline:** `uavlab sweep` runs grid, Latin-hypercube and replicate designs over any config key → `dataset_runs.csv` and `dataset_legs.csv`. The shipped sample `examples/sample_dataset/airspeed_vs_wind/` holds 15 full flights (5 airspeeds × 3 wind speeds). `examples/fit_speed_to_fly.py` learns from it that the energy-optimal airspeed rises from about 14 m/s in still air to about 20 m/s in an 8 m/s head-wind. In the 13 m/s / 8 m/s-wind case the autonomy layer aborted the mission on its own (D5, energy insufficient).
2. **Online:** subclass `policies.Policy` and return airspeed/altitude set-points from wind and energy observations. `wind_aware_best_range` (speed-to-fly in wind, with optional RLS adaptation) is the physics baseline.
3. **RL:** `uavlab.gym_env.UAVEnergyEnv` (Gymnasium; `check_env` clean). The agent acts at the autonomy layer with domain randomisation of the wind. See `examples/train_rl_sb3.py`.

## Verification & validation (`python -m uavlab validate`)

The suite writes `VV_REPORT.html` / `.md` with every criterion, the measured value and figures. The shipped report is in `validation_report/`.
It covers the atmosphere against the 1976 tables, wind injection, Dryden variance and spectra, gust shape, the battery / motor / ESC equations and power balance, and the propeller co-simulation against an independent root-find. It checks steady flight of the full pipeline against an **independent trim model**, and mechanical energy closure in wind (< 0.1 % of gross work). It also covers time-step convergence, bit-exact reproducibility, full flights in 8 wind scenarios, **head-wind/tail-wind leg energy against the analytic ground-speed prediction**, and parameter sensitivity.

**Results of this version (19/19 checks passed):**

| Evidence | Result |
|---|---|
| Atmosphere vs 1976 tables | ≤ 0.001 % error in T, p, ρ (0–11 km) |
| Dryden generator vs MIL-F-8785C | σ within 1 %, spectrum within 0.02 dB |
| Propeller/motor co-simulation vs independent root-find | 0.006 % |
| Full pipeline vs independent trim model, 11–25 m/s | battery power ≤ 2.2 %, RPM ≤ 0.4 %, α ≤ 0.03° |
| Mechanical energy closure over full flights in wind | residual ≤ 5·10⁻⁵ of gross work |
| Halving the time step | total energy changes 0.02 % |
| Head-/tail-wind legs vs `E = P(V_a)·d / V_g` | within 1.6 % (6.5 vs 2.2 Wh/km) |
| Full flights, 8 wind scenarios + 8 turbulence seeds | all take off, fly the mission and land on the runway |
| Wind-aware speed-to-fly vs fixed 17 m/s (same wind, same seed) | 6.4 % less mission energy |
| What to calibrate first (±10 % → cruise power) | CD0 ±5.7 %, mass ±5.6 %, motor I0 (±30 %) ±4.3 %, prop CP (±5 %) ±4.2 % |

Still-air performance of the default configuration: best-range speed ≈ 14.1 m/s (3.11 Wh/km), cruise at 17 m/s ≈ 201 W (3.29 Wh/km), 6.15 kg all-up, 6S 10 Ah.

## Limits you should know (details in `docs/MODEL_CARD.md`)

- The aerodynamic data are those of a SITL/hobby model, not wind-tunnel data. Relative comparisons (strategy A vs B in the same wind) are more reliable than absolute Wh. **Calibrate** `cd0_scale`, `cdi_scale` and `cp_scale` from a few steady flight-log segments before quoting endurance (procedure in the optimisation guide).
- The motor, ESC and battery parameters are *representative* of a 110-size / 6S setup. Replace them with your hardware's datasheet or bench data; every such value is tagged `[REP]` in `configs/defaults.yaml`.
- The model has no prop-wash over the tail, no ground effect, no thermals and no temperature effects on the battery or motor. Sensors have noise but no bias or latency.
- `configs/wind/moderate_turbulence_stress.yaml` (gusts reaching the cruise speed) is outside the aircraft's envelope, and crashes there are expected. Use it to test abort logic.

## Repository layout

```
uavlab/            simulation.py (orchestrator), atmosphere.py, mission.py, autonomy.py, policies.py,
                   control.py, actuators.py, sensors.py, fdm.py, models.py (JSBSim XML builder),
                   energy/ (battery, motor, powertrain), logger.py, metrics.py, batch.py, optimize.py,
                   gym_env.py, plotting.py, cli.py, validation/ (suite.py, performance.py),
                   ui/ (server.py, jobs.py, schema.py, static/ single-page app), data/ (APC file, aircraft)
configs/           defaults.yaml (every parameter documented), missions/, wind/, experiments/
docs/              handbook/ (handbook.html + Markdown sources), MODEL_CARD.md, ARCHITECTURE.md,
                   LOG_SCHEMA.md, OPTIMIZATION_GUIDE.md
run_ui.py          start the interface (IDE-friendly: open and press Run)
run_lab.py         run any lab command from an IDE
tools/handbook/    handbook build (figures generator, Markdown + KaTeX → one HTML page)
examples/          quickstart.py, custom_policy.py, fit_speed_to_fly.py, train_rl_sb3.py
tests/             pytest (unit verification, short flights, Gymnasium contract, interface REST API)
validation_report/ V&V report of this version, performance map, example runs
```

## Licensing note

uPlot (`uavlab/ui/static/vendor/`) is MIT-licensed; its licence file is included. The Rascal base model (`uavlab/data/aircraft/`) comes from ArduPilot (GPLv3), derived from FlightGear (GPL). The APC performance file belongs to APC Propellers and is used here as published data. Choose the lab's own licence with those in mind.
#   u a v _ e n e r g y _ l a b _ F i x e d _ w i n g _ o p t i m i z a t i o n n  
 #   F i x e d - w i n g - U A V - e n e r g y - o p t i m i z a t i o n -  
 