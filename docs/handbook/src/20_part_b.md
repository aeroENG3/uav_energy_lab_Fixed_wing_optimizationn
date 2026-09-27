# Part B: Aerospace-engineering perspective

## B1 Frames, units and sign conventions

| Quantity | Convention |
|---|---|
| Local frame | North-East-Down (NED). The origin is `mission.home`, the runway centre at field elevation. Geodetic ↔ local conversion uses WGS-84 (`geo.LocalFrame`). |
| Body axes | x forward, y right wing, z down. Euler angles (φ, θ, ψ) in the 3-2-1 sequence. |
| JSBSim structural frame | inches, x aft, y right, z up (aircraft XML only). |
| Wind vector **W** | NED components of the air's velocity over the ground. It points where the air moves *to*. |
| Wind direction | meteorological, `from_deg`: the direction the wind blows *from*. W_N = −U cos χ_w, W_E = −U sin χ_w, W_D = −w_up. |
| Velocities | ground velocity $\mathbf V_g$ = air-relative velocity $\mathbf V_a$ + wind $\mathbf W$. TAS = $\lvert\mathbf V_a\rvert$. |
| Along- and across-track wind | for a track angle χ: tail-wind W_a = W_N cos χ + W_E sin χ (positive = helping); cross-wind W_c = −W_N sin χ + W_E cos χ (positive = from the left, pushing right). Head-wind H = −W_a. |
| Control surfaces | +aileron → right roll; +elevator → nose down; +rudder → nose left; +tail-wheel steer → nose left. Normalised commands −1…1 map to ±20.05° (aileron, rudder) and −20.05°…+17.2° (elevator, asymmetric) in the flight-control tables. V15 checks these signs. |
| Throttle | 0…1, the ESC duty cycle (linear mapping). |
| Units | SI inside the lab and in all logs. English units only at the JSBSim boundary. |

## B2 Rigid-body flight dynamics (JSBSim)

JSBSim integrates the full nonlinear six-degree-of-freedom equations of a rigid aircraft over a rotating WGS-84 Earth. In body axes, with total force **F** and moment **M**:

$$
m\left(\dot{\mathbf V}_b + \boldsymbol\omega\times\mathbf V_b\right) = \mathbf F_{aero} + \mathbf F_{prop} + \mathbf F_{gear} + m\,\mathbf g_b
$$

$$
\mathbf I\,\dot{\boldsymbol\omega} + \boldsymbol\omega\times\left(\mathbf I\,\boldsymbol\omega\right) = \mathbf M_{aero} + \mathbf M_{prop} + \mathbf M_{gear}
$$

JSBSim propagates attitude with quaternions and adds the Earth-rotation terms. The propeller contributes thrust, reaction torque and gyroscopic moments. Each landing-gear contact (two main wheels, the steerable tail wheel) and each structural contact point is a spring-damper with rolling and sliding friction:

$$
F_z = k\,\delta + c\,\dot\delta ,\qquad F_{x,y} \le \mu F_z
$$

The lab changes one gear value from the base model. The damping is 10 lbf/(ft/s), which gives a damping ratio of about 0.5 (change M10). The base value of 100 was numerically unstable at 200 Hz for a 6 kg aircraft.

**Mass properties.** All-up mass = airframe 4.80 kg [REP] + battery 1.35 kg [REP] + payload (default 0) = 6.15 kg. Each item is a point mass at a configurable x-station, so the CG moves when the battery or the payload moves. Inertia comes from the base model (I_xx = 1.95, I_yy = 1.55, I_zz = 1.91 slug·ft²) times `aircraft.inertia_scale`.

## B3 Aerodynamic model

The aerodynamics are the Rascal 110 coefficient build-up from the ArduPilot SITL model, originally the FlightGear Rascal110-JSBSim. The reference geometry is S = 10.57 ft² (0.982 m²), b = 9.17 ft (2.80 m) and c̄ = 1.15 ft, which gives aspect ratio 7.96. Forces act in wind axes with dynamic pressure q̄ = ½ρV_a²:

$$
L = \bar q S C_L,\qquad D = \bar q S C_D,\qquad Y = \bar q S C_Y
$$

$$
C_L = k_{CL}\,C_L(\alpha) + C_{L\delta_e}\delta_e
$$

$$
C_D = k_{CD0}\,C_{D0}(\alpha) + k_{CDi}\,K\,C_L^2 + C_{D\beta}(\beta) + C_{D\delta_e}\,|\delta_e|
$$

$$
C_m = C_{m\alpha}\alpha + C_{m\delta_e}\delta_e + \frac{\bar c}{2V_a}\left(C_{mq}\,q + C_{m\dot\alpha}\,\dot\alpha\right)
$$

$$
C_l = C_{l\beta}\beta + \frac{b}{2V_a}\left(C_{lp}\,p + C_{lr}\,r\right) + C_{l\delta_a}\delta_a + C_{l\delta_r}\delta_r
$$

$$
C_n = C_{n\beta}\beta + \frac{b}{2V_a}C_{nr}\,r + C_{n\delta_r}\delta_r + C_{n\delta_a}\delta_a + C_{n,i}
$$

