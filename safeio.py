"""Crash-safe file writing, shared by the data store and the undo history.

A plain write_text() truncates a file first and fills it afterwards, so an
interrupted write leaves a half-written file and the next load dies on it.
Writing to a sibling temp file and renaming it over the target means the file
on disk is always either the old complete version or the new complete one.
"""

import os
from pathlib import Path


def atomic_write(path, text):
    """Replace a file in one step. Returns the path written."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    if os.name != "nt":
        # Written 0600 before the rename, not after: a moment spent at the
        # umask's mercy is still a moment every account on the machine can
        # read the credentials in these files.
        os.chmod(tmp, 0o600)
    os.replace(tmp, path)
    return path