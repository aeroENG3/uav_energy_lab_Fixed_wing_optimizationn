import sys

from .cli import main

if __name__ == "__main__":   # guard: spawned worker processes re-import this module
    sys.exit(main())
