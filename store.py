"""Storage for projects, machines, repository entries and study progress.

Every project is an independent dashboard. It keeps its own machines, its own
repository, its own current and next machine, its own hours, deadline and theme,
and nothing it does touches another project. Switching projects restores that
project's last saved state because every value lives under its own key.

Files in the data folder:
    projects.json   the project list, the active one, and each one's theme
    machines.json   current/next and the machine list, per project
    repository.json   repository entries and their categories, per project
    progress.json   hours and deadline, per project

Writes are atomic and every overwrite is backed up, so a crash cannot take the
data with it.
"""

import json
import os
import re
import shutil
import stat
import time
from datetime import date
from pathlib import Path

from history import History
from safeio import atomic_write
from themes import DEFAULT_THEME, ORDER as THEME_ORDER

APP = Path(__file__).parent
# TDASH_DATA lets the app live somewhere read-only while data sits elsewhere.
DATA = Path(os.environ.get("TDASH_DATA") or APP / "data")
BACKUPS = DATA / "backups"
KEEP_BACKUPS = 10

# The files that must exist for the app to run at all.
DATA_FILES = ("projects", "machines", "repository", "progress")

# Settings hold the active selection, not study data, so undo skips them.
NO_HISTORY = {"settings"}
HISTORY = History()

# The dashboard's lower panel can be called either of these.
PANEL_TOPIC = "Topics"
PANEL_NAMES = (PANEL_TOPIC, "Machines")

STAT_KEYS = ["hours_studied"]
MAX_NAME = 40

# A description is the one-line answer to "what is this box", read to decide
# whether to open it - two lines on a normal terminal and no more. The limit
# is enforced here, in the store, so every door into the field - the add form,
# the edit form, a machine's own categories screen - obeys the same rule.
DESCRIPTION_LIMIT = 160


def description_too_long(description):
    """The error for an over-long description, or None when it fits."""
    if description is not None and len(description.strip()) > DESCRIPTION_LIMIT:
        return (f"Keep the description short - at most {DESCRIPTION_LIMIT} "
                "characters")
    return None


# ---------------------------------------------------------------- persistence

# Control characters never mean anything in the text this app draws, and the
# dangerous ones do not stay inside it: an OSC 52 sequence in a machine name is
# an instruction to the *terminal* to rewrite the clipboard, and a hand-edited
# or imported file is all it takes to get one in. Notes keep their newlines and
# tabs, which are the two that do mean something.
_CONTROL = re.compile("[\x00-\x08\x0b-\x1f\x7f-\x9f]")


def clean_text(text):
    """The same text with control characters taken out."""
    return _CONTROL.sub("", text)


def _clean_data(node):
    """A loaded file with every string safe to draw, keys included."""
    if isinstance(node, dict):
        return {clean_text(k) if isinstance(k, str) else k: _clean_data(v)
                for k, v in node.items()}
    if isinstance(node, list):
        return [_clean_data(v) for v in node]
    if isinstance(node, str):
        return clean_text(node)
    return node


def load(name):
    """Read a data file, keeping the shape the readers already rely on.

    A missing, unreadable or malformed file used to raise on the first screen
    that touched it, so a half-deleted data directory killed the app at the
    door - with nothing left on screen to say what it wanted back. The empty
    shape lets the app open on whatever is left; heal() is what restores the
    real thing from a backup at start-up.

    Everything else in the file is passed through untouched: the registry keeps
    active and order there, and throwing those away would reset the project you
    were working on."""
    data = {}
    path = DATA / f"{name}.json"
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}                  # broken: fall through to the empty shape
    if not isinstance(data, dict):
        data = {}
    raw = data.get("projects")
    if not isinstance(raw, dict):
        raw = {}
    # A record that is not an object would take any loop over it down; it holds
    # nothing worth reading, so it is dropped rather than trusted.
    data = dict(data)
    data["projects"] = {key: value for key, value in raw.items()
                        if isinstance(value, dict)}
    return _clean_data(data)


def readable(path):
    """True when a file holds valid JSON. Missing or broken counts as False."""
    try:
        json.loads(path.read_text(encoding="utf-8"))
        return True
    except (OSError, ValueError):
        return False


def _by_time(paths):
    """Sort backups newest first. Names cannot be trusted: the same-second
    collision suffix ('...-0') sorts before the base name."""
    return sorted(paths, key=lambda p: p.stat().st_mtime_ns, reverse=True)


def newest_backup(stem):
    """The most recent readable backup of one file, or None."""
    for path in _by_time(BACKUPS.glob(f"{stem}.*.json")):
        if readable(path):
            return path
    return None


def backup(path):
    """Copy a file into backups/ before it is overwritten, keeping the newest few."""
    if not path.exists():
        return
    BACKUPS.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    dest = BACKUPS / f"{path.stem}.{stamp}.json"
    tries = 0
    while dest.exists():
        dest = BACKUPS / f"{path.stem}.{stamp}-{tries}.json"
        tries += 1
    # copyfile, not copy2: the backup's own mtime records when it was taken,
    # which is what keeps the backups in order.
    shutil.copyfile(path, dest)
    for stale in _by_time(BACKUPS.glob(f"{path.stem}.*.json"))[KEEP_BACKUPS:]:
        stale.unlink(missing_ok=True)


# Bumped on every write. The dashboard caches its rendered rows, and a cache
# keyed only on the terminal size would keep showing progress that has since
# changed. Counting writes is far cheaper than re-measuring the layout.
VERSION = [0]


def data_version():
    return VERSION[0]


def save(name, data, record=True):
    """Write a data file atomically, backing it up and recording it for undo.

    record=False keeps a write out of the undo stacks - used for switching the
    active project, which changes a file but not any project's content, and
    for bootstrap and heal, which are housekeeping rather than edits.

    The before and after text are both recorded, in one step with the write
    itself; recording only the "before" left redo with nothing to replay."""
    path = DATA / f"{name}.json"
    text = json.dumps(data, indent=2) + "\n"
    remember = record and name not in NO_HISTORY
    before = None
    if remember:
        try:
            before = path.read_text(encoding="utf-8")
        except OSError:
            before = None
    backup(path)
    atomic_write(path, text)
    VERSION[0] += 1
    if remember:
        key = active()
        HISTORY.record(DATA, name, before, text, key,
                       project_name(key) if key else None)


