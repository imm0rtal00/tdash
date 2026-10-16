#!/usr/bin/env python3

"""tdash: a terminal study dashboard, built around independent projects.

Every project is its own dashboard with its own machines, repository, current and
next machine, hours, deadline and theme. Nothing one project does affects
another, and switching back restores exactly what that project was left at.

Menu keys:
    1 Project   switch, create, rename or delete a project
    2 Machines  mark (with details), add, edit or delete machines
    3 Repository  add, edit, delete or read repository entries
    4 Settings  objective, current, next, hours, deadline, themes, reset
    5 Help      key bindings
    6 Summary   what was completed today
    0 Quit
"""

import argparse
import sys

from rich.console import Group
from rich.live import Live
from rich.table import Table
from rich.text import Text

import store
import ui
import themes
from tui import (
    KEY_COPY,
    KEY_DOWN,
    KEY_HOME,
    KEY_LEFT,
    KEY_PGDN,
    KEY_RIGHT,
    KEY_UP,
    console,
    copy_to_clipboard,
    inline_list,
    inline_prompt,
    raw_mode,
    read_key,
    show_details,
    KEY_PGDN,
    KEY_PGUP,
    KEY_WHEEL_DOWN,
    KEY_WHEEL_UP,
    ESCAPE,
    wait_for_key,
)
from ui import (
    MENU_ITEMS,
    build_layout,
    clip,
    detail_panel,
    hint_line,
    menu_move_across,
    menu_move_down,
    summary_panel,
    as_typed,
)

# ctrl+x u / r / q. Handed back from tui, which turns the pair into one token,
# so they work in every picker and editor as well as on the dashboard.
SCROLL_LINES = 3


def show_screen(live, renderable, top):
    """Draw a screen, windowing it when it is taller than the terminal.

    Returns (top, max_top). Nothing else can scroll these screens: the dashboard
    has its own, and a list scrolls its own rows, but a panel taller than the
    screen simply used to run off the bottom with no way to see it."""
    body, top, max_top = ui.window_screen(renderable, top)
    live.update(body)
    live.refresh()
    return top, max_top


def scroll_step(key, top, max_top, height=None):
    """Where a scroll key should move the window to, or None if it is not one.

    Used by every screen that can overflow: the dashboard, the machine detail,
    the summary, the repository. Arrow keys are deliberately absent - they belong
    to whatever list is on screen, and swallowing them is what made navigation
    look broken before."""
    page = (height or console.height) - 1
    if key == KEY_WHEEL_DOWN:
        return min(max_top, top + SCROLL_LINES)
    if key == KEY_WHEEL_UP:
        return max(0, top - SCROLL_LINES)
    if key == KEY_PGDN:
        return min(max_top, top + page)
    if key == KEY_PGUP:
        return max(0, top - page)
    if key == KEY_HOME:
        return 0
    if key == KEY_END:
        return max_top
    return None


from tui import (CHORD_QUIT, CHORD_REDO, CHORD_UNDO, KEY_END, Chord)

BACK = object()


def back():
    """Sentinel meaning "Esc was pressed here"; the caller climbs one level."""
    return BACK


def note(live, message, body, extra="", chords=None):
    """Show a panel until a key is pressed.

    A body taller than the terminal is paged, one keypress per page. Help
    outgrew a short screen and its last lines - undo, ctrl+s - were simply
    invisible, with no keypress able to bring them back.

    A ctrl+x command redraws the same page with what it said rather than
    closing the panel and rebuilding the dashboard behind it.
    """
    if extra:
        body = (body + f"\n{extra}" if isinstance(body, str)
                else body + Text("\n" + extra))
    if isinstance(body, str):
        body = Text(body)
    lines = body.split("\n", allow_blank=True)
    layout = build_layout(message=message)
    room = console.height - len(console.render_lines(layout, console.options))
    room = max(1, room)
    at = 0
    while at < len(lines):
        more = len(lines) - at > room
        take = max(1, room - 1 if more else room)
        chunk = lines[at:at + take]
        more = at + take < len(lines)
        piece = Text("\n").join(chunk)
        if more:
            piece.append("\nany key for more", style="dim")
        # A chord keeps the page up; only a plain key turns it.
        while True:
            live.update(Group(build_layout(message=message), piece))
            live.refresh()
            said = wait_for_key(chords)
            if said is None:
                break
            if isinstance(said, str):
                message = said
        at += take


def confirm(live, question, message=None):
    """Ask a yes/no question. Returns True only for an explicit `Y`.

    The prompt reads `Y/n` and takes nothing else. Enter cancels, `n` cancels,
    `Y` confirms; every other key is ignored and the question is asked again.
    A mistyped answer must not read as a quiet no, and anything that destroys
    work should lose to a stray keypress rather than win by default.

    Enter and Esc both arrive as None from the prompt, and both cancel, so they
    do not need telling apart."""
    while True:
        answer = inline_prompt(live, question, message, placeholder="Y/n")
        if answer is None:
            return False              # Enter or Esc
        answer = answer.strip()
        if answer == "Y":
            return True
        if answer == "n":
            return False
        # Anything else: ask again rather than guess.


# ------------------------------------------------------------------ pickers

def project_choices():
    """[(label, key)] for every project, in order, with its machine tally."""
    reg = store.registry()
    rows = []
    for key in reg["order"]:
        done, total = store.tally(key)
        mark = " (here)" if key == reg["active"] else ""
        count = f"{done}/{total}" if total else "empty"
        rows.append((f"{store.project_name(key)}  [{count}]{mark}", key))
    return rows


def _usable(items):
    """The items that can be listed: an object, with an id to go by.

    A data file edited by hand - or a write cut short - can hold a row that is
    not a machine at all, or one with no id. Indexing straight into it raised
    KeyError and took the list, and everything behind it, down."""
    return [item for item in (items or []) if isinstance(item, dict)
            and isinstance(item.get("id"), str) and item["id"]]


def machine_choices(key=None):
    """[(label, id)] for a project's machines, with a tick on the finished ones."""
    return [(machine_label(machine), machine["id"])
            for machine in _usable(store.machines(key))]


def machine_label(machine):
    name = machine.get("name") or "(untitled)"
    done = machine.get("completed", 0) >= machine.get("total", 1)
    return f"✓ {name}" if done else name


def machine_items(key=None):
    """{id: machine} - what pick() groups by."""
    return {machine["id"]: machine for machine in _usable(store.machines(key))}


def repository_choices(key=None):
    """[(label, id)] for a project's repository entries.

    An untitled entry is shown as (untitled) rather than as a blank line, so
    it can be told apart from an empty list - and so the row you can see is
    the row you can open."""
    return [(i.get("title") or "(untitled)", i["id"])
            for i in _usable(store.repository_items(key))]


def repository_items(key=None):
    """{id: entry} - what pick() groups by."""
    return {i["id"]: i for i in _usable(store.repository_items(key))}


def drawn_rows(pairs, grouped, sort_groups=True):
    """The (section, label) rows the picker will draw, in drawing order.

    A screen that reopens its list after you leave it needs to remember which
    row the cursor was on, and a row number only means something in the order
    the rows were actually drawn - grouped and sorted, not the raw order the
    pairs arrived in.
    """
    section = grouped() if callable(grouped) else grouped
    rows = [(store.group_of(section.get(i)), label) for label, i in pairs]
    if sort_groups:
        order = store.group_order([row[0] for row in rows])
        rows.sort(key=lambda row: order.index(row[0]))
    return rows


def drawn_position(pairs, grouped, key):
    """Where in the drawn list the pair with this id sits, or None.

    The drawn rows carry labels, so the id is read back as a label first; the
    number returned is one the picker's `at` understands, because both come
    from drawn_rows."""
    label = next((label for label, i in pairs if i == key), None)
    drawn = [label for _, label in drawn_rows(pairs, grouped)]
    return drawn.index(label) if label in drawn else None