| Coefficient | Value | Remark |
|---|---|---|
| C_L(α) | −0.75 at −11.5°, 0.25 at 0°, **1.40 at 13.2° (C_Lmax)**, 0.71 at 34° | lift-curve slope about 5.0 /rad; coarse post-stall |
| C_Lδe | 0.20 /rad | |
| C_D0(α) | 0.028 at 0°, 0.056 at ±15°, 1.5 at ±90° | |
| K | 0.040 | e ≈ 1.0 for AR 7.96 (optimistic; see U1) |
| C_Dδe | 0.03 per unit \|δe\| | M5: absolute value (the base model used a signed value) |
| C_Yβ | −1.0 /rad | |
| C_mα, C_mq, C_mα̇ | −0.5, −12, −7 | statically and dynamically stable |
| C_mδe | −0.5 /rad | |
| C_lβ, C_lp, C_lr | −0.1, −0.4, 0.15 | |
| C_lδa, C_lδr | 0.13 /rad, 0.01 /rad | |
| C_nβ, C_nr, C_nδr, C_nδa | 0.12, −0.15, −0.05, −0.03 | weathercock stable, adverse yaw |
| C_n,i | 0.0007 | constant yaw moment from the tail incidence; needs a small rudder trim |

The factors k_CL, k_CD0 and k_CDi (`aircraft.aero_calibration.cl_scale`, `cd0_scale`, `cdi_scale`, default 1) exist to calibrate against flight data (Section B14.4).

**Stall speed.** V_s = √(2mg / (ρ S C_Lmax)) = 8.5 m/s at sea level and 8.7 m/s at the default field (612 m, ρ = 1.155 kg/m³). The lab uses `aircraft.limits.stall_speed_mps = 8.5` for its protections: minimum commanded speed 1.3 V_s, under-speed protection at 1.1 V_s.

**Changes from the base model (M1–M10)**, written into the header of every generated XML:

| # | Change | Reason |
|---|---|---|
| M1 | fuel tank removed; the battery is a point mass | electric aircraft |
| M2 | empty weight = `aircraft.airframe_mass_kg` | battery mass is a separate item |
| M3 | engine = JSBSim electric engine used as a torque source | the motor physics is in the lab's powertrain (Section A6) |
| M4 | propeller = APC 18x8E data, 2-D in J and RPM | the base 18x8 table is an estimate that peaks at about 39 % efficiency |
| M5 | elevator drag uses \|δe\| | the base model's signed term made negative elevator reduce drag |
| M6 | tail wheel steerable ±30° | the real aircraft steers the tail wheel with the rudder |
| M7 | structural contact points (prop tip, nose, wing tips, belly) | crash detection |
| M8 | calibration factors on C_D0, induced drag, C_L | fit to flight-test data |
| M9 | network input port removed | not needed |
| M10 | gear damping 100 → 10 lbf/(ft/s) | numerical stability at 200 Hz |

## B4 Propeller

The propeller follows classical dimensionless propeller theory. With rotational speed n (rev/s), diameter D = 18 in (0.457 m) and axial inflow speed V (the body-x airspeed):

$$
J = \frac{V}{nD},\qquad T = C_T(J,\mathrm{RPM})\,\rho n^2 D^4,\qquad P = C_P(J,\mathrm{RPM})\,\rho n^3 D^5,\qquad Q_p = \frac{P}{2\pi n}
$$

$$
\eta_p = \frac{T V}{P} = J\,\frac{C_T}{C_P}
$$

C_T and C_P come from APC's PER3 file for the 18x8E. They are tabulated at 1000–12000 RPM and interpolated bilinearly in J and RPM. APC computes these data by blade-element/vortex theory; they are not measured. Rows beyond the last tabulated J (the windmilling region, J > 0.64) are linear extrapolations. `ct_scale` and `cp_scale` scale the tables, or you can load measured data in the same format.

The rotor speed is a state that JSBSim integrates. The motor torque comes from the lab (Section A6):

$$
I_r\,\dot\omega = Q_m - Q_p(J,\mathrm{RPM}),\qquad I_r = 0.0014\ \mathrm{kg\,m^2}\ \text{[REP]}
$$

Linearised about a cruise operating point, the rotor speed responds with the time constant:

$$
\tau_r = \frac{I_r}{\partial Q_p/\partial\omega + 1/(K_v^2 R_\Sigma)} \approx 40\ \mathrm{ms}
$$

The back-EMF damping term 1/(K_v² R_Σ), about 0.04 N m s/rad, dominates the propeller term 2Q_p/ω (about 0.001 N m s/rad).

## B5 Electric powertrain

@@FIG:energy@@

### B5.1 Motor (Drela first-order model)

This is a brushless DC motor in its quasi-static form. The electrical time constant L/R is about 0.1 ms, far below the 5 ms step, so the current is algebraic. With Kv in rad/s/V:

$$
E = \frac{\omega}{K_v},\qquad I_m = \frac{V_m - E}{R_m},\qquad Q_m = \frac{I_m - I_0}{K_v}
$$

$$
P_{shaft} = Q_m\omega = (I_m - I_0)E,\qquad P_{cu} = I_m^2 R_m,\qquad P_{fe} = I_0 E
$$

$$
V_m I_m = P_{shaft} + P_{cu} + P_{fe},\qquad \eta_m = \left(1-\frac{I_0}{I_m}\right)\left(1-\frac{I_m R_m}{V_m}\right)
$$

At a fixed terminal voltage, the efficiency peaks at I* = √(I₀V/R_m), which V6 checks. The defaults are Kv = 295 rpm/V, R_m = 25 mΩ, I₀ = 1.8 A and a 70 A limit [REP], typical of a 110-size motor on 6S with an 18x8. I₀ can optionally scale with back-EMF: I₀ = I₀,ref (E/E_ref)^n.

### B5.2 ESC (averaged switch model)

The ESC is modelled as an averaged switch with duty cycle d = throttle:

$$
V_m = d\,V_{bus} - I_m R_{esc}
$$

$$
I_{in} = d\,I_m + k_{sw}|I_m| + \frac{P_q}{V_{bus}},\qquad P_{esc} = I_m^2 R_{esc} + k_{sw}V_{bus}|I_m| + P_q
$$