def heal():
    """Repair unreadable data files from backups. Returns a note per repair."""
    notes = []
    for name in DATA_FILES:
        path = DATA / f"{name}.json"
        if not path.exists() or readable(path):
            continue
        good = newest_backup(name)
        if good is None:
            notes.append(f"{path.name} is unreadable and no backup survives")
            continue
        atomic_write(path, good.read_text(encoding="utf-8"))
        notes.append(f"{path.name} was unreadable, restored from {good.name}")
    notes.extend(_rename_fields_to_categories())
    _rename_retired_themes()
    _flag_os_projects()
    notes.extend(_mark_os_where_it_belongs())
    notes.extend(_migrate_machine_categories())
    _lock_down_permissions()
    return notes


def _lock_down_permissions():
    """Keep the data directory to the person it belongs to.

    These files hold the project's credentials, notes and progress. A default
    umask left them readable by every other account on the machine - and study
    notes are not something to hand out to anyone with a shell. Silent: this
    is housekeeping on your own files, not a repair to report."""
    if os.name == "nt":              # chmod only toggles read-only there
        return
    for root, dirs, files in os.walk(DATA):
        for name in dirs:
            _chmod(Path(root) / name, 0o700)
        for name in files:
            path = Path(root) / name
            if not path.is_symlink():
                _chmod(path, 0o600)
    _chmod(DATA, 0o700)


def _chmod(path, mode):
    """Best effort: a file we cannot tighten is not a reason to fail heal."""
    try:
        if stat.S_IMODE(path.stat().st_mode) != mode:
            os.chmod(path, mode)
    except OSError:
        pass


def _rename_fields_to_categories():
    """Move files written before categories were called that.

    Two keys changed: the list of definitions and the map of what a machine
    shows moved from "fields" to "categories", and the label that draws a list
    into sections moved from "category" to "group" - because a category is now
    the thing a machine chooses, and two different things answering to one name
    is how a list ends up grouped by the wrong thing."""
    notes = []
    # projects.json holds no machines or entries, but it does hold a project's
    # summary settings - which is where the chosen columns are kept.
    for name in ("machines", "repository", "progress", "projects"):
        if not (DATA / f"{name}.json").exists():
            continue
        try:
            data = load(name)
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        changed = False
        for record in (data.get("projects") or {}).values():
            if not isinstance(record, dict):
                continue
            if isinstance(record.get("fields"), list) and "categories" not in record:
                record["categories"] = record.pop("fields")
                changed = True
            for item in [i for i in (record.get("items") or [])
                         if isinstance(i, dict)]:
                # Whatever is under the old key moves, list or map: the very
                # oldest layout kept a machine's own fields as a list, and
                # leaving that behind meant those rows were never migrated.
                if "fields" in item and "categories" not in item:
                    item["categories"] = item.pop("fields")
                    changed = True
                for definition in [f for f in (record.get("categories") or [])
                                   if isinstance(f, dict)]:
                    if "category" in definition and "group" not in definition:
                        definition["group"] = definition.pop("category")
                        changed = True
                if "category" in item and "group" not in item:
                    item["group"] = item.pop("category")
                    changed = True
            saved = record.get("summary")
            if isinstance(saved, dict) and "fields" in saved \
                    and "categories" not in saved:
                saved["categories"] = saved.pop("fields")
                changed = True
        if changed:
            save(name, data, record=False)
            notes.append(f"{name}.json: fields are called categories now")
    return notes


# Theme names that were once somebody's idea of a default, or were cut when
# the list was trimmed to twenty-one vivid ones, and are now somebody else's
# data. Heal renames them in place: a project that chose "htb" keeps exactly
# the look it had, and one that chose a cut name lands on the closest colour
# still in the picker.
RETIRED_THEMES = {
    "htb": "jade", "parrot": "teal", "cyan": "teal",
    "lagoon": "teal", "emerald": "mint", "malachite": "mint",
    "aquamarine": "mint", "lime": "moss", "ocean": "cobalt",
    "green": "jade", "steel": "cornflower", "slate": "cornflower",
    "sky": "cornflower", "indigo": "violet", "amethyst": "violet",
    "plum": "violet", "orchid": "lavender", "fuchsia": "violet",
    "magenta": "rose", "sand": "gold", "butter": "gold",
    "lemon": "gold", "amber": "gold", "crimson": "red",
}


def _rename_retired_themes():
    """Point projects at the current names for the themes they picked."""
    reg = registry()
    renamed = False
    for record in reg["projects"].values():
        if record.get("theme") in RETIRED_THEMES:
            record["theme"] = RETIRED_THEMES[record["theme"]]
            renamed = True
    if renamed:
        save_registry(reg, record=False)


def _flag_os_projects():
    """Turn the OS on for a project that has been using it.

    No names in here: a project whose machines carry OS answers plainly keeps
    the OS as a category, and one that never used it never grows a row. This
    runs before the marking below so a project switched on this way gets the
    same one-time pass over its machines. Silent - a setting, not a repair."""
    try:
        boards = load("machines").get("projects") or {}
    except (OSError, ValueError):
        return
    used = []
    for key, board in boards.items():
        if not isinstance(board, dict):
            continue
        for machine in board.get("items") or []:
            if not isinstance(machine, dict):
                continue
            own = machine.get("categories")
            if (isinstance(own, dict) and OS_CATEGORY in own) \
                    or (machine.get("os") or "").strip():
                used.append(key)
                break
    reg = registry()
    changed = [k for k in used if k in reg["projects"]
               and not reg["projects"][k].get(OS_SETTING)]
    if not changed:
        return
    for key in changed:
        reg["projects"][key][OS_SETTING] = True
    save_registry(reg, record=False)


def _mark_os_where_it_belongs():
    """Put the OS on the machines of a project that uses it.

    One time, and only for a machine that has no answer either way - a machine
    the user has unmarked keeps its answer, and a project that never used the
    OS is left alone."""
    notes = []
    if not (DATA / "machines.json").exists():
        return notes
    try:
        data = load("machines")
    except (OSError, ValueError):
        return notes
    if not isinstance(data, dict):
        return notes
    changed = False
    for key, board in (data.get("projects") or {}).items():
        if not offers_os(key) or not isinstance(board, dict):
            continue
        for machine in [m for m in (board.get("items") or [])
                        if isinstance(m, dict)]:
            own = machine.get("categories")
            if own is None:
                own = {}
                machine["categories"] = own
            if isinstance(own, dict) and OS_CATEGORY not in own:
                own[OS_CATEGORY] = None
                changed = True
    if changed:
        save("machines", data, record=False)
        notes.append("the OS is marked on every machine")
    return notes


