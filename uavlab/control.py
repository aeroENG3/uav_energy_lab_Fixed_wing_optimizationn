"""Controller layer: guidance + inner loops.

  L1 lateral guidance  -> roll command            (Park, Deyst & How, AIAA GNC 2004;
                                                   ArduPilot AP_L1_Control form)
  TECS (total energy)  -> throttle + pitch command (Lambregts 1983; ArduPilot AP_TECS form)
  Attitude loops       -> aileron / elevator / rudder (PID with airspeed gain scheduling)
  Ground steering      -> rudder + tail wheel on the runway

Sign conventions of the Rascal FCS (verified in tests/test_signs.py):
  +aileron  -> right roll;  +elevator -> nose down;  +rudder -> nose left;
  +steer (tail wheel) -> nose left.
"""
from __future__ import annotations

import math

import numpy as np

from .units import DEG, wrap_pi

G = 9.80665


def clamp(x, lo, hi):
    return lo if x < lo else hi if x > hi else x


# =============================================================================== L1
class L1Guidance:
    def __init__(self, period_s: float, damping: float, roll_limit_deg: float):
        self.T = period_s
        self.zeta = damping
        self.roll_lim = roll_limit_deg * DEG
        self.xtrack = 0.0
        self.nu = 0.0
        self.l1_dist = 0.0

    def line(self, pos_ne, vel_ne, A, B) -> float:
        """Track the line A->B. Returns roll command (rad)."""
        pos_ne, vel_ne, A, B = map(np.asarray, (pos_ne, vel_ne, A, B))
        gs = max(float(np.hypot(*vel_ne)), 3.0)
        if np.hypot(*vel_ne) < 1.0:
            vel_ne = np.array([math.cos(math.atan2(*(B - A)[::-1])), math.sin(math.atan2(*(B - A)[::-1]))]) * gs
        K_L1 = 4.0 * self.zeta ** 2
        L1 = max(self.zeta * self.T * gs / math.pi, 15.0)
        self.l1_dist = L1
        AB = B - A
        ab_len = float(np.hypot(*AB))
        ab = AB / ab_len if ab_len > 1e-3 else np.array([1.0, 0.0])
        A_air = pos_ne - A
        a_dist = float(np.hypot(*A_air))
        along = float(A_air @ ab)
        cross = lambda u, v: float(u[0] * v[1] - u[1] * v[0])
        cr = cross(A_air, ab)            # ArduPilot convention (x=N, y=E): <0 when right of track
        self.xtrack = -cr                # logged cross-track error, + = right of the track
        self.along = along
        if a_dist > L1 and along / max(a_dist, 1.0) < -0.7071:
            # far behind A: fly directly towards A
            A_air_u = A_air / max(a_dist, 1e-3)
            nu = math.atan2(cross(vel_ne, -A_air_u), float(vel_ne @ -A_air_u))
        else:
            nu2 = math.atan2(cross(vel_ne, ab), float(vel_ne @ ab))
            nu1 = math.asin(clamp(cr / L1, -0.7071, 0.7071))
            nu = nu1 + nu2
        nu = clamp(nu, -1.5708, 1.5708)
        self.nu = nu
        lat_acc = K_L1 * gs * gs / L1 * math.sin(nu)
        return clamp(math.atan(lat_acc / G), -self.roll_lim, self.roll_lim)

    def heading(self, psi, psi_cmd, gs) -> float:
        """Simple heading hold used when no line is defined."""
        err = wrap_pi(psi_cmd - psi)
        return clamp(math.atan(2.0 * gs * err / (self.T / 2) / G), -self.roll_lim, self.roll_lim)


