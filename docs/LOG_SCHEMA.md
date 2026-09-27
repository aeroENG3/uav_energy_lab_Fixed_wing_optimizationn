# Log schema

Every run writes one folder (default `runs/<run_id>/`). Units are in the column names.
Sign conventions: NED frame (north, east, down); wind vectors point where the air
moves *to*. Wind direction `*_from_deg` is meteorological (where it blows *from*).
`tailwind_mps` is positive along the ground track, and `crosswind_mps` is positive when it pushes the aircraft to the right.

## timeseries.csv / .parquet (one row per log tick, default 10 Hz)

| Group | Columns |
|---|---|
| time & state machine | `t_s`, `mode`, `phase` (approach sub-phase), `leg`, `leg_name` |
| position | `lat_deg`, `lon_deg`, `n_m`, `e_m` (local NED from home), `alt_msl_m`, `alt_agl_m` |
| attitude & rates | `phi_deg`, `theta_deg`, `psi_deg`, `p_dps`, `q_dps`, `r_dps` |
| air data & velocity | `tas_mps`, `cas_mps`, `gs_mps`, `course_deg`, `vn_mps`, `ve_mps`, `vd_mps`, `climb_mps`, `alpha_deg`, `beta_deg`, `nz_g` |
| atmosphere | `rho_kgm3`, `T_K`, `P_pa` |
| wind (truth) | `wind_mean_{n,e,d}_mps`, `wind_turb_{n,e,d}_mps`, `wind_gust_{n,e,d}_mps`, `wind_tot_{n,e,d}_mps` (what JSBSim applied), `wind_mean_speed_mps`, `wind_mean_from_deg`, `tailwind_mps`, `crosswind_mps`, `w20_mps` |
| wind (autopilot estimate) | `wind_est_{n,e}_mps` (fast, τ = 5 s), `wind_est_mean_{n,e}_mps` (slow, τ = 60 s), `gust_sigma_est_mps` |
| commands & actuators | `cmd_{ail,elev,rud,thr,steer}` (controller output), `act_{ail,elev,rud,thr}` (after servo dynamics) |
| set-points & tracking | `phi_cmd_deg`, `theta_cmd_deg`, `h_cmd_m`, `v_cmd_mps`, `xtrack_m`, `wp_dist_m`, `pred_soc_landing` (decision D5), `policy_v_mps` |
| aerodynamics & propeller | `rpm`, `J`, `thrust_N`, `drag_N`, `lift_N`, `CL`, `CD` |
| electrical | `v_bus_V`, `i_batt_A`, `i_motor_A`, `v_motor_V`, `duty`, `back_emf_V`, `torque_Nm`, `esc_regime` (normal / limited / freewheel), `soc`, `v_cell_V` (1 s filtered, under load), `ocv_V` |
| power (W) | `P_batt_chem_W` (OCV·I), `P_batt_W` (terminal), `P_batt_loss_W`, `P_esc_loss_W`, `P_copper_W`, `P_iron_W`, `P_shaft_W`, `P_prop_req_W`, `P_avionics_W`, `P_thrust_W` (T·u_air), `P_drag_W` (D·V_air), `P_wind_W` |
| cumulative energy (Wh) | `E_batt_Wh`, `E_chem_Wh`, `E_batt_loss_Wh`, `E_esc_loss_Wh`, `E_copper_Wh`, `E_iron_Wh`, `E_shaft_Wh`, `E_avionics_Wh`, `E_thrust_Wh`, `E_drag_Wh`, `E_wind_Wh` |
| energy audit | `E_air_J` (½ m V_air² + m g h), `closure_residual_J` |
| distance | `dist_ground_m`, `dist_air_m` |

**Wind power** `P_wind_W = −m g W_down − m V_air·dW/dt`. It is the rate at which the wind field adds mechanical energy to the aircraft in the air-relative frame: updrafts, and flying through shear or gusts. It is the term that wind-exploiting strategies (gust soaring, dynamic soaring, shear use) try to make positive. The balance `dE_air/dt = F·V_air + P_wind` is checked every run (`closure_residual_J`).

All cumulative energies are integrated at the physics rate (200 Hz), not the log rate. The energy of any segment is the difference of the cumulative columns at its ends.

## events.csv

`t_s, kind, name, data(JSON)`. Kinds are `mode` (e.g. `MISSION->APPROACH`), `decision` (D1…D9 with the data behind the decision), `waypoint`, `approach` and `terminal`.

| Decision | Meaning |
|---|---|
| D1_runway | runway direction chosen (into wind) |
| D2_go / D2_no_go / D2_abort_takeoff | wind limits and take-off abort |
| D4_rtl_soc / D4_land_now_soc / D4_rtl_cell_voltage | energy reserve |
| D5_energy_insufficient | predicted SOC at touchdown (route remaining, estimated mean wind, measured cruise power) below the minimum |
| D6_geofence | geofence breach |
| D7_go_around | unstable approach (cross-track, low, long) |
| D8_battery_depleted | battery cut-off in flight, so a glide approach follows |
| D9_gust_approach_speed | approach speed increased by half the estimated gust factor |

## legs.csv (one row per mission leg)

`leg, leg_name, course_mean_deg, t_start_s, t_end_s, duration_s, dist_ground_m, dist_air_m, E_batt_Wh, Wh_per_km,
P_batt_mean_W, tas_mean_mps, gs_mean_mps, alt_agl_mean_m, tailwind_mean_mps, crosswind_mean_mps, wind_mean_speed_mps,
wind_vertical_mean_mps, turb_rms_mps, throttle_mean, rpm_mean, alpha_mean_deg, eta_prop, eta_drive, E_shaft_Wh,
E_thrust_Wh, E_drag_Wh, E_wind_Wh, E_avionics_Wh, xtrack_rms_m, alt_err_rms_m, tas_err_rms_mps, soc_start, soc_end`

This is the main table for wind–energy studies. Each row is one sample of (wind along and across the track, turbulence, airspeed, altitude) → energy per km.

## phases.csv

The same statistics per flight phase: `ground, takeoff, climb, mission, approach, landing`.

## summary.json

Status and termination reason, decisions, flight and air time, distances, battery energy (Wh), Wh/km, SOC start/end, minimum cell voltage, peak current and power, the energy breakdown (battery, ESC, copper and iron losses, shaft, thrust work, propeller loss, avionics, drag work, wind work), average efficiencies, tracking statistics (including steady-state values that exclude turn transients), touchdown (sink rate, position on the runway), wind statistics, energy-closure residual, wall time and real-time factor.

## metadata.json

`run_id`, UTC time, versions of uavlab / JSBSim / Python / NumPy / SciPy / pandas, platform, `config_hash`, seed, the SHA-256 of each JSBSim XML file used, time steps and the provenance of the base model. `config_resolved.yaml` and `jsbsim/` hold the exact configuration and model files. Any run can be reproduced bit-for-bit from its folder.

## Sweep datasets

`dataset_runs.csv`: one row per run. It holds `run_id, point, replicate, seed`, the swept parameters as `param.*` and every summary KPI as `kpi.*` (nested keys flattened with dots).
`dataset_legs.csv`: every leg of every run with the same run parameters. `failures.csv` lists any run that raised an error.