The defaults are R_esc = 3 mΩ, switching loss k_sw = 1 %, quiescent power P_q = 0.3 W, drawn only while the throttle is above zero [REP]. The model has three regimes:

- **normal**, 0 ≤ I_m ≤ I_max;
- **current-limited**, where the effective duty is reduced so that I_m = I_max;
- **freewheel**, where the diode blocks negative winding current when the rotor is driven faster than the applied voltage allows. Regeneration is off by default.

### B5.3 Battery (1-RC Thevenin)

The pack is N_s × N_p cells. From the per-cell values: R₀ = N_s r₀/N_p + R_wiring, R₁ = N_s r₁/N_p, C₁ = c₁ N_p/N_s, Q = N_p Q_cell × derate.

$$
V_{bus} = N_s\,\mathrm{OCV}(\mathrm{SOC}) - V_1 - I_b R_0
$$

$$
\dot V_1 = -\frac{V_1}{R_1C_1} + \frac{I_b}{C_1},\qquad \dot{\mathrm{SOC}} = -\frac{I_b}{3600\,Q}
$$

The step is exact for constant current: V₁ ← V₁ e^(−Δt/τ) + R₁I_b(1 − e^(−Δt/τ)). The heat in R₁ uses the exact integral of V₁²/R₁ over the step. Energy is therefore conserved to round-off: *chemical = terminal + R₀ heat + R₁ heat + change of energy stored in C₁* (V5). The defaults are 6S1P 10 Ah, r₀ = 2.5 mΩ/cell + 4 mΩ wiring, r₁ = 1.5 mΩ/cell, τ = R₁C₁ = 30 s, and a generic LiPo OCV curve (3.27–4.20 V/cell) [REP].

The chemical energy from full to empty is E_cap = Q ∫₀¹ N_s OCV(s) ds, about 231 Wh for the default pack. The pack reports *depleted* when the SOC reaches 0, or when the 1-second-filtered loaded cell voltage drops below `cell_cutoff_v` (3.30 V). The ESC then cuts the motor (decision D8).

### B5.4 Solving the network

The battery current depends on the bus voltage, and the bus voltage depends on the current. For the normal regime, with R_Σ = R_m + R_esc, s = sign(I_m) and auxiliary load P = P_avionics + P_q (P_q only when d > 0), substitute I_m = (dV − E)/R_Σ and I_b = I_in + P_avionics/V into V = V_s − R₀I_b:

$$
(1 + R_0 a)\,V^2 - (V_s + R_0 c)\,V + R_0 P = 0,\qquad a = \frac{(d + k_{sw}s)\,d}{R_\Sigma},\quad c = \frac{(d+k_{sw}s)\,E}{R_\Sigma}
$$

The physical solution is the larger root. The current-limited and freewheel regimes give their own quadratics. If the discriminant turns negative, the load exceeds what the source can deliver (voltage collapse), and the solver clamps it to zero. There is no iteration, and V7 shows the Kirchhoff residual is about 10⁻¹⁴ V over 3000 random operating points.

**Avionics and servos.** 6 W base [REP], plus 0.25 W idle per servo (four servos), plus 0.004 W per deg/s of surface motion. Actively fighting turbulence therefore costs measurable energy.

## B6 Atmosphere

JSBSim's U.S. Standard Atmosphere 1976 provides temperature, pressure and density. In the troposphere:

$$
T(h) = T_0 + \Delta T - L\,h,\qquad \frac{dp}{dh} = -\rho g,\qquad \rho = \frac{p}{R_s T}
$$

with T₀ = 288.15 K, L = 6.5 K/km and R_s = 287.05 J/(kg K). The ISA offset ΔT (`atmosphere.delta_T_K`) shifts the temperature profile, and the pressure then follows hydrostatically. The sea-level pressure and the relative humidity (which lowers density through the virtual temperature) can also be set. V1 checks the tables to 0.001 %. Density enters the dynamic pressure, the propeller thrust and power, and the stall speed. A +20 K day at the 612 m default field lowers the density by about 6 %.

## B7 Wind: mean, turbulence and gusts

@@FIG:wind@@

The total wind applied to the aircraft is the sum of three parts, all in NED:

$$
\mathbf W(t,h) = \mathbf W_{mean}(t,h) + \mathbf W_{turb}(t) + \mathbf W_{gust}(t)
$$

### B7.1 Mean wind

The mean wind has a reference speed U_ref and direction χ_ref at reference height h_ref (10 m). Both can follow a time **schedule**, interpolated component-wise so that direction changes take the short way round. A slow **Ornstein–Uhlenbeck** random variation can be added to speed and direction:

$$
x_{k+1} = e^{-\Delta t/\tau}x_k + \sigma\sqrt{1-e^{-2\Delta t/\tau}}\;n_k,\qquad n_k\sim\mathcal N(0,1)
$$

The defaults are σ_U = 1 m/s, σ_χ = 10° and τ = 300 s. The profile with height is either the **power law** or the **log law**:

$$
U(h) = U_{ref}\left(\frac{\max(h, h_{min})}{h_{ref}}\right)^{\alpha}\qquad\text{or}\qquad U(h) = U_{ref}\,\frac{\ln(h/z_0)}{\ln(h_{ref}/z_0)}
$$

The defaults are α = 0.143 (1/7, open terrain) and z₀ = 0.03 m. The direction can veer linearly with height (`veer_deg_per_100m`), and a steady vertical component can be added.

### B7.2 Turbulence (Dryden, MIL-F-8785C low altitude)

The lab uses the Dryden spectra in their low-altitude form (h < 1000 ft). Scales are in feet, h is clamped to 10–1000 ft as the specification prescribes, and W₂₀ is the wind speed at 20 ft:

$$
L_w = h,\qquad L_u = L_v = \frac{h}{(0.177 + 0.000823\,h)^{1.2}}
$$

$$
\sigma_w = 0.1\,W_{20},\qquad \frac{\sigma_u}{\sigma_w} = \frac{\sigma_v}{\sigma_w} = \frac{1}{(0.177 + 0.000823\,h)^{0.4}}
$$

The spectra in spatial frequency Ω (rad/m) are:

$$
\Phi_u(\Omega) = \sigma_u^2\,\frac{2L_u}{\pi}\,\frac{1}{1 + (L_u\Omega)^2},\qquad
\Phi_{v,w}(\Omega) = \sigma^2\,\frac{L}{\pi}\,\frac{1 + 3(L\Omega)^2}{\left[1 + (L\Omega)^2\right]^2}
$$

Taylor's frozen-turbulence hypothesis (ω = VΩ, with V = TAS floored at 3 m/s on the ground roll) turns them into time-domain shaping filters driven by unit white noise:

$$
H_u(s) = \sigma_u\sqrt{\frac{2L_u}{\pi V}}\;\frac{1}{1 + \frac{L_u}{V}s},\qquad
H_{v,w}(s) = \sigma\sqrt{\frac{L}{\pi V}}\;\frac{1 + \sqrt3\,\frac{L}{V}s}{\left(1 + \frac{L}{V}s\right)^2}
$$

**Discretisation.** The u filter uses the exact first-order update x ← a x + σ√(1 − a²) n with a = e^(−VΔt/L). The v and w filters are two-state systems discretised exactly with **Van Loan's method**, which gives the discrete transition matrix and the process-noise covariance from one matrix exponential. The discretisation is cached against L/V. The generated signal therefore has the specified variance and spectrum at any step size and airspeed; V3 checks σ within 5 % and the PSD within ±0.5 dB.

The turbulence axes follow the low-altitude convention: u along the mean wind, v across it, w vertical. The intensity is set by W₂₀. With `intensity: auto`, W₂₀ is the mean-wind profile at 20 ft. *light*, *moderate* and *severe* give W₂₀ = 15, 30 and 45 kt. Setting `w20_mps` fixes it directly.

`wind.turbulence.model: jsbsim_milspec` selects JSBSim's own Dryden implementation instead. It includes the rotational gust terms (p_g, q_g, r_g), which the lab's generator omits. The default configuration has no turbulence (`model: none`). When turbulence is switched on, prefer the lab's generator (`dryden`): its exact samples are logged, which makes the energy audit of turbulence complete.

### B7.3 Discrete gusts

Each gust has a start time t₀, duration T, horizontal amplitude A with direction, and optional vertical amplitude. With τ = t − t₀:

$$
\text{1-cosine: } W(\tau) = \frac{A}{2}\left[1-\cos\frac{2\pi\tau}{T}\right],\ 0\le\tau\le T
$$

$$
\text{ramp-and-hold: } W(\tau) = \frac{A}{2}\left[1-\cos\frac{\pi\tau}{T}\right],\ \tau\le T;\qquad W = A \text{ for } T<\tau\le T+T_{hold}
$$

The 1-cosine is the MIL-F-8785C discrete-gust shape. Ramp-and-hold models a wind-shear front.

## B8 Energy accounting

The energy ledger is the physical backbone of the lab. It shows where every joule taken from the battery goes, and it shows the energy that the *wind* adds to or removes from the aircraft. This is the quantity a wind-exploiting controller acts on.

### B8.1 Air-relative mechanical energy equation

Define the air-relative specific energy of the aircraft:

$$
E_{air} = \tfrac12 m\,|\mathbf V_a|^2 + m g h
$$

Newton's law in the local frame gives $m\dot{\mathbf V}_g = \mathbf F + m\mathbf g$, where $\mathbf F = \mathbf F_{aero} + \mathbf F_{prop} + \mathbf F_{gear}$. Substitute $\mathbf V_a = \mathbf V_g - \mathbf W$ and $\dot h = -V_{g,D}$:

$$
\frac{d}{dt}\left(\tfrac12 m\,\mathbf V_a\cdot\mathbf V_a\right) = \mathbf V_a\cdot\mathbf F + m\,\mathbf V_a\cdot\mathbf g - m\,\mathbf V_a\cdot\dot{\mathbf W}
$$

$$
m\,\mathbf V_a\cdot\mathbf g = m g\,(V_{g,D} - W_D) = -m g\,\dot h - m g\,W_D
$$

$$
\frac{dE_{air}}{dt} = \underbrace{\mathbf F\cdot\mathbf V_a}_{\text{aero + propulsive + gear}} \;\underbrace{-\,m g\,W_D - m\,\mathbf V_a\cdot\dot{\mathbf W}}_{P_{wind}}
$$

- $\mathbf F_{aero}\cdot\mathbf V_a = -D\,V_a$: lift and side force are perpendicular to $\mathbf V_a$, so only drag does work. The log calls this `P_drag_W` (positive).
- $\mathbf F_{prop}\cdot\mathbf V_a \approx T\,u_a$ is the useful thrust power, `P_thrust_W`.
- $P_{wind}$ is the power the wind field delivers in the air-relative frame. An updraft ($W_D < 0$) adds energy. So does flying into a wind that increases against the direction of flight ($\mathbf V_a\cdot\dot{\mathbf W} < 0$), which is the mechanism behind gust soaring, dynamic soaring and wind-shear exploitation. A sustained updraft of 0.5 m/s is worth m g × 0.5 ≈ 30 W. That is about a quarter of the thrust power needed at 17 m/s (≈ 120 W), and saves about 50 W at the battery.

