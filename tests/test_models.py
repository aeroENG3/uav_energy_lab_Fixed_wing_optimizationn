"""Fast unit-level verification tests (run: pytest -q). The full evidence,
including flight tests, is produced by `python -m uavlab validate`."""
import math
from pathlib import Path

import numpy as np
import pytest

from uavlab.config import ConfigError, load_config
from uavlab.validation import suite as S


@pytest.fixture(scope="module")
def cfg():
    return load_config()


def test_atmosphere_us1976(cfg):
    assert S.v1_atmosphere(cfg)["passed"]


def test_wind_injection(cfg):
    assert S.v2_wind_injection(cfg)["passed"]


def test_gust_shape(cfg):
    assert S.v4_gust(cfg)["passed"]


def test_battery(cfg):
    assert S.v5_battery(cfg)["passed"]


def test_motor(cfg):
    assert S.v6_motor(cfg)["passed"]


def test_powertrain_balance(cfg):
    assert S.v7_powertrain(cfg)["passed"]


def test_static_prop_cosim(cfg):
    assert S.v8_static_prop(cfg)["passed"]


def test_surface_signs(cfg):
    assert S.v15_signs(cfg)["passed"]


def test_config_validation():
    assert S.v16_config()["passed"]


def test_dryden_statistics(cfg, tmp_path):
    assert S.v3_dryden(cfg, True, tmp_path)["passed"]


def test_shear_profiles():
    from uavlab.atmosphere import shear_factor
    m = {"ref_height_m": 10.0, "shear": {"model": "power", "alpha": 0.143, "min_height_m": 1.0}}
    assert shear_factor(10.0, m) == pytest.approx(1.0)
    assert shear_factor(100.0, m) == pytest.approx(10 ** 0.143)
    m["shear"] = {"model": "log", "z0_m": 0.03, "min_height_m": 1.0}
    assert shear_factor(100.0, m) == pytest.approx(math.log(100 / 0.03) / math.log(10 / 0.03))


def test_wind_direction_convention():
    from uavlab.atmosphere import wind_vector_ned
    w = wind_vector_ned(5.0, 270.0)          # westerly: air moves towards the east
    assert w[1] == pytest.approx(5.0) and abs(w[0]) < 1e-12


def test_geodesy_roundtrip():
    from uavlab.geo import LocalFrame
    f = LocalFrame(24.7, 46.7, 600.0)
    lat, lon, h = f.to_geodetic(1234.0, -987.0, -50.0)
    ned = f.to_ned(lat, lon, h)
    assert np.allclose(ned, [1234.0, -987.0, -50.0], atol=1e-6)