def pick(live, prompt, pairs, message, empty="Nothing to choose from yet",
         hint=None, shortcuts=None, refresh=None, ticks=None,
         grouped=None, sort_groups=True, at=None):
    """Pick one id from (label, id) pairs.

    The picker is handed plain label strings, not the pairs: tui.prepare_rows
    reads any two-tuple as (group, name), which would show the label as a
    group heading and the id as the row. `ticks` says which of the pairs carry
    a mark, drawn the way the machines list draws a finished box. Returns
    (id, problem)."""
    if not pairs:
        return None, empty
    # ticks arrives keyed by id (or as a callable that re-reads them) and goes
    # to the picker as a list in the order the rows come out.
    marks = None
    if ticks:
        marks = (ticks if callable(ticks)
                 else lambda: [ticks.get(i, False) for _, i in pairs])
    # `grouped` is {id: item} - or a callable returning it, so a changed list
    # is re-read - for a list drawn in sections by category. The picker is
    # handed (heading, label) pairs, which it reads as groups; the id lookup
    # below is by label either way, so nothing else has to know.
    def group_rows(fresh_pairs):
        # Rows come out grouped, not just labelled: the picker only draws a
        # heading when the group changes, so unsorted rows under two headings
        # would print the same group over and over. A screen that has already
        # put its rows in the order it means to draw them - the categories a
        # machine shows, permanent ones first - says so with sort_groups.
        return drawn_rows(fresh_pairs, grouped, sort_groups)

    if grouped:
        listed = group_rows(pairs)
        # refresh re-reads the pairs, and this is where they are turned back
        # into a drawn list. A screen's refresh used to hand the picker plain
        # names, so one mark dropped every group heading and re-sorted the
        # list out from under the cursor.
        fresh = (lambda: group_rows(refresh())) if refresh else None
    else:
        listed = [label for label, _ in pairs]
        fresh = (lambda: [label for label, _ in refresh()]) if refresh else None
    chosen = inline_list(live, prompt, listed, message,
                         hint=hint, shortcuts=shortcuts,
                         refresh=fresh, ticks=marks, start=at,
                         chords=chord_in_place)
    # None means "cancelled". An empty string is a real answer: a repository
    # entry or a machine with no title still has an id behind it, and testing
    # the label's truth instead of testing it against None made an untitled
    # row impossible to open.
    if chosen is None:
        return None, None
    return next((i for label, i in pairs if label == chosen), None), None


def submenu(live, title, entries, message):
    """A sub-menu: what opens when you pick something from the Menu.

    The second panel is the numbered menu; a sub-menu is the panel this opens,
    and its rows are the sub-menu options. See TERMS.md.

    Shows (label, action) pairs and runs the one chosen.

    Returns (result, finished); finished means the user backed out and the
    caller should return to the dashboard. inline_list hands back the label,
    not the number, so the action is looked up by name."""
    choice = inline_list(live, title,
                         [(None, label, i) for i, (label, _) in enumerate(entries, 1)],
                         message, chords=chord_in_place)
    if not choice:
        return message, True
    action = next((fn for label, fn in entries if label == choice), None)
    if action is None:
        return message, True
    return action(live, message), False


# ------------------------------------------------------------------ projects

def project_switch(live, message):
    key, problem = pick(live, "Switch to which project?", project_choices(), message,
                        "No projects yet")
    if problem:
        return problem
    if not key:
        return back()
    store.select(key)
    return None                          # switching clears any previous Result


def project_create(live, message):
    name = inline_prompt(live, "New project name:", message, placeholder="e.g. Home Lab")
    if not name:
        return back()
    _, error = store.create_project(name)
    return error or None


def project_rename(live, message):
    key, problem = pick(live, "Rename which project?", project_choices(), message,
                        "No projects yet")
    if problem:
        return problem
    if not key:
        return back()
    name = inline_prompt(live, "New name:", message, placeholder="project name")
    if not name:
        return back()
    return store.rename_project(key, name) or None


def project_delete(live, message):
    choices = project_choices()
    if len(choices) < 2:
        return "A project is needed - this is the last one"
    key, problem = pick(live, "Delete which project?", choices, message)
    if problem:
        return problem
    if not key:
        return back()
    name = store.project_name(key)
    if not confirm(live, f"Delete {name} and everything in it?", message):
        return back()
    error, problem = store.delete_project(key)
    return problem or (f"Deleted {name}" if not error else error)


def action_project(live, message):
    """Switch, create, rename or delete projects."""
    menu = [("Switch", project_switch), ("Create", project_create),
            ("Rename", project_rename), ("Delete", project_delete)]
    while True:
        result, finished = submenu(live, "Project:", menu, message)
        if finished:
            return message
        if result is BACK:          # Esc inside an action: come back here
            message = None
            continue
        message = result


# ------------------------------------------------------------------ machines

def group_prompt(live, label, message, current=""):
    """Ask for a group, seeded with what the item has now.

    Free text rather than a list: the groups are whatever the project needs,
    and making one up by typing it is how the first one ever exists. Stepping
    past it leaves it as it was."""
    return inline_prompt(live, label, message, initial=current or "",
                         placeholder="list it under, e.g. Web", optional=True)


def machine_add(live, message):
    name = inline_prompt(live, f"{store.dashboard_panel()[:-1]} name:", message,
                         placeholder="e.g. Active Directory")
    if not name:
        return back()
    # All three are optional and marked as such: stepping past one must leave
    # it blank, not throw away the machine you just named.
    os_name = ""
    if store.offers_os(store.active()):
        os_name = inline_prompt(live, "OS (optional):", message,
                                placeholder="e.g. Linux, Windows",
                                optional=True)
    description = inline_prompt(live, "Description (optional):", message,
                                placeholder="what this box is", optional=True,
                                multiline=True, limit=store.DESCRIPTION_LIMIT)
    notes = inline_prompt(live, "Notes (optional):", message,
                          placeholder="what you worked out on it", optional=True,
                          multiline=True)
    group = group_prompt(live, "Group (optional):", message)
    if group is None:
        return back()
    _, error = store.add_machine(store.active(), name, notes or "",
                                 os_name or "", description or "", group or "")
    return error or f"Added {name}"


def edit_machine_notes(live, machine, message):
    """Edit just the notes of one machine. Returns (machine, message).

    This is what the Summary uses. You go there to correct what the notes say,
    not to rename the box, so it asks for one field instead of the whole form:
    four questions to fix a typo loses the point. Esc keeps you in the summary."""
    notes = inline_prompt(live, f"Notes for {machine.get('name', '?')}:", message,
                          initial=machine.get("notes", ""), multiline=True)
    if notes is None:
        return None, None
    edited, error = store.edit_machine(store.active(), machine["id"], notes=notes)
    if error:
        return None, error
    return edited, f"Notes updated for {edited.get('name')}"


def edit_machine_category_bodies(live, machine, message):
    """Ask for each category this machine shows, in one pass. {id: body}.

    Only the fields marked on this machine: which ones it shows is decided on
    the machine's Fields screen, and asking here for a field it does not use
    would be a question whose answer went nowhere. A blank body puts the
    shared default back."""
    key = machine["id"]
    bodies = {}
    for field in store.machine_categories(store.active(), key):
        body = inline_prompt(
            live, f"{field['title']}:", message,
            initial=field["body"] if field["overridden"] else field["default"],
            optional=True, multiline=True)
        if body is None:
            return None                 # cancelled: change nothing at all
        bodies[field["id"]] = body
    return bodies


def edit_machine_fields(live, machine, message):
    """Prompt for a known machine's details. Returns (machine, message).

    Split out of machine_edit so the Summary can edit the machine it has
    highlighted without making the user pick it all over again. Cancelling any
    prompt returns (None, None): the caller decides whether that means "close"
    or "carry on", and the two want different things."""
    key = machine["id"]
    # Seeded with the current value, so stepping past a field keeps it instead
    # of cancelling the form. optional=True as well as initial: a field that is
    # genuinely empty has no initial to carry the Enter, so without it stepping
    # past a blank OS cancelled the whole edit.
    # Machines carry no grouping label at all - it was extra noise the
    # dashboard stopped showing, and carrying it meant every form asked a
    # question whose answer nothing displayed.
    name = inline_prompt(live, "Name:", message, initial=machine.get("name", ""),
                         optional=True)
    if name is None:
        return None, None
    os_name = None
    if store.offers_os(store.active()):
        os_name = inline_prompt(live, "OS:", message,
                                initial=machine.get("os", ""), optional=True)
        if os_name is None:
            return None, None
    description = inline_prompt(live, "Description:", message,
                                initial=machine.get("description", ""),
                                optional=True, multiline=True,
                                limit=store.DESCRIPTION_LIMIT)
    if description is None:
        return None, None
    notes = inline_prompt(live, "Notes:", message, initial=machine.get("notes", ""),
                          optional=True, multiline=True)
    if notes is None:
        return None, None
    group = group_prompt(live, "Group:", message, machine.get("group", ""))
    if group is None:
        return None, None
    # Then the fields this machine actually uses, one after another, exactly
    # as the rest of the form is: the fields it shows are part of the machine,
    # so editing it means editing them, rather than sending you off to a second
    # screen to find them again.
    bodies = edit_machine_category_bodies(live, machine, message)
    if bodies is None:
        return None, None
    edited, error = store.edit_machine(store.active(), key, name, notes,
                                       os_name, description, group)
    if error:
        return None, error
    if bodies:
        edited, error = store.set_machine_category_bodies(store.active(), key,
                                                       bodies)
        if error:
            return None, error
    return edited, f"Saved {edited.get('name')}"


