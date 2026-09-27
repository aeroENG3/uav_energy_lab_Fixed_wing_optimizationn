<!-- Source of docs/poc/POC_GUIDE.pdf. {{key:fmt}} values and @@...@@ blocks are filled from
     poc_results/ by tools/poc_guide/prepare.py; do not type result numbers by hand. -->

@@COVER@@

# Summary

**Question.** Can an optimisation method, applied to the autonomy layer of the UAV, reduce the battery energy needed to fly a mission in a head-wind? The comparison must be made on the same aircraft model, in the same wind and with the same random seed.

**Experiment.** The Rascal 110 electric UAV flies the same out-and-back mission twice in a steady 6 m/s westerly wind, which is {{wind_h:.1f}} m/s at the 100 m cruise height. The mission has two up-wind legs and two down-wind legs.

- **Baseline:** the aircraft flies the mission's fixed cruise speed of 17 m/s on every leg.
- **Optimised:** the autonomy layer flies a wind-adaptive speed law, $V = v_0 + k_{head}\,H$, where $H$ is the head-wind the aircraft estimates in flight. The lab's **cross-entropy optimiser** (CEM) chooses the two parameters $v_0$ and $k_{head}$. It flew {{n_opt_flights:d}} complete simulated flights, from take-off to full stop, to find them.

**Result.** The optimiser found $v_0$ = {{v0:.2f}} m/s and $k_{head}$ = {{k:.3f}}. The aircraft now flies {{law_up:.1f}} m/s into the wind and {{law_down:.1f}} m/s with the wind.

- **Mission-leg energy:** it fell from **{{base.mission_E_Wh:.2f}} Wh to {{opt.mission_E_Wh:.2f}} Wh ({{saving:.1f}} % less)**.
- **Whole flight** (take-off to stop): {{saving_total:.1f}} % less energy.
- @@CRITSUMMARY@@

**Conclusion.** @@CONCLUSION@@

**How to reproduce.** From the repository folder, run `python poc/run_poc.py`, or open `poc/run_poc.py` in an IDE and press Run. It takes about {{wall_min:.0f}} minutes on the 2-core machine used for this report, and less on a 4–8 core PC. Section 6 gives the step-by-step guide, including a route through the graphical interface that needs no code.

# 1 The proof of concept at a glance

## 1.1 Hypothesis

In a head-wind the ground speed drops, so each kilometre takes longer and costs more energy. Classical flight mechanics predicts that the energy per kilometre is minimised by flying **faster into the wind and slower with the wind** (the speed-to-fly principle, Section 5.5). The hypothesis is:

> A wind-adaptive airspeed law whose parameters are found by the lab's optimiser, using only simulated flights, uses measurably less battery energy than the fixed cruise speed. This holds on the same route, in the same wind, with the same aircraft and the same random seed.

## 1.2 Experimental design

Only one thing differs between the two flights: the rule that sets the airspeed. Everything else is identical and fixed by configuration.

| Item | Baseline | Optimised |
|---|---|---|
| Aircraft, powertrain, controllers | Rascal 110e, defaults | identical |
| Mission | `out_and_back`: legs to W_END, E_END, W_END2, E_END2 at 100 m | identical |
| Wind | steady 6 m/s from 270° at 10 m, power-law shear (α = 1/7) | identical |
| Random seed (sensor noise) | 1 | 1 |
| Airspeed rule (autonomy policy) | `fixed`: 17 m/s | `linear_wind`: $V = v_0 + k_{head} H$, clamped to 12–26 m/s |
| How the rule was chosen | mission default | cross-entropy optimisation, {{n_opt_flights:d}} flights |

The steady wind makes the comparison deterministic: running the same flight again gives the same numbers (V&V check V12). So a single paired comparison is valid, and no averaging is needed. To make sure the result is not an artefact of that idealised wind, step 4 repeats both designs in light Dryden turbulence with three seeds the optimiser never saw.

## 1.3 Success criteria (fixed before the experiment)

@@T:criteria_def@@

## 1.4 Why this design is valid and fast

- **Controlled.** One factor changes, and every other input is identical, including the random numbers (common random numbers).
- **Complete flights.** Each evaluation is a full take-off-to-full-stop flight with all autonomy decisions active. The saving is therefore not a steady-state estimate.
- **Independent checks.** The simulation is checked against physics (C4, using the performance map, which is an independent model). The optimum is checked against unseen conditions (C5). The energy bookkeeping is checked against conservation of energy (C2).
- **Cheap.** {{n_total_flights:d}} flights in total. The optimiser flies each generation in parallel on all CPU cores.

