"""Parameter schema for the UI, derived from configs/defaults.yaml (single source
of truth): every leaf key becomes a typed field with label, unit (from the key
suffix), description and status tag (from the YAML comment), choices and limits.
Adding a key to defaults.yaml makes it appear in the UI automatically."""
from __future__ import annotations

import re
from pathlib import Path

import yaml

from ..config import DEFAULTS
from ..models import DATA

GROUPS = [
    ("sim", "Simulation", "Integration step, loop rates, duration and random seed."),
    ("aircraft", "Aircraft", "Mass, CG, inertia and aerodynamic calibration of the Rascal 110."),
    ("powertrain", "Powertrain", "Propeller, motor, ESC, battery and avionics loads."),
    ("atmosphere", "Atmosphere", "ISA offset, sea-level pressure and humidity."),
    ("wind", "Wind", "Mean wind, shear, time schedule, turbulence and discrete gusts."),
    ("mission", "Mission", "Home, runway, waypoints, take-off, landing, reserves and geofence."),
    ("autonomy", "Autonomy", "Adaptive policy plug-in, wind limits and wind estimator."),
    ("controller", "Controller", "L1 guidance, TECS and attitude loop gains."),
    ("actuators", "Actuators", "Servo and throttle dynamics."),
    ("sensors", "Sensors", "Navigation-estimate errors and inertial noise."),
    ("logging", "Logging", "Output format and location."),
]

UNIT_SUFFIX = [  # longest first
    ("_lbf_per_fps", "lbf/(ft/s)"), ("_deg_per_100m", "deg/100 m"), ("_w_per_dps", "W/(deg/s)"),
    ("_rpm_per_v", "rpm/V"), ("_norm_s", "1/s"), ("_mps2", "m/s²"), ("_kgm2", "kg·m²"), ("_mps", "m/s"),
    ("_dps", "deg/s"), ("_deg", "deg"), ("_ohm", "Ω"), ("_pct", "%"), ("_kg", "kg"), ("_in", "in"),
    ("_hz", "Hz"), ("_pa", "Pa"), ("_ah", "Ah"), ("_m", "m"), ("_s", "s"), ("_a", "A"), ("_v", "V"),
    ("_w", "W"), ("_f", "F"), ("_K", "K"), ("_k", "K"),
]

CHOICES = {
    "aircraft.model": ["rascal110_e"],
    "atmosphere.model": ["jsbsim_us1976"],
    "wind.mean.shear.model": ["power", "log", "none"],
    "wind.turbulence.model": ["none", "dryden", "jsbsim_milspec"],
    "wind.turbulence.intensity": ["auto", "light", "moderate", "severe"],
    "mission.runway.selection": ["into_wind", "first"],
    "powertrain.esc.throttle_to_duty": ["linear"],
    "logging.format": ["csv", "parquet"],
}

LIMITS = {  # (min, max) sanity limits for inputs; config.validate() has the final word
    "sim.dt_physics_s": (0.001, 0.02), "sim.control_rate_hz": (10, 200), "sim.log_rate_hz": (1, 200),
    "sim.t_max_s": (10, 36000), "aircraft.airframe_mass_kg": (1, 20), "powertrain.battery.soc_init": (0.01, 1),
    "wind.mean.speed_mps": (0, 40), "wind.mean.from_deg": (0, 360), "mission.cruise.airspeed_mps": (9, 35),
    "mission.cruise.alt_agl_m": (20, 400), "powertrain.motor.kv_rpm_per_v": (50, 3000),
    "powertrain.battery.cells_series": (1, 14), "powertrain.battery.cells_parallel": (1, 8),
}

# keys edited by dedicated widgets (tables, curves) instead of the property grid
SPECIAL = {"mission.waypoints", "wind.mean.schedule", "wind.gusts", "powertrain.battery.ocv_table",
           "autonomy.policy.params", "autonomy.policy.name"}

TAG_RE = re.compile(r"\[(SPEC|DATA|REP|TUNE)\]")


def _comments() -> dict:
    """dotted key -> trailing comment text in defaults.yaml."""
    out, stack = {}, []
    for line in Path(DEFAULTS).read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#") or line.lstrip().startswith("- "):
            continue
        m = re.match(r"^(\s*)([A-Za-z0-9_]+):\s*(.*)$", line)
        if not m:
            continue
        indent = len(m.group(1)) // 2
        key, rest = m.group(2), m.group(3)
        stack = stack[:indent] + [key]
        c = ""
        if "#" in rest:
            c = rest.split("#", 1)[1].strip()
        out[".".join(stack)] = c
    return out