# ============================================================================== TECS
class TECS:
    """Total Energy Control System (ArduPilot-style simplified).
    Throttle regulates total specific energy rate; pitch regulates the energy
    balance between height and speed."""

    def __init__(self, cfg: dict, pitch_lim_deg, thr_min=0.0, thr_max=1.0):
        self.c = cfg
        self.tau = float(cfg["time_const_s"])
        self.thr_damp = float(cfg["thr_damp"])
        self.ki = float(cfg["integ_gain"])
        self.pitch_damp = float(cfg["pitch_damp"])
        self.w_spd_default = float(cfg["spd_weight"])
        self.max_climb = float(cfg["max_climb_mps"])
        self.max_sink = float(cfg["max_sink_mps"])
        self.thr_cruise = float(cfg["thr_cruise"])
        self.vacc = float(cfg["vert_acc_mps2"])
        self.pmin, self.pmax = pitch_lim_deg[0] * DEG, pitch_lim_deg[1] * DEG
        self.thr_min, self.thr_max = thr_min, thr_max
        self.reset()

    def reset(self, h=0.0, v=0.0):
        self.h_dem = h
        self.hdot_dem = 0.0
        self.v_dem = v
        self.vdot_dem = 0.0
        self.i_thr = 0.0
        self.i_pitch = 0.0
        self.v_filt = v
        self.v_int = 0.0
        self._h_cmd_prev = None
        self.h_cmd_rate = 0.0
        self.vdot = 0.0
        self.thr = self.thr_cruise
        self.pitch = 0.0
        self.ste_err = 0.0
        self.seb_err = 0.0

    def update(self, dt, h, hdot, v, h_cmd, v_cmd, *, ax=None, theta=0.0, w_spd=None, climb_max=None,
               sink_max=None, thr_max=None, thr_min=None, underspeed_v=None, pitch_min=None, pitch_max=None):
        cmax = self.max_climb if climb_max is None else climb_max
        smax = self.max_sink if sink_max is None else sink_max
        tmax = self.thr_max if thr_max is None else thr_max
        tmin = self.thr_min if thr_min is None else thr_min
        pmin = self.pmin if pitch_min is None else pitch_min
        pmax = self.pmax if pitch_max is None else pitch_max
        # airspeed and its rate: 2nd-order complementary filter blending the pitot
        # airspeed (low frequency) with the IMU along-body acceleration
        # (high frequency), as in ArduPilot TECS (TECS_SPDWEIGHT/SPD_OMEGA = 2 rad/s).
        if ax is not None:
            vdot_imu = ax - G * math.sin(theta)
            w = 2.0
            err = v - self.v_filt
            self.v_int += err * w * w * dt
            self.v_filt += (vdot_imu + self.v_int + 2.0 * w * err) * dt
            self.vdot += dt / 0.2 * (vdot_imu - self.vdot)
            v = self.v_filt
        else:
            v_prev = self.v_filt
            self.v_filt += dt / 0.5 * (v - self.v_filt)
            self.vdot += dt / 0.5 * ((self.v_filt - v_prev) / dt - self.vdot)
        w = self.w_spd_default if w_spd is None else w_spd
        # demanded speed: rate limited (1.0 m/s^2)
        dv = clamp(v_cmd - self.v_dem, -1.0 * dt, 1.0 * dt)
        self.v_dem += dv
        self.vdot_dem = dv / dt
        # demanded height: rate/acceleration limited, with feed-forward of the
        # commanded height rate (removes the tau*hdot lag on glide paths/ramps)
        if self._h_cmd_prev is None:
            self._h_cmd_prev = h_cmd
        rate = (h_cmd - self._h_cmd_prev) / dt
        self._h_cmd_prev = h_cmd
        self.h_cmd_rate += dt / (0.5 + dt) * (clamp(rate, -smax, cmax) - self.h_cmd_rate)
        hdot_target = clamp(self.h_cmd_rate + (h_cmd - self.h_dem) / max(self.tau, 1.0), -smax, cmax)
        self.hdot_dem += clamp(hdot_target - self.hdot_dem, -self.vacc * dt, self.vacc * dt)
        self.h_dem += self.hdot_dem * dt
        # keep h_dem from drifting far from the aircraft (e.g. after a mode change)
        self.h_dem = clamp(self.h_dem, h - 30.0, h + 30.0)

        underspeed = underspeed_v is not None and v < underspeed_v
        if underspeed:
            w = 2.0
        spe_w, ske_w = 2.0 - w, w
        SPE_dem, SKE_dem = G * self.h_dem, 0.5 * self.v_dem ** 2
        SPE, SKE = G * h, 0.5 * v ** 2
        SPEdot_dem, SKEdot_dem = G * self.hdot_dem, self.v_dem * self.vdot_dem
        SPEdot, SKEdot = G * hdot, v * self.vdot
        # ---------------- throttle
        STEdot_max = G * cmax
        STEdot_min = -G * smax
        ste_err = (SPE_dem - SPE) + (SKE_dem - SKE)
        self.ste_err = ste_err
        stedot_dem = clamp(SPEdot_dem + SKEdot_dem, STEdot_min, STEdot_max)
        stedot = SPEdot + SKEdot
        K = (tmax - tmin) / (STEdot_max - STEdot_min)
        ff = self.thr_cruise + stedot_dem * K
        thr_p = K * (ste_err / self.tau + self.thr_damp * (stedot_dem - stedot))
        self.i_thr = clamp(self.i_thr + ste_err * self.ki * K * dt, -0.3, 0.3)
        thr = ff + thr_p + self.i_thr
        if underspeed:
            thr = tmax
        if thr > tmax:
            self.i_thr = min(self.i_thr, max(0.0, tmax - ff - thr_p))
        if thr < tmin:
            self.i_thr = max(self.i_thr, min(0.0, tmin - ff - thr_p))
        self.thr = clamp(thr, tmin, tmax)
        # ---------------- pitch
        SEB_dem = SPE_dem * spe_w - SKE_dem * ske_w
        SEB = SPE * spe_w - SKE * ske_w
        SEBdot_dem = SPEdot_dem * spe_w - SKEdot_dem * ske_w
        SEBdot = SPEdot * spe_w - SKEdot * ske_w
        seb_err = SEB_dem - SEB
        self.seb_err = seb_err
        gain_inv = max(v, 5.0) * G
        p_raw = (seb_err / self.tau + SEBdot_dem + self.pitch_damp * (SEBdot_dem - SEBdot)) / gain_inv
        self.i_pitch = clamp(self.i_pitch + seb_err * self.ki / gain_inv * dt, -0.2, 0.2)
        pitch = p_raw + self.i_pitch
        if pitch > pmax:
            self.i_pitch = min(self.i_pitch, max(0.0, pmax - p_raw))
        if pitch < pmin:
            self.i_pitch = max(self.i_pitch, min(0.0, pmin - p_raw))
        self.pitch = clamp(pitch, pmin, pmax)
        return self.thr, self.pitch