# 2 The autonomous layer: its logic and how it is simulated

## 2.1 Where autonomy sits

The lab mirrors a real autopilot stack. The **autonomous layer** decides *what* to do: which flight phase, which waypoint, whether there is enough energy, and which airspeed and height to fly. The **controller layer** decides *how*: which bank angle, pitch angle and throttle achieve it. The control surfaces and the JSBSim flight dynamics then produce the motion. The autonomy never sees the true state, only sensor measurements with realistic errors.

@@FIG:pipeline@@

## 2.2 Flight phases (mode machine)

The autonomy is a state machine. Each mode has its own guidance targets, and each transition has an explicit condition that is logged with its reason.

@@FIG:modes@@

| Mode | What the autonomy does | Leaves when |
|---|---|---|
| PREFLIGHT | settles 2 s on the gear; decides runway and go/no-go (D1, D2) | armed |
| TAKEOFF_ROLL | full throttle in 1.5 s; steers on the centre line; tail up at 6 m/s | 13 m/s → ROTATE (abort after 25 s or at the runway end) |
| ROTATE | pitches up to 9° at 6°/s | 3 m above the ground |
| CLIMB_OUT | full power, speed priority at 14 m/s | 25 m → MISSION |
| MISSION | flies the legs; **calls the policy every 20 ms for airspeed and height** | last waypoint, or an energy/safety decision |
| APPROACH | flies to the align point, joins the centre line, follows a 6° glide path | 3 m → FLARE |
| FLARE, ROLLOUT | exponential flare, wheel landing, stops on the runway | ground speed < 0.5 m/s → LANDED |

## 2.3 Decisions

Every decision is a rule with a measurable condition. The decisions that matter in a head-wind are highlighted.

| ID | Rule | Action | Role in this PoC |
|---|---|---|---|
| **D1** | runway heading with the largest head-wind | choose runway | take-off and landing to the west (into wind) |
| **D2** | 10 m wind > 13 m/s or cross-wind > 6 m/s | refuse flight / abort take-off | 6 m/s: go |
| D3 | acceptance radius, passed waypoint or turn-anticipation distance | next leg | sequences the 4 legs |
| D4 | SOC < 25 % (RTL) or < 12 % (land now); cell < 3.45 V | return now | must not trigger |
| **D5** | predicted SOC at touchdown for the rest of the route, using the estimated wind, < 15 % for 10 s | early return | energy feasibility in wind; must not trigger |
| D6 | outside the 3 km geofence or above the ceiling | return | – |
| D7 | unstable final approach or bounce > 2 m | go-around / re-flare | – |
| D8 | battery empty | glide landing | – |
| D9 | gust level on final | add up to 2 m/s to the approach speed | smooth air: 0 |

D5 is itself a small model-based energy prediction. Once per second it evaluates

$$
\widehat{\mathrm{SOC}}_{land} = \mathrm{SOC} - \frac{1}{E_{cap}}\sum_i \frac{\hat P\,d_i}{\sqrt{V_a^2 - W_{c,i}^2} + W_{a,i}}
$$

over the remaining legs $i$ (length $d_i$), using the measured cruise power $\hat P$ and the estimated tail- and cross-wind components $W_a$, $W_c$ of each leg.

## 2.4 What the autonomy sees

The autonomy works on **measurements**, not on the truth. Each measurement is the true value plus an error:

- **Navigation values** (airspeed, GPS position and velocity, baro height, attitude, heading) carry slowly varying Gauss–Markov errors, like the output of an EKF: σ = 0.3 m/s for airspeed, 0.6 m for position, 0.3° for attitude.
- **Gyros and accelerometers** carry white noise.

The **wind estimator** solves the wind triangle from these measurements:

$$
\hat{\mathbf W} = \mathbf V_g - V_a\cos\theta\,[\cos\psi,\ \sin\psi]^{\mathsf T}
$$

It filters the result twice: a fast estimate (τ = 5 s) and a slow mean (τ = 60 s). The slow mean, resolved along the current leg, is the head-wind $H$ that the optimised speed law uses. The aircraft therefore adapts to the wind it *estimates*, as a real UAV would. It is never told the true wind.

## 2.5 The policy slot: where the optimised controller acts