def _label(key: str) -> tuple[str, str]:
    unit = ""
    base = key
    for suf, u in UNIT_SUFFIX:
        if key.endswith(suf) and len(key) > len(suf):
            base, unit = key[: -len(suf)], u
            break
    label = base.replace("_", " ").strip()
    fix = {"kv rpm": "Kv", "soc": "SOC", "cg x": "CG x", "cd0 scale": "CD0 scale", "cdi scale": "CDi scale",
           "cl scale": "CL scale", "ct scale": "CT scale", "cp scale": "CP scale", "r0 cell": "R0 per cell",
           "r1 cell": "R1 per cell", "c1 cell": "C1 per cell", "l1": "L1", "w20": "W20", "vne": "VNE",
           "tecs": "TECS", "rtl soc": "RTL SOC", "esc": "ESC", "ocv": "OCV", "dt physics": "Physics step"}
    lab = label[:1].upper() + label[1:]
    for k, v in fix.items():
        if label.lower().startswith(k):
            lab = v + label[len(k):]
    return lab, unit


LABELS = {
    "sim.t_max_s": "Maximum simulated time", "sim.seed": "Random seed", "sim.dt_physics_s": "Physics step",
    "sim.settle_time_s": "Ground settle time", "aircraft.cg_x_in": "CG station x",
    "mission.acceptance_radius_m": "Waypoint acceptance radius", "mission.repeat": "Repeat waypoint list",
    "powertrain.motor.no_load_current_a": "No-load current I0", "wind.mean.from_deg": "Direction (from)",
    "wind.mean.speed_mps": "Speed at reference height", "wind.turbulence.w20_mps": "W20 override (blank = auto)",
    "autonomy.wind_limits.max_mean_mps": "Max mean wind for take-off",
}


def build_schema() -> dict:
    d = yaml.safe_load(Path(DEFAULTS).read_text(encoding="utf-8"))
    com = _comments()
    fields = []

    def walk(node, path):
        for k, v in node.items():
            p = f"{path}.{k}" if path else k
            if p in SPECIAL:
                continue
            if isinstance(v, dict) and not (p.startswith("controller.") and _flow_gain(v)):
                walk(v, p)
                continue
            if isinstance(v, dict):          # flow-style gain dicts, e.g. controller.roll {kp, ki, ...}
                walk(v, p)
                continue
            label, unit = _label(k)
            desc = com.get(p, "")
            tag = TAG_RE.search(desc)
            desc_clean = TAG_RE.sub("", desc).strip()
            t = ("bool" if isinstance(v, bool) else "int" if isinstance(v, int) else
                 "float" if isinstance(v, float) else "list" if isinstance(v, list) else
                 "null" if v is None else "str")
            if p in LABELS:
                label = LABELS[p]
            f = {"path": p, "group": p.split(".")[0], "section": ".".join(p.split(".")[1:-1]) or "general",
                 "key": k, "label": label, "unit": unit, "type": t, "default": v, "description": desc_clean,
                 "tag": tag.group(1) if tag else None}
            if p in CHOICES:
                f["type"], f["choices"] = "enum", CHOICES[p]
            if p == "powertrain.propeller.data_file":
                f["type"], f["choices"] = "enum", sorted(x.name for x in DATA.glob("PER3_*.dat"))
            if p == "wind.turbulence.w20_mps":
                f["type"], f["nullable"], f["unit"] = "float", True, "m/s"
            if p in LIMITS:
                f["min"], f["max"] = LIMITS[p]
            fields.append(f)

    walk(d, "")
    from ..policies import REGISTRY, policy_doc, policy_parameters
    policies = {n: {"params": policy_parameters(n), "doc": policy_doc(n)} for n in sorted(REGISTRY)}
    return {"groups": [{"id": g, "label": l, "description": dsc} for g, l, dsc in GROUPS],
            "fields": fields, "policies": policies, "defaults": d}


def _flow_gain(v: dict) -> bool:
    return all(isinstance(x, (int, float)) for x in v.values())
