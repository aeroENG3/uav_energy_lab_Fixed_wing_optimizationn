# UAV Energy Lab: Engineering Handbook

This handbook covers the `uavlab` simulation lab from three sides. The lab simulates the Rascal 110 electric fixed-wing UAV on JSBSim and is built for energy-consumption studies and for developing wind-adaptive energy-optimising controllers.

- **Part A (software)** shows how the code is organised and how data moves through it. It covers each call and each log row, and how to extend the lab without breaking reproducibility.
- **Part B (aerospace engineering)** gives the physics and control theory behind each block: equations, sign conventions, sources, assumptions and the range where each model can be trusted.
- **Part C (user interface)** gives step-by-step workflows for each type of experiment, all run from the graphical interface without editing code.

The appendices hold the full parameter reference (generated from `configs/defaults.yaml`), the log-signal dictionary, the command-line and REST references, symbols and literature.

> **How to read the numbers in this handbook.** Every model value quoted here is the shipped default. Values tagged **[REP]** are representative of this aircraft class, not measured on a specific aircraft. Replace them with your hardware data before you quote absolute energy numbers (Section B14.4). Relative comparisons, such as strategy A against strategy B in the same wind, are much less sensitive to these values than absolute watt-hours are.

| Item | Value |
|---|---|
| Lab version | uavlab 0.1.0 |
| Flight dynamics | JSBSim 1.3.1 (Python bindings) |
| Aircraft | Rascal 110, electric conversion (ArduPilot SITL model, changes M1–M10) |
| Powertrain | APC 18x8E propeller data, Drela motor, averaged ESC, 1-RC LiPo 6S 10 Ah |
| Default rates | physics 200 Hz, control 50 Hz, logging 10 Hz |

## Quick start

**Graphical interface** (recommended). From the repository root:

```bash
python -m pip install -r requirements.txt
python -m uavlab ui
```

The second command opens `http://127.0.0.1:8050` in the browser. `python -m uavlab ui --workspace <folder>` keeps runs, studies and scenarios in another folder.

On the Overview page, pick a template and press **Load and run**. You then see the flight live and can open the results. Part C walks through every workflow.

**Command line.** Every action in the interface has a command-line equivalent that uses the same code path:

```bash
python -m uavlab run configs/missions/survey_box.yaml configs/wind/gusty.yaml
python -m uavlab run scenarios/my_case.yaml --set wind.mean.speed_mps=6
python -m uavlab sweep configs/experiments/airspeed_vs_wind.yaml
python -m uavlab performance
python -m uavlab validate
```

Every line is one complete command. Run them one at a time; this works the same in PowerShell, cmd and Linux shells. On Windows, a virtual environment is created with `python -m venv .venv` and activated with `.\.venv\Scripts\Activate.ps1`. Use `python -m pytest -q` for the tests.

**From an IDE** (PyCharm, VS Code, Spyder), open `run_ui.py` in the repository folder and press Run. `run_lab.py` runs any command given in the run configuration's parameters, for example `performance`. The files inside `uavlab/` are parts of a package and cannot be run on their own.

A scenario saved in the interface is a YAML file. The command line runs it unchanged, and the interface can load a file written by hand.
