"""Gymnasium environment: the agent acts at the autonomy layer (airspeed and
altitude set-points in MISSION mode) on top of the full pipeline; take-off,
approach and landing stay with the autopilot, so learning cannot crash the
aircraft through low-level control.

Episode: reset() flies the take-off and climb, then hands control over at the
first mission leg. Each step() advances `decision_dt_s` of simulated time.
The episode terminates when the mission is complete (or the autonomy layer
aborts it: reserve/geofence/crash); optionally the landing is then simulated so
the run's logs are complete.

Reward (per step): -(battery energy used in the step, Wh) / e_scale
                   + terminal bonus on mission completion, penalty on crash/abort.
Because the route is fixed, maximising the return = minimising the energy to fly it.

Observation (float32, roughly normalised):
  0 soc               1 tas/20            2 gs/20             3 h/100
  4 tailwind_mean/10  5 crosswind_mean/10 6 |wind_mean|/10    7 gust_sigma/5
  8 dist_to_wp/1000   9 route_fraction   10 p_batt/500       11 v_cmd/20
Action (float32 in [-1, 1]^2): airspeed in [v_min, v_max]; altitude offset +-alt_range_m.
"""
from __future__ import annotations

import math

import numpy as np

try:
    import gymnasium as gym
    from gymnasium import spaces
except ImportError as e:  # pragma: no cover
    raise ImportError("gymnasium is required for the RL environment: pip install gymnasium") from e

from .config import load_config, set_path
from .policies import ExternalPolicy
from .simulation import Simulation


class UAVEnergyEnv(gym.Env):
    metadata = {"render_modes": []}

    def __init__(self, scenario_files=("configs/missions/survey_box.yaml",), overrides=None,
                 decision_dt_s: float = 2.0, v_range=(12.0, 24.0), alt_range_m: float = 30.0,
                 randomize: dict | None = None, e_scale_wh: float = 1.0, success_bonus: float = 5.0,
                 fail_penalty: float = 50.0, finish_landing: bool = False, write_logs: bool = False,
                 log_dir: str = "runs_rl"):
        super().__init__()
        self.scenario_files = list(scenario_files)
        self.overrides = dict(overrides or {})
        self.decision_dt = decision_dt_s
        self.v_range = v_range
        self.alt_range = alt_range_m
        self.randomize = randomize or {}
        self.e_scale = e_scale_wh
        self.bonus, self.penalty = success_bonus, fail_penalty
        self.finish_landing = finish_landing
        self.write_logs = write_logs
        self.log_dir = log_dir
        self.observation_space = spaces.Box(-10.0, 10.0, shape=(12,), dtype=np.float32)
        self.action_space = spaces.Box(-1.0, 1.0, shape=(2,), dtype=np.float32)
        self.sim: Simulation | None = None
        self.policy = ExternalPolicy()
        self._episode = 0

    # --------------------------------------------------------------------------
    def _sample_overrides(self, rng: np.random.Generator) -> dict:
        ov = dict(self.overrides)
        for key, spec in self.randomize.items():
            if "uniform" in spec:
                lo, hi = spec["uniform"]
                ov[key] = float(rng.uniform(lo, hi))
            elif "choice" in spec:
                ov[key] = spec["choice"][int(rng.integers(len(spec["choice"])))]
        return ov

    def _obs(self) -> np.ndarray:
        s = self.sim
        ap, m = s.ap, s.m
        b = s.pt.battery
        wm = ap.west.w_mean
        leg = min(ap.leg, len(ap.legs) - 1)
        A, B = ap.legs[leg][1], ap.legs[leg][2]
        trk = math.atan2(B[1] - A[1], B[0] - A[0])
        wa, wc = ap.west.along_cross(wm, trk)
        dist = float(np.hypot(*(B - s.pos_ne)))
        o = [b.soc, m["tas"] / 20, m["gs"] / 20, m["h"] / 100, wa / 10, wc / 10, float(np.hypot(*wm)) / 10,
             ap.west.gust_sigma / 5, dist / 1000, ap.leg / max(len(ap.legs), 1), s.pt.s.p_batt_term / 500,
             ap.sp.v_cmd / 20]
        return np.clip(np.asarray(o, np.float32), -10, 10)

    def _advance(self, seconds: float):
        t_end = self.sim.t + seconds
        while self.sim.t < t_end - 1e-9:
            if not self.sim.step():
                break
            if self.sim.ap.mode != "MISSION":
                break

    # --------------------------------------------------------------------------
    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        self._episode += 1
        ov = self._sample_overrides(self.np_random)
        ov["sim.seed"] = int(self.np_random.integers(1, 2**31 - 1))
        cfg = load_config(*self.scenario_files, overrides=ov)
        cfg["logging"]["out_dir"] = self.log_dir
        self.policy = ExternalPolicy()
        self.sim = Simulation(cfg, policy=self.policy, write_logs=self.write_logs, keep_timeseries=False,
                              run_id=f"rl_ep{self._episode:05d}_{ov['sim.seed']}")
        # autopilot flies take-off and climb-out
        while self.sim.step() and self.sim.ap.mode != "MISSION":
            pass
        if self.sim.ap.mode != "MISSION":
            raise RuntimeError(f"episode could not reach MISSION mode (status {self.sim.status})")
        self._e_prev = self.sim.pt.battery.e_term / 3600.0
        return self._obs(), {"overrides": ov}

    def step(self, action):
        a = np.clip(np.asarray(action, np.float64), -1, 1)
        v = self.v_range[0] + (a[0] + 1) / 2 * (self.v_range[1] - self.v_range[0])
        leg = min(self.sim.ap.leg, len(self.sim.ap.legs) - 1)
        self.policy.airspeed_mps = float(v)
        self.policy.alt_agl_m = float(self.sim.ap.legs[leg][3] + a[1] * self.alt_range)
        self._advance(self.decision_dt)
        e_now = self.sim.pt.battery.e_term / 3600.0
        reward = -(e_now - self._e_prev) / self.e_scale
        self._e_prev = e_now
        mode, status = self.sim.ap.mode, self.sim.status
        terminated = truncated = False
        info = {"mode": mode, "status": status, "energy_Wh": e_now, "airspeed_cmd": v}
        if status == "CRASHED":
            reward -= self.penalty
            terminated = True
        elif status == "TIMEOUT":
            truncated = True
        elif mode != "MISSION":
            terminated = True
            if self.sim.ap.rtl_reason == "mission_complete":
                reward += self.bonus
                info["mission_complete"] = True
            else:
                reward -= self.penalty
                info["aborted"] = self.sim.ap.rtl_reason
        if (terminated or truncated) and self.finish_landing:
            while self.sim.step():
                pass
            info["final_status"] = self.sim.status
        if terminated or truncated:
            res = self.sim.finish()
            info["summary"] = res.summary
        return self._obs(), float(reward), terminated, truncated, info