def _migrate_machine_categories():
    """Turn categories written on a machine into shared ones the machine uses.

    One loaded copy throughout. Calling the store's own add function from in
    here would reload the file and save its own version, throwing away the
    categories the migration had not written yet."""
    notes = []
    if not (DATA / "machines.json").exists():
        return notes
    data = load("machines")            # load already returns the empty shape
    changed = False
    # Straight into the copy this function saves. sections() loads the file
    # again, so walking its records mutated a second copy and the save wrote
    # back the untouched original: the migration reported that it had moved
    # the fields, and left every one of them where it was.
    for board in ((data.get("projects") or {}) if isinstance(data, dict)
                  else {}).values():
        if not isinstance(board, dict):
            continue
        board.setdefault("categories", [])
        by_title = {category_title(f).strip().lower(): f.get("id")
                    for f in board_categories(board)}
        used = {f.get("id") for f in board_categories(board)}
        # These are the same objects `data` holds, which is the whole point of
        # this function: mutating a copy and saving the original would throw
        # the migration away. A row that is not an object holds nothing to
        # move, and would take any loop over it down.
        for machine in [m for m in (board.get("items") or [])
                        if isinstance(m, dict)]:
            legacy = machine.get("categories")
            if not isinstance(legacy, list):
                continue
            own = {}
            for field in legacy:
                if not isinstance(field, dict):
                    continue      # a row of junk holds nothing to move
                title = category_title(field).strip()
                if not title:
                    continue
                if title.lower() not in by_title:
                    number = 1
                    while f"f{number}" in used:
                        number += 1
                    used.add(f"f{number}")
                    by_title[title.lower()] = f"f{number}"
                    board.setdefault("categories", []).append({
                        "id": f"f{number}", "title": title,
                        "default": (field.get("body") or "").strip()})
                own[by_title[title.lower()]] = (field.get("body") or
                                                "").strip()
            machine["categories"] = own
            changed = True
    if changed:
        save("machines", data, record=False)
        notes.append("categories written on a machine are now shared by "
                     "the project")
    return notes


def today_iso():
    """Today's local date, shared by marking and Summary so they cannot drift.

    TDASH_TODAY pins the date, which keeps Summary testable and lets someone
    travelling across a date line pin the day they actually mean.
    """
    return os.environ.get("TDASH_TODAY") or date.today().isoformat()


def undo():
    """Undo this session's last change, or None when there is nothing to undo.

    The history writes files directly, so the write counter is bumped by hand:
    the dashboard caches its rows on it, and without the bump the data went
    back while the screen kept showing what was there before."""
    said = HISTORY.undo(DATA)
    if said is not None:
        VERSION[0] += 1
    return said


def redo():
    """Redo this session's last undone change, or None if there is nothing."""
    said = HISTORY.redo(DATA)
    if said is not None:
        VERSION[0] += 1
    return said


# ------------------------------------------------------------------- projects

def empty_project(name="New Project", theme=DEFAULT_THEME):
    return {"name": name, "theme": theme, "objective": "", "created": today_iso()}


def registry():
    """The project list, guaranteed to have an active project."""
    try:
        data = load("projects")
    except (OSError, ValueError):
        return _fresh_registry()
    raw = data.get("projects")
    if not isinstance(raw, dict):
        return _fresh_registry()
    # Ignore anything that is not a real project record, so a stray key in the
    # file cannot take the whole app down with it.
    projects = {k: v for k, v in raw.items() if isinstance(v, dict)}
    if not projects:
        return _fresh_registry()
    order = [k for k in data.get("order", []) if k in projects]
    order += [k for k in projects if k not in order]
    active = data.get("active")
    return {"projects": projects, "order": order,
            "active": active if active in projects else order[0]}


def _fresh_registry():
    key = slug("My Project")
    return {
        "projects": {key: empty_project()},
        "order": [key],
        "active": key,
    }


def save_registry(reg, record=True):
    save("projects", {"projects": reg["projects"],
                      "order": reg["order"],
                      "active": reg["active"]}, record=record)


def active():
    """The project currently being viewed."""
    return registry()["active"]


def project_keys(reg=None):
    return (reg or registry())["order"]


def project(reg=None, key=None):
    """One project's record (name, theme, created)."""
    reg = reg or registry()
    return reg["projects"].get(key or reg["active"], {})


def project_name(key=None):
    return project(key=key).get("name", "?")


def project_objective(key=None):
    """What this project is for. Defaults to its name when never set."""
    key = key or active()
    return project(key=key).get("objective") or project_name(key)


def set_objective(key, text):
    """Set a project's objective. Blank clears it back to its name."""
    reg = registry()
    if key not in reg["projects"]:
        return "No such project"
    reg["projects"][key]["objective"] = text.strip()
    save_registry(reg)
    return None


SUMMARY_ALWAYS = ("Status", "Date", "Notes")

# The OS is not one of the project's categories - it is written on the machine,
# one box at a time - but it is chosen the same way and sits in the same list.
# This is the id it answers to.
OS_CATEGORY = "os"


def summary_settings(key=None):
    """What Show Summary puts on screen for this project.

    Only the two things that can be turned off are stored: whether the
    machines are named at all, and which of the project's fields are shown.
    Status, Date and Notes are in every summary - that is what makes one a
    summary - so there is nothing to save for them and nothing that can be
    switched off by accident."""
    key = key or active()
    saved = project(key=key).get("summary") or {}
    have = [f.get("id") for f in project_categories(key)]
    chosen = [f for f in (saved.get("categories") or [])
              if f == OS_CATEGORY or f in have]
    return {"machines": saved.get("machines", True) is not False,
            "categories": chosen, "always": list(SUMMARY_ALWAYS)}


def summary_status_word(key=None):
    """What the Status column says for a finished machine.

    "Done" unless the project asked for the other one, so the column does not
    begin every write-up with a word that means nothing outside the lab."""
    key = key or active()
    saved = project(key=key).get("summary") or {}
    return "pwned" if saved.get("status") == "pwned" else "Done"


def summary_toggle_status_word(key=None):
    """Switch the Status column between Done and pwned."""
    key = key or active()
    other = "Done" if summary_status_word(key) == "pwned" else "pwned"
    return _save_summary(key, {"status": other.lower()})


