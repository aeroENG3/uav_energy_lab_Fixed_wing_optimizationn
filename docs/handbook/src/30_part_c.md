# Part C: Working in the user interface

## C1 Layout and conventions

Start the interface with `python -m uavlab ui`. It opens `http://127.0.0.1:8050`. Every page has the same frame:

- **Toolbar (top).**
  - **Open preset** loads a mission preset, a wind preset, a saved scenario, or resets to defaults.
  - **Save scenario** writes the scenario as YAML.
  - **Validate** runs the server-side range and consistency checks.
  - **Run simulation** starts a full flight (also Ctrl+Enter).
  - The scenario name shows **● edited** when there are unsaved changes, and a count of how many parameters differ from the defaults.
- **Navigation (left)**, in the order of an experiment:
  - Set up: *Overview*, *Scenario*.
  - Run & analyse: *Live run*, *Results*, *Compare runs*.
  - Studies: *Parameter study*, *Optimisation*, *Performance map*.
  - Assurance: *Verification & validation*, *Jobs*, *Handbook*.

  Badges show running jobs and the number of runs selected for comparison.
- **Status bar (bottom).** Server connection, versions, CPU cores, the running job with its progress, and the workspace folder.

**Reading the screen.** Surfaces are neutral grey. Colour appears only where it carries meaning, and the state is always also written as text:

| Colour | Meaning |
|---|---|
| green | passed, landed, done |
| amber | warning, modified value, go-around |
| red | alarm, failed, crashed, no-go, invalid input |
| blue | running, selected, the command or set-point in a chart |

Numbers are right-aligned in tabular figures and always carry their unit. A value you changed is marked in the left margin. **↺** resets it to its default, and its tooltip shows the default. Each parameter shows its description and provenance tag (**REP**, **DATA**, **SPEC**, **TUNE**; Section A4.2). Invalid input is outlined in red with the reason, and is not accepted into the scenario.

## C2 Setting up a scenario

1. **Pick a starting point.** On *Overview*, each template combines a mission preset and a wind preset:
   - survey in calm air;
   - survey in gusty wind;
   - head-wind/tail-wind legs;
   - wind that strengthens;
   - endurance to reserve;
   - strong-wind stress case.

   **Load** opens it in the editor, and **Load and run** starts it at once. Alternatively, use **Open preset** in the toolbar and combine any mission with any wind.
2. **Edit on the Scenario page.** The tabs follow the configuration sections:

| Tab | What you set | Tools |
|---|---|---|
| Mission | waypoints, repeats, cruise speed and height, runway, take-off, landing pattern, reserves, geofence | **map**: *Add waypoint* then click; *Select / move* then drag; Delete removes the selected waypoint; *Fit*. The waypoint table accepts exact values; airspeed and radius per waypoint are optional. The map shows the runway, approach points and a scale. |
| Wind | reference speed and direction, shear law, veer, vertical wind, time schedule, slow variability, turbulence model and intensity, discrete gusts | **preview**: the mean-wind profile with height, and a seeded 300 s sample of the wind at cruise height. |
| Atmosphere | ISA offset, sea-level pressure, humidity | |
| Aircraft | masses and stations, inertia scale, aerodynamic calibration, limits, gear | |
| Powertrain | propeller calibration, motor, ESC, battery cells, OCV table, avionics loads | **preview**: pack OCV against SOC; total energy and energy usable down to the RTL reserve; nominal voltage, R₀, R₁, τ; specific energy; all-up mass |
| Autonomy & policy | policy and its parameters (with its documentation), wind limits, wind-estimator time constants | |
| Controller | L1, TECS, attitude, steering and throttle-shaping gains | |
| Actuators & sensors | servo time constants, rate limits, deadbands; sensor-noise switch and levels | |
| Simulation & logging | physics step, control and log rates, time limit, seed, output format | |

3. **Search.** The *Search all parameters* box at the top of the page matches paths, labels and descriptions across every tab. For example, type `soc` to find every state-of-charge setting. **Export YAML** downloads the scenario (only values that differ from the defaults).
4. **Validate.** Press **Validate** in the toolbar. The same checks run before every simulation, and every problem is listed at once.
5. **Save.** **Save scenario** writes `<workspace>/scenarios/<name>.yaml` with only the values that differ from the defaults. It reappears under *Open preset → Saved scenarios* and runs from the command line unchanged.