def machine_edit(live, message):
    key, problem = pick(live, f"Edit which {store.panel_noun()}?",
                        machine_choices(), message,
                        f"No {store.panel_noun_plural()} yet")
    if problem:
        return problem
    if not key:
        return back()
    machine = store.find_machine(store.active(), key)
    if machine is None:
        return f"No such {store.panel_noun()}"
    edited, result = edit_machine_fields(live, machine, message)
    if edited is None and result is None:
        return back()                    # cancelled: leave the submenu
    return result


def machine_panel_name(live, message):
    """Switch the dashboard's lower panel between Topics and Machines."""
    key = store.active()
    current = store.dashboard_panel(key)
    chosen, problem = pick(live, f"Call the panel what? (now {current})",
                           [(name, name) for name in store.PANEL_NAMES],
                           message)
    if problem:
        return problem
    if not chosen:
        return back()
    if chosen == current:
        # Say so plainly. Re-picking the name already in use stored it again
        # and the heading did not move, which read as the switch being broken.
        return f"It is already called {current}"
    _, error = store.set_dashboard_panel(key, chosen)
    return error or f"Panel is now called {chosen}"


def machine_view(live, key):
    """Open one machine and read it a page at a time. Esc goes back.

    Enter leads with the box itself - name and description - and then walks
    forward through the categories one per page: OS where it is kept, Notes,
    then whatever else the machine chose. On the last page Enter leaves the
    view, so a whole machine can be read with one key. Read only: marking is
    the `m` key on the list, so there is one place to do it rather than two -
    and no way to complete a machine while only reading it."""
    message = None
    top = 0
    step = 0
    while True:
        machine = store.find_machine(store.active(), key)
        if machine is None:
            return None
        done = machine.get("completed", 0) >= machine.get("total", 1)
        stamp = machine.get("completed_on") or ""
        state = (f"complete{stamp and ' on ' + stamp}" if done else "not complete")
        # Page one carries the description - what the machine is, in one
        # line. It is not written a second time on any other page: the
        # permanent Description field would repeat it word for word.
        description = machine.get("description") or "No description yet."
        body = Text(description, style="none" if machine.get("description")
                    else "dim")
        pages = [(as_typed(machine.get("name", "?")), body)]
        shown = store.machine_builtin_categories(store.active(), machine["id"])
        shown = [field for field in shown if field["id"] != "description"]
        shown += store.machine_categories(store.active(), machine["id"])
        for field in shown:
            text = (field["body"] if field["overridden"]
                    else field["default"]).strip()
            # The star means "this machine's own copy of a shared default".
            # Description, Notes and the OS have no shared default, so there
            # is nothing for it to mark.
            mark = "*" if (field["overridden"] and not field.get("permanent")
                           and field.get("default")) else ""
            title = f"{as_typed(field.get('title'))}{mark}"
            pages.append((title, as_typed(text) if text
                          else "[dim]not written yet[/]"))
        step = min(step, len(pages) - 1)    # categories can shrink under `c`
        title, body = pages[step]
        last = step == len(pages) - 1
        # State and the keys sit below the page, not inside its panel. They
        # used to be drawn in the panel's own footer *and* again on the hint
        # line, so the same two words appeared twice on one screen.
        parts = [build_layout(message=message),
                 detail_panel(title, body, None),
                 f"[dim]State:[/] {state}"]
        parts.append(hint_line(
            f"↵ ({'Exit' if last else 'Next'})  c (Categories)  esc back  "
            f"({step + 1}/{len(pages)})"))
        top, max_top = show_screen(live, Group(*parts), top)
        try:
            k = read_key(0.2)
        except Chord as chord:
            if chord.token == CHORD_QUIT:
                return None
            message = apply_chord(chord, message)
            continue                        # undo from inside a machine
        if k is None:
            continue                        # nothing pressed yet; hold the view
        moved = scroll_step(k, top, max_top)
        if moved is not None and moved != top:
            top = moved
            continue
        if k == ESCAPE:
            return None                    # back to the machine list
        if k in ("\r", "\n"):
            if last:
                return None                 # stepped off the last page: out
            step += 1
            top = 0                         # every page starts at its top
            continue
        if k == "c":
            message = machine_categories_screen(live, machine["id"],
                                            None) or message
            continue
        # Marking is not here any more. It is one key on the list, on the row
        # you are already standing on, so putting it behind a second Enter in
        # the detail view only gave the same job two doors - and one of them
        # was a stray Enter away from completing something.
        continue


def empty_list_screen(live, message, title, body, on_add, after=None,
                      hint="a (Add)  esc back"):
    """A list with nothing in it, where the keys still work.

    pick() hands back the moment there are no rows to choose from, so the
    keys belonging to that list were never registered. An empty repository
    said "press a to add the first one" and then ignored a - the screen the
    message was trying to explain away."""
    top = 0
    while True:
        top, max_top = show_screen(live, Group(
            build_layout(message=message),
            detail_panel(title, Text(body, style="dim"), None),
            hint_line(hint)), top)
        try:
            key = read_key(0.2)
        except Chord as chord:
            if chord.token == CHORD_QUIT:
                return message
            message = apply_chord(chord, message)
            continue
        if key is None:
            continue
        moved = scroll_step(key, top, max_top)
        if moved is not None and moved != top:
            top = moved
            continue
        if key == ESCAPE:
            return message
        if key == "a":
            said = on_add(live, None)
            if isinstance(said, str) and after is not None:
                # Straight on to the list it was just added to, rather than
                # back out to a menu with another press before it shows up.
                return after(live, said)
            return said


def universal_categories_entry(live, message):
    """The Categories entry of the Machines sub-panel."""
    return universal_categories(live, message)


def universal_categories(live, message):
    """The project's categories, defined once and shared by every machine.

    This is the only place a field can be created: its title belongs to the
    field, so reading the same field across a dozen boxes compares like with
    like. Each machine only says which of these it uses, and may override the
    body for itself. The OS is listed too where the project uses it - it is
    kept on each machine, so it can be read here but not renamed or removed."""
    os_row = os_category_choice()

    def add_it(here, title):
        return category_add(here)

    def edit_it(here, title):
        if os_row and title == os_row[0]:
            return "The OS is kept on each machine - open one and press c"
        field_id = _field_id_for(title)
        if field_id is None:
            return "That category is gone"
        return category_edit(here, field_id)

    def delete_it(here, title):
        if os_row and title == os_row[0]:
            return "The OS is kept on each machine - open one and press c"
        field_id = _field_id_for(title)
        if field_id is None:
            return "That category is gone"
        if not confirm(here, f"Delete the category '{title}'?", None):
            return "Left it alone"
        return store.delete_category(store.active(), field_id) or \
            f"Deleted {title}"

    if not categories_screen_choices():
        return empty_list_screen(
            live, message, "Categories",
            "No categories defined yet. a defines the first one.",
            category_add, universal_categories)

    while True:
        key, problem = pick(live, "Categories:", categories_screen_choices(),
                            message,
                            "No categories defined yet",
                            hint="↑↓ move  ↵ (Read)  a (Add)  e (Edit)  "
                                 "d (Delete)  esc back",
                            grouped=categories_screen_items,
                            shortcuts={"a": add_it, "e": edit_it,
                                       "d": delete_it},
                            refresh=categories_screen_choices)
        if problem:
            return problem
        if not key:
            return message
        # pick() hands back the row's id, not its label.
        if os_row and key == store.OS_CATEGORY:
            show_details(live, "OS",
                         Text("What each machine runs - Linux, Windows and "
                              "so on. It is kept on the machine: open one, "
                              "press c, and edit the OS row there.",
                              style="dim"),
                         hint_line("esc back"), chords=chord_in_place)
            message = None
            continue
        field = next((f for f in store.project_categories()
                      if f.get("id") == key), None)
        if field:
            show_details(live, field.get("title", "?"),
                         Text(field.get("default") or "No content yet.",
                              style="none" if field.get("default") else "dim"),
                         hint_line("esc back"), chords=chord_in_place)
        message = None


