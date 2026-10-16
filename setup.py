#!/usr/bin/env python3
"""Create .venv and install the dependencies. Safe to run again at any time.

    python setup.py

Then run it with ./tdash, or `python tdash.py` on Windows.
"""

import os
import subprocess
import sys
import venv
from pathlib import Path

APP = Path(__file__).resolve().parent
VENV = APP / ".venv"


def venv_python(root):
    return root / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def main():
    if not VENV.exists():
        print(f"Creating virtualenv at {VENV}")
        venv.EnvBuilder(with_pip=True).create(VENV)
    else:
        print(f"Reusing virtualenv at {VENV}")

    python = venv_python(VENV)
    subprocess.check_call([str(python), "-m", "pip", "install", "--quiet", "--upgrade",
                           "pip"])
    subprocess.check_call([str(python), "-m", "pip", "install", "--quiet", "-r",
                           str(APP / "requirements.txt")])
    print("\nReady. Run it with:\n"
          f"  {APP / 'tdash'}\n"
          "or, on Windows:\n"
          f"  python {APP / 'tdash.py'}\n"
          f"\nTo get the `tdash` command on your PATH, run:  python {APP / 'install.py'}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())