> The configuration you are editing is kept in the browser between sessions. A reload does not lose it, but only **Save** makes it a file.

## C3 Running and monitoring a flight

Press **Run simulation**. The *Live run* page shows:

- the flight mode and progress;
- key figures: simulated time, true airspeed, altitude, battery power, SOC, energy used, distance;
- the track on the map, coloured by flight phase;
- charts of altitude against command, speed against command, and battery power and SOC;
- a log of every mode change and decision (D1–D9) with its data.

**Stop** terminates the run at once. A stopped run writes no log files, because the logs are written when a run ends. To shorten a run instead, lower `sim.t_max_s`. When the run finishes, **Open results** goes to its result page. A 7-minute mission simulates in about 20 s.

## C4 Analysing results

*Results* lists every finished run in the workspace: label, status, wind, turbulence, policy, cruise speed, flight time, energy, Wh/km and final SOC. The V&V runs shipped with the repository are listed separately. Click a run to open it:

| Tab | Content |
|---|---|
| Summary | key figures; **where the battery energy went** (battery loss, ESC, motor copper and iron, propeller loss, useful thrust work, avionics and servos); wind work; efficiencies; tracking and landing statistics; autonomy decisions and the reason for return; configuration hash; energy-balance residual; the dashboard image |
| Plots | preset plot groups (flight path, energy, powertrain, wind, aerodynamics) or any custom set of signals. Ctrl/Shift-click to pick several; each gets its own chart. |
| Map | the flown track with waypoints, runway and touchdown point |
| Legs | energy, Wh/km, airspeed, ground speed, tail- and cross-wind, turbulence, propeller efficiency and wind work per mission leg, plus a chart of energy per km against mean tail-wind |
| Events | the full event log |
| Files | every file of the run folder for download |

**Load configuration** copies the run's exact configuration back into the editor, so you can repeat or vary it. **Add a label** names the run for tables and comparisons.

**Compare runs.** Tick runs on *Results* (or use **Add to compare**), then open *Compare runs*. You get a KPI table with differences to the first run (the baseline), a list of the parameters that differ between the runs, and overlaid signals.

## C5 Parameter studies (design of experiments)

*Parameter study* turns the current scenario into a dataset.

1. Optionally load an experiment preset from `configs/experiments/`.
2. Add **factors**. Pick any numeric, choice or on/off parameter, including the current policy's parameters, and choose a kind:
   - *list of values* or *linear range*: these form a full-factorial grid;
   - *random uniform* or *random choice*: Latin-hypercube samples, crossed with the grid.
3. Set **replicates** (seeds per point, needed when turbulence is on), **parallel workers**, and the **log rate**. 2–5 Hz is enough for studies, and the energies stay exact.
4. Check the run count and the estimated duration, then press **Start study**. Progress and each finished run appear live. **Stop** keeps the finished runs.
5. Explore the dataset: each run with its parameters and KPIs, and a response chart of any KPI against any factor, grouped by another. Click a run to open its full results. The CSV datasets (`dataset_runs.csv`, `dataset_legs.csv`) are in the study folder for offline modelling.

## C6 Optimisation

*Optimisation* finds the parameter values that minimise or maximise a KPI over several flight conditions.

1. **Decision variables.** Pick any numeric parameters with lower and upper bounds, and mark integers.
2. **Objective.** Pick a KPI, for example mission-leg energy per km, total battery energy, flight time, cross-track RMS or touchdown sink rate. Choose minimise or maximise.
3. **Constraints.** Every run must satisfy them. The default is `status == LANDED`. Add, for example, `soc_end >= 0.3`.
4. **Conditions.** The objective is the mean over these. Each condition is a wind preset or a set of overrides. Using several winds makes the result robust, instead of tuned to one case.
5. **Seeds, population, generations, workers.** Every candidate flies with the same seeds (common random numbers). Cost = population × generations × conditions × seeds runs.
6. **Start optimisation.** The convergence chart shows the best and mean feasible objective per generation, and the table lists every evaluation. **Stop after this generation** ends cleanly.
7. **Apply best design to scenario** copies the result into the editor. **Open verification run** shows the best design flown with full logs.