Every term is integrated with the trapezoidal rule at the physics rate. The wind term uses the mid-point air velocity across each discrete wind change. The ledger checks the balance continuously:

$$
\varepsilon = \Delta E_{air} - \int\left(P_{aero} + P_{prop} + P_{gear} + P_{wind}\right)dt
$$

This residual is logged as `closure_residual_J` and summarised in `summary.energy_closure`. V10 requires |ε| < 0.1 % of the gross work over full flights in turbulence with the lab's wind models (0.2 % with JSBSim's turbulence, whose rotational gust terms are not in the balance). The small remainder comes from the flat-Earth form of the equation (JSBSim integrates over a rotating ellipsoid) and from the integration.

### B8.2 From battery to air

The electrical meters and the mechanical ledger connect along the chain in the energy-flow figure:

$$
E_{chem} = E_{batt,loss} + E_{batt},\quad E_{batt} = E_{avionics} + E_{esc,in},\quad E_{esc,in} = E_{esc,loss} + E_{cu} + E_{fe} + E_{shaft}
$$

$$
E_{shaft} = E_{thrust} + E_{prop,loss} + \Delta E_{rotor},\qquad E_{thrust} + E_{wind} - E_{drag} + W_{gear} + \ldots = \Delta E_{air}
$$

The per-leg efficiencies in `legs.csv` are η_prop = E_thrust/E_shaft and η_drive = E_shaft/E_batt. Energy per ground distance, the figure of merit for range in wind, is:

$$
\frac{E}{d} = \frac{P_{batt}}{V_g}\qquad[\mathrm{Wh/km}] = \frac{E_{batt}\ [\mathrm{Wh}]}{d_{ground}\ [\mathrm{km}]}
$$

## B9 Steady performance and speed-to-fly in wind

### B9.1 Power required

In steady level flight L = W and T = D. With the parabolic polar C_D = C_D0 + K C_L² and C_L = 2W/(ρV²S), the power needed to overcome drag is:

$$
P_{air} = D\,V = \tfrac12\rho S C_{D0}\,V^3 + \frac{2 K W^2}{\rho S}\,\frac1V
$$

The battery must supply this through the propeller, motor, ESC and battery losses, plus the fixed loads. The lab measures battery power across the speed range with the full pipeline (the performance map) and fits:

$$
P_{batt}(V) = a\,V^3 + \frac{b}{V} + c
$$

using non-negative least squares. a carries parasite drag, b induced drag, and c the fixed loads (avionics, no-load motor loss, ESC quiescent). Because the drivetrain efficiency varies with the operating point, the coefficients describe this aircraft–powertrain combination, not the airframe alone. The fit shipped in the V&V report is a ≈ 0.0203 W s³/m³, b ≈ 178 W m/s, c ≈ 88.5 W at ρ = 1.143 kg/m³ (100 m above the 612 m default field, where the map is flown) and m = 6.15 kg, with an RMS residual of about 3 W.

- **Best endurance** (minimum power): dP/dV = 0 gives V_E = (b/3a)^(1/4). This is about 7.4 m/s for the fit, below the stall speed, so within the permitted envelope the endurance optimum is the minimum safe speed of about 11 m/s.
- **Best range in still air** (minimum energy per distance): d(P/V)/dV = 0 gives 2aV⁴ − cV − 2b = 0, so V_R ≈ 14.1 m/s, at 3.11 Wh/km.

### B9.2 Speed-to-fly in wind

Along a track with tail-wind W_a and cross-wind W_c, the ground speed at airspeed V is (crab angle included):

@@FIG:triangle@@

$$
V_g(V) = \sqrt{V^2 - W_c^2} + W_a
$$

The energy per ground distance P(V)/V_g(V) is minimised at:

$$
\frac{P'(V^*)}{P(V^*)} = \frac{V_g'(V^*)}{V_g(V^*)}
$$

With no cross-wind and a head-wind H (W_a = −H), this becomes:

$$
P'(V^*)\,(V^* - H) = P(V^*)
$$

Geometrically, V* is where a line from the point (H, 0) on the speed axis touches the power curve. This is the tangent construction used for speed-to-fly problems. A head-wind moves the tangent point to a higher speed, and a tail-wind moves it lower. With the shipped fit:

| Head-wind H (m/s) | V* (m/s) | Wh/km at V* | Wh/km at 14.1 m/s | Saving |
|---|---|---|---|---|
| −6 (tail-wind) | 12.1 | 2.14 | 2.18 | 2.2 % |
| −3 | 13.0 | 2.55 | 2.57 | 0.7 % |
| 0 | 14.1 | 3.11 | 3.11 | 0 |
| +3 | 15.6 | 3.90 | 3.96 | 1.4 % |
| +6 | 17.5 | 5.01 | 5.42 | 7.6 % |
| +9 | 19.9 | 6.56 | 8.62 | 23.9 % |

This is the basis of the `wind_aware_best_range` policy. It evaluates P(V)/V_g(V) on a speed grid, using the slow (60 s) wind estimate so that it does not chase gusts, smooths the resulting command (τ = 10 s), and can refine (a, b, c) online by recursive least squares. The `linear_wind` policy is the linearisation V* ≈ v₀ + k_head H; the table gives k_head ≈ 0.5–0.6 for this aircraft. V14 validates the underlying physics: steady head-wind and tail-wind leg energies agree with P(V_a)·d/V_g within 3 %. D1 demonstrates a saving of about 6 % on the out-and-back mission in a 6 m/s wind.

> **Why not just fly faster in a head-wind?** Faster is right, but the optimum is not simply V_R + H. The saving grows steeply with the ratio of wind to airspeed. At H = 9 m/s, flying 14.1 m/s gives a ground speed of only 5.1 m/s and about 31 % more energy per km than flying 19.9 m/s. The autonomy layer's D5 decision (Section B13) protects against the extreme case where the ground speed on an up-wind leg would leave too little energy to return.