def category_choices(key=None):
    """Every defined category as (name, id)."""
    return [(store.category_title(f) or "?", f["id"])
            for f in _usable(store.project_categories(key))]


def category_items(key=None):
    """{id: category} - what pick() draws the sections from."""
    return {f["id"]: f for f in _usable(store.project_categories(key))}


def os_category_choice(key=None):
    """The OS as a row of the Categories screen, where the project uses it.

    The OS is not a definition like the others - its content lives on each
    machine - but it is a category all the same, and the screen that lists the
    project's categories should say so rather than leave a project whose
    machines carry an OS reading "No categories defined yet". A project that
    defines a category called OS keeps only that one: the row here would draw
    the same name twice."""
    key = key or store.active()
    if not store.offers_os(key):
        return None
    for field in store.project_categories(key):
        if field.get("id") == store.OS_CATEGORY \
                or store.category_title(field).strip().lower() == "os":
            return None
    return ("OS", store.OS_CATEGORY)


def categories_screen_choices(key=None):
    """[(label, id)] for the Categories screen: the OS first where it is in
    use, then the project's own definitions."""
    row = os_category_choice(key)
    return ([row] if row else []) + category_choices(key)


def categories_screen_items(key=None):
    """{id: category} for the Categories screen, OS row included."""
    items = dict(category_items(key))
    row = os_category_choice(key)
    if row:
        items[row[1]] = {"id": row[1], "title": row[0],
                         "default": "", "group": ""}
    return items


def _field_id_for(title):
    return next((fid for name, fid in category_choices() if name == title), None)


def category_add(live, message=None):
    """Define a category for the project.

    The live view is passed through to the prompts. Handing them None drew the
    questions on a screen nobody was looking at - and, on any terminal, raised
    on the first keystroke instead of asking."""
    title = inline_prompt(live, "Category name:", message,
                          placeholder="e.g. foothold")
    if not title:
        return "Needs a title"
    body = inline_prompt(live, f"Default content for '{title}':", message,
                         placeholder="what it holds by default", optional=True,
                         multiline=True)
    group = group_prompt(live, "Group (optional):", message)
    if group is None:
        return back()
    _, error = store.add_category(store.active(), title, body or "", group or "")
    return error or f"Added {title}"


def category_edit(live, field_id):
    field = next((f for f in store.project_categories() if f.get("id") == field_id),
                 None)
    if field is None:
        return "That category is gone"
    title = inline_prompt(live, "Category name:", None,
                          initial=field.get("title", ""), optional=True)
    if title is None:
        return None
    body = inline_prompt(live, f"Default content for '{title}':", None,
                         initial=field.get("default", ""), optional=True,
                         multiline=True)
    if body is None:
        return None
    group = group_prompt(live, "Group:", None, field.get("group", ""))
    if group is None:
        return None
    _, error = store.edit_category(store.active(), field_id, title, body, group)
    return error or f"Saved {title}"


def category_name(field_id, key=None):
    """A category's name by id, for a message that names the row it is about."""
    return next((title for title, fid in category_choices() if fid == field_id),
                "?")


def _permanent_says(title):
    """What pressing enter on a permanent row says."""
    return f"{title} is always shown"


def _category_rows(key, machine_id):
    """Every row on a machine's Categories screen, in the order it is drawn.

    (kind, name, id, marked) where kind is "head", "permanent" or "row". The
    permanent ones are first because they are always there; the OS follows
    them where the project uses it; the rest are the project's own."""
    on = set(store.machine_category_ids(key, machine_id))
    listed = [("head", "Always shown", None, None)]
    for _, title in store.PERMANENT_CATEGORIES:
        listed.append(("permanent", title, title, True))
    if store.offers_os(key):
        listed.append(("row", "OS", store.OS_CATEGORY,
                       store.OS_CATEGORY in on))
    if category_choices(key):
        listed.append(("head", "Choose the rest", None, None))
        for title, field_id in category_choices(key):
            listed.append(("row", title, field_id, field_id in on))
    return listed


def machine_categories_screen(live, machine_id, message):
    """What this machine shows: the permanent ones, then the ones it chose.

    Description and Notes are permanent - every machine has them, they are
    never unmarked, and their content is the machine's own. The OS is here too
    where the project uses it, on by default and unmarked like any other. The
    rest are the project's own, ticked or not.

    The names are read-only here: they belong to the category, and are renamed
    in one place for the whole project. The content is this machine's own,
    which is the part that can differ from one box to the next."""
    def rows():
        return _category_rows(store.active(), machine_id)

    def toggle(here, field_id):
        """Enter hands back the row's id, not its label."""
        if field_id not in {fid for kind, _, fid, _ in rows() if kind == "row"}:
            return "That category is gone"
        on = set(store.machine_category_ids(store.active(), machine_id))
        if field_id in on:
            error = store.attach_machine_categories(
                store.active(), machine_id,
                [f for f in on if f != field_id])
            return error or f"Unmarked {category_name(field_id)}"
        error = store.attach_machine_categories(store.active(), machine_id,
                                               list(on) + [field_id])
        return error or f"Marked {category_name(field_id)}"

    def edit_it(here, title):
        field_id = next((fid for kind, name, fid, _ in rows()
                         if kind == "row" and name == title), None)
        if field_id is None:
            return "That category is gone"
        return machine_field_edit(live, machine_id, field_id, title)

    position = 0
    if not category_choices() and not store.offers_os(store.active()):
        return empty_list_screen(
            live, message, "Categories",
            "This project has no categories yet. Define them under "
            f"{store.dashboard_panel()} > Categories.", None)

    while True:
        listed = rows()
        shown = [(name, fid) for kind, name, fid, _ in listed if kind != "head"]
        key, problem = pick(live, "Categories on this machine:", shown,
                            message,
                            "Nothing to choose yet",
                            hint="↑↓ move  ↵ (Mark or unmark)  "
                                 "e (Edit content)  esc back",
                            ticks={fid: mark for kind, _, fid, mark in listed
                                   if kind != "head"},
                            grouped=lambda: _section_of(rows()),
                            sort_groups=False, at=position,
                            shortcuts={"e": edit_it},
                            refresh=lambda: [(name, fid)
                                             for kind, name, fid, _ in rows()
                                             if kind != "head"])
        if problem:
            return problem
        if not key:
            return message
        # Remember which row that was, so the list comes back with the cursor
        # on it rather than at the top.
        position = next((n for n, (_name, fid) in enumerate(shown)
                         if fid == key), position)
        kind = next((this for this, _name, fid, _mark in rows()
                     if fid == key and this != "head"), "row")
        if kind == "permanent":
            message = _permanent_says(next(n for k, n, fid, _m in rows()
                                           if fid == key and k == "permanent"))
        else:
            said = toggle(live, key)
            message = said if isinstance(said, str) else None


def _section_of(rows):
    """{id: {"group": section}} for the picker to draw the headings from.

    The screen's own headings would be taken for rows if they went into the
    list as-is, so each row is handed the heading above it separately."""
    heading, sections = None, {}
    for kind, name, field_id, _mark in rows:
        if kind == "head":
            heading = name or store.NO_GROUP
        else:
            sections[field_id] = {"group": heading or store.NO_GROUP}
    return sections


def edit_machine_attribute(live, machine_id, field_id, title):
    """Edit Description, Notes or the OS on the machine itself."""
    machine = store.find_machine(store.active(), machine_id)
    if machine is None:
        return "That machine is gone"
    lines = field_id == "notes"
    # The description keeps its limit wherever it is edited; notes have none.
    body = inline_prompt(live, f"{title} for this machine:", None,
                         initial=machine.get(field_id, ""), optional=True,
                         multiline=lines,
                         limit=(store.DESCRIPTION_LIMIT
                                if field_id == "description" else None))
    if body is None:
        return None
    # The store calls it os_name; the field is called os everywhere else.
    as_stored = {"os": "os_name"}.get(field_id, field_id)
    edited, error = store.edit_machine(store.active(), machine_id,
                                       **{as_stored: body})
    return error or f"Saved {title}"


