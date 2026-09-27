"""Short closed-loop tests of the full pipeline (about 1 minute)."""
import pytest

from uavlab.config import load_config
from uavlab.simulation import Simulation


def _run(overrides, files=("configs/missions/survey_box.yaml",)):
    cfg = load_config(*files, overrides=overrides)
    return Simulation(cfg, write_logs=False).run()


def test_takeoff_and_climb_energy_closure():
    r = _run({"sim.t_max_s": 60.0})
    s = r.summary
    assert s["status"] == "TIMEOUT"                       # still flying at 60 s
    assert r.timeseries["alt_agl_m"].iloc[-1] > 40.0      # climbed
    assert abs(s["energy_closure"]["relative"]) < 1e-3
    assert 0.0 < s["E_batt_Wh"] < 15.0


def test_reproducible_with_turbulence():
    ov = {"sim.t_max_s": 40.0, "wind.mean.speed_mps": 5.0, "wind.turbulence.model": "dryden"}
    a = _run(ov).timeseries
    b = _run(ov).timeseries
    num = a.select_dtypes("number").columns
    assert a[num].equals(b[num])


def test_no_go_on_excess_wind():
    r = _run({"wind.mean.speed_mps": 15.0})
    assert r.status == "NO_GO"
    assert "D2_no_go" in r.summary["decisions"]


def test_gym_env_contract():
    gym = pytest.importorskip("gymnasium")
    from gymnasium.utils.env_checker import check_env
    from uavlab.gym_env import UAVEnergyEnv
    env = UAVEnergyEnv(decision_dt_s=5.0)
    check_env(env, skip_render_check=True)
