"""Configuration: YAML loading, deep-merge onto defaults, dotted overrides,
validation and a stable content hash (stored in every run's metadata)."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
DEFAULTS = ROOT / "configs" / "defaults.yaml"


class ConfigError(ValueError):
    pass


def deep_merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def set_path(cfg: dict, dotted: str, value: Any) -> None:
    """set_path(cfg, 'wind.mean.speed_mps', 6.0)"""
    keys = dotted.split(".")
    d = cfg
    for k in keys[:-1]:
        if k not in d or not isinstance(d[k], dict):
            raise ConfigError(f"unknown config path '{dotted}' (at '{k}')")
        d = d[k]
    if keys[-1] not in d and not (len(keys) >= 2 and keys[-2] == "params"):
        raise ConfigError(f"unknown config key '{dotted}'")   # free-form only under *.params
    d[keys[-1]] = value


def get_path(cfg: dict, dotted: str) -> Any:
    d = cfg
    for k in dotted.split("."):
        d = d[k]
    return d


def _load_yaml(p: Path) -> dict:
    with open(p, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_config(*scenario_files: str | Path, overrides: dict | None = None) -> dict:
    """defaults <- scenario files (in order, each may 'include' others) <- overrides."""
    cfg = _load_yaml(DEFAULTS)
    for f in scenario_files:
        f = Path(f)
        if not f.is_absolute() and not f.exists():
            f = ROOT / f
        sc = _load_yaml(f)
        for inc in sc.pop("include", []) or []:
            ip = (f.parent / inc) if not Path(inc).is_absolute() else Path(inc)
            cfg = deep_merge(cfg, _load_yaml(ip))
        cfg = deep_merge(cfg, sc)
    for k, v in (overrides or {}).items():
        set_path(cfg, k, v)
    validate(cfg)
    return cfg


def config_from_dict(base: dict, overrides: dict | None = None) -> dict:
    """Full configuration from an in-memory dict (e.g. edited in the UI):
    defaults <- base <- dotted overrides, then validated."""
    cfg = deep_merge(_load_yaml(DEFAULTS), base or {})
    for k, v in (overrides or {}).items():
        set_path(cfg, k, v)
    validate(cfg)
    return cfg


def diff_from_defaults(cfg: dict) -> dict:
    """Nested dict holding only the values that differ from configs/defaults.yaml
    (what a saved scenario file needs)."""
    d0 = _load_yaml(DEFAULTS)

    def _diff(a, b):
        out = {}
        for k, v in a.items():
            if isinstance(v, dict) and isinstance(b.get(k), dict):
                sub = _diff(v, b[k])
                if sub:
                    out[k] = sub
            elif k not in b or b[k] != v:
                out[k] = copy.deepcopy(v)
        return out
    return _diff(cfg, d0)


def config_hash(cfg: dict) -> str:
    blob = json.dumps(cfg, sort_keys=True, default=str).encode()
    return hashlib.sha256(blob).hexdigest()[:16]


def _chk(cond: bool, msg: str, errs: list):
    if not cond:
        errs.append(msg)


def validate(cfg: dict) -> None:
    """Physical-range checks. Raise ConfigError listing every problem found."""
    e: list[str] = []
    s = cfg["sim"]
    _chk(0 < s["dt_physics_s"] <= 0.02, "sim.dt_physics_s must be in (0, 0.02]", e)
    ratio = 1.0 / (s["dt_physics_s"] * s["control_rate_hz"])
    _chk(abs(ratio - round(ratio)) < 1e-6 and ratio >= 1,
         "sim.control_rate_hz must divide the physics rate", e)
    ac = cfg["aircraft"]
    _chk(1.0 < ac["airframe_mass_kg"] < 20.0, "aircraft.airframe_mass_kg out of range (1-20 kg)", e)
    pt = cfg["powertrain"]
    m, b, esc = pt["motor"], pt["battery"], pt["esc"]
    _chk(50 <= m["kv_rpm_per_v"] <= 3000, "motor.kv_rpm_per_v out of range", e)
    _chk(0 < m["resistance_ohm"] < 1.0, "motor.resistance_ohm out of range", e)
    _chk(0 <= m["no_load_current_a"] < 20, "motor.no_load_current_a out of range", e)
    _chk(b["cells_series"] >= 1 and b["cells_parallel"] >= 1, "battery cell counts must be >= 1", e)
    _chk(0 < b["capacity_ah"] < 100, "battery.capacity_ah out of range", e)
    _chk(0 < b["soc_init"] <= 1.0, "battery.soc_init must be in (0, 1]", e)
    soc, v = b["ocv_table"]["soc"], b["ocv_table"]["v"]
    _chk(len(soc) == len(v) and len(soc) >= 2, "battery.ocv_table soc/v length mismatch", e)
    _chk(all(x < y for x, y in zip(soc, soc[1:])), "battery.ocv_table.soc must increase", e)
    _chk(all(x <= y for x, y in zip(v, v[1:])), "battery.ocv_table.v must be non-decreasing", e)
    _chk(0.0 <= esc["switching_loss_frac"] < 0.2, "esc.switching_loss_frac out of range", e)
    w = cfg["wind"]
    _chk(0 <= w["mean"]["speed_mps"] < 40, "wind.mean.speed_mps out of range", e)
    _chk(w["mean"]["shear"]["model"] in ("power", "log", "none"), "wind.mean.shear.model invalid", e)
    _chk(w["turbulence"]["model"] in ("none", "dryden", "jsbsim_milspec"), "wind.turbulence.model invalid", e)
    _chk(w["turbulence"]["intensity"] in ("auto", "light", "moderate", "severe"),
         "wind.turbulence.intensity invalid", e)
    for i, g in enumerate(w.get("gusts") or []):
        _chk(g.get("duration_s", 0) > 0, f"wind.gusts[{i}].duration_s must be > 0", e)
    for i, p in enumerate(w["mean"].get("schedule") or []):
        _chk("t_s" in p and "speed_mps" in p and "from_deg" in p,
             f"wind.mean.schedule[{i}] needs t_s, speed_mps, from_deg", e)
    mi = cfg["mission"]
    _chk(len(mi["waypoints"]) >= 1, "mission.waypoints must not be empty", e)
    for i, wp in enumerate(mi["waypoints"]):
        _chk(("n_m" in wp and "e_m" in wp) or ("lat_deg" in wp and "lon_deg" in wp),
             f"mission.waypoints[{i}] needs n_m/e_m or lat_deg/lon_deg", e)
    _chk(mi["reserve"]["land_now_soc"] < mi["reserve"]["rtl_soc"], "reserve.land_now_soc must be < rtl_soc", e)
    _chk(mi["landing"]["approach_airspeed_mps"] > 1.2 * ac["limits"]["stall_speed_mps"],
         "landing.approach_airspeed_mps should be > 1.2 x stall speed", e)
    _chk(mi["cruise"]["airspeed_mps"] > 1.3 * ac["limits"]["stall_speed_mps"],
         "cruise.airspeed_mps should be > 1.3 x stall speed", e)
    _chk(cfg["logging"]["format"] in ("csv", "parquet"), "logging.format must be csv or parquet", e)
    if e:
        raise ConfigError("invalid configuration:\n  - " + "\n  - ".join(e))
