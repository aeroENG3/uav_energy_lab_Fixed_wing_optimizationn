"""Run any lab command from an IDE (PyCharm, VS Code, Spyder).

Set the command in the run configuration's "Parameters" field, for example:
    run configs/missions/survey_box.yaml configs/wind/gusty.yaml
    performance
    sweep configs/experiments/airspeed_vs_wind.yaml
    validate --quick
With no parameters it prints the list of commands.

Same as typing, in the repository folder:  python -m uavlab <parameters>
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

if __name__ == "__main__":      # required: the lab runs simulations in worker processes
    os.chdir(ROOT)              # relative paths (configs/, runs/) are relative to the repository
    from uavlab.cli import main

    sys.exit(main(sys.argv[1:] or ["--help"]))