def machine_field_edit(live, machine_id, field_id, title):
    """Change this machine's copy of a category's content.

    The permanent categories and the OS are written on the machine rather than
    defined for the project, so editing one edits that field of the machine."""
    if field_id in dict(store.PERMANENT_CATEGORIES) or field_id == store.OS_CATEGORY:
        return edit_machine_attribute(live, machine_id, field_id, title)
    field = next((f for f in store.machine_categories(store.active(), machine_id)
                  if f.get("id") == field_id), None)
    if field is None:
        return "That category is gone"
    body = inline_prompt(live, f"{field['title']} for this machine:", None,
                         initial=field["body"] if field["overridden"]
                         else field["default"], optional=True, multiline=True)
    if body is None:
        return None
    error = store.machine_category_body(store.active(), machine_id, field_id,
                                     body)
    return error or f"Saved {field['title']}"


def machine_list(live, message):
    """The list, and everything done from it by a single key.

    Mark, Add, Edit and Delete used to be four entries in the submenu, each of
    which opened the same list again and then walked you back out to choose
    what to do with the row you had already highlighted. They are keys on the
    list instead, acting on the highlighted row, so the whole panel is worked
    from one screen."""
    def mark_it(here, name):
        machine = _machine_by_name(name)
        if machine is None:
            return "That one is gone"
        machine, error = store.toggle_machine(store.active(), machine["id"])
        if error:
            return error
        now = machine.get("completed", 0) >= machine.get("total", 1)
        return f"{machine.get('name')}: " + ("marked complete" if now
                                             else "unmarked")

    def add_it(here, name):
        return machine_add(here, None)

    def edit_it(here, name):
        machine = _machine_by_name(name)
        if machine is None:
            return "That one is gone"
        return edit_machine_fields(here, machine, None)

    def delete_it(here, name):
        machine = _machine_by_name(name)
        if machine is None:
            return "That one is gone"
        if not confirm(here, f"Delete {machine.get('name')}?", None):
            return "Left it alone"
        return store.delete_machine(store.active(), machine["id"]) or \
            f"Deleted {machine.get('name')}"

    def field_it(here, name):
        """c: choose which categories this machine shows."""
        machine = _machine_by_name(name)
        if machine is None:
            return "That one is gone"
        return machine_categories_screen(here, machine["id"], None)

    shortcuts = {"m": mark_it, "a": add_it, "e": edit_it, "d": delete_it,
                 "c": field_it}
    # The letter is the key and the bracket says what it does, so a shortcut
    # and its meaning cannot be mistaken for one another at a glance.
    hint = (f"\u2191\u2193 move  \u23ce (Open)  m (Mark)  a (Add)  "
            f"e (Edit)  d (Delete)  c (Categories)  esc back")
    def fresh():
        """Re-read the pairs, so a mark shows its tick straight away. The
        picker re-groups them; this hands back the raw list."""
        return machine_choices()

    if not machine_choices():
        return empty_list_screen(
            live, message, store.dashboard_panel(),
            f"No {store.panel_noun_plural()} yet. a adds the first one.",
            machine_add, machine_list)

    # Which row the cursor was on. Esc out of a machine and the list reopened
    # at the top, so reading the last machine in a long list meant walking
    # back down to it every time.
    position = 0
    while True:
        key, problem = pick(live, f"{store.dashboard_panel()}:",
                            machine_choices(), message,
                            f"No {store.panel_noun_plural()} yet",
                            hint=hint, shortcuts=shortcuts, refresh=fresh,
                            grouped=machine_items, at=position)
        if problem:
            return problem
        if not key:
            return message                     # esc: back to the submenu
        found = drawn_position(machine_choices(), machine_items, key)
        if found is not None:
            position = found
        result = machine_view(live, key)       # \u23ce opens it to read
        message = result or None               # back here afterwards


def _machine_by_name(name):
    """The machine a list row refers to, whether or not it is ticked off.

    The rows carry a tick for a finished one, so the same machine reads
    "✓ Target" before and "Target" after - matching on the bare name keeps
    the shortcuts working on a row that was just marked."""
    wanted = name.lstrip("\u2713 ")
    return next((m for m in store.machines()
                 if m.get("name") == wanted), None)


# The Machines submenu: the list, the fields, and the panel's name. Creating a
# field is universal, so it gets an entry of its own; the machines pick up which
# fields they use from inside the list, on the row they are standing on.
MACHINES_MENU = [("View", machine_list),
                 ("Categories", universal_categories_entry),
                 ("Panel", machine_panel_name)]


def action_machines(live, message):
    """Open, add, edit or delete the project's machines, or rename the panel."""
    while True:
        # The label carries the panel's current name. Without it the menu read
        # "Panel name" forever and there was no way to see what it was set to,
        # so switching it looked like it had done nothing.
        menu = [(f"Panel ({store.dashboard_panel()})" if label == "Panel"
                 else label, fn)
                for label, fn in MACHINES_MENU]
        # The title follows the panel's name, like the menu entry above it
        # does. It used to read "Machines" whatever the project had chosen, so
        # a project set to Topics showed one name in the menu and another on
        # the screen you opened from it.
        result, finished = submenu(live, f"{store.dashboard_panel()}:", menu,
                                   message)
        if finished:
            return message
        if result is BACK:          # Esc lands on the Machines menu, not the dashboard
            message = None
            continue
        message = result


# ------------------------------------------------------------------ repository

def repository_add(live, message):
    title = inline_prompt(live, "Repository title:", message, placeholder="e.g. Kerberos")
    if not title:
        return back()
    body = inline_prompt(live, "Details (optional):", message,
                         placeholder="what it covers", optional=True, multiline=True)
    group = group_prompt(live, "Group (optional):", message)
    if group is None:
        return back()
    _, error = store.add_repository(store.active(), title, body or "",
                                    group or "")
    return error or f"Added {title}"


def repository_edit_fields(live, item, message):
    """Edit one entry's fields. Returns (item, message).

    Seeded with the current values, so stepping past a field keeps it. Details
    is multi-line for the same reason a machine's notes are: a repository entry is
    a paragraph, and one key cannot both break its lines and commit it."""
    title = inline_prompt(live, "Title:", message, initial=item.get("title", ""),
                          optional=True)
    if title is None:
        return None, None
    body = inline_prompt(live, "Details:", message, initial=item.get("body", ""),
                         optional=True, multiline=True)
    if body is None:
        return None, None
    group = group_prompt(live, "Group:", message, item.get("group", ""))
    if group is None:
        return None, None
    edited, error = store.edit_repository(store.active(), item["id"], title, body,
                                          group)
    if error:
        return None, error
    return edited, f"Saved {edited.get('title')}"


def repository_edit(live, message):
    key, problem = pick(live, "Edit which entry?", repository_choices(), message,
                        "No repository yet")
    if problem:
        return problem
    if not key:
        return back()
    item = store.find_repository(store.active(), key)
    if item is None:
        return "No such entry"
    _, result = repository_edit_fields(live, item, message)
    return result


def repository_read(live, key, message):
    """Read an entry. `e` edits it in place; Esc goes back.

    Reading is why the repository menu gets opened, so the edit belongs here too:
    noticing a typo while reading is the moment you want to fix it, not the
    moment you go looking for the Edit entry."""
    top = 0
    while True:
        item = store.find_repository(store.active(), key)
        if item is None:
            return "No such entry"
        body = Text((item.get("body") or "No details yet."),
                    style="none" if item.get("body") else "dim")
        parts = [build_layout(message=message),
                 detail_panel(as_typed(item.get("title", "?")), body, None)]
        parts.append(hint_line("e (Edit)  esc back"))
        top, max_top = show_screen(live, Group(*parts), top)
        try:
            pressed = read_key(0.2)
        except Chord as chord:
            if chord.token == CHORD_QUIT:
                return message
            message = apply_chord(chord, message)
            continue                        # undo from inside an entry
        if pressed is None:
            continue                        # nothing pressed; hold the page
        moved = scroll_step(pressed, top, max_top)
        if moved is not None and moved != top:
            top = moved
            continue
        if pressed == ESCAPE:
            return message
        if pressed == "e":
            edited, result = repository_edit_fields(live, item, message)
            message = result if edited is not None else None