## B10 Lateral guidance: L1

@@FIG:l1@@

The L1 law (Park, Deyst & How, 2004, in the ArduPilot form) steers towards a reference point on the path at distance L₁ ahead of the aircraft. The required lateral acceleration is centripetal:

$$
a_{cmd} = K_{L1}\,\frac{V_g^2}{L_1}\,\sin\eta,\qquad \eta = \eta_1 + \eta_2
$$

$$
\eta_1 = \arcsin\!\left(\frac{y}{L_1}\right)\ \text{(clipped to }\pm45^\circ),\qquad \eta_2 = \text{angle from the track to }\mathbf V_g
$$

$$
L_1 = \max\!\left(\frac{\zeta T V_g}{\pi},\,15\ \mathrm m\right),\qquad K_{L1} = 4\zeta^2,\qquad \phi_{cmd} = \arctan\frac{a_{cmd}}{g}
$$

Here y is the cross-track error. For small errors this is a second-order system in y with natural period T and damping ζ, independent of speed:

$$
\ddot y + 2\zeta\omega_n\dot y + \omega_n^2 y = 0,\qquad \omega_n = \frac{2\pi}{T}
$$

The defaults T = 18 s and ζ = 0.75 give L₁ ≈ 73 m at 17 m/s. The roll command is limited to 35°. Because the law works with *ground* velocity, it compensates the wind crab angle automatically.

**Turn anticipation (D3).** The next waypoint becomes active when the aircraft reaches the acceptance radius, passes the waypoint's perpendicular, or comes within the turn tangent distance:

$$
d_{turn} = R\tan\frac{\Delta\chi}{2},\qquad R = \frac{\max(V_g, V_a)^2}{g\tan(0.8\,\phi_{max})}
$$

The tangent distance is capped at 4R, and Δχ at 150°.

## B11 Speed and height: TECS

The Total Energy Control System (Lambregts, 1983; ArduPilot form) separates *how much* energy the aircraft has, which the throttle controls, from *how it is split* between height and speed, which the pitch controls. With specific energies SPE = g h and SKE = ½V²:

$$
\text{STE} = \text{SPE} + \text{SKE},\qquad \text{SEB} = (2-w)\,\text{SPE} - w\,\text{SKE}
$$

Here w ∈ [0, 2] is the speed weight. w = 1 is balanced. w = 2 means speed priority, used on take-off, go-around, in under-speed and when gliding without a motor.

**Throttle** (feed-forward plus PI on the total-energy error):

$$
\delta_t = \delta_{t,cruise} + K\,\dot{\text{STE}}_{dem} + K\left[\frac{\text{STE}_{err}}{\tau} + k_d\left(\dot{\text{STE}}_{dem} - \dot{\text{STE}}\right)\right] + k_i K\!\int\!\text{STE}_{err}\,dt
$$

$$
K = \frac{\delta_{t,max} - \delta_{t,min}}{g\,(\dot h_{climb,max} + \dot h_{sink,max})}
$$

**Pitch** (energy balance):

$$
\theta_{cmd} = \frac{1}{V g}\left[\frac{\text{SEB}_{err}}{\tau} + \dot{\text{SEB}}_{dem} + k_{pd}\left(\dot{\text{SEB}}_{dem} - \dot{\text{SEB}}\right)\right] + \frac{k_i}{V g}\!\int\!\text{SEB}_{err}\,dt
$$

Both integrators have anti-windup: they are clamped when their output saturates. The demands are shaped:

- the speed demand is rate-limited to 1 m/s²;
- the height demand follows the command through a rate- and acceleration-limited path, with a feed-forward of the commanded height rate, so glide paths and altitude ramps are followed without the τḣ lag.

The **airspeed** used by TECS comes from a second-order complementary filter. It blends the pitot TAS (low frequency) with the along-body acceleration from the IMU, V̇ = a_x − g sin θ (high frequency), at ω = 2 rad/s. This removes most turbulence noise without delay. The defaults are τ = 5 s, k_d = 0.5, k_i = 0.1, k_pd = 0.3, cruise throttle 0.60, and climb and sink limits of 3 m/s.

## B12 Inner loops, steering and actuators

@@FIG:control@@

The attitude loops are PID controllers. Their gains are scheduled on dynamic pressure through the speed scaler s = clamp((V_ref/V)², 0.4, 2.0), with V_ref the cruise speed. The low-speed gain increase is capped at 2 so that the loops do not overshoot in the flare.

$$
\delta_a = s\left[k_p(\phi_{cmd}-\phi) + k_i\!\int(\phi_{cmd}-\phi)\,dt - k_d\,p\right]
$$

$$
\delta_e = \delta_{e,trim} + s\left[-k_p(\theta_{cmd}-\theta) - k_i\!\int(\theta_{cmd}-\theta)\,dt + k_d\,(q - q_{ff})\right],\qquad q_{ff} = \frac{g}{V}\tan\phi\,\sin\phi
$$

$$
\delta_r = s\left[-k_\beta\,\beta + k_r\,(r - r_{ff})\right] - k_{ff}\,\delta_a,\qquad r_{ff} = \frac{g\tan\phi}{V}
$$

The pitch turn compensation q_ff supplies the extra pitch rate a banked turn needs. The yaw loop coordinates the turn and damps the Dutch roll; the k_ff term cancels adverse yaw. The throttle command is filtered (τ = 0.15 s) and slew-limited (1 /s), both for motor life and so that turbulence does not modulate motor power.