def summary_category_ids(key=None):
    """The chosen fields in the order they were picked, not the order defined.

    The OS leads when it is one of them: it is the field every machine has, so
    it reads as the start of the row rather than as one more column somewhere
    in the middle."""
    key = key or active()
    want = summary_settings(key)["categories"]
    out = [OS_CATEGORY] if OS_CATEGORY in want and offers_os(key) else []
    out += [f.get("id") for f in project_categories(key)
            if f.get("id") in want and f.get("id") != OS_CATEGORY]
    return out


def summary_category_title(field_id, key=None):
    """What a chosen field is called in the summary's column heading."""
    if field_id == OS_CATEGORY:
        return "OS"
    field = next((f for f in project_categories(key)
                  if f.get("id") == field_id), None)
    return (field or {}).get("title", "?")


def summary_category_known(field_id, key=None):
    """True if this id is something the summary can show."""
    return (field_id == OS_CATEGORY
            or any(f.get("id") == field_id
                   for f in project_categories(key)))


def summary_toggle_category(key, field_id, on=None):
    """Put a field in the summary, take it out, or flip it.

    The order picked in is the order shown in, and taking one out does not
    disturb the rest."""
    key = key or active()
    if not summary_category_known(field_id, key):
        return "No such category"
    chosen = summary_settings(key)["categories"]
    if on is None:
        on = field_id not in chosen
    if on and field_id not in chosen:
        chosen = chosen + [field_id]
    elif not on:
        chosen = [f for f in chosen if f != field_id]
    else:
        chosen = list(chosen)
    return _save_summary(key, {"categories": chosen})


def summary_show_machines(key, on=None):
    """Whether Show Summary names the machines at all."""
    key = key or active()
    current = summary_settings(key)["machines"]
    return _save_summary(key, {"machines": (not current) if on is None else on})


def _save_summary(key, change):
    """Write part of a project's summary settings, keeping the rest."""
    reg = registry()
    if key not in reg["projects"]:
        return "No such project"
    saved = dict(reg["projects"][key].get("summary") or {})
    saved.update(change)
    reg["projects"][key]["summary"] = saved
    save_registry(reg)
    return None


def project_theme(key=None):
    """The theme for a project, defaulting when it is missing or unknown."""
    value = project(key=key).get("theme")
    return value if value in THEME_ORDER else DEFAULT_THEME


def select(key):
    """Switch the active project.

    Not recorded for undo: moving between projects is navigation, not an edit,
    and an undoable switch would put a change on the undo stack belonging to
    whichever project you had just left - so undoing in the new one touched the
    old one's data."""
    reg = registry()
    if key in reg["projects"]:
        reg["active"] = key
        save_registry(reg, record=False)


def slug(text):
    """A stable key for a project name."""
    cleaned = "".join(ch.lower() if ch.isalnum() else "-" for ch in text.strip())
    cleaned = "-".join(part for part in cleaned.split("-") if part)
    return (cleaned or "project")[:MAX_NAME]


def unique_key(base, taken):
    key = base
    n = 2
    while key in taken:
        key = f"{base}-{n}"
        n += 1
    return key


def create_project(name):
    """Add a project. Returns (key, error)."""
    name = name.strip()
    if not name:
        return None, "A project needs a name"
    reg = registry()
    key = unique_key(slug(name), reg["projects"])
    reg["projects"][key] = empty_project(name)
    reg["order"].append(key)
    reg["active"] = key
    # All four files in one undo step: a half-restored project is worse than
    # no undo at all, and undoing a creation should put the app back in one
    # press, the way the creation did.
    with HISTORY.group(f"created the project {name}"):
        save_registry(reg)
        save("machines", {"projects": {**load("machines").get("projects", {}), key: new_board()}})
        save("repository", {"projects": {**load("repository").get("projects", {}), key: new_repository()}})
        save("progress", {"projects": {**load("progress").get("projects", {}), key: new_stats()}})
    return key, None


def rename_project(key, name):
    """Rename a project, keeping its key so its data stays put."""
    name = name.strip()
    if not name:
        return "A project needs a name"
    reg = registry()
    if key not in reg["projects"]:
        return "No such project"
    reg["projects"][key]["name"] = name
    save_registry(reg)
    return None


def set_theme(key, theme):
    if theme not in THEME_ORDER:
        return "Unknown theme"
    reg = registry()
    if key not in reg["projects"]:
        return "No such project"
    reg["projects"][key]["theme"] = theme
    save_registry(reg)
    return None


def delete_project(key):
    """Remove a project and everything in it. Never deletes the last one."""
    reg = registry()
    if key not in reg["projects"]:
        return None, "No such project"
    if len(reg["projects"]) < 2:
        return None, "Cannot delete the last project"
    name = project_name(key)
    del reg["projects"][key]
    reg["order"] = [k for k in reg["order"] if k != key]
    if reg["active"] == key:
        reg["active"] = reg["order"][0]
    # The whole deletion is one undo step, so a project deleted by mistake
    # comes back whole - machines, repository and hours together.
    with HISTORY.group(f"deleted the project {name}"):
        save_registry(reg)
        for fname in ("machines", "repository", "progress"):
            data = load(fname)
            data.get("projects", {}).pop(key, None)
            save(fname, data)
    return None, None


# ------------------------------------------------------------------- machines

def new_board():
    return {"current": "", "next": "", "items": [], "categories": []}


def new_repository():
    return {"items": []}


def new_stats():
    return dict.fromkeys(STAT_KEYS, 0) | {"deadline": "", "panel": PANEL_TOPIC}


def sections(name):
    """The project records of a data file, with the ones that are not
    objects dropped - a stray key in the file cannot take the app down."""
    data = load(name)
    raw = data.get("projects") if isinstance(data, dict) else None
    if not isinstance(raw, dict):
        return {}
    return {key: value or {} for key, value in raw.items()
            if isinstance(value, dict)}


def board(key=None):
    """The machine board for a project, with its counts kept in step."""
    data = load("machines")
    projects = data.get("projects")
    if not isinstance(projects, dict):
        projects = {}
        data["projects"] = projects
    key = key or active()
    entry = projects.setdefault(key, new_board())
    # An item that is not an object would take any loop over the board down
    # with it; it says nothing you want to read, so it is dropped.
    entry["items"] = [item for item in entry.get("items") or []
                      if isinstance(item, dict)]
    if not isinstance(entry.get("categories"), list):
        entry["categories"] = []
    entry.setdefault("current", "")
    entry.setdefault("next", "")
    return entry


