"""REST API of the graphical interface (FastAPI TestClient, isolated workspace)."""
import time

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from uavlab.ui.server import create_app  # noqa: E402


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    ws = tmp_path_factory.mktemp("ws")
    with TestClient(create_app(ws)) as c:
        c.ws = ws
        yield c


def test_meta_schema_defaults(client):
    m = client.get("/api/meta").json()
    assert m["version"] and m["jsbsim"]
    s = client.get("/api/schema").json()
    assert len(s["fields"]) > 150
    paths = {f["path"] for f in s["fields"]}
    assert {"wind.mean.speed_mps", "mission.cruise.airspeed_mps", "powertrain.motor.kv_rpm_per_v"} <= paths
    assert all("unit" in f and "label" in f for f in s["fields"])
    assert {"fixed", "wind_aware_best_range", "linear_wind"} <= set(s["policies"])
    d = client.get("/api/config/defaults").json()
    assert d["sim"]["dt_physics_s"] == 0.005


def test_validation_reports_every_problem(client):
    cfg = client.get("/api/config/defaults").json()
    assert client.post("/api/config/validate", json=cfg).json()["ok"]
    cfg["mission"]["cruise"]["airspeed_mps"] = 9.0          # below 1.3 x stall
    cfg["sim"]["control_rate_hz"] = 33                      # does not divide 200 Hz
    r = client.post("/api/config/validate", json=cfg).json()
    assert not r["ok"] and len(r["errors"]) >= 2


def test_presets_and_scenario_roundtrip(client):
    p = client.get("/api/presets").json()
    assert any(x["name"] == "gusty" for x in p["wind"])
    assert any(x["name"] == "out_and_back" for x in p["missions"])
    base = client.get("/api/config/defaults").json()
    cfg = client.post("/api/config/apply", json={"kind": "wind", "name": "gusty", "config": base}).json()
    assert cfg["wind"]["turbulence"]["model"] != "none"
    assert cfg["mission"] == base["mission"]                # a wind preset keeps the mission
    cfg["mission"]["cruise"]["airspeed_mps"] = 18.0
    r = client.post("/api/scenarios/save", json={"name": "t_case", "description": "test", "config": cfg}).json()
    f = client.ws / "scenarios" / "t_case.yaml"
    assert f.exists() and r["changed_keys"] >= 2
    assert "dt_physics_s" not in f.read_text(encoding="utf-8")               # only differences are written
    back = client.post("/api/config/apply", json={"kind": "scenarios", "name": "t_case", "config": base}).json()
    assert back["mission"]["cruise"]["airspeed_mps"] == 18.0


def test_previews(client):
    cfg = client.get("/api/config/defaults").json()
    b = client.post("/api/preview/battery", json=cfg).json()
    assert 200 < b["energy_Wh"] < 260
    m = client.post("/api/preview/mission", json=cfg)
    assert m.status_code == 200
    w = client.post("/api/preview/wind", json={"config": cfg})
    assert w.status_code == 200


def test_static_pages_and_path_safety(client):
    assert "UAV Energy Lab" in client.get("/").text
    assert "Handbook" in client.get("/handbook").text
    assert client.get("/api/run", params={"ref": "../../etc"}).status_code == 400


def test_run_job_streams_telemetry_and_writes_logs(client):
    cfg = client.get("/api/config/defaults").json()
    cfg["sim"]["t_max_s"] = 12.0                            # short: ends as TIMEOUT on the take-off roll
    j = client.post("/api/run", json={"config": cfg, "label": "api test"}).json()
    t0 = time.time()
    while True:
        d = client.get(f"/api/jobs/{j['id']}").json()
        if d["state"] not in ("queued", "running"):
            break
        assert time.time() - t0 < 180, "run job did not finish"
        time.sleep(0.5)
    assert d["state"] == "done", d.get("error")
    assert d["counts"]["rows"] > 50 and d["counts"]["events"] >= 2
    ref = d["result"]["ref"]
    run = client.get("/api/run", params={"ref": ref}).json()
    assert run["summary"]["status"] == "TIMEOUT"
    s = client.get("/api/run/series", params={"ref": ref, "cols": "t_s,P_batt_W,soc"}).json()
    assert len(s["t_s"]) > 50 and max(s["P_batt_W"]) > 100
    assert any(r["ref"] == ref for r in client.get("/api/runs").json())


def test_repository_vv_runs_are_readable_but_read_only(client):
    runs = client.get("/api/runs", params={"source": "repo:validation_report/runs"}).json()
    if not runs:
        pytest.skip("no V&V runs shipped in this checkout")
    ref = runs[0]["ref"]
    assert ref.startswith("repo:validation_report/runs/")
    assert client.get("/api/run", params={"ref": ref}).json()["summary"]["status"]
    assert client.post("/api/run/label", json={"ref": ref, "label": "x"}).status_code == 403
    assert client.get("/api/run", params={"ref": "repo:uavlab"}).status_code == 400
