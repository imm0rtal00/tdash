"""Undo/redo for data changes.

Every write that goes through store.save() is recorded, so undo and redo cover
any change made in the app - from the menu or from the command line - without
each command having to know about history.

One stack covers the whole session and every project in it. A project made,
filled, deleted, and another one worked on can all be walked back and forward
with ctrl+x u / r, newest step first, until there is nothing left to step
through. Each step remembers which file held what before and after, so
replaying one never has to ask which project is on screen.

The stacks are deliberately in memory only: undo and redo cover this session
and nothing else. Closing the app discards them, so an undo can never reach
back past the point where you last saved. The data files themselves are still
protected by backups and atomic writes.
"""

from contextlib import contextmanager

from safeio import atomic_write

LIMIT = 200

# Plain words for the data files, so undo can say what it put back.
FILE_NOUNS = {"projects": "the project list", "machines": "machines",
              "repository": "the repository", "progress": "the progress"}


def describe(step):
    """What one step changed, for the message the dashboard shows."""
    if step.get("label"):
        return step["label"]
    parts = []
    for entry in step["entries"]:
        noun = FILE_NOUNS.get(entry["name"], entry["name"])
        who = entry.get("who")
        # The project list is not "in" one project, so its name is left off.
        said = (f"{noun} in {who}" if who and entry["name"] != "projects"
                else noun)
        if said not in parts:
            parts.append(said)
    return ", ".join(parts) or "a change"


class History:
    """The session's changes, newest last.

    Each step is a list of file snapshots taken together: one save is one
    snapshot, and the saves that make up creating or deleting a project are
    grouped into one step so a single undo puts the whole project back."""

    def __init__(self, limit=LIMIT):
        self.limit = limit
        self.undo_stack = []
        self.redo_stack = []
        self._open = None           # entries being gathered into one step
        self._open_label = None

    def path(self, data_dir, name):
        return data_dir / f"{name}.json"

    def read(self, data_dir, name):
        try:
            return self.path(data_dir, name).read_text(encoding="utf-8")
        except OSError:
            return None

    def write(self, data_dir, name, text):
        path = self.path(data_dir, name)
        if text is None:
            # The file did not exist before the change, so putting it back
            # means taking the file away again.
            path.unlink(missing_ok=True)
            return
        atomic_write(path, text)

    @contextmanager
    def group(self, label=None):
        """Gather the saves made inside into one undo step.

        Creating or deleting a project writes several files; without this each
        one was its own step and a project came back one file at a time. A
        nested group joins the one already open."""
        if self._open is not None:
            yield
            return
        self._open = []
        self._open_label = label
        try:
            yield
        finally:
            entries, label = self._open, self._open_label
            self._open, self._open_label = None, None
            if entries:
                self._push(entries, label)

    def record(self, data_dir, name, before, after, project=None, who=None):
        """Remember what a file held before and after it was overwritten.

        `project` and `who` are the project the change belonged to; they are
        kept for the message undo shows. A write that changed nothing is not a
        step - a press of ctrl+x u should never land on a snapshot that looks
        the same as the text already on screen."""
        if before is None or before == after:
            return
        entry = {"name": name, "before": before, "after": after,
                 "project": project, "who": who}
        if self._open is not None:
            self._open.append(entry)
            return
        self._push([entry], None)

    def _push(self, entries, label):
        self.undo_stack.append({"entries": entries, "label": label})
        del self.undo_stack[:-self.limit]
        self.redo_stack.clear()

    def undo(self, data_dir):
        """Step back one change. Returns a message, or None if nothing to do."""
        if not self.undo_stack:
            return None
        step = self.undo_stack.pop()
        # Reverse order, so when one file was saved twice inside a group the
        # first snapshot - the oldest text - is the one left in place.
        for entry in reversed(step["entries"]):
            self.write(data_dir, entry["name"], entry["before"])
        self.redo_stack.append(step)
        del self.redo_stack[:-self.limit]
        return f"Undid: {describe(step)}"

    def redo(self, data_dir):
        """Replay one undone change. Returns a message, or None if nothing to do."""
        if not self.redo_stack:
            return None
        step = self.redo_stack.pop()
        for entry in step["entries"]:
            self.write(data_dir, entry["name"], entry["after"])
        self.undo_stack.append(step)
        del self.undo_stack[:-self.limit]
        return f"Redid: {describe(step)}"
