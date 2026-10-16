#!/usr/bin/env python3
"""Install `tdash`: a copy in its own folder, and the command on your PATH.

    python setup.py     # once: creates .venv and installs rich
    python install.py   # copies the program into its install folder

The installed copy is what the `tdash` command runs, so the folder you ran
install.py from can be moved or deleted afterwards. Running install.py
again from a newer copy upgrades the program: the installed virtualenv and
the installed data folder are kept, so progress carries over.

On Windows the installer also puts its bin folder on your user PATH (a
registry edit, no admin rights); on POSIX the launcher goes to
~/.local/bin, which is normally already on your PATH. Launchers are plain
scripts, not symlinks, so they survive being zipped, copied to another
machine, and checked out on Windows. Your data lives next to the installed
program: <install>/app/data.
"""

import os
import re
import shutil
import stat
import sys
from pathlib import Path

APP = Path(__file__).resolve().parent
NAMES = ("tdash",)
# Earlier versions also installed a "dashboard" command; remove it.
STALE = ("dashboard",)
# The plain copy leaves these alone: each gets its own rules below.
SKIP = (".venv", "data", "__pycache__", ".git")

POSIX = """#!/bin/sh
# tdash - a terminal study dashboard. Re-run `python install.py` if it moves.
exec "{python}" "{entry}" "$@"
"""

WINDOWS = """@echo off
rem tdash - a terminal study dashboard. Re-run `python install.py` if it moves.
"{python}" "{entry}" %*
"""


def user_root():
    """The per-user folder everything lives under; no admin rights needed."""
    if os.name == "nt":
        local = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(local) / "tdash"
    share = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(share) / "tdash"


def bin_dir():
    """Where the launchers go."""
    if os.name == "nt":
        return user_root() / "bin"
    return Path.home() / ".local" / "bin"


def install_dir():
    """Where the program itself is installed."""
    return user_root() / "app"


def venv_python(root):
    """The interpreter the launchers for `root` should use."""
    candidate = root / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    return candidate if candidate.exists() else Path(sys.executable)


def write_launcher(target, python, entry):
    """Write one launcher, POSIX shell script or Windows batch file."""
    template = WINDOWS if os.name == "nt" else POSIX
    target.write_text(template.format(python=python, entry=entry), encoding="utf-8")
    if os.name != "nt":
        target.chmod(target.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def expand_vars(text):
    """Environment variables in `text`: $NAME and %NAME% alike.

    os.path.expandvars only understands one style per platform, and Windows
    PATHs are full of %VAR% entries, so expand both here."""
    text = os.path.expandvars(text)
    return re.sub(r"%([^%]+)%",
                  lambda match: os.environ.get(match.group(1), match.group(0)),
                  text)


def path_entry(text):
    """One PATH entry ready to compare: unquoted, variables expanded."""
    return os.path.normcase(expand_vars(text.strip().strip('"')).rstrip("\\/"))


def path_with(folder, current):
    """`current` with `folder` appended, or None if it is already in there.

    Nothing else is rewritten: the existing text goes back byte for byte
    (minus a trailing separator), so entries this script does not understand
    are left exactly as they were. None means "no change needed", which is
    what makes re-running the installer safe."""
    folder = str(folder)
    target = path_entry(folder)
    for entry in current.split(os.pathsep):
        if entry and path_entry(entry) == target:
            return None
    current = current.rstrip(os.pathsep)
    return f"{current}{os.pathsep}{folder}" if current else folder


def add_to_user_path(folder):
    """Windows: append `folder` to the user PATH in the registry.

    HKCU\\Environment only - per-user, no admin rights, no system change.
    The value keeps its type, because PATHs routinely hold %USERPROFILE%
    style entries that only expand when stored as REG_EXPAND_SZ. Returns
    True when it wrote, False when the folder was already there. Raises
    OSError if the registry cannot be written."""
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0,
                        winreg.KEY_READ | winreg.KEY_WRITE) as key:
        try:
            current, kind = winreg.QueryValueEx(key, "Path")
        except FileNotFoundError:
            current, kind = "", winreg.REG_EXPAND_SZ
        updated = path_with(folder, current)
        if updated is None:
            return False
        winreg.SetValueEx(key, "Path", 0, kind, updated)
        return True