def machines(key=None):
    """A project's machines, as a list of objects.

    A row that is not an object, or that has no id to be found by, is dropped
    here rather than at each screen that draws one: the list, the panel and the
    tally then count the same machines, instead of the total being larger than
    the number of rows anyone can see."""
    return [m for m in (board(key).get("items") or []) if isinstance(m, dict)
            and isinstance(m.get("id"), str) and m["id"]]


def board_categories(entry):
    """A project's universal categories, as a list of objects.

    `board` keeps the key in step; this is the same guarantee for readers
    handed a whole record instead. A category that is not an object holds
    nothing you can read - no name, no body, no id, so it is dropped rather
    than trusted."""
    fields = (entry or {}).get("categories")
    if not isinstance(fields, list):
        return []
    return [f for f in fields if isinstance(f, dict)]


def repository_items(key=None):
    """The repository list for a project - a separate list from machines."""
    data = load("repository")
    key = key or active()
    entry = data.setdefault("projects", {}).setdefault(key, new_repository())
    entry.setdefault("items", [])
    # A repository entry that is not an object is not an entry.
    entry["items"] = [item for item in entry["items"] if isinstance(item, dict)]
    return entry["items"]


def stats(key=None):
    """Hours and deadline for a project, defaulted and live."""
    data = load("progress")
    if not isinstance(data.get("projects"), dict):
        data["projects"] = {}
    key = key or active()
    entry = data["projects"].setdefault(key, new_stats())
    for stat in STAT_KEYS:
        try:
            entry[stat] = int(entry.get(stat, 0) or 0)
        except (TypeError, ValueError):
            entry[stat] = 0
    entry.setdefault("deadline", "")
    return entry


def tally(key=None):
    """(completed, total) machines for a project.

    The counts come from machines(), so they cannot disagree with the list: a
    row the counts included and the list dropped made progress add up to more
    than there was."""
    items = machines(key)
    done = sum(1 for m in items
               if _as_int(m.get("completed")) >= _as_int(m.get("total"), 1))
    return done, len(items)


