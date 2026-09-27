"""Start the UAV Energy Lab interface.

In PyCharm, VS Code or Spyder: open this file and press Run. It opens the
interface in your browser (http://127.0.0.1:8050). Stop it with the IDE's
Stop button (or Ctrl+C in a terminal).

Same as typing, in the repository folder:  python -m uavlab ui

Note: the files inside the uavlab/ folder are parts of a package and cannot be
run on their own; always start the lab from here or with `python -m uavlab ...`.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

if __name__ == "__main__":      # required: the lab runs simulations in worker processes
    from uavlab.cli import main

    # results are kept in this folder unless --workspace is given
    sys.exit(main(["ui", "--workspace", str(ROOT), *sys.argv[1:]]))