def repository_list(live, message):
    """The repository, opened straight onto its entries.

    Add, edit and delete used to be a sub-panel you had to walk through to find
    a fourth item; they are keys on the list now, on the highlighted entry, so
    the repository opens on the thing you came to read."""
    def add_it(here, title):
        return repository_add(here, None)

    def edit_it(here, title):
        entry_id = next((i for name, i in repository_choices()
                         if name == title), None)
        if entry_id is None:
            return "That entry is gone"
        return repository_edit_fields(
            here, store.find_repository(store.active(), entry_id), None)

    def delete_it(here, title):
        entry_id = next((i for name, i in repository_choices()
                         if name == title), None)
        if entry_id is None:
            return "That entry is gone"
        entry = store.find_repository(store.active(), entry_id)
        if not confirm(here, f"Delete {entry.get('title')}?", None):
            return "Left it alone"
        return store.delete_repository(store.active(), entry_id) or \
            f"Deleted {entry.get('title')}"

    if not repository_choices():
        return empty_list_screen(
            live, message, "Repository",
            "Nothing in the repository yet. a adds the first entry.",
            repository_add, repository_list)

    # Same memory as the machines list: read a long entry and Esc puts you
    # back on its row, not at the top of the repository.
    position = 0
    while True:
        key, problem = pick(live, "Repository:",
                            repository_choices(), message,
                            "Nothing in the repository yet",
                            hint="↑↓ move  ↵ (Read)  a (Add)  e (Edit)  "
                                 "d (Delete)  esc back",
                            shortcuts={"a": add_it, "e": edit_it,
                                       "d": delete_it},
                            grouped=repository_items,
                            refresh=repository_choices, at=position)
        if problem:
            return problem
        if not key:
            return message
        found = drawn_position(repository_choices(), repository_items, key)
        if found is not None:
            position = found
        result = repository_read(live, key, message)
        message = result or None


REPOSITORY_MENU = [("View", repository_list)]


def action_repository(live, message):
    """The way into the repository.

    It used to open the entries straight away, which was one press fewer when
    there were entries to read - and a dead end when there were none: an empty
    repository flashed "No repository yet" and dropped you back on the
    dashboard with nothing on screen to enter or leave. The menu is always
    there to answer to, whatever the repository holds."""
    while True:
        result, finished = submenu(live, "Repository:", REPOSITORY_MENU,
                                   message)
        if finished:
            return message
        if result is BACK:
            message = None
            continue
        message = result


# ------------------------------------------------------------------- options

def slot_set(live, message, field):
    """Point current or next at a machine, or clear it."""
    pairs = [("— clear —", "")] + machine_choices()
    labels = [label for label, _ in pairs]
    chosen = inline_list(live, f"Set {field} to:", labels, message,
                         chords=chord_in_place)
    if not chosen:
        return message
    key = next((i for label, i in pairs if label == chosen), "")
    error = store.set_slot(store.active(), field, key or "")
    if error:
        return error
    return f"{field.title()} set to {store.slot_name(store.active(), field) or 'nothing'}"


def option_objective(live, message):
    """Set what this project is for. Blank puts the project name back."""
    key = store.active()
    current = store.project_objective(key)
    text = inline_prompt(live, "Objective:", message,
                         placeholder=current if current != store.project_name(key) else "why")
    if text is None:
        return message
    return store.set_objective(key, text) or None


def option_hours(live, message):
    delta = inline_prompt(live, "Hours studied (+/-):", message, placeholder="e.g. 2 or -1")
    if delta is None:
        return message
    try:
        amount = int(delta)
    except ValueError:
        return "Hours must be a whole number"
    return f"{store.active()} hours: {store.add_hours(store.active(), amount)}h"


def option_deadline(live, message):
    when = inline_prompt(live, "Deadline (YYYY-MM-DD):", message,
                         placeholder=store.stats(store.active()).get("deadline") or "2026-11-29")
    if not when:
        return message
    try:
        from datetime import date
        date.fromisoformat(when.strip())
    except ValueError:
        return "Use the format YYYY-MM-DD"
    store.set_deadline(store.active(), when.strip())
    return f"{store.active()} deadline: {when.strip()}"


def option_theme(live, message):
    here = store.project_theme()
    shown = [(f"{themes.label(k)}{' (here)' if k == here else ''}", k) for k in themes.ORDER]
    key, problem = pick(live, "Themes for this project:", shown, message)
    if problem or not key:
        return problem or message
    error = store.set_theme(store.active(), key)
    return error or f"Themes: {themes.label(key)}"


def option_reset(live, message):
    key = store.active()
    if not confirm(live, f"Reset {store.project_name(key)} progress and hours?", message):
        return message
    cleared, hours = store.reset_project(key)
    return f"Reset {store.project_name(key)}: {cleared} unmarked, {hours}h cleared"


def action_settings(live, message):
    """Current, Next, Hours, Deadline, Theme and Reset for this project."""
    menu = [("Objective", option_objective),
            ("Current", lambda l, m: slot_set(l, m, "current")),
            ("Next", lambda l, m: slot_set(l, m, "next")),
            ("Hours", option_hours), ("Deadline", option_deadline),
            ("Themes", option_theme), ("Reset", option_reset)]
    while True:
        result, finished = submenu(live, "Settings:", menu, message)
        if finished:
            return message
        if result is BACK:
            message = None
            continue
        message = result


# ---------------------------------------------------------------- misc menus

def action_help(live, message):
    text = Text.from_markup(
        "[bold]1 Project[/]   switch, create, rename or delete a project\n"
        f"[bold]2 {store.dashboard_panel()}[/]  mark, add, edit, delete,"
        f" rename the panel\n"
        "[bold]3 Repository[/]  add, edit, delete or read repository entries\n"
        "[bold]4 Settings[/]  objective, current, next, hours, deadline, themes, reset\n"
        "[bold]5 Help[/]      this text\n"
        "[bold]6 Summary[/]   finished machines; edit notes, unmark\n"
        "[bold]0 Quit[/]\n\n"
        "In the menu, use [bold]↑↓[/] to highlight and [bold]↵[/] to run it, or press\n"
        "its number directly. [bold]←→[/] move between the menu columns.\n"
        "[bold]Esc[/] goes back one level.\n"
        "[bold]ctrl+x u[/] undo   [bold]ctrl+x r[/] redo   "
        "[bold]ctrl+x q[/] quit   [bold]ctrl+x m[/] mouse on/off\n"
        "Those three work from anywhere, including a picker or an editor.\n"
        "Marking is [bold]m[/] on the machines list, on the row you are\n"
        "standing on, so a stray key while reading cannot complete a box.\n"
        "Description and notes take several\n"
        "lines: [bold]↵[/] adds a line, [bold]ctrl+s[/] saves; the description\n"
        "is kept to 160 characters.\n\n"
        "Undo and redo cover this session only. Every save is atomic and backed up.\n\n"
        f"Currently in [bold]{as_typed(store.project_name())}[/]."
    )
    if live is None:                 # `tdash help` has no live view to draw on
        console.print(text)
        return None
    note(live, message, text, chords=chord_in_place)
    return message


# The Summary Settings rows, in the order they are drawn. Each is one of:
#   ("head",  text)                  a section heading, not a row
#   ("row",   option, label, state)  a row you can stand on and change
#   ("fixed", label, note)           always in the summary, nothing to change
# What Show Summary puts on screen. Each entry is one of:
#   ("head",  text)                  a section heading, not a row
#   ("row",   option, label, state)  a row the cursor lands on and changes
#   ("fixed", label, note)           always in the summary, nothing to change
def summary_settings_rows():
    """The Summary Settings screen, as the panel draws it.

    Status, Date and Notes come last and are not rows: they are in every
    summary by design, so they are shown as the fixed tail of the screen rather
    than as switches that could be left off."""
    key = store.active()
    settings = store.summary_settings(key)
    # summary_settings() hands back ids, not the fields themselves.
    shown = set(settings["categories"])
    every = []
    if store.offers_os(key):
        every.append((store.summary_category_title(store.OS_CATEGORY, key),
                      store.OS_CATEGORY))
    every += category_choices()
    noun = store.dashboard_panel()
    rows = [("row", "machines", noun,
             "shown" if settings["machines"] else "hidden")]
    rows.append(("row", "fields", "Categories",
                 f"{len(shown)} of {len(every)} chosen"))
    rows.append(("head", "What a machine can show"))
    for title, field_id in every:
        rows.append(("row", field_id, title,
                     "shown" if field_id in shown else ""))
    rows.append(("row", "wording", "Status wording",
                 f"reads {store.summary_status_word(key)}"))
    rows.append(("head", "Always shown"))
    rows.append(("fixed", "Status", "whether the box is finished"))
    rows.append(("fixed", "Date", "when it was finished"))
    rows.append(("fixed", "Notes", "the Notes field of each machine"))
    return rows


