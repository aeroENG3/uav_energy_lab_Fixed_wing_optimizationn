# Model card: Rascal 110 electric (uavlab)

This card lists what every model in the lab is based on, what was changed, which
parameters are published data and which are representative, and where the
models stop being valid. The evidence that each model is implemented correctly
is in the V&V report (`python -m uavlab validate`).

Status tags used in `configs/defaults.yaml`:
**[SPEC]** from a standard or specification · **[DATA]** from a manufacturer data file ·
**[REP]** representative value for this class of aircraft (replace it with your measured hardware) ·
**[TUNE]** controller tuning.

---

## 1. Airframe and aerodynamics (JSBSim)

| Item | Value | Source |
|---|---|---|
| Base model | ArduPilot SITL `Tools/autotest/aircraft/Rascal/Rascal.xml` (commit 66c8985), derived from the FlightGear Rascal110-JSBSim | shipped unmodified as `uavlab/data/aircraft/Rascal_ArduPilot_original.xml` |
| Wing area / span / MAC | 10.57 ft² (0.982 m²) / 9.17 ft (2.80 m) / 1.15 ft | base model (matches the Sig Rascal 110 kit: 110 in span, 1522 in²) |
| Aspect ratio | 7.96 | derived |
| Inertia (Ixx, Iyy, Izz) | 1.95, 1.55, 1.91 slug·ft² | base model; `aircraft.inertia_scale` scales them |
| Mass | airframe 4.80 kg [REP] + battery 1.35 kg [REP] = 6.15 kg | lab config (base model: 13 lb + 1.5 lb of fuel = 6.58 kg) |
| Lift | CL(α) table: 0.25 at α=0, slope ≈ 5.0 /rad, CLmax 1.40 at 13.2° | base model |
| Drag | CD0(α) table (0.028 at α=0), induced K = 0.040 (e ≈ 1.0), sideslip and elevator terms | base model (+ fix M5) |
| Moments | Cmα −0.5, Cmq −12, Cmα̇ −7, Cmδe −0.5, Cnβ 0.12, Clβ −0.1, Clp −0.4, Cnr −0.15, … | base model |

**Changes made to the base model (all in the generated XML header of every run):**

| # | Change | Why |
|---|---|---|
| M1 | Fuel tank removed; battery is a point mass | electric aircraft |
| M2 | Empty weight = `aircraft.airframe_mass_kg` | battery mass is a separate, configurable item |
| M3 | Engine = JSBSim `<electric_engine>` used as a torque source | motor physics is computed by the lab's powertrain (section 2) |
| M4 | Propeller = APC 18x8E data, 2-D in (J, RPM) | the base 18x8 table is an Aero-Matic estimate peaking at only ~39 % efficiency, which would roughly double the energy use |
| M5 | Drag due to elevator uses the absolute value of deflection | the base model used a signed value, so negative elevator *reduced* drag |
| M6 | Tail wheel steerable ±30° (was castering) | on the real aircraft the tail wheel is linked to the rudder; needed for autonomous ground roll |
| M7 | STRUCTURE contact points (prop tip, nose, wing tips, belly) | crash detection |
| M8 | Calibration factors `cd0_scale`, `cdi_scale`, `cl_scale` | fit the model to flight-test data |
| M9 | Network `<input port>` removed | not needed |
| M10 | Landing-gear damping 100 → 10 lbf/(ft/s) | the base value (damping ratio ≈ 6) is numerically unstable with 200 Hz explicit integration on a 6 kg aircraft and made it bounce on the ground; 10 gives a damping ratio ≈ 0.5, typical of spring-wire gear |

**Validity and limitations**
- The aerodynamic data are those of a hobby/SITL model. They are not wind-tunnel or flight-test derived. The results are internally consistent (V&V V9), but absolute energy numbers carry the uncertainty of CD0 and K. Comparisons between strategies (e.g. airspeed A vs B in the same wind) are more trustworthy than absolute Wh. Calibrate `cd0_scale` and `cdi_scale` from a few steady-speed flight-log segments before quoting absolute endurance.
- There is no propeller slipstream over the tail, so the tail lifts late on the take-off roll (at about 11 m/s). There is no ground effect and there are no flaps.
- The post-stall table is coarse (α > 13°). The autopilot keeps above 1.1·Vs, and results that spend time near stall should not be trusted.
- The weathercock term `Cndi` in the base model is a constant yaw moment (tail incidence), so the rudder and sideslip carry a small trim. It contributes about 1–2 % extra drag at high speed, which is the main source of the V9 difference.

## 2. Electric powertrain (lab co-simulation)

Chain: battery → ESC → motor → propeller (JSBSim). Each 5 ms step the lab reads the propeller speed ω from JSBSim and solves the electrical network in closed form. It then hands the motor torque to JSBSim, which integrates `I·dω/dt = Q_motor − Q_prop(J, RPM)` and computes thrust.