# ======================================================================= inner loops
class AttitudeController:
    def __init__(self, cfg: dict, v_ref: float):
        self.r = cfg["roll"]
        self.p = cfg["pitch"]
        self.y = cfg["yaw"]
        self.v_ref = v_ref
        self.i_roll = 0.0
        self.i_pitch = 0.0

    def scaler(self, v):
        # surface effectiveness ~ q; cap the gain increase at low speed to avoid overshoot
        return clamp((self.v_ref / max(v, 5.0)) ** 2, 0.4, 2.0)

    def reset_integrators(self):
        self.i_roll = 0.0
        self.i_pitch = 0.0

    def roll(self, dt, phi_cmd, phi, p, v, integrate=True):
        s = self.scaler(v)
        e = phi_cmd - phi
        if integrate:
            self.i_roll = clamp(self.i_roll + self.r["ki"] * e * dt, -0.2, 0.2)
        return clamp(s * (self.r["kp"] * e + self.i_roll - self.r["rate_kd"] * p), -1.0, 1.0)

    def pitch(self, dt, theta_cmd, theta, q, phi, v, integrate=True):
        s = self.scaler(v)
        e = theta_cmd - theta
        # turn compensation: extra nose-up rate needed in a banked turn
        q_ff = G / max(v, 5.0) * math.tan(clamp(phi, -1.2, 1.2)) * math.sin(phi)
        if integrate:
            self.i_pitch = clamp(self.i_pitch + self.p["ki"] * e * dt, -0.4, 0.4)
        # +elevator = nose down  => elevator = -(kp e + i) + kd (q - q_ff)
        return clamp(self.p["trim_elev"] + s * (-(self.p["kp"] * e) - self.i_pitch
                                               + self.p["rate_kd"] * (q - q_ff)), -1.0, 1.0)

    def yaw(self, beta, r, phi, v, ail_cmd):
        s = self.scaler(v)
        r_ff = G * math.tan(clamp(phi, -1.2, 1.2)) / max(v, 5.0)
        # +rudder = nose left. Positive beta (wind from the right) needs nose right -> -rudder.
        return clamp(s * (-self.y["k_beta"] * beta + self.y["k_r"] * (r - r_ff))
                     - self.y["k_ff_ail"] * ail_cmd, -1.0, 1.0)


class GroundSteering:
    """Runway centre-line tracking with rudder + tail wheel (same sign sense)."""

    def __init__(self, cfg: dict):
        self.kp = cfg["kp"]
        self.kd = cfg["kd"]

    def update(self, psi, r, psi_rw, xtrack_right_m):
        # desired heading correction towards the centre line (limited to 10 deg)
        psi_cmd = psi_rw - clamp(0.08 * xtrack_right_m, -10 * DEG, 10 * DEG)
        err = wrap_pi(psi_cmd - psi)
        # need nose right (err>0) -> negative rudder/steer
        return clamp(-(self.kp * err) + self.kd * r, -1.0, 1.0)