In MISSION mode, every control step (50 Hz), the autonomy calls the **policy** with an observation: SOC, battery power, airspeed, ground speed, fast and slow wind estimates, head- and cross-wind on the leg, gust level, distance to the waypoint. The policy returns an airspeed set-point, a height set-point or both. The autonomy clamps them to safe limits: airspeed between 1.3 × stall speed and 0.85 × V_NE, height between 20 m and the geofence ceiling. It then hands them to the controllers, which fly them. The policy cannot touch take-off, landing or the inner loops, so no policy value can crash the aircraft through its low-level control.

| Policy | Law | Used here as |
|---|---|---|
| `fixed` | $V = V_{cruise}$ = 17 m/s | baseline |
| `linear_wind` | $V = v_0 + k_{head}\,H + k_{cross}\lvert W_c\rvert + k_{gust}\,\sigma_{gust}$ | optimised design ($k_{cross} = k_{gust} = 0$) |
| `wind_aware_best_range` | $V = \arg\min_V P(V)/V_g(V)$ online | physics reference (Section 5.5) |
| `external` | set by an outside program | reinforcement learning (Gymnasium) |

## 2.6 How the autonomy is simulated

The autonomy is Python code (`uavlab/autonomy.py`) executed inside the simulation loop every 4th physics step, that is at 50 Hz. It reads the sensor model's output and writes set-points and surface commands. Every mode change and every decision is written to `events.csv` with its time, its reason and the numbers behind it. The whole behaviour is therefore auditable after the flight. Here is the timeline of the baseline flight of this PoC:

@@T:events@@

# 3 Flight-dynamics model, logs and criteria

## 3.1 Flight-dynamics model

The motion is computed by **JSBSim**, an open-source 6-degree-of-freedom flight-dynamics engine used in research and industry. It runs the Rascal 110 model from the ArduPilot SITL (documented changes M1–M10). JSBSim integrates the rigid-body equations with the aerodynamic, propeller, gravity and landing-gear forces at 200 Hz:

$$
m\left(\dot{\mathbf V}_b + \boldsymbol\omega\times\mathbf V_b\right) = \mathbf F_{aero} + \mathbf F_{prop} + \mathbf F_{gear} + m\,\mathbf g_b,\qquad
\mathbf I\,\dot{\boldsymbol\omega} + \boldsymbol\omega\times\mathbf I\boldsymbol\omega = \mathbf M
$$

The **electric powertrain** is computed by the lab and coupled to JSBSim every step:

- **Propeller:** APC 18x8E data, $T = C_T\rho n^2D^4$, $P = C_P\rho n^3D^5$ as functions of advance ratio and RPM.
- **Motor:** Drela model, $E = \omega/K_v$, $Q = (I - I_0)/K_v$.
- **ESC:** averaged, with conduction, switching and quiescent losses.
- **Battery:** 6S LiPo, open-circuit voltage as a function of SOC, series resistance and one RC pair.

@@FIG:coupling@@

The **wind** is a steady westerly. Its speed increases with height following the power law:

$$
U(h) = U_{10}\left(\frac{h}{10\ \mathrm m}\right)^{1/7}\quad\Rightarrow\quad U(100\ \mathrm m) = 6 \times 10^{1/7} = {{wind_h:.2f}}\ \mathrm{m/s}
$$

For the robustness step, MIL-F-8785C Dryden turbulence is added. Its intensity follows the 20 ft wind, which gives light turbulence.

## 3.2 Energy accounting

Every joule is tracked from the battery chemistry to the air. The cumulative meters are integrated at 200 Hz. The mechanical energy of the aircraft relative to the air, $E_{air} = \tfrac12 m V_a^2 + m g h$, must obey

$$
\frac{dE_{air}}{dt} = \mathbf F\cdot\mathbf V_a - m g W_D - m\,\mathbf V_a\cdot\dot{\mathbf W}
$$

The simulation checks this balance continuously. The remainder is logged as the closure residual, and criterion C2 limits it.

@@FIG:energy@@

## 3.3 What is logged