def summary_settings_panel(cursor=0):
    """The Summary Settings screen.

    Its own panel rather than a picker: it is not a list of things to choose
    between, it is a list of things that are on or off, and a picker numbered
    them all as if every row were the same kind of choice - including the three
    rows that cannot be changed at all. Here the cursor only ever lands on a row
    that can change, and the fixed tail is shown to be read."""
    rows = summary_settings_rows()
    selectable = [i for i, row in enumerate(rows) if row[0] == "row"]
    if cursor not in selectable:
        cursor = selectable[0] if selectable else 0
    where = selectable.index(cursor)
    grid = Table.grid(expand=True, padding=(0, 2))
    grid.add_column(justify="left", no_wrap=True)
    grid.add_column(justify="left", ratio=1)
    for i, row in enumerate(rows):
        kind = row[0]
        if kind == "head":
            grid.add_row(f"[bold {ui.accent()}]{row[1]}[/]", "")
            continue
        if kind == "fixed":
            grid.add_row(f"  [dim]{row[1]}[/]", f"[dim]{row[2]}[/]")
            continue
        _, option, label, state = row
        if option == "fields":
            label_text = f"  [bold {ui.bright()}]{label}[/]"
        else:
            # The same tick the machines list uses on a finished box, so a
            # field marked here reads the same way a machine marked there does.
            tick = "\u2713 " if state == "shown" else "  "
            label_text = f" {tick}[bold {ui.bright()}]{label}[/]"
        if i == cursor:
            label_text = f"\u25b8 [reverse]{label_text}[/]"
        grid.add_row(label_text, f"[dim]{state}[/]" if state else "")
    content = Group(grid, "",
                    hint_line("\u2191\u2193 move  \u23ce (Turn on or off)  "
                              "esc back"))
    return (ui.inner_panel(content, "Summary Settings",
                           height=ui.content_height(content) + 2), where)


def summary_option_action(option, where=0):
    """What one row does. Returns (message, row_to_stand_on_next)."""
    if option in ("status", "date", "notes"):
        return "Status, Date and Notes are always in the summary", where

    if option == "machines":
        store.summary_show_machines(store.active())
        return ("Summary: machines "
                + ("shown" if store.summary_settings(store.active())["machines"]
                   else "hidden")), where

    if option == "wording":
        store.summary_toggle_status_word(store.active())
        return ("Status reads "
                f"{store.summary_status_word(store.active())}"), where

    if option == "fields":
        # Enter on the heading means "take me to the fields", which is what
        # most people want from it: the point of opening Settings is usually
        # the fields, and the names row sits right above.
        rows = summary_settings_rows()
        first = next((i for i, row in enumerate(rows)
                      if row[0] == "row"
                      and row[1] not in ("machines", "fields")), None)
        if first is None:
            return "No categories defined yet", where
        return "Pick the fields below", first

    field_id = option
    if not store.summary_category_known(field_id, store.active()):
        return "That category is gone", where
    error = store.summary_toggle_category(store.active(), field_id)
    if error:
        return error, where
    title = store.summary_category_title(field_id, store.active())
    return (f"Summary: {title} "
            + ("shown" if field_id in store.summary_settings(
                store.active())["categories"] else "not shown")), where


def summary_settings(live, message):
    """Summary Settings: what Show Summary puts on screen.

    Every row is the answer to "is this in the summary?" and shows its own
    state, so there is nothing to save: the screen reads what is stored each
    time it is drawn, and a press writes straight through."""
    cursor = 0
    scroll = 0
    while True:
        panel, where = summary_settings_panel(cursor)
        scroll, max_top = show_screen(
            live, Group(build_layout(message=message), panel), scroll)
        try:
            key = read_key(0.2)
        except Chord as chord:
            if chord.token == CHORD_QUIT:
                return message
            message = apply_chord(chord, message)
            continue
        if key is None:
            continue
        if key == ESCAPE:
            return message
        moved = scroll_step(key, scroll, max_top)
        if moved is not None and moved != scroll:
            scroll = moved
            continue
        rows = summary_settings_rows()
        selectable = [i for i, row in enumerate(rows) if row[0] == "row"]
        if not selectable:
            return message
        if key == KEY_UP:
            cursor = selectable[(where - 1) % len(selectable)]
        elif key == KEY_DOWN:
            cursor = selectable[(where + 1) % len(selectable)]
        elif key in ("\r", "\n"):
            option = rows[cursor][1]
            said, cursor = summary_option_action(option, cursor)
            if isinstance(said, str):
                message = said


SUMMARY_MENU = [("Show Summary", lambda l, m: show_summary(l, m)),
                ("Summary Settings", summary_settings)]


def summary_rows():
    """The machines the summary is currently listing, newest first.

    The same list the panel draws, so the highlighted row always refers to the
    machine under the cursor."""
    key = store.active()
    today = store.completed_today(key)
    return today[:ui.SUMMARY_ROWS] if today else store.recent_completed(key)


def action_summary(live, message):
    """Two ways in: look at the summary, or decide what it shows."""
    while True:
        result, finished = submenu(live, "Summary:", SUMMARY_MENU, message)
        if finished:
            return message
        if result is BACK:
            message = None
            continue
        message = result


def show_summary(live, message):
    """The tracker view, editable in place.

    Everything here used to be read-only, so fixing a typo in a note meant
    leaving the summary, finding the machine and editing it, then coming back.
    Now the row under the cursor can be re-noted or unmarked without going
    anywhere: the panel redraws after every change. Editing asks only for the
    notes - the name is not what you came here to change. The full form, name
    and all, is still under [2] Machines > Edit."""
    selected = 0
    top = 0
    scroll = 0          # where the whole screen sits, if it is too tall
    while True:
        rows = summary_rows()
        if rows:
            selected = min(selected, len(rows) - 1)
        # The list is windowed to the room available and scrolled here, so a
        # machine further down is reachable instead of cropped off the screen.
        limit = ui.summary_limit()
        top = max(0, min(top, max(0, len(rows) - limit)))
        if selected < top:
            top = selected
        elif selected >= top + limit:
            top = selected - limit + 1
        scroll, max_top = show_screen(
            live, Group(build_layout(message=message),
                        summary_panel(selected=selected if rows else None,
                                     hint=True, top=top, limit=limit)), scroll)
        try:
            key = read_key(0.2)
        except Chord as chord:
            if chord.token == CHORD_QUIT:
                return message
            message = apply_chord(chord, message)
            continue
        if key is None:
            continue
        if key == ESCAPE:
            return message
        page = max(1, limit - 1)
        if key in (KEY_WHEEL_DOWN, KEY_PGDN):
            if top + page < len(rows):
                top += 3 if key == KEY_WHEEL_DOWN else page
                if key == KEY_PGDN and rows:
                    selected = min(len(rows) - 1, selected + page)
            else:
                # The list has run out; scroll the screen itself instead.
                moved = scroll_step(key, scroll, max_top)
                if moved is not None and moved != scroll:
                    scroll = moved
            continue
        if key in (KEY_WHEEL_UP, KEY_PGUP):
            if top > 0:
                top = max(0, top - (3 if key == KEY_WHEEL_UP else page))
                if key == KEY_PGUP:
                    selected = max(0, selected - page)
            else:
                moved = scroll_step(key, scroll, max_top)
                if moved is not None and moved != scroll:
                    scroll = moved
            continue
        if key == KEY_END:
            scroll = max_top
            continue
        if key == KEY_HOME:
            scroll = 0
            continue
        if not rows:
            if key in (KEY_UP, KEY_DOWN, "\r", "\n"):
                continue
            continue
        if key == KEY_UP:
            selected = (selected - 1) % len(rows)      # wraps at both ends
        elif key == KEY_DOWN:
            selected = (selected + 1) % len(rows)
        elif key == KEY_HOME:
            selected = 0
        elif key == KEY_PGDN:
            selected = len(rows) - 1
        elif key in ("\r", "\n"):
            machine = rows[selected]
            edited, result = edit_machine_notes(live, machine, message)
            # Esc during the prompt puts you back on the summary, not out of it.
            message = result if edited is not None else None
        elif key in ("x", " "):
            # Unmark straight from the summary, then drop the row: it is no
            # longer finished, so it no longer belongs in this list.
            machine, error = store.toggle_machine(store.active(), rows[selected]["id"])
            if error:
                message = error
            else:
                message = (f"{machine.get('name')}: unmarked")
                selected = min(selected, max(0, len(summary_rows()) - 1))
        elif key == KEY_COPY:
            # The lists copy the highlighted row, so the summary does too:
            # a finished machine and what its notes say is what you paste into
            # a write-up. The hint used to advertise a "y" key that nothing
            # here answered to.
            machine = rows[selected]
            body = "\n".join(part for part in
                              (machine.get("name", ""), machine.get("notes"))
                              if part)
            copy_to_clipboard(body)
            message = f"Copied: {machine.get('name', '?')}"


