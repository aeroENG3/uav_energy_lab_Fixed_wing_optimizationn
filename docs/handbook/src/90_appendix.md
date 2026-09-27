# Appendices

## Appendix A: Parameter reference

This table is generated from `configs/defaults.yaml` when the handbook is built, so it always matches the shipped defaults. Paths are the dotted keys used in scenario files, in `--set` overrides and in study specifications. Tags: **REP** representative (replace with your hardware), **DATA** manufacturer data, **SPEC** standard or specification, **TUNE** controller tuning.

@@PARAMS@@

## Appendix B: Log signals

### B.1 `timeseries.csv` (one row per log tick)

| Group | Columns |
|---|---|
| time and state machine | `t_s`, `mode`, `phase` (approach sub-phase), `leg`, `leg_name` |
| position | `lat_deg`, `lon_deg`, `n_m`, `e_m` (local NED from home), `alt_msl_m`, `alt_agl_m` |
| attitude and rates | `phi_deg`, `theta_deg`, `psi_deg`, `p_dps`, `q_dps`, `r_dps` |
| air data and velocity | `tas_mps`, `cas_mps`, `gs_mps`, `course_deg`, `vn_mps`, `ve_mps`, `vd_mps`, `climb_mps`, `alpha_deg`, `beta_deg`, `nz_g` |
| atmosphere | `rho_kgm3`, `T_K`, `P_pa` |
| wind (truth) | `wind_mean_{n,e,d}_mps`, `wind_turb_{n,e,d}_mps`, `wind_gust_{n,e,d}_mps`, `wind_tot_{n,e,d}_mps` (what JSBSim applied), `wind_mean_speed_mps`, `wind_mean_from_deg`, `tailwind_mps`, `crosswind_mps`, `w20_mps` |
| wind (autopilot estimate) | `wind_est_{n,e}_mps` (fast, τ = 5 s, policy input), `wind_est_mean_{n,e}_mps` (slow, τ = 60 s), `gust_sigma_est_mps` |
| commands and actuators | `cmd_{ail,elev,rud,thr,steer}` (controller output), `act_{ail,elev,rud,thr}` (after servo dynamics) |
| set-points and tracking | `phi_cmd_deg`, `theta_cmd_deg`, `h_cmd_m`, `v_cmd_mps`, `xtrack_m`, `wp_dist_m`, `pred_soc_landing` (D5), `policy_v_mps` |
| aerodynamics and propeller | `rpm`, `J`, `thrust_N`, `drag_N`, `lift_N`, `CL`, `CD` |
| electrical | `v_bus_V`, `i_batt_A`, `i_motor_A`, `v_motor_V`, `duty`, `back_emf_V`, `torque_Nm`, `esc_regime` (normal, limited, freewheel), `soc`, `v_cell_V` (1 s filtered, under load), `ocv_V` |
| power (W) | `P_batt_chem_W` (OCV·I), `P_batt_W` (terminal), `P_batt_loss_W`, `P_esc_loss_W`, `P_copper_W`, `P_iron_W`, `P_shaft_W`, `P_prop_req_W`, `P_avionics_W`, `P_thrust_W` (T·u_a), `P_drag_W` (D·V_a), `P_wind_W` |
| cumulative energy (Wh) | `E_batt_Wh`, `E_chem_Wh`, `E_batt_loss_Wh`, `E_esc_loss_Wh`, `E_copper_Wh`, `E_iron_Wh`, `E_shaft_Wh`, `E_avionics_Wh`, `E_thrust_Wh`, `E_drag_Wh`, `E_wind_Wh` |
| energy audit | `E_air_J` (½mV_a² + mgh), `closure_residual_J` |
| distance | `dist_ground_m`, `dist_air_m` |

The cumulative energies are integrated at the physics rate. The energy of any segment is the difference of the cumulative columns at its ends.

### B.2 `events.csv`

Columns are `t_s, kind, name, data` (JSON). The kinds are:

- `mode`: a mode change such as `MISSION->APPROACH`, with its reason;
- `decision`: D1–D9, with the data behind the decision;
- `waypoint`: `leg_start` and `reached`, the latter with `by = radius | passed`;
- `approach`: `align_reached`, `final`;
- `terminal`: `crash`, `timeout`.

### B.3 `legs.csv` and `phases.csv`

One row per mission leg: `leg, leg_name, course_mean_deg, t_start_s, t_end_s, duration_s, dist_ground_m, dist_air_m, E_batt_Wh, Wh_per_km, P_batt_mean_W, tas_mean_mps, gs_mean_mps, alt_agl_mean_m, tailwind_mean_mps, crosswind_mean_mps, wind_mean_speed_mps, wind_vertical_mean_mps, turb_rms_mps, throttle_mean, rpm_mean, alpha_mean_deg, eta_prop, eta_drive, E_shaft_Wh, E_thrust_Wh, E_drag_Wh, E_wind_Wh, E_avionics_Wh, xtrack_rms_m, alt_err_rms_m, tas_err_rms_mps, soc_start, soc_end`.

`phases.csv` holds the same statistics for the phases `ground, takeoff, climb, mission, approach, landing`.