**Ground steering.** On the runway, the rudder and the steerable tail wheel track the centre line. The heading command bends towards the line at 0.08 rad per metre of offset, limited to 10°, followed by a PD on the heading error.

**Actuators.** Each channel is modelled as saturation → deadband → first-order lag → rate limit. The defaults are τ = 30 ms, 4 /s in normalised units (about 80°/s) and a 0.2 % deadband for the surfaces, and τ = 20 ms for the throttle.

## B13 Autonomy: modes, decisions and landing

@@FIG:modes@@

### B13.1 Flight phases

1. **Pre-flight.** The aircraft settles on its gear for 2 s. D1 chooses the runway heading with the largest head-wind component, −**W**₁₀·**u**. D2 refuses the flight if the 10 m wind exceeds 13 m/s or the crosswind exceeds 6 m/s.
2. **Take-off roll.** The throttle ramps to full in 1.5 s and the aircraft steers on the centre line. Above 6 m/s the tail comes up and the controller holds 3° pitch.
3. **Rotate.** At 13 m/s the pitch command rises at 6°/s to 9°. The take-off is aborted (D2_abort_takeoff) if rotation speed is not reached within 25 s or before the runway end plus 20 m.
4. **Climb-out.** Above 3 m the aircraft climbs at full throttle with TECS in speed priority at 14 m/s. Pitch is limited to 18°, and roll to 12° below 12 m. At 25 m it switches to the mission.
5. **Mission.** L1 flies the legs and TECS holds the leg's height and speed, both possibly set by the policy.
6. **Approach.** The aircraft returns to the *align* point, joins the extended centre line at the *entry* point and follows the glide path (default 6°) down from the pattern altitude (45 m).
7. **Flare and roll-out.** The flare starts at 3 m and is followed by a wheel landing: the controller holds 2° until 9 m/s, then pins the tail down. LANDED is declared when the ground speed falls below 0.5 m/s.

### B13.2 Decisions

Decisions are logged in `events.csv` with the data behind them. D9 is logged only when it adds more than 0.3 m/s.

| ID | Rule | Action |
|---|---|---|
| D1 | runway heading maximising −**W**₁₀·**u** | runway selection |
| D2 | $\lvert\mathbf W_{10}\rvert$ > `max_mean_mps` or crosswind > `max_crosswind_mps` | NO_GO; D2_abort_takeoff on the roll |
| D3 | acceptance radius, passed perpendicular, or turn-tangent distance | next waypoint |
| D4 | SOC < `land_now_soc` (0.12), SOC < `rtl_soc` (0.25), filtered cell voltage < `min_cell_voltage_v` (3.45 V) | approach now (RTL) |
| D5 | predicted SOC at touchdown < `min_landing_soc` (0.15) for `d5_persist_s` (10 s) | early RTL |
| D6 | distance > geofence radius, or height > ceiling + 20 m | RTL |
| D7 | on final: cross-track > 12 m below 15 m; more than 6 m low below 8 m; long (past 60 % of the runway above 2 m); bounce > 2 m after touchdown | go-around (max 2), otherwise re-flare |
| D8 | battery depleted (SOC = 0 or cell cut-off) | motor off, glide approach with speed priority |
| D9 | on joining final: V_app += min(½ · 2σ̂_gust · gain, max) | gust-corrected approach speed |

**D5, wind-aware energy feasibility.** Once per second in MISSION, the autonomy layer predicts the SOC at touchdown if it flies the remaining route now. The route is the remaining legs, then align, entry and touchdown. The prediction uses the smoothed measured cruise power P̂ (an exponential average with a 20 s time constant) and the slow wind estimate:

$$
\widehat{\mathrm{SOC}}_{land} = \mathrm{SOC} - \frac{1}{E_{cap}}\sum_{i}\frac{\hat P\,d_i}{V_{g,i}},\qquad V_{g,i} = \sqrt{V_a^2 - W_{c,i}^2} + W_{a,i}
$$

If any leg's ground speed falls below 2 m/s, the prediction is SOC = 0. The decision must persist for 10 consecutive evaluations, so a gust cannot trigger it. D5 is a model-based energy decision, and an adaptive policy can make it less likely to trigger by flying the energy-optimal speed.

**D9, gust additive.** The wind estimator's gust level σ̂ comes from wings-level flight. Its own noise floor (0.4 m/s, set by the sensor errors) is removed: σ̂ = √(σ_gust² − σ_floor²). Half the gust factor 2σ̂ is added to the approach speed, capped at 2 m/s. This is a standard practice for manned aircraft.

### B13.3 Landing geometry and flare law

@@FIG:approach@@

The approach points lie on the extended centre line:

- touchdown point TD, 40 m past the threshold;
- final approach fix FAF at h_pattern/tan γ before TD (428 m at the defaults);
- entry, 350 m before the FAF;
- align, 250 m before the entry.

The glide-path height is h_gp = tan γ × (distance to TD), capped at the pattern altitude.

The **flare** commands a sink rate proportional to height (an exponential flare) with a floor:

$$
\dot h_{cmd} = -\max\!\left(\dot h_{min},\ \dot h_0\,\frac{h}{h_0}\right),\qquad \theta_{cmd} = \theta_0 + 0.10\,(\dot h_{cmd} - \dot h) + \int 0.05\,(\dot h_{cmd}-\dot h)\,dt
$$

The throttle only arrests excess sink from down-gusts, δ_t = clamp(0.35 (ḣ_cmd − ḣ), 0, 0.5), and is otherwise idle. Throughout the flare the bank command is limited to ±5° for wing-tip clearance. Below 1.5 m the rudder also aligns the nose with the runway (de-crab). After a bounce the aircraft re-flares, or goes around if it bounced above 2 m (D7).

### B13.4 Sensors and wind estimation

