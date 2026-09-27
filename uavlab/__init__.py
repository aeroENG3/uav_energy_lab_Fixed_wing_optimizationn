"""UAV Energy Lab: JSBSim-based simulation of the Rascal 110 electric UAV for
energy-consumption and wind-adaptive optimisation studies.

Pipeline: atmosphere -> mission -> autonomy -> controller -> actuators ->
JSBSim flight dynamics <-> electric powertrain (battery/ESC/motor/propeller).
"""
__version__ = "0.1.0"

from .config import load_config  # noqa: E402,F401


def run(*scenario_files, overrides=None, **kw):
    """Convenience: load config and run one simulation. Returns a RunResult."""
    from .simulation import Simulation
    cfg = load_config(*scenario_files, overrides=overrides)
    return Simulation(cfg, **kw).run()