### B.4 `summary.json` (main keys)

| Group | Keys |
|---|---|
| identity | `run_id`, `config_hash`, `seed`, `sim_time_s` |
| outcome | `status`, `termination`, `success`, `decisions`, `go_arounds`, `rtl_reason`, `stop.*` |
| time and distance | `flight_time_s`, `air_time_s`, `dist_ground_km`, `dist_air_km` |
| energy | `E_batt_Wh`, `E_chem_Wh`, `Wh_per_km`, `mission_E_Wh`, `mission_Wh_per_km`, `battery_capacity_Wh`, `soc_start`, `soc_end`, `min_cell_v`, `max_i_batt_A`, `max_P_batt_W`, `mean_P_batt_air_W` |
| energy breakdown (Wh) | `energy_breakdown_Wh.{battery_internal_loss, esc_loss, motor_copper_loss, motor_iron_friction_loss, shaft, thrust_useful, propeller_loss, avionics_servos, drag_work, wind_work}` |
| efficiencies | `eta.{propeller, motor, esc}` |
| tracking | `tracking.{xtrack_rms_m, xtrack_rms_steady_m, xtrack_max_m, alt_err_rms_m, alt_err_rms_steady_m, tas_err_rms_mps, tas_err_rms_steady_mps, throttle_tv_per_s}` |
| landing | `touchdown.{sink_mps, tas_mps, along_runway_m, xtrack_m}` |
| wind | `wind.{mean_speed_mps, max_speed_mps, turb_rms_mps}` |
| audit and cost | `energy_closure.{residual_J, relative}`, `wall_time_s`, `realtime_factor` |

In `dataset_runs.csv` these keys appear flattened with dots, prefixed `kpi.`. The optimiser uses the same names for objectives and constraints, for example `mission_Wh_per_km` or `touchdown.sink_mps`.

## Appendix C: Command-line reference

| Command | Purpose | Main options |
|---|---|---|
| `python -m uavlab run [files…]` | one simulation; files are merged over the defaults in order | `--set path=value` (repeatable), `--out DIR`, `--no-plot` |
| `python -m uavlab sweep SPEC` | parameter study or Monte Carlo sweep → dataset | `--out DIR` (default `sweeps`), `--workers N` |
| `python -m uavlab performance` | steady-flight performance map and P(V) fit | `--out DIR`, `--set path=value` |
| `python -m uavlab validate` | V&V suite and report | `--out DIR`, `--quick` |
| `python -m uavlab ui` | graphical interface | `--workspace DIR`, `--host`, `--port` (8050), `--no-browser` |
| `python -m uavlab config [files…]` | print the resolved configuration | `--set path=value` |

`--host 0.0.0.0` makes the interface reachable from other machines on the network. It has no authentication, so use it only on a trusted lab network.

## Appendix D: REST API reference

All endpoints accept and return JSON. The interactive documentation is at `/api/docs`. `ref` is a path relative to the workspace, for example `runs/<run_id>`.

| Method and path | Purpose |
|---|---|
| `GET /api/meta` | versions, CPU count, workspace |
| `GET /api/schema` | parameter groups, fields (unit, type, limits, tag, description), policies and their parameters |
| `GET /api/config/defaults` | the default configuration |
| `POST /api/config/validate` | validate a configuration → `{ok, errors[]}` |
| `GET /api/presets` | mission, wind, experiment and saved-scenario presets |
| `POST /api/config/apply` | apply a preset `{kind, name, config}` → new configuration |
| `GET /api/preset/raw?kind=&name=` | raw content of a preset file |
| `POST /api/scenarios/save` | save `{name, description, config}` as YAML (differences only) |
| `POST /api/config/export` | configuration → YAML text |
| `POST /api/preview/mission`, `/wind`, `/battery` | geometry, wind profile and sample, battery curve for the editor |
| `POST /api/run` | start a simulation `{config, label}` → job |
| `POST /api/sweep`, `POST /api/optimise` | start a parameter study or an optimisation (specification as in Section A8) → job |
| `POST /api/tools/performance`, `POST /api/tools/validate` | start a performance map or the V&V suite → job |
| `GET /api/jobs`, `GET /api/jobs/{id}` | job list; job detail with incremental telemetry, events, log and results (`since_row`, `since_event`, `since_log`, `since_result`) |
| `GET /api/jobs/{id}/config`, `POST /api/jobs/{id}/cancel` | configuration of a run job; cancel |
| `GET /api/runs?source=` | finished runs: `runs` (workspace) or `repo:validation_report/runs` (repository V&V runs, read-only) |
| `GET /api/run?ref=` | summary, legs, phases, events, metadata and file list of a run |
| `GET /api/run/columns?ref=`, `GET /api/run/series?ref=&cols=` | time-series column names; decimated signal data |
| `GET /api/run/config?ref=`, `GET /api/file?ref=&name=`, `POST /api/run/label` | resolved configuration; download a file; set a label |
| `GET /api/sweeps`, `GET /api/sweep?name=` | studies; study dataset |
| `GET /api/optimisations`, `GET /api/optimisation?name=` | optimisations; generations, evaluations and result |
| `GET /api/performance`, `GET /api/validation` | latest performance map; latest V&V results |

