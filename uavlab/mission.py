"""Mission layer: waypoints, runway geometry and the landing pattern.

Local frame: NED with origin at `mission.home` (runway centre, field elevation).
Waypoints may be given as local offsets (n_m, e_m) or lat/lon; altitudes are AGL.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from .geo import LocalFrame
from .units import DEG


@dataclass
class Waypoint:
    name: str
    ne: np.ndarray
    alt_agl: float
    airspeed: float | None = None
    radius: float = 40.0


@dataclass
class Runway:
    heading: float                 # rad, direction of take-off/landing roll
    length: float
    width: float

    @property
    def u(self):
        return np.array([math.cos(self.heading), math.sin(self.heading)])

    @property
    def start(self):               # threshold at the beginning of the roll
        return -0.5 * self.length * self.u

    @property
    def end(self):
        return 0.5 * self.length * self.u


class Mission:
    def __init__(self, cfg: dict):
        mc = cfg["mission"]
        self.cfg = mc
        h = mc["home"]
        self.frame = LocalFrame(h["lat_deg"], h["lon_deg"], h["alt_msl_m"])
        self.field_elev = float(h["alt_msl_m"])
        self.cruise_v = float(mc["cruise"]["airspeed_mps"])
        self.cruise_h = float(mc["cruise"]["alt_agl_m"])
        self.accept = float(mc.get("acceptance_radius_m", 40.0))
        wps = []
        for i, w in enumerate(mc["waypoints"]):
            if "n_m" in w:
                ne = np.array([float(w["n_m"]), float(w["e_m"])])
            else:
                ne = self.frame.to_ned(w["lat_deg"], w["lon_deg"], self.field_elev)[:2]
            wps.append(Waypoint(w.get("name", f"WP{i + 1}"), ne, float(w.get("alt_agl_m", self.cruise_h)),
                                w.get("airspeed_mps"), float(w.get("acceptance_radius_m", self.accept))))
        self.waypoints = wps * int(mc.get("repeat", 1))
        self.runway: Runway | None = None
        self.landing = mc["landing"]

    # ----------------------------------------------------------------- runway
    def choose_runway(self, wind_ne: np.ndarray) -> tuple[Runway, str]:
        rc = self.cfg["runway"]
        heads = [float(x) for x in rc["headings_deg"]]
        if rc.get("selection", "into_wind") == "into_wind" and np.hypot(*wind_ne) > 0.5:
            # headwind component = -(wind . u); pick the largest
            best = max(heads, key=lambda hd: -(wind_ne @ np.array([math.cos(hd * DEG), math.sin(hd * DEG)])))
            reason = "into_wind"
        else:
            best, reason = heads[0], "first_listed"
        self.runway = Runway(best * DEG, float(rc["length_m"]), float(rc["width_m"]))
        return self.runway, reason

    # ------------------------------------------------------------- geometry
    def runway_xtrack_right(self, ne) -> float:
        rw = self.runway
        d = np.asarray(ne) - rw.start
        u = rw.u
        return float(d[1] * u[0] - d[0] * u[1])

    def runway_along(self, ne) -> float:
        rw = self.runway
        return float((np.asarray(ne) - rw.start) @ rw.u)

    def touchdown_point(self) -> np.ndarray:
        return self.runway.start + float(self.landing["touchdown_point_m"]) * self.runway.u

    def glide_distance(self) -> float:
        """Horizontal distance from the glide-path start (pattern altitude) to touchdown."""
        return float(self.landing["pattern_alt_agl_m"]) / math.tan(float(self.landing["glide_slope_deg"]) * DEG)

    def approach_points(self) -> dict:
        """Points of the straight-in approach, all on the extended centre line."""
        u = self.runway.u
        td = self.touchdown_point()
        d_gs = self.glide_distance()
        faf = td - d_gs * u                                  # glide path starts here
        entry = faf - float(self.landing["final_length_m"]) * u   # join the centre line here
        align = entry - 250.0 * u                            # line-up point before entry
        return {"td": td, "faf": faf, "entry": entry, "align": align}

    def glide_path_alt(self, ne) -> float:
        """Glide-path altitude (AGL) above the point's projection on the centre line."""
        td = self.touchdown_point()
        dist_to_td = float((td - np.asarray(ne)) @ self.runway.u)
        h = math.tan(float(self.landing["glide_slope_deg"]) * DEG) * max(dist_to_td, 0.0)
        return min(h, float(self.landing["pattern_alt_agl_m"]))

    def climbout_point(self) -> np.ndarray:
        return self.runway.end + 300.0 * self.runway.u

    def legs(self) -> list[tuple[str, np.ndarray, np.ndarray, float, float | None]]:
        """(name, A, B, alt, airspeed) for every mission leg after climb-out."""
        out = []
        prev = self.climbout_point()
        for w in self.waypoints:
            out.append((w.name, prev, w.ne, w.alt_agl, w.airspeed))
            prev = w.ne
        return out