def refresh_environment():
    """Tell Windows the user environment changed; new terminals see the PATH.

    Explorer and friends react to this broadcast. Best effort: a machine
    where it fails still picks the change up at the next sign-in."""
    try:
        import ctypes
        user32 = ctypes.windll.user32
        user32.SendMessageTimeoutW.argtypes = (
            ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_wchar_p,
            ctypes.c_uint, ctypes.c_uint, ctypes.POINTER(ctypes.c_ulong))
        HWND_BROADCAST, WM_SETTINGCHANGE, SMTO_ABORTIFHUNG = 0xFFFF, 0x001A, 0x0002
        user32.SendMessageTimeoutW(HWND_BROADCAST, WM_SETTINGCHANGE, None,
                                   "Environment", SMTO_ABORTIFHUNG, 5000,
                                   ctypes.byref(ctypes.c_ulong()))
    except Exception:
        pass


def same_folder(one, other):
    """True when two paths point at the same folder (case-blind on Windows)."""
    return os.path.normcase(os.path.realpath(str(one))) == \
        os.path.normcase(os.path.realpath(str(other)))


def copy_app(source, destination):
    """Copy the program itself: everything except SKIP and build junk."""
    destination.mkdir(parents=True, exist_ok=True)
    copied = 0
    for item in source.iterdir():
        if item.name in SKIP:
            continue
        target = destination / item.name
        if item.is_dir():
            shutil.copytree(item, target, dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns("__pycache__"))
        else:
            shutil.copy2(item, target)
            copied += 1
    return copied


def copy_venv(source, destination):
    """Copy .venv on the first install; later runs keep what is there."""
    origin, target = source / ".venv", destination / ".venv"
    if target.exists():
        return False
    shutil.copytree(origin, target, symlinks=True)
    return True


def copy_data(source, destination):
    """Carry existing progress over on a first install; never overwrite."""
    origin, target = source / "data", destination / "data"
    if target.exists() or not origin.exists():
        return False
    shutil.copytree(origin, target)
    return True


def install_into(source, destination):
    """Install, unless the source is where it already is.

    Returns which pieces were copied: (files, virtualenv, data). Running
    install.py from the installed folder itself only refreshes launchers."""
    if same_folder(source, destination):
        return 0, False, False
    return (copy_app(source, destination),
            copy_venv(source, destination),
            copy_data(source, destination))


def main():
    destination = install_dir()
    same = same_folder(destination, APP)
    # A fresh download used for an upgrade has no .venv of its own: the
    # installed virtualenv is kept, and setup.py is only for a first install.
    if not (APP / ".venv").exists() and (same or not (destination / ".venv").exists()):
        print(f"No virtualenv at {APP / '.venv'}.\n"
              f"Create it first with:  python setup.py", file=sys.stderr)
        return 1

    if not same:
        print(f"Installing to {destination}")
        files, copied_venv, copied_data = install_into(APP, destination)
        print(f"  copied {files} files")
        if copied_venv:
            print("  copied the virtualenv")
        if copied_data:
            print("  copied the data folder")

    target_dir = bin_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    python = venv_python(destination)
    entry = destination / "tdash.py"

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
        write_launcher(path, python, entry)
        print(f"  wrote {path}")

    tail = ("The folder you ran this from can now be moved or deleted.\n"
            "To upgrade, run install.py from a newer copy; your progress is kept.")

    if os.name != "nt":
        print(f"\nDone. Add this folder to your PATH if the commands do not work yet:\n"
              f"  {target_dir}\n"
              f"\n{tail}")
        return 0

    try:
        changed = add_to_user_path(target_dir)
    except Exception as error:              # locked-down registry, odd PATH value
        print(f"\nDone. Could not update your PATH automatically:\n  {error}\n"
              f"Add this folder to your PATH yourself, then open a new terminal:\n"
              f"  {target_dir}\n"
              f"(Until then, the full path works: {target_dir / 'tdash.cmd'})\n"
              f"\n{tail}")
        return 0

    if changed:
        refresh_environment()
        print(f"\nDone. Added this folder to your PATH:\n  {target_dir}")
    else:
        print(f"\nDone. This folder is already on your PATH:\n  {target_dir}")
    print("\nOpen a new terminal, then run:\n  tdash\n")
    print(tail)
    return 0


if __name__ == "__main__":
    sys.exit(main())