| File | Content | Used in this PoC for |
|---|---|---|
| `timeseries.csv` | about 110 signals at 10 Hz: state, wind, set-points, electrical and mechanical power, cumulative energies | Figures {{fignum:fig2_signals}} and {{fignum:fig1_track}} |
| `events.csv` | mode changes and decisions with their data | timeline (Section 2.6), criteria C1 and C6 |
| `legs.csv` | per mission leg: energy, Wh/km, mean airspeed and ground speed, tail-wind, efficiencies | Figure {{fignum:fig3_legs}}, leg table |
| `summary.json` | status, energies, breakdown, efficiencies, touchdown, closure residual | results table, criteria |
| `metadata.json`, `config_resolved.yaml`, `jsbsim/` | versions, seed, configuration and its hash, exact model files | reproducibility |

The PoC uses these key quantities:

| Quantity | Definition | Log |
|---|---|---|
| Mission-leg energy | battery energy used on the four mission legs (optimisation objective) | `summary.mission_E_Wh` |
| Total energy | battery energy from take-off roll to full stop | `summary.E_batt_Wh` |
| Energy per km | leg energy ÷ ground distance of the leg | `legs.Wh_per_km` |
| Head-/tail-wind | wind component along the ground track | `tailwind_mps`, `legs.tailwind_mean_mps` |
| Closure residual | energy balance error ÷ gross work | `summary.energy_closure.relative` |

## 3.4 Criteria

Two kinds of criteria apply.

**Model credibility.** The lab's verification and validation suite checks every model against a published reference, an analytic solution or an independent re-implementation. The checks most relevant to this PoC are below; all 19 checks pass in the shipped report.

@@T:vv@@

**PoC evaluation.** Criteria C1–C6 (Section 1.3) judge this experiment. The objective is the mission-leg energy, not the total. Take-off, climb, approach and landing are nearly identical in both flights and would dilute the effect. The total is reported as well.

# 4 The simulation process

## 4.1 One run from start to finish

1. **Configuration.** `configs/defaults.yaml` is merged with the mission and wind files and the overrides (policy, seed), then validated. The result is one resolved configuration with a hash.
2. **Model files.** The lab writes the exact JSBSim aircraft, engine and propeller files for this run and records their SHA-256.
3. **Set-up.** The lab builds the wind field, mission, powertrain, actuators, sensors, logger and autopilot. The autonomy takes the pre-flight decisions (D1 runway, D2 go/no-go), and the aircraft is placed on the runway.
4. **Time loop.** It runs 5 ms steps until the aircraft stops (LANDED), crashes or reaches the time limit. A 22-minute flight is about 266 000 steps.
5. **Outputs.** The lab writes the logs of Section 3.3 and computes the per-leg and per-phase tables and the summary.

## 4.2 One time step

@@FIG:step@@

| Rate | What runs |
|---|---|
| 200 Hz (5 ms) | wind, actuators, powertrain, JSBSim, energy ledger, crash check |
| 50 Hz (20 ms) | sensors, autonomy (modes, decisions, **policy**), guidance, TECS speed/height control, attitude loops |
| 1 Hz | energy-reserve, geofence and energy-feasibility decisions (D4–D6) |
| 10 Hz | one log row |

## 4.3 Determinism and seeds

All randomness (sensor noise, turbulence) comes from one seed. The same configuration and seed give a bit-identical flight on any computer (check V12). That is why a single paired comparison is meaningful here. The optimiser relies on the same property: every candidate design flies with the same seed (common random numbers), so the differences between candidates come only from the design.

# 5 How the lab applies optimisation

## 5.1 Four routes into an optimising controller

| Route | Method | What it optimises | Where |
|---|---|---|---|
| Offline, from data | parameter sweeps → dataset → surrogate model / Bayesian optimisation | mission settings from `dataset_runs.csv` and `dataset_legs.csv` | `batch.py`, *Parameter study* page |
| Online, model-based | speed-to-fly: $\arg\min_V P(V)/V_g(V)$ each control step, optional online RLS learning of $P(V)$ | airspeed in flight | `wind_aware_best_range` policy |
| **Design optimisation (this PoC)** | **cross-entropy method over any parameters, with full flights as evaluations** | **parameters of a control law, here $v_0$ and $k_{head}$** | **`optimize.py`, *Optimisation* page** |
| Learning | reinforcement learning in the Gymnasium environment | a neural policy for airspeed and height | `gym_env.py` |

All four act at the same place, the policy slot of the autonomy layer (Section 2.5). They are evaluated with the same full-flight simulation and the same logs.

## 5.2 The optimisation problem of this PoC

**Decision variables:** $x = (v_0,\ k_{head})$ with bounds $12 \le v_0 \le 20$ m/s and $0 \le k_{head} \le 1.2$.