The autopilot never sees the true state. Navigation quantities carry first-order Gauss–Markov errors, which is what the output of an EKF looks like. Inertial rates and accelerations carry white noise:

| Signal | σ | Correlation time |
|---|---|---|
| TAS | 0.3 m/s | 0.5 s |
| GPS position N, E | 0.6 m | 5 s |
| GPS velocity N, E, D | 0.08 m/s | 1 s |
| baro height | 0.25 m | 2 s |
| roll, pitch | 0.3° | 1 s |
| heading | 1.0° | 5 s |
| gyros | 0.5 °/s | white |
| along-body accelerometer | 0.1 m/s² | white |

Sideslip is treated as known, as if estimated from the lateral accelerometer. There are no biases, latency or GPS dropouts. `sensors.noise_enabled: false` gives an ideal-sensor baseline.

The **wind estimator** solves the wind triangle with sideslip and angle of attack neglected:

$$
\hat{\mathbf W}_{raw} = \mathbf V_g - V_a\cos\theta\,[\cos\psi,\ \sin\psi]^{\mathsf T}
$$

It filters the result into a fast estimate (τ = 5 s, given to the policy and logged; L1 itself steers on GPS ground velocity) and a slow mean (τ = 60 s, used by D5 and the policies). The gust level is the running per-axis variance of the raw estimate about the slow mean, computed in wings-level flight over 30 s. The estimate is biased in turns, which is why only wings-level data are used.

## B14 Verification, validation and credibility

### B14.1 Philosophy

*Verification* asks whether each model is implemented as specified. *Validation* asks whether the complete simulation reproduces known physics and practice. The suite follows the credibility practice of NASA-STD-7009 and ASME V&V 10/20 in spirit: every check states its criterion before it runs, measures one number, and writes that number to the report together with a figure where one helps.

### B14.2 The checks

| ID | Kind | What it proves |
|---|---|---|
| V1 | verification | T, p, ρ match the U.S. Standard Atmosphere 1976 tables (0–11 km) |
| V2 | verification | the wind is injected correctly: JSBSim's total wind = mean + gust inputs, and $\lvert\mathbf V_g - \mathbf W\rvert$ = TAS |
| V3 | verification | the Dryden generator has the specified σ and spectrum for u, v, w |
| V4 | verification | the 1-cosine gust shape is exact |
| V5 | verification | the battery conserves charge and energy exactly, and its step response matches R₀ and R₁ |
| V6 | verification | the motor has zero torque at the analytic no-load speed, and peak efficiency at √(I₀V/R) |
| V7 | verification | the network solver satisfies Kirchhoff's voltage law and every power balance in all three ESC regimes |
| V8 | verification | the propeller–motor co-simulation reaches the RPM and thrust of an independent torque-balance root-find |
| V9 | verification | steady flight of the full pipeline matches an independent trim model (power, RPM, α, lift = weight) |
| V10 | verification | the mechanical energy balance closes in turbulent flight |
| V11 | verification | halving the physics step changes energy and flight time by less than 1 % |
| V12 | verification | identical seeds give bit-identical time series; different seeds give different turbulence |
| V13 | validation | full flights in 8 wind scenarios all land on the runway with acceptable sink rates and tracking |
| V14 | validation | head-wind and tail-wind leg energies match P(V_a)·d/V_g; head-wind legs cost more than twice as much per km |
| V15 | verification | the control-surface signs match what the controllers assume |
| V16 | verification | invalid configurations are rejected |
| V17 | validation | landing reliability over 8 turbulence seeds (95th-percentile sink < 2.5 m/s) |
| U1 | uncertainty | one-at-a-time sensitivity of cruise power to the [REP] parameters |
| D1 | demonstration | the wind-aware policy against fixed speed on the same route and wind |

The measured values are in `validation_report/VV_REPORT.html`, which also opens from the Verification page of the interface.

### B14.3 Validity envelope and limitations

- **Aerodynamics** come from a hobby/SITL model, not from wind-tunnel or flight-test data. Comparisons between strategies are more trustworthy than absolute watt-hours. The largest single sensitivity is C_D0: ±10 % changes cruise power by about ±6 % (U1).
- There is **no propeller slipstream** over the tail, no ground effect and no flaps. The post-stall data are coarse (α > 13°). The autopilot keeps above 1.1 V_s; do not trust results that spend time near the stall.
- The **propeller** data are APC's computed values. Wind-tunnel tests of APC propellers generally show somewhat lower efficiency, so calibrate `cp_scale` and `ct_scale` or load measured data.
- The **motor and battery** models have no temperature dependence. The battery has no ageing beyond `capacity_derate`, and its OCV curve is generic.
- The lab's **Dryden** generator is the low-altitude form without rotational gust terms. Thermals, terrain-induced flow and convective turbulence are not modelled.
- The **sensors** have no biases, latency or dropouts, and sideslip is treated as measured.
- **Landing** in turbulence is firm, and a bounce with re-flare is common. This is typical of a light tail-dragger on spring gear. The autoland closes every flight for energy accounting, but it is not tuned for gentle landings.

### B14.4 Calibrating against flight data

Before quoting absolute endurance or range:

1. Fly 4–6 steady, level, constant-speed segments in calm air across the speed range. Log battery voltage and current, airspeed and altitude.
2. Set your mass, battery (cells, capacity, R₀, OCV table) and motor constants in the scenario. Run a performance map.
3. Adjust `cd0_scale` to match the high-speed power and `cdi_scale` to match the low-speed power. Then adjust `cp_scale` if the RPM disagrees.
4. Save the calibrated scenario. Its configuration hash then identifies every later run made with it.

For absolute SOC accuracy, replace the OCV table with a pulse-test curve of your own cells.
