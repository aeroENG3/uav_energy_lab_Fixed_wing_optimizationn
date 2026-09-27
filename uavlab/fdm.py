"""Thin JSBSim wrapper. All English/SI conversions for the flight-dynamics core
happen here; the rest of the lab sees SI only."""
from __future__ import annotations

import math
import os
from pathlib import Path

import numpy as np

import jsbsim

# silence JSBSim's start-up banner and loader chatter (must precede FGFDMExec creation)
try:
    jsbsim.FGJSBBase().debug_lvl = 0
except Exception:  # pragma: no cover - older bindings
    pass

from .models import TORQUE_SOURCE_POWER_W
from .units import DEG, FT, FTLBF, LBF, PSF, RANKINE, SLUG, SLUG_FT3

STRUCTURE_UNITS = {3: "PROP_TIP", 4: "NOSE", 5: "LEFT_WINGTIP", 6: "RIGHT_WINGTIP", 7: "BELLY"}
GEAR_UNITS = {0: "LEFT_MLG", 1: "RIGHT_MLG", 2: "TAIL_LG"}


class FDM:
    def __init__(self, model_root: str | Path, dt: float, model: str = "rascal110_e"):
        root = str(Path(model_root).resolve())
        # JSBSim prints to stdout; silence it for batch work.
        self.fdm = jsbsim.FGFDMExec(root, None)
        self.fdm.set_debug_level(0)
        self.fdm.set_aircraft_path("aircraft")
        self.fdm.set_engine_path("engine")
        self.fdm.set_systems_path("systems")
        if not self.fdm.load_model(model):
            raise RuntimeError(f"JSBSim failed to load model '{model}' from {root}")
        self.fdm.set_dt(dt)
        self.dt = dt
        self._p = self.fdm.get_property_value
        self._s = self.fdm.set_property_value

    # ------------------------------------------------------------------ setup
    def set_atmosphere(self, delta_T_K: float = 0.0, sl_pressure_pa: float = 101325.0,
                       rh_pct: float = 0.0):
        self._s("atmosphere/delta-T", delta_T_K / RANKINE)
        self._s("atmosphere/P-sl-psf", sl_pressure_pa / PSF)
        self._s("atmosphere/RH", rh_pct)

    def set_seed(self, seed: int):
        self._s("simulation/randomseed", int(seed) % 2_147_483_647)
        self._s("atmosphere/randomseed", int(seed) % 2_147_483_647)

    def init_on_ground(self, lat, lon, terrain_msl_m, heading_deg):
        s = self._s
        s("ic/terrain-elevation-ft", terrain_msl_m / FT)
        s("position/terrain-elevation-asl-ft", terrain_msl_m / FT)
        s("ic/lat-geod-deg", lat)
        s("ic/long-gc-deg", lon)
        s("ic/h-agl-ft", 1.2)           # just above the gear, then it settles
        s("ic/psi-true-deg", heading_deg)
        s("ic/theta-deg", 14.0)          # tail-down attitude of the tail-dragger
        s("ic/phi-deg", 0.0)
        s("ic/u-fps", 0.0); s("ic/v-fps", 0.0); s("ic/w-fps", 0.0)
        s("ic/p-rad_sec", 0.0); s("ic/q-rad_sec", 0.0); s("ic/r-rad_sec", 0.0)
        if not self.fdm.run_ic():
            raise RuntimeError("JSBSim run_ic failed")
        self._s("propulsion/set-running", -1)

    def init_in_air(self, lat, lon, terrain_msl_m, h_agl_m, heading_deg, tas_mps,
                    gamma_deg: float = 0.0):
        s = self._s
        s("ic/terrain-elevation-ft", terrain_msl_m / FT)
        s("position/terrain-elevation-asl-ft", terrain_msl_m / FT)
        s("ic/lat-geod-deg", lat)
        s("ic/long-gc-deg", lon)
        s("ic/h-agl-ft", h_agl_m / FT)
        s("ic/psi-true-deg", heading_deg)
        s("ic/vt-fps", tas_mps / FT)
        s("ic/gamma-deg", gamma_deg)
        if not self.fdm.run_ic():
            raise RuntimeError("JSBSim run_ic failed")
        self._s("propulsion/set-running", -1)

    def trim(self, mode: int = 1) -> bool:
        """JSBSim trim (1 = full longitudinal+lateral). Returns success."""
        try:
            self.fdm.do_trim(mode)
            return True
        except Exception:
            return False

    # ----------------------------------------------------------------- inputs
    def set_wind(self, mean_ned_mps, gust_ned_mps):
        s = self._s
        s("atmosphere/wind-north-fps", mean_ned_mps[0] / FT)
        s("atmosphere/wind-east-fps", mean_ned_mps[1] / FT)
        s("atmosphere/wind-down-fps", mean_ned_mps[2] / FT)
        s("atmosphere/gust-north-fps", gust_ned_mps[0] / FT)
        s("atmosphere/gust-east-fps", gust_ned_mps[1] / FT)
        s("atmosphere/gust-down-fps", gust_ned_mps[2] / FT)

    def set_jsbsim_turbulence(self, w20_mps: float, severity: int):
        self._s("atmosphere/turb-type", 3)  # ttMilspec (Dryden, MIL-F-8785C/MIL-HDBK-1797)
        self._s("atmosphere/turbulence/milspec/windspeed_at_20ft_AGL-fps", w20_mps / FT)
        self._s("atmosphere/turbulence/milspec/severity", severity)

    def set_surfaces(self, aileron, elevator, rudder, steer):
        s = self._s
        s("fcs/aileron-cmd-norm", aileron)
        s("fcs/elevator-cmd-norm", elevator)
        s("fcs/rudder-cmd-norm", rudder)
        s("fcs/steer-cmd-norm", steer)

    def set_motor_torque(self, torque_nm: float, omega_rad_s: float):
        """Impose the motor shaft torque on JSBSim's propeller ODE.
        JSBSim computes torque = P/omega (omega > 0.01) or P/1.0 (omega <= 0.01)."""
        p_w = torque_nm * (omega_rad_s if omega_rad_s > 0.01 else 1.0)
        self._s("fcs/throttle-cmd-norm[0]", p_w / TORQUE_SOURCE_POWER_W)

    def set_prop_krpm(self, krpm: float):
        self._s("propulsion/engine[0]/blade-angle", krpm)

    def run(self) -> bool:
        return self.fdm.run()

    # ----------------------------------------------------------------- output
    def prop_rpm(self) -> float:
        return self._p("propulsion/engine[0]/propeller-rpm")

    def state(self) -> dict:
        p = self._p
        d = {}
        d["t"] = p("simulation/sim-time-sec")
        d["lat"] = p("position/lat-geod-deg")
        d["lon"] = p("position/long-gc-deg")
        d["h_msl"] = p("position/h-sl-ft") * FT
        d["h_agl"] = p("position/h-agl-ft") * FT
        d["phi"] = p("attitude/phi-rad")
        d["theta"] = p("attitude/theta-rad")
        d["psi"] = p("attitude/psi-rad")
        d["p"] = p("velocities/p-rad_sec")
        d["q"] = p("velocities/q-rad_sec")
        d["r"] = p("velocities/r-rad_sec")
        d["vn"] = p("velocities/v-north-fps") * FT
        d["ve"] = p("velocities/v-east-fps") * FT
        d["vd"] = p("velocities/v-down-fps") * FT
        d["u_air"] = p("velocities/u-aero-fps") * FT
        d["v_air"] = p("velocities/v-aero-fps") * FT
        d["w_air"] = p("velocities/w-aero-fps") * FT
        d["tas"] = p("velocities/vt-fps") * FT
        d["cas"] = p("velocities/vc-kts") * 0.514444
        d["alpha"] = p("aero/alpha-rad")
        d["beta"] = p("aero/beta-rad")
        d["qbar"] = p("aero/qbar-psf") * PSF
        d["nz"] = -p("accelerations/n-pilot-z-norm")   # load factor, +1 in level flight
        # specific force at the CG, body axes (what an ideal IMU accelerometer reads), m/s^2
        d["ax"] = p("accelerations/Nx") * 9.80665
        d["ay"] = p("accelerations/Ny") * 9.80665
        d["rho"] = p("atmosphere/rho-slugs_ft3") * SLUG_FT3
        d["T_K"] = p("atmosphere/T-R") * RANKINE
        d["P_pa"] = p("atmosphere/P-psf") * PSF
        d["g"] = p("accelerations/gravity-ft_sec2") * FT
        d["mass"] = p("inertia/mass-slugs") * SLUG
        d["wind_tot_n"] = p("atmosphere/total-wind-north-fps") * FT
        d["wind_tot_e"] = p("atmosphere/total-wind-east-fps") * FT
        d["wind_tot_d"] = p("atmosphere/total-wind-down-fps") * FT
        d["turb_n"] = p("atmosphere/turb-north-fps") * FT
        d["turb_e"] = p("atmosphere/turb-east-fps") * FT
        d["turb_d"] = p("atmosphere/turb-down-fps") * FT
        # forces (body axes, N)
        for ax in ("x", "y", "z"):
            d[f"f{ax}_aero"] = p(f"forces/fb{ax}-aero-lbs") * LBF
            d[f"f{ax}_prop"] = p(f"forces/fb{ax}-prop-lbs") * LBF
            d[f"f{ax}_gear"] = p(f"forces/fb{ax}-gear-lbs") * LBF
        # JSBSim reports wind-axis aero forces as positive drag / positive lift magnitudes
        # (verified: level flight gives fwz = +weight). Kept positive here.
        d["drag"] = p("forces/fwx-aero-lbs") * LBF
        d["side"] = p("forces/fwy-aero-lbs") * LBF
        d["lift"] = p("forces/fwz-aero-lbs") * LBF
        d["thrust"] = p("propulsion/engine[0]/thrust-lbs") * LBF
        d["rpm"] = p("propulsion/engine[0]/propeller-rpm")
        d["J"] = p("propulsion/engine[0]/advance-ratio")
        d["prop_power_w"] = p("propulsion/engine[0]/propeller-power-ftlbps") * FTLBF
        d["prop_ct"] = p("propulsion/engine[0]/thrust-coefficient")
        d["elev_pos"] = p("fcs/elevator-pos-norm")
        d["ail_pos"] = p("fcs/left-aileron-pos-norm")
        d["rud_pos"] = p("fcs/rudder-pos-norm")
        d["wow"] = p("gear/wow")
        d["gear_wow"] = [p(f"gear/unit[{i}]/WOW") for i in GEAR_UNITS]
        d["struct_wow"] = {n: p(f"gear/unit[{i}]/WOW") for i, n in STRUCTURE_UNITS.items()}
        return d