HANDLERS = {
    "1": action_project,
    "2": action_machines,
    "3": action_repository,
    "4": action_settings,
    "5": action_help,
    "6": action_summary,
}


def apply_chord(chord, message):
    """Run a ctrl+x command and say what it did.

    Kept in one place because it is used from the dashboard loop and from every
    panel loop, and the three had drifted apart - the panels had none at all,
    so undo from inside one threw you back to the main menu."""
    if chord.token == CHORD_QUIT:
        return None
    if chord.token == CHORD_UNDO:
        return store.undo() or "Nothing to undo"
    return store.redo() or "Nothing to redo"


def chord_in_place(token):
    """Run a ctrl+x command on the screen that caught it.

    The screens that read keys themselves call apply_chord directly. The
    pickers and detail panels hand the token here through tui, so the command
    runs and the screen stays put. Letting the chord reach the dashboard loop
    instead rebuilt the main menu, so undoing a mark or an edit closed the
    list you were on and read as the app restarting itself."""
    if token == CHORD_QUIT:
        raise Chord(token)
    return apply_chord(Chord(token), None)


def interactive():
    """The dashboard loop.

    ctrl+x u / r / q are raised from wherever the keys were read - a picker,
    an editor, the dashboard. Most of them are caught by the loop they were
    raised in, so the screen you were on stays on screen. Anything that escapes
    all the way here still has to be honoured rather than dropped."""
    message = None
    while True:
        try:
            return _interactive(message)
        except Chord as chord:
            if chord.token == CHORD_QUIT:
                return None
            message = apply_chord(chord, message)


SCROLL_LINES = 3


def _interactive(start_message=None):
    message = start_message
    dirty = True
    hovered = 0
    last_size = None

    def screen():
        """The dashboard for the current terminal size.

        It adapts to the terminal rather than scrolling: the full layout, then
        the compact progress bar, then the menu alone. The wheel scrolls the
        pickers and every panel screen, none of which is this one."""
        return ui.dashboard_window(hovered=hovered, message=message)

    with raw_mode():
        with Live(screen()[0], console=console, screen=True,
                  auto_refresh=False) as live:
            while True:
                size = console.size
                if dirty or size != last_size:
                    last_size = size
                    body, _ = screen()
                    live.update(body)
                    live.refresh()
                    dirty = False
                # Everything a chord can interrupt lives inside this try. It
                # used to escape the loop, and the only handler of it rebuilt
                # the dashboard from scratch - so ctrl+x u threw you back to the
                # main menu with nothing undone, which looked exactly like the
                # keys doing nothing at all.
                try:
                    key = read_key(0.2)
                    if key is None:
                        continue
                    if key in (KEY_LEFT, KEY_RIGHT):
                        hovered = menu_move_across(
                            hovered, -1 if key == KEY_LEFT else 1)
                        ui.set_highlight(hovered)
                        dirty = True
                        continue
                    if key in (KEY_UP, KEY_DOWN):
                        hovered = menu_move_down(
                            hovered, -1 if key == KEY_UP else 1)
                        ui.set_highlight(hovered)
                        dirty = True
                        continue
                    if key in ("\r", "\n"):
                        choice = ui.menu_items()[hovered][0]
                        # Quit is handled by the loop, not by HANDLERS.
                        if choice in ("0", "q"):
                            break
                        message = HANDLERS[choice](live, message)
                        dirty = True
                        continue
                    if key in ("0", "\x03", "\x04"):
                        break
                    handler = HANDLERS.get(key)
                    if handler is None:
                        continue      # unrecognised key: show no Result
                    # A digit runs an entry directly; the highlight moves to
                    # it so the panel that opens is shown to belong to the
                    # entry that opened it, the same as pressing Enter there.
                    opened = next((i for i, (k, _) in enumerate(ui.menu_items())
                                   if k == key), None)
                    if opened is not None:
                        hovered = opened
                        ui.set_highlight(hovered)
                    message = handler(live, message)
                    dirty = True
                except Chord as chord:
                    if chord.token == CHORD_QUIT:
                        break
                    message = apply_chord(chord, message)
                    dirty = True
                    continue


# ---------------------------------------------------------------------- CLI

def build_parser():
    parser = argparse.ArgumentParser(prog="tdash", description="A terminal study dashboard")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("dashboard", help="show the dashboard without the menu")
    sub.add_parser("projects", help="list every project")
    sub.add_parser("help", help="show the help text")
    p_use = sub.add_parser("use", help="switch the active project")
    p_use.add_argument("name")

    p_machine = sub.add_parser("machine", help="add, remove or mark a machine")
    p_machine.add_argument("action", choices=["add", "remove", "mark", "unmark"])
    p_machine.add_argument("name")
    p_machine.add_argument("--notes", default="")

    p_repository = sub.add_parser("repository", help="add or remove a repository entry")
    p_repository.add_argument("action", choices=["add", "remove"])
    p_repository.add_argument("title")
    p_repository.add_argument("--details", default="")

    p_hours = sub.add_parser("hours", help="add or subtract study hours")
    p_hours.add_argument("delta", type=int)

    p_theme = sub.add_parser("themes", help="set this project's themes")
    p_theme.add_argument("name", choices=[t for t in themes.ORDER])
    return parser


def cli(args):
    """Run one command and print the result. Used by the non-interactive paths."""
    key = store.active()
    if args.command == "projects":
        for line, _ in project_choices():
            console.print(line)
    elif args.command == "use":
        found = next((k for k, n in store.registry()["projects"].items()
                      if n["name"].lower() == args.name.lower()), None)
        if found:
            store.select(found)
            console.print(f"Now viewing {as_typed(store.project_name(found))}")
        else:
            console.print(f"No project called {as_typed(args.name)}")
    elif args.command == "machine":
        existing = store.find_machine_by_name(key, args.name)
        if args.action == "add":
            machine, error = store.add_machine(key, args.name, args.notes)
            console.print(error or f"Added {machine['name']}")
        else:
            if not existing:
                console.print(f"No machine called {args.name}")
            elif args.action == "remove":
                console.print(store.delete_machine(key, existing["id"])
                              or f"Deleted {existing['name']}")
            else:
                machine, error = store.mark_machine(
                    key, existing["id"], args.action == "mark")
                console.print(error or f"{machine['name']}: "
                                       f"{'complete' if args.action == 'mark' else 'not complete'}")
    elif args.command == "repository":
        item = next((i for i in store.repository_items(key)
                     if i["title"].lower() == args.title.lower()), None)
        if args.action == "add":
            entry, error = store.add_repository(key, args.title, args.details)
            console.print(error or f"Added {entry['title']}")
        elif not item:
            console.print(f"No repository entry called {args.title}")
        else:
            console.print(as_typed(store.delete_repository(key, item["id"])
                                   or f"Deleted {item['title']}"))
    elif args.command == "hours":
        console.print(f"{as_typed(store.project_name(key))} hours: "
                      f"{store.add_hours(key, args.delta)}h")
    elif args.command == "themes":
        store.set_theme(key, args.name)
        console.print(f"Themes: {themes.label(args.name)}")
    return 0


def main():
    args = build_parser().parse_args()
    for line in store.heal() + store.bootstrap(demo=True):
        console.print(f"[yellow]{line}[/]")

    if args.command == "dashboard":
        from ui import show_dashboard
        show_dashboard()
    elif args.command == "help":
        action_help(None, None)
    elif args.command:
        cli(args)
    elif sys.stdin.isatty():
        interactive()
    else:
        from ui import show_dashboard
        show_dashboard()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        console.print("\n[dim]Bye[/]")
        sys.exit(130)