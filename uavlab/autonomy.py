"""Autonomy layer: flight-mode state machine and real-time decisions.

Modes
  PREFLIGHT -> TAKEOFF_ROLL -> ROTATE -> CLIMB_OUT -> MISSION -> APPROACH -> FLARE
  -> ROLLOUT -> LANDED            (GO_AROUND loops back to APPROACH)
Terminal: LANDED (success), NO_GO, CRASHED, TIMEOUT.

Decisions (each logged as an event with its reason and the data behind it)
  D1 runway selection (into wind)       D2 go / no-go on wind limits
  D3 waypoint sequencing                 D4 energy reserve (SOC, cell voltage) -> RTL / land now
  D5 wind-aware energy feasibility: predicted SOC at touchdown for the rest of
     the route, using the estimated wind and the measured cruise power -> early RTL
  D6 geofence -> RTL                     D7 go-around on a bad approach
  D8 battery depleted -> glide approach  Policy plug-in: airspeed/altitude set-points in MISSION
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from .control import TECS, AttitudeController, GroundSteering, L1Guidance, clamp
from .mission import Mission
from .sensors import WindEstimator
from .units import DEG, wrap_pi

TERMINAL = {"LANDED", "NO_GO", "CRASHED", "TIMEOUT"}


@dataclass
class Commands:
    ail: float = 0.0
    elev: float = 0.0
    rud: float = 0.0
    steer: float = 0.0
    thr: float = 0.0


@dataclass
class Setpoints:
    mode: str = "PREFLIGHT"
    phase: str = ""
    leg: int = -1
    leg_name: str = ""
    phi_cmd: float = 0.0
    theta_cmd: float = 0.0
    h_cmd: float = 0.0
    v_cmd: float = 0.0
    xtrack: float = 0.0
    wp_dist: float = 0.0
    pred_soc_landing: float = float("nan")
    policy_v: float = float("nan")


class Autopilot:
    def __init__(self, cfg: dict, mission: Mission, policy, log_event):
        self.cfg = cfg
        self.mission = mission
        self.policy = policy
        self.ev = log_event
        cc = cfg["controller"]
        self.l1 = L1Guidance(cc["l1"]["period_s"], cc["l1"]["damping"], cc["roll_limit_deg"])
        self.tecs = TECS(cc["tecs"], cc["pitch_limit_deg"])
        self.att = AttitudeController(cc, v_ref=mission.cruise_v)
        self.steer = GroundSteering(cc["ground_steer"])
        we = cfg["autonomy"]["wind_estimator"]
        self.west = WindEstimator(we["tau_s"], we.get("tau_mean_s", 60.0), we.get("gust_window_s", 30.0))
        self._d5_count = 0
        self.to = cfg["mission"]["takeoff"]
        self.ld = cfg["mission"]["landing"]
        self.res = cfg["mission"]["reserve"]
        self.fence = cfg["mission"]["geofence"]
        self.lim = cfg["aircraft"]["limits"]
        self.mode = "PREFLIGHT"
        self.sp = Setpoints()
        self.cmd = Commands()
        self.t_mode = 0.0
        self.legs = []
        self.leg = 0
        self.phase = ""
        self.go_arounds = 0
        self.rtl_reason = ""
        self.ap_points = {}
        self.theta_cmd_prev = 0.0
        self._last_decision_t = -1e9
        self._p_cruise_ema = None
        self._flare = {}
        self.depleted_handled = False
        self.success = None

    # ------------------------------------------------------------------ helpers
    def set_mode(self, t, mode, reason="", **data):
        if mode == self.mode:
            return
        self.ev(t, "mode", f"{self.mode}->{mode}", reason=reason, **data)
        self.mode = mode
        self.t_mode = t
        if mode in ("CLIMB_OUT", "GO_AROUND"):
            self.att.reset_integrators()

    # ------------------------------------------------------- D1/D2 pre-flight
    def preflight_decision(self, t, wind_report_ne: np.ndarray) -> bool:
        rw, why = self.mission.choose_runway(wind_report_ne)
        spd = float(np.hypot(*wind_report_ne))
        head = -float(wind_report_ne @ rw.u)
        cross = float(abs(wind_report_ne[0] * rw.u[1] - wind_report_ne[1] * rw.u[0]))
        self.ev(t, "decision", "D1_runway", heading_deg=round(math.degrees(rw.heading) % 360, 1),
                reason=why, headwind_mps=round(head, 2), crosswind_mps=round(cross, 2))
        limit = float(self.cfg["autonomy"]["wind_limits"]["max_mean_mps"])
        xlim = float(self.to["max_crosswind_mps"])
        if spd > limit or cross > xlim:
            self.ev(t, "decision", "D2_no_go", wind_mps=round(spd, 2), crosswind_mps=round(cross, 2),
                    limit_mps=limit, crosswind_limit_mps=xlim)
            self.mode = "NO_GO"
            self.success = False
            return False
        self.ev(t, "decision", "D2_go", wind_mps=round(spd, 2), crosswind_mps=round(cross, 2))
        self.legs = self.mission.legs()
        self.ap_points = self.mission.approach_points()
        return True

    # ------------------------------------------------------ D5 energy predict
    def predict_landing_soc(self, m, energy, wind_ne, pos_ne) -> float:
        """Predicted SOC at touchdown if the remaining route is flown now.
        Energy/time per leg = P_cruise / V_ground(leg), with V_ground from the
        estimated wind; plus the return to the approach and a fixed approach cost."""
        if self._p_cruise_ema is None:
            return float("nan")
        va = max(self.sp.v_cmd, 1.0)
        pts = [np.asarray(pos_ne)]
        if self.mode == "MISSION":
            pts += [np.asarray(l[2]) for l in self.legs[self.leg:]]
        pts += [self.ap_points["align"], self.ap_points["entry"], self.ap_points["td"]]
        e_j = 0.0
        for a, b in zip(pts[:-1], pts[1:]):
            d = float(np.hypot(*(b - a)))
            if d < 1.0:
                continue
            trk = math.atan2(b[1] - a[1], b[0] - a[0])
            wa, wc = WindEstimator.along_cross(wind_ne, trk)
            vg = math.sqrt(max(va * va - wc * wc, 1.0)) + wa
            if vg < 2.0:
                return 0.0
            e_j += self._p_cruise_ema * d / vg
        e_total_j = energy["capacity_j"]
        return energy["soc"] - e_j / e_total_j

    # ------------------------------------------------------------------ update
    def update(self, t, dt, m, energy, pos_ne, wind_report_ne=None) -> tuple[Commands, Setpoints]:
        mode = self.mode
        sp, cmd = self.sp, self.cmd
        airborne = not m["wow"]
        wind = self.west.update(m, dt, airborne and mode not in ("PREFLIGHT", "TAKEOFF_ROLL"))
        v, h = m["tas"], m["h"]
        hdot = -m["vd"]
        vel_ne = np.array([m["vn"], m["ve"]])
        rw = self.mission.runway
        sp.mode = mode

        if mode in TERMINAL:
            cmd.thr, cmd.ail, cmd.rud, cmd.steer = 0.0, 0.0, 0.0, 0.0
            cmd.elev = -1.0 if mode == "LANDED" else 0.0
            return cmd, sp

        # ---------------------------------------------- energy / safety decisions
        if mode in ("MISSION", "CLIMB_OUT") and t - self._last_decision_t >= 1.0:
            self._last_decision_t = t
            if mode == "MISSION":
                p = energy["p_batt"]
                self._p_cruise_ema = p if self._p_cruise_ema is None else self._p_cruise_ema + 0.05 * (p - self._p_cruise_ema)
            reason = None
            if energy["soc"] < self.res["land_now_soc"]:
                reason = ("D4_land_now_soc", {"soc": round(energy["soc"], 3)})
            elif energy["soc"] < self.res["rtl_soc"]:
                reason = ("D4_rtl_soc", {"soc": round(energy["soc"], 3)})
            elif energy["v_cell"] is not None and energy["v_cell"] < self.res["min_cell_voltage_v"]:
                reason = ("D4_rtl_cell_voltage", {"v_cell": round(energy["v_cell"], 3)})
            elif float(np.hypot(*pos_ne)) > self.fence["radius_m"] or h > self.fence["max_alt_agl_m"] + 20:
                reason = ("D6_geofence", {"dist_m": round(float(np.hypot(*pos_ne)), 1), "h_m": round(h, 1)})
            elif mode == "MISSION":
                # D5 uses the slow (mean) wind estimate and must persist for N s
                ps = self.predict_landing_soc(m, energy, self.west.w_mean, pos_ne)
                sp.pred_soc_landing = ps
                min_ls = float(self.res.get("min_landing_soc", 0.15))
                self._d5_count = self._d5_count + 1 if (not math.isnan(ps) and ps < min_ls) else 0
                if self._d5_count >= int(self.res.get("d5_persist_s", 10)):
                    reason = ("D5_energy_insufficient", {"pred_soc_landing": round(ps, 3),
                                                        "min_landing_soc": min_ls,
                                                        "wind_mean_est_ne": [round(float(x), 2) for x in self.west.w_mean]})
            if reason:
                self.ev(t, "decision", reason[0], **reason[1])
                self.rtl_reason = reason[0]
                self.phase = "to_align"
                self.set_mode(t, "APPROACH", reason[0])
                mode = "APPROACH"
        if energy["depleted"] and not self.depleted_handled:
            self.depleted_handled = True
            self.ev(t, "decision", "D8_battery_depleted", soc=round(energy["soc"], 3),
                    reason=energy["depleted_reason"])
            if mode in ("MISSION", "CLIMB_OUT", "GO_AROUND"):
                self.phase = "to_align"
                self.set_mode(t, "APPROACH", "battery_depleted")
                mode = "APPROACH"

        # ------------------------------------------------------------- modes
        if mode == "PREFLIGHT":
            cmd.thr, cmd.ail, cmd.rud, cmd.steer, cmd.elev = 0.0, 0.0, 0.0, 0.0, -0.3
            return cmd, sp

        if mode == "TAKEOFF_ROLL":
            cmd.thr = clamp((t - self.t_mode) / 1.5, 0.0, 1.0)
            xt = self.mission.runway_xtrack_right(pos_ne)
            cmd.steer = cmd.rud = self.steer.update(m["psi"], m["r"], rw.heading, xt)
            cmd.ail = self.att.roll(dt, 0.0, m["phi"], m["p"], v, integrate=False)
            if v < self.to["tail_up_speed_mps"]:
                cmd.elev = -0.2
                self.theta_cmd_prev = m["theta"]
            else:
                # tail up: hold ~3 deg attitude (low angle of attack) until rotation speed
                self.theta_cmd_prev = 3.0 * DEG
                cmd.elev = self.att.pitch(dt, self.theta_cmd_prev, m["theta"], m["q"], 0.0, v, integrate=False)
            sp.theta_cmd, sp.v_cmd, sp.xtrack = self.theta_cmd_prev, self.to["rotate_speed_mps"], xt
            if v >= self.to["rotate_speed_mps"]:
                self.set_mode(t, "ROTATE", "rotate_speed", tas=round(v, 2))
            elif t - self.t_mode > 25.0 or self.mission.runway_along(pos_ne) > rw.length + 20:
                self.ev(t, "decision", "D2_abort_takeoff", tas=round(v, 2))
                self.set_mode(t, "NO_GO", "takeoff_abort")
                self.success = False
            return cmd, sp

        if mode == "ROTATE":
            cmd.thr = 1.0
            th = 9.0 * DEG
            if self.theta_cmd_prev < m["theta"] - 4 * DEG:
                self.theta_cmd_prev = m["theta"] - 4 * DEG
            self.theta_cmd_prev += clamp(th - self.theta_cmd_prev, -6 * DEG * dt, 6 * DEG * dt)
            cmd.elev = self.att.pitch(dt, self.theta_cmd_prev, m["theta"], m["q"], m["phi"], v)
            xt = self.mission.runway_xtrack_right(pos_ne)
            if m["wow"]:
                cmd.steer = cmd.rud = self.steer.update(m["psi"], m["r"], rw.heading, xt)
                cmd.ail = self.att.roll(dt, 0.0, m["phi"], m["p"], v, integrate=False)
            else:
                cmd.steer = 0.0
                cmd.ail = self.att.roll(dt, 0.0, m["phi"], m["p"], v)
                cmd.rud = self.att.yaw(m["beta"], m["r"], m["phi"], v, cmd.ail)
            sp.theta_cmd, sp.xtrack = self.theta_cmd_prev, xt
            if not m["wow"] and h > 3.0:
                self.tecs.reset(h, v)
                self.tecs.pitch = self.theta_cmd_prev
                self.set_mode(t, "CLIMB_OUT", "airborne", h=round(h, 2), tas=round(v, 2))
            return cmd, sp

        if mode == "CLIMB_OUT":
            A, B = rw.start, self.mission.climbout_point()
            lim = 12 * DEG if h < 12 else self.l1.roll_lim
            phi_c = clamp(self.l1.line(pos_ne, vel_ne, A, B), -lim, lim)
            safe = float(self.to["safe_alt_agl_m"])
            thr, th_c = self.tecs.update(dt, h, hdot, m["tas"], safe + 10.0, float(self.to["climb_airspeed_mps"]), ax=m["ax"], theta=m["theta"],
                                         w_spd=2.0, thr_min=1.0, thr_max=1.0,
                                         pitch_max=float(self.to["climb_pitch_max_deg"]) * DEG,
                                         underspeed_v=1.1 * self.lim["stall_speed_mps"])
            self._inner(dt, m, phi_c, th_c, thr, v)
            sp.phi_cmd, sp.theta_cmd, sp.h_cmd, sp.v_cmd, sp.xtrack = phi_c, th_c, safe, self.to["climb_airspeed_mps"], self.l1.xtrack
            if h >= safe:
                self.leg = 0
                self.set_mode(t, "MISSION", "safe_altitude", h=round(h, 1))
                self.ev(t, "waypoint", "leg_start", leg=0, name=self.legs[0][0])
            return cmd, sp

        if mode == "MISSION":
            name, A, B, alt, vleg = self.legs[self.leg]
            v_c = float(vleg) if vleg else self.mission.cruise_v
            h_c = alt
            # ---- policy plug-in (online optimiser / RL action / baseline)
            if self.policy is not None:
                trk = math.atan2(B[1] - A[1], B[0] - A[0])
                wa, wc = WindEstimator.along_cross(wind, trk)
                wam, wcm = WindEstimator.along_cross(self.west.w_mean, trk)
                obs = {"t": t, "tas": v, "gs": m["gs"], "h": h, "soc": energy["soc"], "p_batt": energy["p_batt"],
                       "wind_ne": wind.copy(), "wind_mean_ne": self.west.w_mean.copy(),
                       "gust_sigma": self.west.gust_sigma, "tailwind_mean": wam, "crosswind_mean": wcm,
                       "tailwind": wa, "crosswind": wc, "leg": self.leg,
                       "leg_track": trk, "dist_to_wp": float(np.hypot(*(B - pos_ne))),
                       "v_default": v_c, "h_default": h_c}
                out = self.policy.update(obs) or {}
                if out.get("airspeed_mps") is not None:
                    v_c = float(out["airspeed_mps"])
                    sp.policy_v = v_c
                if out.get("alt_agl_m") is not None:
                    h_c = float(out["alt_agl_m"])
            vmin = 1.3 * self.lim["stall_speed_mps"]
            v_c = clamp(v_c, vmin, self.lim["vne_mps"] * 0.85)
            h_c = clamp(h_c, 20.0, self.fence["max_alt_agl_m"])
            phi_c = self.l1.line(pos_ne, vel_ne, A, B)
            thr, th_c = self.tecs.update(dt, h, hdot, m["tas"], h_c, v_c, ax=m["ax"], theta=m["theta"], underspeed_v=1.1 * self.lim["stall_speed_mps"])
            self._inner(dt, m, phi_c, th_c, thr, v)
            dist = float(np.hypot(*(B - pos_ne)))
            ab = (B - A) / max(float(np.hypot(*(B - A))), 1e-3)
            passed = float((pos_ne - B) @ ab) > 0.0
            sp.leg, sp.leg_name, sp.wp_dist = self.leg, name, dist
            sp.phi_cmd, sp.theta_cmd, sp.h_cmd, sp.v_cmd, sp.xtrack = phi_c, th_c, h_c, v_c, self.l1.xtrack
            radius = self.mission.waypoints[self.leg].radius if self.leg < len(self.mission.waypoints) else 40.0
            # turn anticipation: start the turn when the distance to the waypoint
            # equals the turn-arc tangent length R*tan(dchi/2) for the next leg
            if self.leg + 1 < len(self.legs):
                A2, B2 = self.legs[self.leg + 1][1], self.legs[self.leg + 1][2]
                chi1 = math.atan2(B[1] - A[1], B[0] - A[0])
                chi2 = math.atan2(B2[1] - A2[1], B2[0] - A2[0])
                dchi = abs(wrap_pi(chi2 - chi1))
                R = max(m["gs"], v) ** 2 / (9.80665 * math.tan(0.8 * self.l1.roll_lim))
                radius = max(radius, min(R * math.tan(min(dchi, 2.6) / 2.0), 4 * R))
            if dist < radius or passed:
                self.ev(t, "waypoint", "reached", leg=self.leg, name=name, dist_m=round(dist, 1),
                        by="radius" if dist < radius else "passed")
                self.leg += 1
                if self.leg >= len(self.legs):
                    self.phase = "to_align"
                    self.rtl_reason = "mission_complete"
                    self.set_mode(t, "APPROACH", "mission_complete")
                else:
                    self.ev(t, "waypoint", "leg_start", leg=self.leg, name=self.legs[self.leg][0])
            return cmd, sp

        if mode in ("APPROACH", "GO_AROUND"):
            return self._approach(t, dt, m, pos_ne, vel_ne, energy)

        if mode == "FLARE":
            return self._flare_update(t, dt, m, pos_ne, vel_ne)

        if mode == "ROLLOUT":
            cmd.thr = 0.0
            xt = self.mission.runway_xtrack_right(pos_ne)
            # bounce handling: airborne again after touchdown
            if not m["wow"] and h > 0.5:
                self._bounce_t = getattr(self, "_bounce_t", None) or t
            else:
                self._bounce_t = None
            if self._bounce_t is not None and t - self._bounce_t > 0.3:
                self._bounce_t = None
                if h > 2.0 and not energy["depleted"] and self.go_arounds < int(self.ld["max_go_arounds"]):
                    self.go_arounds += 1
                    self.ev(t, "decision", "D7_go_around", why="bounce", h=round(h, 2), count=self.go_arounds)
                    self.tecs.reset(h, v)
                    self.set_mode(t, "GO_AROUND", "bounce")
                else:
                    self._flare = {"theta0": max(m["theta"], 2 * DEG), "sink0": max(-hdot, 0.3), "h0": max(h, 0.5),
                                   "i": 0.0}
                    self.ev(t, "decision", "D7_reflare", why="bounce", h=round(h, 2))
                    self.set_mode(t, "FLARE", "bounce")
                return cmd, sp
            # wheel landing: keep the attitude low while fast, pin the tail when slow
            tail_v = float(self.ld.get("tail_down_speed_mps", 9.0))
            if v > tail_v:
                cmd.elev = self.att.pitch(dt, 2.0 * DEG, m["theta"], m["q"], 0.0, v, integrate=False)
            else:
                cmd.elev = max(-1.0, self.cmd.elev - 0.5 * dt)
            cmd.steer = cmd.rud = self.steer.update(m["psi"], m["r"], rw.heading, xt)
            cmd.ail = self.att.roll(dt, 0.0, m["phi"], m["p"], v, integrate=False)
            sp.xtrack = xt
            if m["gs"] < 0.5:
                self.success = True
                self.set_mode(t, "LANDED", "stopped", along_m=round(self.mission.runway_along(pos_ne), 1),
                              xtrack_m=round(xt, 2))
            return cmd, sp
        raise RuntimeError(f"unhandled mode {mode}")

    # --------------------------------------------------------------- inner loop
    def _inner(self, dt, m, phi_c, th_c, thr, v, integrate=True):
        c = self.cmd
        tc = self.cfg["controller"]["throttle"]
        slew = float(tc["slew_per_s"]) * dt
        tau = float(tc.get("filter_tau_s", 0.0))
        if tau > 0:
            thr = c.thr + dt / (tau + dt) * (thr - c.thr)
        thr = clamp(thr, c.thr - slew, c.thr + slew)
        c.ail = self.att.roll(dt, phi_c, m["phi"], m["p"], v, integrate)
        c.elev = self.att.pitch(dt, th_c, m["theta"], m["q"], m["phi"], v, integrate)
        c.rud = self.att.yaw(m["beta"], m["r"], m["phi"], v, c.ail)
        c.steer = 0.0
        c.thr = thr

    # ------------------------------------------------------------------ approach
    def _approach(self, t, dt, m, pos_ne, vel_ne, energy):
        sp, ap, ld = self.sp, self.ap_points, self.ld
        v, h, hdot = m["tas"], m["h"], -m["vd"]
        pat = float(ld["pattern_alt_agl_m"])
        va = float(ld["approach_airspeed_mps"]) + getattr(self, "_va_add", 0.0)
        motor_ok = not energy["depleted"]
        if self.mode == "GO_AROUND":
            A, B = self.mission.runway.start, self.mission.climbout_point()
            phi_c = self.l1.line(pos_ne, vel_ne, A, B)
            thr, th_c = self.tecs.update(dt, h, hdot, m["tas"], pat + 15.0, float(self.to["climb_airspeed_mps"]), ax=m["ax"], theta=m["theta"],
                                         w_spd=2.0, thr_min=1.0, thr_max=1.0,
                                         underspeed_v=1.1 * self.lim["stall_speed_mps"])
            self._inner(dt, m, phi_c, th_c, thr, v)
            sp.phi_cmd, sp.theta_cmd, sp.h_cmd, sp.v_cmd = phi_c, th_c, pat + 15, self.to["climb_airspeed_mps"]
            if h > pat:
                self.phase = "to_align"
                self.set_mode(t, "APPROACH", "go_around_complete")
            return self.cmd, sp

        if self.phase == "to_align":
            if not hasattr(self, "_to_align_A") or self._to_align_t != self.t_mode:
                # latch the start point and altitude of the return leg
                self._to_align_A, self._to_align_t = np.array(pos_ne, float), self.t_mode
                self._to_align_h = max(pat, min(h, self.mission.cruise_h))
            A, B = self._to_align_A, ap["align"]
            h_c, v_c = self._to_align_h, self.mission.cruise_v
            if np.hypot(*(B - pos_ne)) < 80.0 or float((pos_ne - B) @ ((B - A) / max(np.hypot(*(B - A)), 1))) > 0:
                self.phase = "align"
                self.ev(t, "approach", "align_reached")
        if self.phase == "align":
            A, B = ap["align"], ap["entry"]
            h_c, v_c = pat, va + 1.5
            if float((pos_ne - B) @ self.mission.runway.u) > 0:
                self.phase = "final"
                # D9: add half the gust factor (2 sigma) to the approach speed, capped
                # remove the estimator's own noise floor (sensor errors) before using it
                floor = float(ld.get("gust_noise_floor_mps", 0.4))
                sig = math.sqrt(max(self.west.gust_sigma ** 2 - floor ** 2, 0.0))
                gf = 2.0 * sig
                self._va_add = min(0.5 * gf * float(ld.get("gust_additive_gain", 1.0)),
                                   float(ld.get("gust_additive_max_mps", 3.0)))
                self.ev(t, "approach", "final", h=round(h, 1), xtrack_m=round(self.l1.xtrack, 1))
                if self._va_add > 0.3:
                    self.ev(t, "decision", "D9_gust_approach_speed", gust_sigma_mps=round(self.west.gust_sigma, 2),
                            add_mps=round(self._va_add, 2), v_app_mps=round(float(ld["approach_airspeed_mps"]) + self._va_add, 2))
        if self.phase == "final":
            A, B = ap["entry"], ap["td"] + 400.0 * self.mission.runway.u
            h_c, v_c = self.mission.glide_path_alt(pos_ne), va
        phi_c = self.l1.line(pos_ne, vel_ne, A, B)
        kw = {}
        if not motor_ok:
            kw = dict(thr_min=0.0, thr_max=0.0, w_spd=2.0)
        if self.phase == "final":
            phi_c = clamp(phi_c, -20 * DEG, 20 * DEG)
        thr, th_c = self.tecs.update(dt, h, hdot, m["tas"], h_c, v_c, ax=m["ax"], theta=m["theta"], underspeed_v=1.1 * self.lim["stall_speed_mps"], **kw)
        self._inner(dt, m, phi_c, th_c, thr, v)
        sp.phase = self.phase
        sp.phi_cmd, sp.theta_cmd, sp.h_cmd, sp.v_cmd, sp.xtrack = phi_c, th_c, h_c, v_c, self.l1.xtrack
        sp.wp_dist = float(np.hypot(*(ap["td"] - pos_ne)))
        if self.phase == "final":
            # D7 go-around
            bad_x = abs(self.l1.xtrack) > float(ld["go_around_xtrack_m"]) and h < 15.0
            bad_h = h < 8.0 and (h_c - h) > 6.0
            long = self.mission.runway_along(pos_ne) > self.mission.runway.length * 0.6 and h > 2.0
            if (bad_x or bad_h or long) and motor_ok and self.go_arounds < int(ld["max_go_arounds"]):
                self.go_arounds += 1
                why = "xtrack" if bad_x else ("low" if bad_h else "long")
                self.ev(t, "decision", "D7_go_around", why=why, xtrack_m=round(self.l1.xtrack, 1), h=round(h, 1),
                        count=self.go_arounds)
                self.tecs.reset(h, v)
                self.set_mode(t, "GO_AROUND", why)
                return self.cmd, sp
            if h < float(ld["flare_height_m"]):
                self._flare = {"theta0": m["theta"], "sink0": max(-hdot, 0.3), "h0": h, "i": 0.0}
                self.set_mode(t, "FLARE", "flare_height", h=round(h, 2), sink_mps=round(-hdot, 2), tas=round(v, 2))
        return self.cmd, sp

    def _flare_update(self, t, dt, m, pos_ne, vel_ne):
        sp, cmd, ld, f = self.sp, self.cmd, self.ld, self._flare
        v, h, hdot = m["tas"], m["h"], -m["vd"]
        rw = self.mission.runway
        # exponential flare: target sink rate proportional to height, floored
        hdot_c = -max(float(ld["flare_sink_rate_mps"]), f["sink0"] * max(h, 0.0) / f["h0"])
        err = hdot_c - hdot                      # >0: sinking too fast -> pitch up
        f["i"] = clamp(f["i"] + 0.05 * err * dt, -0.1, 0.15)
        th_c = clamp(f["theta0"] + 0.10 * err + f["i"], -2 * DEG, 12 * DEG)
        # power-assisted flare: throttle only arrests excess sink (down-gusts); idle otherwise
        k_thr = float(ld.get("flare_throttle_gain", 0.35))
        cmd.thr = clamp(k_thr * err, 0.0, 0.5) if not self.depleted_handled else 0.0
        A, B = rw.start, rw.end + 400 * rw.u
        # near the ground wings-level has priority over the centre line (wing-tip clearance ~17 deg)
        phi_c = clamp(0.5 * self.l1.line(pos_ne, vel_ne, A, B), -5 * DEG, 5 * DEG)
        cmd.ail = self.att.roll(dt, phi_c, m["phi"], m["p"], v)
        cmd.elev = self.att.pitch(dt, th_c, m["theta"], m["q"], m["phi"], v)
        if h < 1.5:
            # de-crab: align the nose with the runway before touchdown
            cmd.rud = clamp(-1.5 * wrap_pi(rw.heading - m["psi"]) + 0.2 * m["r"], -1.0, 1.0)
        else:
            cmd.rud = self.att.yaw(m["beta"], m["r"], m["phi"], v, cmd.ail)
        cmd.steer = cmd.rud
        sp.phi_cmd, sp.theta_cmd, sp.h_cmd, sp.xtrack = phi_c, th_c, h, self.l1.xtrack
        if m["wow"]:
            self.set_mode(t, "ROLLOUT", "touchdown", sink_mps=round(-hdot, 2), tas=round(v, 2),
                          along_m=round(self.mission.runway_along(pos_ne), 1),
                          xtrack_m=round(self.mission.runway_xtrack_right(pos_ne), 2))
        return cmd, sp