**Control law** flown by the autonomy in every MISSION step:

$$
V_{cmd}(t) = \mathrm{clamp}\left(v_0 + k_{head}\,\hat H(t),\ 12,\ 26\right)
$$

where $\hat H$ is the slow wind estimate resolved against the current leg (positive = head-wind).

**Objective:** minimise the mission-leg battery energy of a complete simulated flight,

$$
J(x) = E_{mission}(x;\ \text{mission},\ \text{wind},\ \text{seed}=1)
$$

**Constraints**, each violation adding a penalty of $10^6$:

1. the flight ends with status LANDED (no no-go, crash, timeout or failure);
2. the mission is flown completely: the return reason is `mission_complete`.

> **Why the second constraint matters: a lesson from this PoC.** The first optimisation attempt had only constraint 1. In generation 1 it sampled $v_0$ = 19.1 m/s, $k_{head}$ = 0.94, which means 26 m/s up-wind. At that speed the battery power is so high that decision D5 predicted only 13 % charge at touchdown, below the 15 % minimum. After 2 min 23 s the autonomy returned and landed safely, exactly as designed. The flight used only 16.9 Wh of mission energy, instead of about 60 Wh, because most of the mission was never flown, and the optimiser ranked it best. **An energy objective must always be paired with a mission-completion constraint.** The interface now sets both constraints by default. In the final run the optimiser sampled the same design again in generation 1, and constraint 2 correctly rejected it.

$J$ has no formula and no gradient. Each evaluation is a 22-minute simulated flight with its turbulence-free but nonlinear dynamics, turns, climbs and autonomy decisions. It is a black-box, simulation-based optimisation problem.

## 5.3 The cross-entropy method, step by step

CEM keeps a Gaussian search distribution $\mathcal N(\boldsymbol\mu, \boldsymbol\sigma^2)$ over the decision variables. It moves that distribution towards the best designs, generation by generation:

1. **Initialise.** $\boldsymbol\mu$ is the centre of the bounds, (16 m/s, 0.6). $\boldsymbol\sigma$ is 30 % of the bound range, (2.4 m/s, 0.36).
2. **Sample** a population of $N = 8$ candidates $x_j \sim \mathcal N(\boldsymbol\mu, \boldsymbol\sigma^2)$, clipped to the bounds. Candidate 0 is always $\boldsymbol\mu$ itself.
3. **Evaluate** every candidate by flying the full mission in the PoC condition with seed 1, in parallel on all CPU cores. Every run is recorded in `evaluations.csv`.
4. **Score** $s_j = J(x_j) + 10^6 \times (\text{number of violated constraints})$. Feasible designs therefore always rank above infeasible ones.
5. **Select** the $N_e = 2$ best candidates (the elite, 25 %).
6. **Update** with smoothing $a = 0.7$ and a floor on σ so that the search never collapses too early:

   $$
   \boldsymbol\mu \leftarrow (1-a)\,\boldsymbol\mu + a\,\overline{x}_{elite},\qquad
   \boldsymbol\sigma \leftarrow \max\!\left((1-a)\,\boldsymbol\sigma + a\,\mathrm{std}(x_{elite}),\ 0.02\,(hi - lo)\right)
   $$

7. **Repeat** steps 2–6 for 5 generations. The best feasible design ever seen is the result (`result.json`). The lab then flies it once more with full logs (`best_run/`, and `optimised/` in the PoC folder).

@@FIG:studies@@

**Why CEM.**

- It needs no gradients, so the full nonlinear simulation can be used as it is.
- It tolerates noisy evaluations: the smoothing and elite averaging handle turbulence.
- A whole generation runs in parallel.
- It needs only bounds.

With 2 variables, 8 candidates and 5 generations it costs 40 flights. That is small enough for a laptop and large enough to find the optimum reliably, as the convergence in Figure {{fignum:fig4_cem}} shows.

@@T:cem_gens@@

## 5.4 What the optimiser found

@@CEMNOTE@@

@@IMG:fig4_cem|The cross-entropy search. Left: every design evaluated, coloured by mission energy (darker = less energy), with the path of the generation mean and the best design. Right: best and mean feasible mission energy per generation, compared with the baseline.@@

## 5.5 The physics behind the result: speed-to-fly