def _as_int(value, default=0):
    """A count as a number, whatever is stored under it."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def next_id(items):
    """A short id that does not clash with anything already in the list."""
    used = {m.get("id") for m in items}
    n = 1
    while f"m{n}" in used:
        n += 1
    return f"m{n}"


def add_machine(key, name, notes="", os_name="", description="",
                group=""):
    """Add a machine to a project. Returns (machine, error).

    description is the one-line summary of what the machine is ("Windows SMB box,
    medium"); notes are what you worked out on it. They are kept apart because
    they are read at different moments: the description to decide whether to
    open the box, the notes afterwards.

    os_name is the machine's operating system - Linux, Windows and so on. It is
    optional and the field is called "os" in the stored data; the parameter is
    not, because "os" is also the name of the standard library module."""
    name = name.strip()
    if not name:
        return None, "A machine needs a name"
    problem = description_too_long(description)
    if problem:
        return None, problem
    data = load("machines")
    entry = data["projects"].setdefault(key or active(), new_board())
    entry.setdefault("items", [])
    machine = {"id": next_id(entry["items"]), "name": name,
               "notes": notes.strip(),
               "os": os_name.strip(), "description": description.strip(),
               "group": (group or "").strip(),
               "completed": 0, "total": 1, "completed_on": ""}
    # Where a project uses the OS, a new machine starts with it marked; any
    # one machine can still be unmarked.
    if offers_os(key):
        machine.setdefault("categories", {})[OS_CATEGORY] = None
    entry["items"].append(machine)
    save("machines", data)
    return machine, None


def find_machine(key, machine_id):
    return next((m for m in machines(key) if m.get("id") == machine_id), None)


def find_machine_by_name(key, name):
    wanted = name.strip().lower()
    return next((m for m in machines(key)
                 if m.get("name", "").strip().lower() == wanted), None)


def edit_machine(key, machine_id, name=None, notes=None,
                 os_name=None, description=None, group=None):
    """Change a machine's fields. Returns (machine, error).

    Loaded once and mutated in place: reloading before the save would throw
    the edits away, because the edited item lives in a different copy."""
    key = key or active()
    data = load("machines")
    entry = data["projects"].get(key) or new_board()
    machine = next((m for m in entry.get("items", []) if m.get("id") == machine_id), None)
    if machine is None:
        return None, "No such machine"
    problem = description_too_long(description)
    if problem:
        return None, problem
    if name is not None:
        if not name.strip():
            return None, "A machine needs a name"
        machine["name"] = name.strip()
    if notes is not None:
        machine["notes"] = notes.strip()
    if os_name is not None:
        machine["os"] = os_name.strip()
    if description is not None:
        machine["description"] = description.strip()
    if group is not None:
        machine["group"] = group.strip()
    data["projects"][key] = entry
    save("machines", data)
    return machine, None


# ------------------------------------------------------------------ fields
#
# A field is defined once, universally, for the project: a title and a default
# body. Each machine then says which fields it uses and may override the body
# for itself. The title belongs to the field, never to the machine, so reading
# the same field across a dozen boxes compares like with like.

def project_categories(key=None):
    """The project's universal field definitions."""
    data = load("machines")
    return list(board_categories(data["projects"].get(key or active()) or {}))


NO_GROUP = "Ungrouped"


def category_title(field):
    """A field's title as text, whatever is stored under it.

    A hand-edited file, or a write interrupted halfway, can leave a title as a
    number or a list. Reading it as a string is what stops one odd row taking
    the whole list - and the migration - down."""
    title = (field or {}).get("title")
    return title if isinstance(title, str) else ("" if title is None
                                                else str(title))


def group_of(item):
    """An item's group, or the name for "none of them".

    The one place the empty group is spelled, so a list drawn by it and a
    prompt that seeds it cannot disagree about what a blank one is called."""
    return (item or {}).get("group", "").strip() or NO_GROUP


def group_order(groups):
    """Groups for a grouped list, each one once: the named ones in the order
    they were first seen, and the empty one last - a list of sections should
    not open on the ones nobody has named."""
    seen = []
    for name in groups:
        if name not in seen:
            seen.append(name)
    named = [c for c in seen if c and c != NO_GROUP]
    rest = [c for c in seen if c == NO_GROUP]
    return named + rest


def add_category(key, title, default="", group=""):
    """Define a field. Returns (field, error)."""
    title = (title or "").strip()
    if not title:
        return None, "A category needs a name"
    if any(f.get("title", "").strip().lower() == title.lower()
           for f in project_categories(key)):
        return None, f"There is already a category called {title}"
    data = load("machines")
    board = data["projects"].setdefault(key or active(), new_board())
    used = {f.get("id") for f in board.setdefault("categories", [])}
    n = 1
    while f"f{n}" in used:
        n += 1
    field = {"id": f"f{n}", "title": title, "default": (default or "").strip(),
             "group": (group or "").strip()}
    board["categories"].append(field)
    save("machines", data)
    return field, None


def edit_category(key, field_id, title=None, default=None, group=None):
    """Change a category's name, its default body or its group.

    Returns (field, error)."""
    key = key or active()
    data = load("machines")
    board = data["projects"].setdefault(key, new_board())
    field = next((f for f in board_categories(board)
                  if f.get("id") == field_id), None)
    if field is None:
        return None, "No such category"
    if title is not None:
        title = title.strip()
        if not title:
            return None, "A category needs a name"
        if any(f.get("id") != field_id and
               f.get("title", "").strip().lower() == title.lower()
               for f in board["categories"]):
            return None, f"There is already a category called {title}"
        field["title"] = title
    if default is not None:
        field["default"] = default.strip()
    save("machines", data)
    return field, None


def delete_category(key, field_id):
    """Remove a category everywhere: the definition and every machine's copy."""
    data = load("machines")
    board = data["projects"].get(key or active()) or new_board()
    fields = board_categories(board)
    if not any(f.get("id") == field_id for f in fields):
        return "No such category"
    board["categories"] = [f for f in fields if f.get("id") != field_id]
    # Take the deleted field off each machine and leave every other field, and
    # every other machine, exactly as it was. Dropping the whole "categories" key
    # instead took the marks of fields that had nothing to do with this one.
    for machine in board.get("items", []):
        own = machine.get("categories")
        if isinstance(own, dict) and field_id in own:
            own = {k: v for k, v in own.items() if k != field_id}
            if own:
                machine["categories"] = own
            else:
                machine.pop("categories", None)
    save("machines", data)
    return None


def attach_machine_categories(key, machine_id, field_ids):
    """Say which of the universal fields a machine uses.

    Nothing else changes: a field is either shown on a machine or it is not,
    and the content is the default unless the machine has overridden it."""
    data = load("machines")
    board = data["projects"].get(key or active()) or new_board()
    machine = next((m for m in board.get("items", [])
                    if m.get("id") == machine_id), None)
    if machine is None:
        return "No such machine"
    known = {f.get("id") for f in project_categories(key)}
    have = machine.get("categories") or {}
    # Every field the machine uses is a key here, even one that still reads the
    # shared default - its value is then empty, which is precisely "not
    # overridden". Keeping only the ones with a body made an unedited field
    # look unmarked.
    kept = {fid: have.get(fid) for fid in field_ids if fid in known}
    # An empty map and no key at all mean the same thing - the machine uses no
    # fields - so the key goes rather than leaving "{}" behind in the file.
    if kept:
        machine["categories"] = kept
    else:
        machine.pop("categories", None)
    save("machines", data)
    return None


def set_machine_category_bodies(key, machine_id, bodies):
    """Set several of a machine's field bodies in one go.

    bodies is {field_id: body}; a blank body puts the shared default back.
    One write means one backup and one step on the undo stack for editing a
    machine's fields, instead of one per field."""
    key = key or active()
    data = load("machines")
    board = data["projects"].get(key) or new_board()
    machine = next((m for m in board.get("items", [])
                    if m.get("id") == machine_id), None)
    if machine is None:
        return None, "No such machine"
    known = {f.get("id") for f in project_categories(key)}
    own = dict(machine.get("categories") or {}) if isinstance(
        machine.get("categories"), dict) else {}
    for field_id, body in bodies.items():
        if field_id not in known:
            return machine, f"No such category"
    for field_id, body in bodies.items():
        own[field_id] = (body or "").strip() or None
    if own:
        machine["categories"] = own
    else:
        machine.pop("categories", None)
    data["projects"][key] = board
    save("machines", data)
    return machine, None


def machine_category_body(key, machine_id, field_id, body):
    """Override one field's body for one machine. Empty body means the
    default, which is what a machine still reading the shared text sees."""
    data = load("machines")
    board = data["projects"].get(key or active()) or new_board()
    machine = next((m for m in board.get("items", [])
                    if m.get("id") == machine_id), None)
    if machine is None:
        return "No such machine"
    if field_id not in (machine.get("categories") or {}):
        return "That category is not on this machine"
    body = (body or "").strip()
    # An empty body keeps the field marked and simply drops the override, so
    # the machine goes back to reading the shared default. Popping the key
    # instead would have unmarked it.
    machine["categories"][field_id] = body or None
    save("machines", data)
    return None


# Whether a project tracks boxes by their OS is that project's own setting,
# kept with its name and theme. It is a setting rather than a rule about names
# so that nothing is special-cased: a project that has never used the OS never
# grows a row for it, and heal() turns it on for one that has.
OS_SETTING = "tracks_os"

# Description and Notes are permanent categories: every machine has them, they
# are never unmarked, and their content is the machine's own.
PERMANENT_CATEGORIES = (("description", "Description"),
                        ("notes", "Notes"))


def offers_os(key=None):
    """Whether this project's machines may show the OS as a category."""
    return bool(project(key=key).get(OS_SETTING))


def machine_os_marked(key, machine_id):
    machine = find_machine(key, machine_id)
    return isinstance((machine or {}).get("categories"), dict) \
        and OS_CATEGORY in (machine.get("categories") or {})


def machine_builtin_categories(key=None, machine_id=None):
    """The categories every machine has, whatever the project: Description and
    Notes, plus the OS where the project offers it and the machine keeps it.

    These are not in the project's list of definitions and are not ticked on:
    they are always there, which is what makes them permanent. Their content
    lives on the machine where it always did. The OS reads between them: it
    says what the box is, the way the description does, and a page of notes
    should not push it out of sight."""
    key = key or active()
    machine = find_machine(key, machine_id) or {}
    shown = set((machine.get("categories") or {})) \
        if isinstance(machine.get("categories"), dict) else set()
    out = [{"id": "description", "title": "Description",
            "body": machine.get("description", ""), "default": "",
            "overridden": True, "permanent": True}]
    if offers_os(key) and OS_CATEGORY in shown:
        out.append({"id": OS_CATEGORY, "title": "OS",
                    "body": machine.get("os", ""), "default": "",
                    "overridden": True, "permanent": False})
    out.append({"id": "notes", "title": "Notes",
                "body": machine.get("notes", ""), "default": "",
                "overridden": True, "permanent": True})
    return out


def machine_categories(key, machine_id):
    """The fields a machine uses, in the order they were defined, with the
    body this machine sees: its own override, or the shared default."""
    by_id = {f.get("id"): f for f in project_categories(key)}
    machine = find_machine(key, machine_id)
    own = (machine or {}).get("categories") or {}
    if not isinstance(own, dict):      # an older layout kept a list here
        own = {}
    out = []
    for field_id in by_id:
        if field_id not in own:
            continue
        out.append({"id": field_id,
                    "title": by_id[field_id].get("title", "?"),
                    "default": by_id[field_id].get("default", ""),
                    "body": own.get(field_id),
                    "overridden": bool(own.get(field_id))})
    return out


def machine_category_ids(key, machine_id):
    machine = find_machine(key, machine_id)
    return list(((machine or {}).get("categories") or {}).keys())


def delete_machine(key, machine_id):
    """Remove a machine, clearing it from current/next if it was one."""
    data = load("machines")
    entry = data["projects"].get(key) or new_board()
    before = len(entry.get("items", []))
    entry["items"] = [m for m in entry.get("items", []) if m.get("id") != machine_id]
    if len(entry["items"]) == before:
        return "No such machine"
    for field in ("current", "next"):
        if entry.get(field) == machine_id:
            entry[field] = ""
    save("machines", data)
    return None


def mark_machine(key, machine_id, done=True):
    """Mark a machine complete, or undo it. Returns (machine, error)."""
    data = load("machines")
    entry = data["projects"].get(key) or new_board()
    machine = next((m for m in entry.get("items", []) if m.get("id") == machine_id), None)
    if machine is None:
        return None, "No such machine"
    machine["completed"] = machine.get("total", 1) if done else 0
    machine["completed_on"] = today_iso() if done else ""
    save("machines", data)
    return machine, None


def toggle_machine(key, machine_id):
    """Flip a machine between complete and not, and report which it became."""
    machine = find_machine(key, machine_id)
    if machine is None:
        return None, "No such machine"
    was_done = machine.get("completed", 0) >= machine.get("total", 1)
    return mark_machine(key, machine_id, not was_done)


def set_slot(key, field, machine_id):
    """Point current or next at a machine. An empty id clears the slot."""
    if field not in ("current", "next"):
        return "Unknown field"
    data = load("machines")
    entry = data["projects"].get(key) or new_board()
    if machine_id and find_machine(key, machine_id) is None:
        return "No such machine"
    entry[field] = machine_id
    save("machines", data)
    return None


def slot_name(key, field):
    """The machine name in current or next, or an empty string."""
    machine = find_machine(key, board(key).get(field, ""))
    return machine.get("name", "") if machine else ""


def recent_completed(key=None, limit=5):
    """Machines marked complete, newest first, for the summary panel.

    Falls back to this when nothing was completed today, so the panel still has
    something to show - a tracker you cannot read without finishing a machine is
    no use on the days you are stuck."""
    done = [m for m in machines(key)
            if m.get("completed", 0) >= m.get("total", 1)]
    done.sort(key=lambda m: (m.get("completed_on") or "", m.get("name") or ""),
              reverse=True)
    return done[:limit]


def completed_today(key=None):
    """Machines completed today in a project, with their notes."""
    today = today_iso()
    return [m for m in machines(key)
            if m.get("completed_on") == today
            and m.get("completed", 0) >= m.get("total", 1)]


def reset_project(key):
    """Clear this project's machines and hours, keeping everything else."""
    data = load("machines")
    if not isinstance(data.get("projects"), dict):
        data["projects"] = {}
    entry = data["projects"].get(key) or new_board()
    cleared = sum(1 for m in entry.get("items", []) if m.get("completed", 0) > 0)
    for machine in entry.get("items", []):
        machine["completed"] = 0
        machine["completed_on"] = ""
    entry["current"] = ""
    entry["next"] = ""
    save("machines", data)
    hours = stats(key).get("hours_studied", 0)
    data = load("progress")
    data["projects"].setdefault(key, new_stats())["hours_studied"] = 0
    save("progress", data)
    return cleared, hours


# ------------------------------------------------------------------- repository

def add_repository(key, title, body="", group=""):
    """Add a repository entry. Returns (entry, error)."""
    title = title.strip()
    if not title:
        return None, "A repository entry needs a title"
    data = load("repository")
    entry = data["projects"].setdefault(key or active(), new_repository())
    entry.setdefault("items", [])
    item = {"id": next_id(entry["items"]), "title": title,
            "body": body.strip(), "group": (group or "").strip()}
    entry["items"].append(item)
    save("repository", data)
    return item, None


def find_repository(key, item_id):
    return next((i for i in repository_items(key) if i.get("id") == item_id), None)


def edit_repository(key, item_id, title=None, body=None, group=None):
    """Change a repository entry. Returns (entry, error)."""
    key = key or active()
    data = load("repository")
    entry = data["projects"].get(key) or new_repository()
    item = next((i for i in entry.get("items", []) if i.get("id") == item_id), None)
    if item is None:
        return None, "No such repository entry"
    if title is not None:
        if not title.strip():
            return None, "A repository entry needs a title"
        item["title"] = title.strip()
    if body is not None:
        item["body"] = body.strip()
    data["projects"][key] = entry
    save("repository", data)
    return item, None


def delete_repository(key, item_id):
    data = load("repository")
    entry = data["projects"].get(key) or new_repository()
    before = len(entry.get("items", []))
    entry["items"] = [i for i in entry.get("items", []) if i.get("id") != item_id]
    if len(entry["items"]) == before:
        return "No such repository entry"
    save("repository", data)
    return None


# ----------------------------------------------------------------- statistics

def add_hours(key, delta):
    data = load("progress")
    if not isinstance(data.get("projects"), dict):
        data["projects"] = {}
    entry = data["projects"].setdefault(key or active(), new_stats())
    entry["hours_studied"] = max(0, entry.get("hours_studied", 0) + delta)
    save("progress", data)
    return entry["hours_studied"]


def dashboard_panel(key=None):
    """Which name the dashboard's lower panel carries: Topics or Machines.

    Same figures either way - it is only the heading, and which one reads
    truer depends on whether you are thinking of the boxes or the list."""
    return stats(key).get("panel") or PANEL_TOPIC


def panel_noun(key=None):
    """The word for one entry in the dashboard panel: "machine" or "topic".

    A project that calls its panel Topics should not be told "No machines yet"
    three screens later. Every user-facing string goes through here rather than
    hard-coding the noun, which is how half of them drifted out of step."""
    return "machine" if dashboard_panel(key) == "Machines" else "topic"


def panel_noun_plural(key=None):
    return panel_noun(key) + "s"


def set_dashboard_panel(key, name):
    if name not in PANEL_NAMES:
        return None, f"Pick one of: {', '.join(PANEL_NAMES)}"
    data = load("progress")
    data["projects"].setdefault(key or active(), new_stats())["panel"] = name
    save("progress", data)
    return name, None


def set_deadline(key, iso):
    data = load("progress")
    data["projects"].setdefault(key or active(), new_stats())["deadline"] = iso
    save("progress", data)


def days_left(key=None):
    """Days remaining for a project, from its own deadline."""
    try:
        target = date.fromisoformat(stats(key).get("deadline") or "")
        return max(0, (target - date.fromisoformat(today_iso())).days)
    except (TypeError, ValueError):
        return "?"


# --------------------------------------------------------------- the example
#
# A fresh install opens on a worked example rather than an empty room: every
# screen has something in it, the notes on the first machine are the tour, and
# deleting the project leaves a clean one behind the way an empty install
# does. Nothing here is special - it is made of the same records the app
# writes when you use it.

DEMO_KEY = "demo"
DEMO_OBJECTIVE = ("A guided tour of tdash \u2014 delete this project when "
                  "you are done")

DEMO_TOUR = """Welcome. This is an example project: every screen has something in it, and these notes are the tour. Start a project of your own when you have looked around, then delete this one from the Project menu.

The menu at the top lists the screens and the key that opens each; every screen also prints what its own keys do along the bottom, so nothing here needs remembering. Enter opens whatever the cursor is on, Esc goes back, and Help explains the rest.

A few things to try:
  - Machines, then Enter on this one: a machine's page, with its fields and its notes. On the list, m marks a machine complete and c opens the categories a machine uses.
  - Summary: the whole project in one table.
  - Repository: a place for the commands and write-ups worth keeping.

Machines are sorted by the group you give them, under a heading per group; leave the group empty and a machine lands in the Ungrouped section at the end, like this one and "Loose End"."""


def _seed_demo():
    """Write the example project in one go, without history.

    There is nothing to undo on a fresh install, and half an example would be
    worse than none - which is why this builds the records directly instead
    of going through add_machine() and friends, each of which saves its own."""

    def machine(mid, name, notes="", description="", group="",
                categories=None, completed=0, completed_on=""):
        record = {"id": mid, "name": name, "notes": notes, "os": "",
                  "description": description, "group": group,
                  "completed": completed, "total": 1,
                  "completed_on": completed_on}
        if categories:
            record["categories"] = categories
        return record

    record = empty_project("Demo Project")
    record["objective"] = DEMO_OBJECTIVE
    save_registry({"projects": {DEMO_KEY: record},
                   "order": [DEMO_KEY], "active": DEMO_KEY}, record=False)

    start = machine("m1", "Start Here", notes=DEMO_TOUR,
                    description="Read this first: the notes are a short tour.")
    web = machine("m2", "Web Box", group="Web",
                  description="A finished machine, so a complete row has "
                              "something to show.",
                  notes="Marked off with m on the machines list: the tick and "
                        "the date are all the record there is. The date here "
                        "is an example.",
                  categories={"f1": None, "f2": None},
                  completed=1, completed_on="2026-01-15")
    ad = machine("m3", "AD Box", group="Windows",
                 description="Still going - it and Loose End are this "
                             "project's current and next.",
                 notes="Its Credentials line is answered for this machine "
                       "alone; the star on the machine's page marks an answer "
                       "that is not the shared default.",
                 categories={"f1": "svc_backup:try-me", "f2": None})
    loose = machine("m4", "Loose End",
                    description="A machine with no group, so it sits on its "
                                "own.",
                    notes="Give a machine a group to sort it under a heading "
                          "in the list.")
    board = {"current": "m3", "next": "m4",
             "items": [start, web, ad, loose],
             "categories": [
                 {"id": "f1", "title": "Credentials",
                  "default": "user:password", "group": ""},
                 {"id": "f2", "title": "Ticket", "default": "", "group": ""}]}
    save("machines", {"projects": {DEMO_KEY: board}}, record=False)
    save("repository", {"projects": {DEMO_KEY: {"items": [
        {"id": "r1", "title": "Keep the commands that worked",
         "body": "nmap -sC -sV -oA scan <ip>", "group": ""}]}}}, record=False)
    save("progress", {"projects": {DEMO_KEY: new_stats()}}, record=False)
    return ["An example project has been created - look around, then delete "
            "it and make one of your own"]


def bootstrap(demo=False):
    """Create anything missing. Returns the notes of what it made.

    demo is for the real thing: a first run gets the worked example above,
    while tests and tools that call this without asking get the empty first
    project hundreds of assumptions are built on."""
    notes = []
    # None of this is the user's doing, so none of it lands on the undo
    # stacks: a fresh session should not open with an undoable "first project
    # has been created" that undoing would take away.
    for name in DATA_FILES:
        if not (DATA / f"{name}.json").exists():
            save(name, {"projects": {}} if name != "projects" else
                 {"projects": {}, "order": [], "active": ""}, record=False)
            notes.append(f"{name}.json was missing and has been created")
    # The file, not registry(): registry() hands out a fresh project in
    # memory when the file is empty, so asking it here would never say "no".
    stored = load("projects").get("projects")
    if not isinstance(stored, dict) or not stored:
        if demo:
            notes.extend(_seed_demo())
        else:
            save_registry(_fresh_registry(), record=False)
            notes.append("A first project has been created")
    return notes