> **Recipe: tune a wind-adaptive speed law.**
> 1. On *Scenario → Autonomy & policy*, select `linear_wind`.
> 2. Load the head-wind/tail-wind template.
> 3. In *Optimisation*, add the variables `autonomy.policy.params.v0` (12–20) and `autonomy.policy.params.k_head` (0–1.2).
> 4. Set the objective to *mission-leg energy per km*, minimise, with conditions such as calm, a 6 m/s westerly and a 6 m/s northerly.
> 5. Compare the result with `wind_aware_best_range` on the same seeds.

## C7 Performance map

*Performance map* flies straight-and-level at 8 airspeeds (3 in quick mode) with the full pipeline, and solves the same points with the independent trim model. It shows:

- battery power against airspeed with the fit a·V³ + b/V + c;
- energy per km;
- component efficiencies (propeller, motor, ESC);
- the operating-point table (RPM, α, L/D, duty, current, endurance, range);
- best-endurance and best-range speeds.

**Use fit in wind-aware policy** copies (a, b, c) into the `wind_aware_best_range` policy of the current scenario. Re-run the map whenever you change mass, aerodynamics, propeller, motor or battery.

## C8 Verification & validation, Jobs

*Verification & validation* shows the latest check results (19 checks). **Run quick suite** uses shorter statistical tests, for a check after small changes. **Run full suite** uses the reference settings and takes about 10–25 minutes depending on the CPU. **Open full report** shows the HTML report with every criterion, value and figure. Re-run the suite after any change to the models.

*Jobs* lists every job of the session with its state, progress and log, and lets you cancel it or jump to its results.

## C9 From the interface to code and back

| In the interface | Equivalent outside it |
|---|---|
| Save scenario | `<workspace>/scenarios/<name>.yaml` → `python -m uavlab run <file>` |
| Run simulation | `python -m uavlab run …` or `Simulation(cfg).run()` |
| Parameter study | `python -m uavlab sweep <spec.yaml>` or `batch.run_sweep(spec)` |
| Optimisation | `optimize.run_optimisation(spec)`; the spec is saved as `spec.yaml` in the result folder |
| Performance map | `python -m uavlab performance` |
| Verification & validation | `python -m uavlab validate [--quick]` |
| Results, Compare | the run folders: `timeseries.csv`, `legs.csv`, `summary.json`, … |

Everything the interface produces is an ordinary file in the workspace. Nothing is stored only in the browser or the server, so notebooks, scripts and other tools can pick up any result.

## C10 Typical experiments

1. **How much does wind cost?** Load *Survey in calm air*. In *Parameter study*, set `wind.mean.speed_mps` to 0, 3, 6, 9 and `wind.mean.from_deg` to 0, 90, 180, 270, with 2 replicates and turbulence on. Chart Wh/km against wind speed, grouped by direction.
2. **Best cruise speed in each wind.** Head-wind/tail-wind template. Grid `mission.cruise.airspeed_mps` 13–23 against `wind.mean.speed_mps` 0–9. Use `dataset_legs.csv` to fit Wh/km(V, tail-wind). This reproduces the speed-to-fly table in Section B9.2.
3. **Does the adaptive policy help?** Run the same route and wind with `fixed` and with `wind_aware_best_range`, using the same seed. Compare the two runs and look at mission-leg energy and wind work.
4. **Energy-reserve logic.** *Endurance to reserve* with a strong wind. Watch D4/D5 on the Live page, and read `pred_soc_landing` in the Plots tab.
5. **Calibration against flight data.** Section B14.4, using *Performance map* and the aircraft and powertrain tabs.
6. **Dataset for reinforcement learning.** Use the Gymnasium environment (Section A8.5) with the wind randomised over the ranges of your parameter study, and compare the trained policy with the baselines in the interface through the `external` policy or a registered policy.