The optimiser is not given any physics. Its result can therefore be checked against classical flight mechanics. The battery power needed in steady level flight, measured with the full pipeline on the **independent** performance map, is fitted as $P(V) = aV^3 + b/V + c$. The ground speed on a leg with head-wind $H$ is $V_g = V - H$. The energy per ground distance is then $P(V)/V_g$, and it is minimised where

$$
\frac{d}{dV}\,\frac{P(V)}{V - H} = 0 \quad\Longleftrightarrow\quad P'(V^*)\,(V^* - H) = P(V^*)
$$

With the shipped fit ($a$ = {{fit_a:.4f}}, $b$ = {{fit_b:.1f}}, $c$ = {{fit_c:.1f}}) and $H = \pm {{wind_h:.2f}}$ m/s, the theory predicts:

- up-wind: **{{pred_up:.1f}} m/s**; the optimised law flies {{law_up:.1f}} m/s;
- down-wind: **{{pred_down:.1f}} m/s** (at the 12 m/s lower limit of the policy); the optimised law flies {{law_down:.1f}} m/s.

@@IMG:fig5_physics|Energy per ground kilometre against airspeed on the up-wind and down-wind legs, from the performance map. Solid: the fitted power curve used by criterion C4, with its optimum (dot). Dashed: the measured map points (post-hoc diagnosis). The fixed 17 m/s (diamond) is too slow into the wind and too fast with it. The optimised law (star) sits at the minimum of the measured curve.@@

@@C4NOTE@@

## 5.6 From this PoC to the adaptive optimising controller

- **Robust design.** Optimise over several wind conditions at once: add conditions on the *Optimisation* page. The objective is then the mean over conditions, and the law becomes valid for a range of winds, not just one.
- **More adaptation.** Free $k_{cross}$, $k_{gust}$ and the altitude offset `dh`. Or switch to `wind_aware_best_range` with online RLS, which learns $P(V)$ in flight.
- **Learning.** Train a reinforcement-learning policy in `UAVEnergyEnv` with randomised wind, and compare it with both baselines using exactly this PoC procedure.
- **Hardware.** Calibrate drag, propeller and battery against flight logs (handbook, Section B14.4) before quoting absolute watt-hours. Relative savings such as this PoC's are much less sensitive to calibration.

# 6 Step-by-step guide to run the proof of concept

## Route A: one command (about {{wall_min:.0f}} min on 2 cores, less on more cores)

**Step 1: Install once.** In PowerShell, in the repository folder, run each line on its own:

```powershell
cd $HOME\Documents\uav_energy_lab
python -m pip install -r requirements.txt
python -m pytest -q
```

*Check:* the tests end with "24 passed".

**Step 2: Run the proof of concept.**

```powershell
python poc/run_poc.py
```

In an IDE, open `poc/run_poc.py` and press Run instead. Use `--quick` for a first test (16 optimisation flights) and `--workers N` to set the number of parallel flights.

*Check:* the console shows STEP 1/6 to STEP 6/6. The last block prints the saving and PASS or FAIL for C1–C6.

**Step 3: What each step does and where its output goes** (in `poc_results/`):

| Step | Action | Output |
|---|---|---|
| 1 | baseline flight, fixed 17 m/s | `baseline/` (full logs) |
| 2 | CEM optimisation, 8 × 5 flights | `optimisation/` (`evaluations.csv`, `generations.csv`, `result.json`) |
| 3 | optimised flight with the best $(v_0, k_{head})$ | `optimised/` (full logs) |
| 4 | both designs in light turbulence, seeds 11–13 | `robustness/` |
| 5 | speed-to-fly prediction from `validation_report/performance/performance_fit.json` | `poc_results.json` → `physics` |
| 6 | criteria, tables, figures | `poc_results.json`, `comparison.csv`, `legs.csv`, `figures/` |

**Step 4: Read the results.** Open `poc_results/figures/`. Or start the interface from the repository folder (`python -m uavlab ui` or `run_ui.py`), go to *Results*, choose the source *Proof-of-concept runs*, tick `baseline` and `optimised`, and press *Compare selected*. The numbers in Section 7 of this document come from `poc_results.json`.

**Step 5: If a step failed.** Rerun with `--resume`. Finished flights and the finished optimisation are reused, and only the missing steps run.

## Route B: in the graphical interface (no code)

