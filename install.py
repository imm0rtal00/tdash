#!/usr/bin/env python3
"""Put `tdash` on your PATH.

    python install.py

Writes two small launchers into a bin folder you add to your PATH. They are
plain scripts, not symlinks, so they survive being zipped, copied to another
machine, and checked out on Windows.

The launchers remember this folder's location, so run this again if you move
or rename the project.
"""

import os
import stat
import sys
from pathlib import Path

APP = Path(__file__).resolve().parent
ENTRY = APP / "tdash.py"
NAMES = ("tdash",)
# Earlier versions also installed a "dashboard" command; remove it.
STALE = ("dashboard",)

POSIX = """#!/bin/sh
# tdash - a terminal study dashboard. Re-run `python install.py` if it moves.
exec "{python}" "{entry}" "$@"
"""

WINDOWS = """@echo off
rem tdash - a terminal study dashboard. Re-run `python install.py` if it moves.
"{python}" "{entry}" %*
"""


def bin_dir():
    """Where the launchers go: a per-user folder, no admin rights needed."""
    if os.name == "nt":
        local = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(local) / "tdash" / "bin"
    return Path.home() / ".local" / "bin"


def venv_python():
    """The interpreter the launchers should use: the local venv if present."""
    candidate = APP / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    return candidate if candidate.exists() else Path(sys.executable)


def write_launcher(target, python):
    """Write one launcher, POSIX shell script or Windows batch file."""
    template = WINDOWS if os.name == "nt" else POSIX
    text = template.format(python=python, entry=ENTRY)
    target.write_text(text, encoding="utf-8")
    if os.name != "nt":
        target.chmod(target.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def main():
    if not (APP / ".venv").exists():
        print(f"No virtualenv at {APP / '.venv'}.\n"
              f"Create it first with:  python setup.py", file=sys.stderr)
        return 1

    target_dir = bin_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    python = venv_python()

    for name in STALE:
        old = target_dir / (f"{name}.cmd" if os.name == "nt" else name)
        if old.is_symlink() or old.exists():
            old.unlink()
            print(f"  removed stale {old}")

    for name in NAMES:
        # A stale symlink here would make write_text follow it and clobber the
        # target, so clear anything already sitting there first.
        path = target_dir / (f"{name}.cmd" if os.name == "nt" else name)
        if path.is_symlink() or path.exists():
            path.unlink()
        write_launcher(path, python)
        print(f"  wrote {path}")

    print(f"\nDone. Add this folder to your PATH if the commands do not work yet:\n"
          f"  {target_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())