## Appendix E: Symbols and glossary

| Symbol | Meaning | Unit |
|---|---|---|
| V_a, TAS | true airspeed, $\lvert\mathbf V_a\rvert$ | m/s |
| V_g | ground speed | m/s |
| **W**, W_a, W_c, H | wind vector; tail-wind, cross-wind, head-wind component | m/s |
| W₂₀ | wind speed at 20 ft (turbulence intensity reference) | m/s |
| h | height above ground | m |
| α, β | angle of attack, sideslip | rad |
| φ, θ, ψ | roll, pitch, yaw (heading) | rad |
| p, q, r | body angular rates | rad/s |
| q̄ | dynamic pressure ½ρV_a² | Pa |
| ρ | air density | kg/m³ |
| S, b, c̄ | wing area, span, mean chord | m², m, m |
| C_L, C_D, C_m… | aerodynamic coefficients | – |
| J | propeller advance ratio V/(nD) | – |
| C_T, C_P, η_p | thrust and power coefficients, propeller efficiency | – |
| K_v | motor speed constant | rad/s/V (rpm/V in the configuration) |
| E | motor back-EMF | V |
| I₀, R_m | motor no-load current, winding resistance | A, Ω |
| d | ESC duty cycle (throttle) | – |
| OCV, SOC | open-circuit voltage, state of charge | V, – |
| R₀, R₁, C₁ | battery series resistance, polarisation resistance and capacitance | Ω, Ω, F |
| E_air | air-relative mechanical energy ½mV_a² + mgh | J |
| P_wind | wind power $-m g W_D - m\,\mathbf V_a\cdot\dot{\mathbf W}$ | W |
| STE, SEB | total specific energy, specific energy balance (TECS) | J/kg |
| L₁ | L1 guidance look-ahead distance | m |

| Term | Meaning |
|---|---|
| CEM | cross-entropy method, the derivative-free optimiser used by the lab |
| CRN | common random numbers: evaluating every candidate on the same seeds |
| D1–D9 | the autonomy layer's logged decisions (Section B13.2) |
| Dryden | turbulence model with rational spectra (MIL-F-8785C) |
| ESC | electronic speed controller |
| FAF | final approach fix, where the glide path starts |
| L1 | nonlinear path-following guidance law |
| LHS | Latin-hypercube sampling |
| OU | Ornstein–Uhlenbeck process, a mean-reverting random process |
| REP / DATA / SPEC / TUNE | provenance tags of parameters |
| RTL | return to launch (here: start the approach) |
| TECS | total energy control system |
| V&V | verification and validation |
| WOW | weight on wheels |

## Appendix F: References

1. J. S. Berndt and the JSBSim development team, *JSBSim: An open source, platform-independent, flight dynamics model in C++*, JSBSim Reference Manual; JSBSim 1.3.1, [github.com/JSBSim-Team/jsbsim](https://github.com/JSBSim-Team/jsbsim).
2. ArduPilot SITL, `Tools/autotest/aircraft/Rascal` (commit 66c8985), and the FlightGear Rascal110-JSBSim model.
3. APC Propellers, performance data file `PER3_18x8E.dat`, [apcprop.com](https://www.apcprop.com/technical-information/performance-data/).
4. M. Drela, *First-Order DC Electric Motor Model*, MIT Aero & Astro, 2007 (the QPROP motor model).
5. G. L. Plett, *Battery Management Systems, Vol. 1: Battery Modeling*, Artech House, 2015.
6. U.S. Standard Atmosphere, 1976, NOAA/NASA/USAF, NOAA-S/T 76-1562.
7. MIL-F-8785C, *Flying Qualities of Piloted Airplanes*, 1980, §3.7 (atmospheric disturbances).
8. MIL-HDBK-1797, *Flying Qualities of Piloted Aircraft*, 1997.
9. F. M. Hoblit, *Gust Loads on Aircraft: Concepts and Applications*, AIAA, 1988.
10. C. F. Van Loan, "Computing integrals involving the matrix exponential", *IEEE Trans. Automatic Control* 23(3), 1978.
11. S. Park, J. Deyst, J. P. How, "A New Nonlinear Guidance Logic for Trajectory Tracking", AIAA GNC Conference, 2004.
12. A. A. Lambregts, "Vertical Flight Path and Speed Control Autopilot Design Using Total Energy Principles", AIAA 83-2239, 1983.
13. R. W. Beard, T. W. McLain, *Small Unmanned Aircraft: Theory and Practice*, Princeton University Press, 2012.
14. B. W. McCormick, *Aerodynamics, Aeronautics, and Flight Mechanics*, 2nd ed., Wiley, 1995.
15. R. Y. Rubinstein, D. P. Kroese, *The Cross-Entropy Method*, Springer, 2004.
16. ANSI/ISA-101.01-2015, *Human Machine Interfaces for Process Automation Systems*; ISO 9241-110:2020, *Interaction principles*.
17. NASA-STD-7009A, *Standard for Models and Simulations*, 2016; ASME V&V 10-2019 and V&V 20-2009.