1. Start the interface: `python -m uavlab ui`, or run `run_ui.py` in the IDE.
2. **Overview** → template **"Head-wind / tail-wind legs"** → **Load**. This loads `out_and_back` + `steady_headwind_6`, the PoC condition.
3. **Baseline:** press **Run simulation**. Watch it on **Live run**. When it lands, press **Open results** and label the run "baseline".
4. **Scenario → Autonomy & policy:** select the policy **`linear_wind`**.
5. **Optimisation** page. The defaults already match this PoC:
   - variables `autonomy.policy.params.v0` (12–20) and `k_head` (0–1.2);
   - objective *Mission-leg battery energy*, *Minimise*;
   - constraints `status == LANDED` and `rtl_reason == mission_complete`;
   - condition *base*, seed 1, population 8, 5 generations.

   Press **Start optimisation** and watch the convergence chart.
6. When it finishes, press **Apply best design to scenario**, then **Run simulation**. Label the run "optimised".
7. **Results** → tick both runs → **Compare runs**. You get the KPI table with differences and the overlaid signals (airspeed, power, energy).
8. *(Optional, criterion C5)* On **Scenario → Wind**, set the turbulence model to *dryden*, the seed to 11, 12 and 13 in turn (*Simulation & logging*), and run both designs for each seed.

Route B uses the same code, settings and optimiser seed, so it gives the same design and the same energies as Route A. This was checked: one candidate flown through both routes gives a bit-identical mission energy.

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| PowerShell: "Missing expression after unary operator '--'" | A multi-line command was pasted. Run one line at a time; every command in this guide is a single line. |
| "attempted relative import with no known parent package" | A file inside `uavlab/` was run directly. Run `poc/run_poc.py`, `run_ui.py` or `python -m uavlab …` instead. |
| The optimisation is slow | Each flight is about 1 minute of CPU. Use `--workers` equal to the number of cores, or `--quick`. |
| A flight fails with an error | `poc_results/optimisation/evaluations.csv` shows which candidate. Failed candidates are penalised, not fatal. |

# 7 Results

## 7.1 Comparison in the PoC condition

@@T:results@@

@@REFNOTE@@

@@IMG:fig2_signals|Signals against ground distance, same route and wind. The optimised law flies faster on the shaded up-wind legs (higher ground speed, shorter time against the wind) and slower on the down-wind legs (lower power). The gap in cumulative battery energy opens on every leg.@@

## 7.2 Where the saving comes from: leg by leg

@@T:legs@@

@@IMG:fig3_legs|Energy per ground kilometre on each leg. Up-wind legs cost about three times as much per km as down-wind legs. The optimised law saves on both kinds of leg.@@

@@IMG:fig1_track|Ground track of both flights: the same route within the guidance tolerance.@@

## 7.3 Robustness in unseen turbulence

@@T:robust@@

@@IMG:fig6_robustness|The same two designs in light Dryden turbulence with three seeds the optimiser never saw. Each pair flies identical turbulence.@@

## 7.4 Criteria

@@T:criteria_res@@

## 7.5 Interpretation and limits

@@INTERPRETATION@@

**Limits of this PoC.** The absolute watt-hours depend on the representative [REP] aircraft and powertrain data (drag, propeller, battery). The relative saving is much less sensitive to them, but the lab should be calibrated against flight logs before absolute numbers are quoted. The optimised law is tuned to one wind condition. Section 5.6 describes how to extend it to a range of winds. The landing and take-off are identical in both designs, so the saving comes entirely from the mission legs.

# Appendix A: Configuration of the experiment

@@T:config@@

# Appendix B: Files and commands

| Item | Location |
|---|---|
| PoC script | `poc/run_poc.py` (figures: `poc/poc_figures.py`) |
| Results | `poc_results/`: `poc_results.json`, `comparison.csv`, `legs.csv`, `figures/`, `baseline/`, `optimised/`, `optimisation/`, `robustness/` |
| This document | `docs/poc/POC_GUIDE.pdf`, source `docs/poc/src/poc_guide.md`, build `tools/poc_guide/` |
| Model and lab reference | `docs/handbook/handbook.html`, `validation_report/VV_REPORT.html` |

| Command | Purpose |
|---|---|
| `python poc/run_poc.py` | full proof of concept |
| `python poc/run_poc.py --quick` | smaller search for a first check |
| `python poc/run_poc.py --resume` | complete an interrupted run |
| `python poc/poc_figures.py` | redraw the figures from `poc_results/` |
| `python -m uavlab ui` | graphical interface (Route B) |
