#!/usr/bin/env python3
"""Start tdash using the local virtualenv, on any platform.

    python tdash.py            -> interactive
    python tdash.py dashboard  -> one-shot print
    python tdash.py --help     -> command list

The `tdash` shell wrapper calls this, so Windows users run it directly instead
of needing bash.
"""

import os
import subprocess
import sys
from pathlib import Path

APP = Path(__file__).resolve().parent
VENV = APP / ".venv"


def venv_python():
    """The interpreter inside .venv, or None when it has not been created."""
    candidate = VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    return candidate if candidate.exists() else None


def main(argv):
    entry = str(APP / "dashboard.py")
    python = venv_python()
    if python is None:
        print(f"No virtualenv found at {VENV}.\n"
              f"Create it once with:  python setup.py", file=sys.stderr)
        return 1
    if os.name == "nt":
        return subprocess.call([str(python), entry, *argv])
    os.execv(str(python), [str(python), entry, *argv])


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))