| Block | Model | Parameters |
|---|---|---|
| Propeller | APC 18x8E performance file `PER3_18x8E.dat` [DATA], tables CT(J, RPM), CP(J, RPM) for 1000–12000 RPM, bilinear interpolation. The RPM axis is carried through JSBSim's `blade-angle` (manual pitch mode). Rows with J > 0.64 (windmilling) are linear extrapolations. | D = 18 in, rotor inertia 0.0014 kg·m² [REP], `ct_scale`/`cp_scale` calibration |
| Motor | Drela first-order DC model: E = ω/Kv, I = (Vm − E)/R, Q = (I − I0)/Kv | Kv 295 rpm/V, R 25 mΩ, I0 1.8 A, 70 A limit [REP]. This is the 110-size class used on 6S with an 18x8. |
| ESC | averaged switch: Vm = d·Vbus − I·R_esc; losses I²R_esc + k_sw·Vbus·I + P_q; current limiting; freewheel diode (no regen by default) | 3 mΩ, 1 %, 0.3 W [REP] |
| Battery | 1-RC Thevenin: V = N_s·OCV(SOC) − I·R0 − V1, coulomb counting, exact discretisation, filtered low-voltage cut-off | 6S1P 10 Ah, R0 2.5 mΩ/cell + 4 mΩ wiring, R1 1.5 mΩ/cell, τ = 30 s, typical LiPo OCV curve [REP] |
| Avionics | constant 6 W + servos (0.25 W idle each + 0.004 W per deg/s of motion) | [REP] |

**Notes**
- APC data are computed by the manufacturer (blade-element/vortex theory), not measured. Independent wind-tunnel tests of APC propellers generally show somewhat lower efficiency than APC's predictions. If you have measured data (e.g. from the UIUC Propeller Database or your own thrust stand), put it in a PER3-format file or use `cp_scale`/`ct_scale`.
- The motor model has no temperature dependence (winding resistance rises about 0.4 %/K). Iron loss is lumped into I0, which is constant by default; `i0_voltage_exponent` makes it speed-dependent.
- The battery has no temperature or ageing dynamics beyond `capacity_derate`. The OCV curve is a generic LiPo curve; replace it with a pulse-test curve of your cells for absolute SOC accuracy.

## 3. Atmosphere and wind

| Item | Model | Reference |
|---|---|---|
| T, p, ρ | JSBSim U.S. Standard Atmosphere 1976, ISA offset ΔT, sea-level pressure, relative humidity | V&V V1: matches the 1976 tables to 0.001 % |
| Mean wind | reference speed/direction + power-law (α = 1/7) or log-law (z0) shear, veer with height, steady vertical wind, time schedule, Ornstein–Uhlenbeck slow variability | standard boundary-layer profiles |
| Turbulence | Dryden, MIL-F-8785C low-altitude scales and intensities (L_w = h, L_u = L_v = h/(0.177+0.000823h)^1.2, σ_w = 0.1·W20), exact discrete-time implementation, axes aligned with the mean wind | MIL-F-8785C §3.7; MIL-HDBK-1797 |
| Turbulence (alternative) | JSBSim's built-in MIL-spec Dryden (`jsbsim_milspec`), which includes rotational gust terms | JSBSim FGWinds |
| Gusts | 1-cosine (full) and ramp-and-hold, any direction including vertical | MIL-F-8785C discrete gust |

**Limits:** the lab's Dryden generator uses the low-altitude form. Heights are clamped to 10–1000 ft as the specification prescribes, and there are no rotational turbulence terms. Thermals and terrain-induced flow are not modelled.

## 4. Guidance, control and autonomy

The controller layer has these parts:
- L1 lateral guidance (Park, Deyst & How 2004, in its ArduPilot form).
- TECS total-energy speed/height control (Lambregts 1983, ArduPilot structure) with a complementary airspeed filter (pitot + IMU) and glide-path feed-forward.
- PID attitude loops with airspeed gain scheduling (capped at 2× at low speed), turn coordination and yaw damping.
- Ground steering on the runway (rudder + steerable tail wheel).

The mission phases are take-off (tail-up roll, rotation), climb-out, the waypoint mission with turn anticipation, and return. A straight-in approach follows with a glide path and a gust-corrected approach speed (D9). Then comes an exponential flare with power assist against down-gusts, and a wheel-landing roll-out. If the aircraft bounces, it re-flares, or goes around when it bounces higher than 2 m (D7). Decisions D1–D9 are listed in `uavlab/autonomy.py` and logged in `events.csv`.

Landing performance is characterised statistically (V&V V17: 8 turbulence seeds). In turbulence, touchdowns are firm and a bounce followed by a re-flare is common. This is typical of a light tail-dragger with spring gear, whose main wheels sit ahead of the CG. The autoland is good enough to close every flight for energy accounting, but it is not tuned for gentle landings.

Sensors are modelled as navigation-estimate errors (first-order Gauss–Markov, as an EKF output would look) plus white noise on the gyros and accelerometers. There is no bias, latency or GPS dropout.

## 5. Numerical scheme

JSBSim at 200 Hz (default integrators), control at 50 Hz, logging at 10 Hz (configurable). Powertrain–propeller coupling is explicit, with a one-step lag. The rotor time constant is about 40 ms, far above the 5 ms step. Halving the step changes total mission energy by < 1 % (V&V V11). The mechanical energy balance closes to < 0.1 % of the gross work over a full flight (V10).
