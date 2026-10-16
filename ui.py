"""Terminal rendering: dashboard panels and the full layout.

The structure is the same for every project - only the numbers, the names and
the colours change. Each project's theme decides the accent colour, so
switching projects changes the whole look of the app.
"""

from rich import box
from rich.console import Console, Group
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

import store
from themes import accent as theme_accent
from themes import bright as theme_bright
from themes import label as theme_label
from themes import soft as theme_soft

console = Console()

# (key, label) in display order. The menu fills five rows per column.
# "2" is a placeholder: its label follows the project's chosen panel name, so
# the menu says the same word the panel does.
MENU_ITEMS = [("1", "Project"), ("2", "Machines"), ("3", "Repository"),
              ("4", "Settings"), ("5", "Help"), ("6", "Summary"), ("0", "Quit")]
MENU_ROWS = 5
PANEL_MENU_KEY = "2"


def menu_items():
    """The menu as it should read right now, with the panel's own name in it.

    Built on demand rather than stored, because the name is a per-project
    setting that can change while the app is running."""
    name = store.dashboard_panel()
    return [(key, name if key == PANEL_MENU_KEY else label)
            for key, label in MENU_ITEMS]

PANEL_BORDER = "grey37"
# What the Menu box costs around its contents: two borders and 3 of padding
# either side. Used to decide whether the options fit side by side.
MENU_FRAME = 8


# ------------------------------------------------------------------- theming

def theme():
    """The active project's theme key."""
    return store.project_theme()


def accent():
    return theme_accent(theme())


def bright():
    return theme_bright(theme())


def dim():
    return theme_soft(theme())


# -------------------------------------------------------------------- pieces

def as_typed(text):
    """Data written so it is drawn exactly as it was typed.

    A machine called "x[/]" used to take the screen down with a markup error
    the moment a list drew it, and "[link=...]" in a note or a name drew as a
    link nobody meant. Escaping at the point the text is written into a line
    keeps brackets readable and keeps the line parsing-safe."""
    return escape(store.clean_text(str(text)))


def panel_title(name, detail=None):
    """Section heading: bold, with the detail dimmed after it."""
    head = f"[bold]{name}[/]"
    return f"{head} [dim]{detail}[/]" if detail else head


def inner_panel(renderable, title, **style):
    """A soft, rounded sub-panel with a dimmed border."""
    return Panel(renderable, title=f"[bold {PANEL_BORDER}]{title}[/]",
                 border_style=PANEL_BORDER, box=box.ROUNDED, padding=(0, 1),
                 **style)


def rounded(renderable, **style):
    """Panel with soft rounded corners and consistent padding."""
    return Panel(renderable, box=box.ROUNDED, padding=(0, 1), **style)


def progress_bar(completed, total, width=24):
    """Coloured bar. Clamped so bad data cannot stretch the layout, while the
    counts stay exactly as stored rather than being tidied up."""
    if total > 0:
        pct = round(100 * completed / total)
        filled = max(0, min(width, round(width * completed / total)))
    else:
        pct, filled = 0, 0
    track = f"[{PANEL_BORDER}]{'░' * (width - filled)}[/]"
    # Percentages stay in one calm colour. Colour-coding them red/amber/green
    # made a normal low percentage look like something had gone wrong.
    return f"[{accent()}]{'█' * filled}[/]{track} [bold]{pct}%[/] [dim]{completed}/{total}[/]"


def active():
    return store.active()


def kv_table(pairs):
    """Two-column label/value table with dimmed labels."""
    table = Table.grid(padding=(0, 2))
    for name, value in pairs:
        table.add_row(f"[{dim()}]{name}[/]", value)
    return table


def status_table():
    """Which project you are in, where you are, and how much runway is left."""
    key = active()
    left = days_left()
    current = store.slot_name(key, "current")
    nxt = store.slot_name(key, "next")
    return kv_table([
        ("Objective", f"[bold white]{store.project_objective(key)}[/]"),
        ("Current", f"[bold {accent()}]{current}[/]" if current
                   else f"[{dim()}]not set yet[/]"),
        ("Next", f"[bold {accent()}]{nxt}[/]" if nxt
                else f"[{dim()}]not set yet[/]"),
        ("Days left", f"[{days_style(left)}]{left}[/]"),
    ])


def stats_table():
    """Hours, deadline and the theme this project uses."""
    key = active()
    stats = store.stats(key)
    deadline = stats.get("deadline") or ""
    return kv_table([
        ("Project", f"[bold {bright()}]{as_typed(store.project_name(key))}[/]"),
        ("Hours", f"[bold green]{stats.get('hours_studied', 0)}h[/]"),
        ("Deadline", f"[{urgency(days_left())}]{as_typed(deadline)}[/]" if deadline
                    else f"[{dim()}]not set[/]"),
        ("Themes", f"[bold {bright()}]{theme_label(theme())}[/]"),
    ])


def progress_block():
    """How far through the project's machines you are, and nothing else.

    The heading above it is the project's choice of "Topics" or "Machines" -
    same figures either way, switched from [2] Machines.

    One bar and one number. A per-machine list was tried here and removed: the
    descriptions said nothing you could act on, and the names are already one
    keypress away under [2] Machines."""
    key = active()
    done, total = store.tally(key)
    grid = Table.grid(expand=True, padding=(0, 2))
    grid.add_column(justify="left", no_wrap=True, width=22)
    grid.add_column(justify="left", no_wrap=True)
    grid.add_row(f"[bold {accent()}]{as_typed(store.project_name(key))}[/]",
                 progress_bar(done, total))
    if not total:
        grid.add_row(f"  [{dim()}]No {store.panel_noun_plural()} yet - add "
                     f"some with [2] {store.dashboard_panel()}[/]", "")
    return grid


def days_left():
    return store.days_left()


def urgency(days):
    """Colour for the deadline: calm when there is room, urgent when there is not."""
    if not isinstance(days, int):
        return "dim"
    return "dim" if days > 7 else "bold red"


def days_style(days):
    """Days left is always maroon: the one number worth interrupting for.

    Rich has no colour called "maroon", so dark_red is used - it is the same
    maroon shade (rgb 135,0,0) and resolves to a 256-colour index, so it
    renders on 8-colour terminals too. A literal #8b0000 would force truecolor
    escape codes and fall apart on terminals without it."""
    return "bold dark_red" if isinstance(days, int) else "dim"


def active():
    return store.active()


# --------------------------------------------------------------------- menu

# Three rows to a column. Seven options therefore run 1 2 3 | 4 5 6 | 0, which
# keeps the panel short and leaves room between the columns.
MENU_COLUMNS = 3


def menu_columns():
    """Options split into MENU_COLUMNS columns, filled downwards.

    Reading down a column before moving on is what makes the keys feel right:
    Down at the bottom of a column lands on the top of the next one."""
    items = menu_items()
    per = -(-len(items) // MENU_COLUMNS)
    return [[i for i in range(start, min(start + per, len(items)))]
            for start in range(0, len(items), per)]


# Which menu item the highlight is on. The Menu is context behind every
# panel: while a picker or an editor is open the menu stays on screen, and the
# box should mark the parent of whatever panel is open - opening Settings and
# having the highlight snap back to [1] Project said the wrong panel was
# chosen. The dashboard loop keeps this in step; every screen that redraws the
# layout itself reads it.
_HIGHLIGHT = [0]


def set_highlight(index):
    _HIGHLIGHT[0] = index


def highlight():
    return _HIGHLIGHT[0]


def menu_move_across(index, step):
    """Left/Right: the same row of the neighbouring column, if one exists."""
    columns = menu_columns()
    here = next((c for c, items in enumerate(columns) if index in items), 0)
    row = columns[here].index(index)
    target = here + step
    if not 0 <= target < len(columns) or row >= len(columns[target]):
        return index
    return columns[target][row]


def menu_move_down(index, step):
    """Up/Down: down the column, then the top of the next one.

    Down from the bottom of a column lands on the top of the next, wrapping to
    the first column at the end; Up mirrors it, from the top of a column to the
    bottom of the previous, wrapping to the last column."""
    columns = menu_columns()
    where = next(c for c, items in enumerate(columns) if index in items)
    row = columns[where].index(index)
    total = len(columns)
    if step > 0:
        if row + 1 < len(columns[where]):
            return columns[where][row + 1]
        for ahead in range(where + 1, total + 1):
            column = columns[ahead % total]
            if column:
                return column[0]
    else:
        if row > 0:
            return columns[where][row - 1]
        for behind in range(where - 1, -total - 1, -1):
            column = columns[behind % total]
            if column:
                return column[-1]
    return index


def _narrow_menu_panel(items, hovered):
    """The menu as a single column, for terminals too narrow for two."""
    rows = []
    for index, (key, text) in enumerate(items):
        item = f"  [{key}]  {text}"
        rows.append(f"[reverse bold {accent()}]{item}[/]" if index == hovered
                    else item)
    rows.append("")
    rows.append("[dim]↑↓ move  ↵ select  ctrl+x q quit[/]")
    return Panel("\n".join(rows),
                 title=f"[bold {accent()}]Menu[/]",
                 title_align="left",
                 border_style=PANEL_BORDER, box=box.ROUNDED, padding=(0, 1))


def menu_panel(hovered=0):
    """The Menu - the second panel: every option in one bordered box."""
    items = menu_items()
    columns = menu_columns()
    gap = 7
    # Does the multi-column layout actually fit? Measured, not guessed at a
    # fixed width: three columns need every label plus a gutter each, and on a
    # narrow terminal they wrapped onto a second line and pushed "[0] Quit" off
    # the row. One column always fits and costs a few rows.
    needed = (sum(max(len(f"  [{items[i][0]}]  {items[i][1]}") for i in column)
                  for column in columns)
              + gap * (len(columns) - 1)
              + MENU_FRAME)          # borders and the panel's side padding
    if console.width < needed:
        return _narrow_menu_panel(items, hovered)
    # Every column is padded to its own widest label. Padding only the first
    # one - which is all two columns ever needed - left the second and third
    # hard against each other, so the gaps down the panel were 12, 2 and 0.
    widths = [max(len(f"  [{items[i][0]}]  {items[i][1]}") for i in column)
              for column in columns]

    rows = []
    last = len(columns) - 1
    for row in range(max(len(c) for c in columns)):
        parts = []
        for position, column in enumerate(columns):
            if row >= len(column):
                # A short column still holds its place, so the ones below stay
                # where they are instead of sliding left on the later rows.
                parts.append(" " * (widths[position] + gap)
                             if position < last else "")
                continue
            index = column[row]
            key, text = items[index]
            item = f"  [{key}]  {text}"
            # Pad outside the markup so a highlighted cell keeps its width.
            shown = f"[reverse bold {accent()}]{item}[/]" if index == hovered else item
            if position < last:
                shown += " " * (widths[position] - len(item) + gap)
            parts.append(shown)
        rows.append("".join(parts).rstrip())

    rows.append("")
    # A short hint on a narrow terminal. The full one wrapped to four extra
    # rows at 40 columns, which pushed the dashboard itself down to a single
    # row and left the wheel scrolling through blank padding.
    if console.width >= 74:
        rows.append("[dim]↑↓ column  ←→ columns  ↵ select  ctrl+x u undo  "
                    "ctrl+x r redo  ctrl+x q quit[/]")
    else:
        rows.append("[dim]↑↓ move  ↵ select  ctrl+x q quit[/]")
    return Panel("\n".join(rows),
                 title=f"[bold {accent()}]Menu[/]",
                 title_align="left",
                 border_style=accent(),
                 box=box.ROUNDED,
                 padding=(1, 3))


def clip(text, limit=88):
    """First sentence, or a word-boundary clip, so one long note cannot swamp
    a list. The full text stays in the detail panel."""
    text = " ".join((text or "").split())
    if not text:
        return ""
    if len(text) <= limit:
        return text
    first = text.split(". ")[0]
    if first.endswith("."):
        return first
    return text[:limit].rsplit(" ", 1)[0] + "…"


# The summary is a glance, not a report: a long day would otherwise push the
# panel past the bottom of the screen.
SUMMARY_ROWS = 6


def first_lines(text, count=3):
    """A note as a Text, keeping its line breaks and cutting after `count`.

    Notes are several lines long now. Rich only honours newlines inside a Text
    object - handed a plain string, a table cell collapses them into one run-on
    line - and a note squashed onto one line misrepresents what was written."""
    lines = (text or "").split("\n")
    while lines and not lines[-1].strip():
        lines.pop()
    if not lines:
        return Text("no notes yet", style=dim())
    body = Text("\n".join(lines[:count]))
    if len(lines) > count:
        body.append(f"\n...+{len(lines) - count} more", style=dim())
    return body


def is_done(machine):
    """True when a machine's completed count has reached its total."""
    return machine.get("completed", 0) >= machine.get("total", 1)


def summary_stats(done, total, today_count, word="Done"):
    """The row of figures across the top, Total left, the finished and Today
    right.

    The middle figure is named by the project's own word - Done, or pwned
    where the project asked for it - so the headline and the Status cells
    below it cannot disagree about what a finished machine is called.

    Mirrors the Goal Tracker layout: each figure is a label with its count in
    brackets, so the numbers sit in one line and can be compared at a glance."""
    grid = Table.grid(expand=True, padding=(0, 3))
    for _ in range(3):
        grid.add_column(justify="left")
    grid.add_row(f"[bold {bright()}]Total ({total})[/]",
                 f"[bold green]\u2705 {word} ({done})[/]",
                 f"[bold {accent()}]\U0001F4C5 Completed Today ({today_count})[/]")
    return grid


def summary_categories(key, rows):
    """The chosen categories, in the order they were picked, and what each
    machine
    says in them.

    Read once per row rather than per field: a field's body lives under the
    machine that marks it, and asking the store once per cell re-read the file
    for every cell of the table. The OS is one of these fields - it is written
    on the machine rather than shared, so it is read straight off it."""
    wanted = store.summary_category_ids(key)
    titles = [store.summary_category_title(f, key) for f in wanted]
    bodies = []
    for machine in rows:
        own = {entry.get("title", "?"): (entry.get("body")
                                         or entry.get("default") or "")
               for entry in store.machine_categories(key, machine["id"])}
        row = dict(own)
        if store.OS_CATEGORY in wanted:
            row[store.summary_category_title(store.OS_CATEGORY, key)] = \
                machine.get("os") or ""
        bodies.append(row)
    return titles, bodies


def summary_table(rows, heading="", selected=None, key=None, settings=None):
    """What each finished machine shows in the summary.

    The columns are whatever Summary Settings has asked for: the machine itself
    can be left out, any number of the project's fields can be shown beside it,
    and Status, Date and Notes are always the last three. heading is optional:
    the top row already carries the counts, so the common case passes nothing
    rather than repeating them."""
    key = key or active()
    settings = settings if settings is not None else store.summary_settings(key)
    titles, bodies = summary_categories(key, rows)
    done = store.summary_status_word(key)
    table = Table(box=box.SIMPLE_HEAD, expand=True, pad_edge=False,
                  padding=(0, 1), header_style=f"bold {dim()}")
    if settings.get("machines"):
        # The column is called whatever the dashboard calls it, so switching
        # Topics to Machines moves the heading with it instead of leaving a
        # "Machine" column sitting under a panel headed "Topics".
        table.add_column(store.dashboard_panel(key), no_wrap=True)
    for title in titles:
        table.add_column(as_typed(title), ratio=1, overflow="fold")
    table.add_column("Status", no_wrap=True)
    table.add_column("Date", no_wrap=True)
    table.add_column("Notes", ratio=1, overflow="fold")
    for i, machine in enumerate(rows):
        marker = "\u25b8 " if i == selected else "  "
        cells = []
        if settings.get("machines"):
            cells.append(f"[bold {bright()}]{marker}"
                         f"{as_typed(machine.get('name', '?'))}[/]")
        for title in titles:
            cells.append(first_lines(bodies[i].get(title), 3))
        cells.append(f"[green]{as_typed(done)}[/]" if is_done(machine)
                     else "[dim]open[/]")
        cells.append(as_typed(machine.get("completed_on"))
                     if machine.get("completed_on") else "[dim]-[/]")
        cells.append(first_lines(machine.get("notes")))
        table.add_row(*cells)
    return Group(f"[{dim()}]{heading}[/]", table) if heading else table


def summary_panel(selected=None, hint=False, top=0, limit=None):
    """Today at a glance, falling back to the most recent wins.

    The headline figures are Total, the finished (everything up to now, named
    by the project's own word) and Completed Today, with the machines
    underneath: which OS, when it
    was completed and what the notes say. The figure and the list say the same
    thing once between them, so the list carries no heading of its own. On a day when nothing has been completed
    yet the recent list is shown instead of an empty box - a tracker that is
    blank exactly when you most want to check it is no use."""
    key = active()
    done, total = store.tally(key)
    today = store.completed_today(key)
    # Just "Summary", like the Status and Stats panels. It used to read
    # "<project> \u00b7 <date>", naming the panel after its contents while
    # the menu item above it already said Summary.
    title = "Summary"
    stats = summary_stats(done, total, len(today),
                          store.summary_status_word(key))
    rows = today if today else (store.recent_completed(key) or [])
    # A long list used to be cropped by Rich with the rest simply unreachable:
    # no wheel, no page keys, no way to see a machine you had scrolled past.
    if limit:
        top = max(0, min(top, max(0, len(rows) - limit)))
        shown = rows[top:top + limit]
    else:
        shown = rows[:SUMMARY_ROWS]
    if not rows:
        block = Text("Nothing completed yet. Mark one from the list: "
                     f"[2] {store.dashboard_panel()} > Open, then press m "
                     "on the row.", style="dim")
    elif today:
        # No heading: the "Completed Today" figure above already says this, and
        # printing it twice read as two different counts.
        block = summary_table(shown, "", selected, key)
        if len(rows) > len(shown):
            block = Group(block, _more_above(top),
                          _more_below(len(rows) - top - len(shown)))
    else:
        block = summary_table(
            shown,
            f"[dim]Nothing completed today \u00b7 showing your "
            f"{len(rows)} most recent:[/]", selected, key)
        if len(rows) > len(shown):
            block = Group(block, _more_above(top),
                          _more_below(len(rows) - top - len(shown)))
    # A bare table needs no spacer above it; the extra blank line only showed up
    # as a gap now that the heading is gone.
    parts = [stats, block if isinstance(block, Table) else Group("", block)]
    if hint:
        parts.append(hint_line("\u2191\u2193 (Select)  \u23ce (Edit notes)  "
                               "\u00d7 (Unmark)  ctrl+shift+c (Copy)  "
                               "wheel/pgup/pgdn (Scroll)  esc back"))
    content = Group(*parts)
    # Sized to its contents so the panel can be scrolled rather than cropped.
    return inner_panel(content, title, height=content_height(content) + 2)


def _more_above(top):
    if not top:
        return Text("")
    return Text(f"\u2191 {top} more above", style="dim")


def _more_below(count):
    if count <= 0:
        return Text("")
    return Text(f"\u2193 {count} more below", style="dim")


def summary_limit():
    """How many rows of the Summary fit below the rest of the screen."""
    fixed = _natural_height(body()) + _menu_rows() + 4      # dashboard + gap
    return max(3, console.height - fixed - 8)              # stats + hint


def _clean(lines):
    """render_lines pads to the height asked for; that padding is not content."""
    while lines and not any(seg.text.strip() for seg in lines[-1]):
        lines.pop()
    return lines


def content_height(renderable, probe=2000):
    """How many rows a renderable actually needs.

    A Panel fills whatever height it is offered, so the only way to find out
    what a panel wants is to measure what is inside it and size it explicitly."""
    rows = ["".join(seg.text for seg in line)
            for line in _rendered(renderable, probe)]
    while rows and not rows[-1].strip():
        rows.pop()
    return len(rows)


def _rendered(renderable, height=10000):
    opts = console.options.update(height=height)
    return _clean(console.render_lines(renderable, opts, pad=False))


def _natural_height(renderable, probe=400):
    """How tall a Panel really wants to be.

    A Panel grows to fill whatever height it is offered, so asking for 10000
    rows does not measure the content - it measures the request. This renders
    generously, drops the bottom border and the blank rows under it, and counts
    what is left. Without this the menu was rendered 10000 rows tall and pushed
    clean off the bottom of the screen."""
    rows = ["".join(seg.text for seg in line) for line in _rendered(renderable, probe)]
    last = -1
    for i, row in enumerate(rows):
        # Rows of the panel's own border are not content. Everything inside it
        # starts with the left border, so a row that both does and carries
        # something between the bars is a real line of the panel.
        if row.startswith("\u2502") and row.strip("\u2502 "):
            last = i
    return last + 2 if last >= 0 else len(rows)


# Rendering the whole dashboard costs about 27ms and measuring the menu about
# 4ms. The old code did both on every keystroke, purely to decide whether the
# dashboard could scroll, which capped the scroll wheel at roughly a dozen
# notches a second - it felt like the wheel was sticking. Both are cached now and
# only rebuilt when the data changes or the terminal is resized.
_DASHBOARD_CACHE = {}
_MENU_CACHE = {}


def invalidate_dashboard():
    """Forget the cached rows; call after anything the dashboard shows changes."""
    _DASHBOARD_CACHE.clear()


def _cache_key():
    return (console.width, console.height, store.data_version())


def _menu_rows():
    """How many rows the Menu panel takes at the current width."""
    key = console.width
    if key not in _MENU_CACHE:
        _MENU_CACHE[key] = _natural_height(menu_panel(0))
    return _MENU_CACHE[key]


_BODY_CACHE = {}


def body(compact=False):
    """The dashboard panel, cached.

    Building it measures two sub-panels, which means rendering them. That is
    fine once and ruinous on every keystroke."""
    key = (compact, console.width, store.data_version())
    hit = _BODY_CACHE.get(key)
    if hit is None:
        hit = dashboard_body(compact)
        # Drop rows measured for a different terminal width, but keep the other
        # variant: clearing on every miss threw away the full layout as soon as
        # the compact one was built, and the next frame rebuilt both.
        for stale in [k for k in _BODY_CACHE if k[1] != console.width]:
            _BODY_CACHE.pop(stale, None)
        _BODY_CACHE[key] = hit
    return hit


def _dashboard_lines():
    """The dashboard's rows in both sizes, cached."""
    key = _cache_key()
    hit = _DASHBOARD_CACHE.get(key)
    if hit is None:
        hit = (_rendered(body()), _rendered(body(compact=True)))
        for stale in [k for k in _DASHBOARD_CACHE if k[0] != console.width]:
            _DASHBOARD_CACHE.pop(stale, None)
        _DASHBOARD_CACHE[key] = hit
    return hit


def dashboard_budget(message=None):
    """Rows the dashboard may use once the menu has been given its space.

    The menu used to be cropped away on a short terminal, which left the arrow
    keys moving a highlight nobody could see - it looked like the dashboard had
    stopped responding. The menu is how you get out of here, so it stays put and
    the dashboard scrolls above it.

    Zero is a real answer. When the menu leaves no room the old code squeezed
    the dashboard into a single row anyway, and the wheel then scrolled through
    blank padding: it looked like scrolling, but nothing ever came into view."""
    reserved = _menu_rows() + 1 + (1 if message else 0)
    return max(0, console.height - reserved)


def window_screen(renderable, top=0):
    """A screen that may be taller than the terminal.

    Rich crops whatever does not fit and there was no way to see the rest: a
    long summary, a long machine detail or a long repository entry simply ran off
    the bottom of the screen. Returns (renderable, top, max_top) so the caller
    can move `top` with the wheel or the page keys.

    Lines are sliced out of Rich's own rendered segments, so colours survive."""
    lines = _clean(console.render_lines(
        renderable, console.options.update(height=10000), pad=False))
    if len(lines) <= console.height:
        return renderable, 0, 0
    max_top = len(lines) - console.height
    top = max(0, min(top, max_top))
    window = Group(*[styled_line(line) for line in lines[top:top + console.height]])
    return window, top, max_top


def styled_line(segments):
    """A rendered line as Text, keeping the colours.

    Scrolling means slicing already-rendered lines; rebuilding them as plain
    strings would throw the theme away."""
    text = Text()
    for seg in segments:
        text.append(seg.text, seg.style)
    return text


def dashboard_window(top=0, hovered=None, message=None):
    """The dashboard, windowed to the space above the menu.

    On a screen tall enough this is the dashboard unchanged. On a short one the
    layout is taller than the terminal, where Rich simply crops the bottom -
    the wheel and the page keys then scroll it instead. Lines are taken from
    Rich's own rendered segments so the theme colours survive the slice.

    hovered is passed through because the menu is part of this renderable: left
    out, the arrow keys moved the selection and Enter opened the right panel,
    while the highlight sat on [1] for ever."""
    if hovered is None:
        hovered = highlight()
    budget = dashboard_budget(message)
    full, small = _dashboard_lines()
    lines = full
    if len(lines) <= budget:
        return build_layout(message, hovered), 0
    if len(small) <= budget:
        return build_layout(message, hovered, compact=True), 0
    # Not even the compact dashboard fits: a zoomed terminal, or one so short
    # the menu fills it. Show the menu on its own. Squeezing the dashboard into
    # the rows that remain looked worse than this and scrolled through nothing.
    return Group(menu_panel(hovered),
                 Text(message, style="green") if message else Text("")), 0


def dashboard_body(compact=False):
    """The dashboard area - what we call the first panel.

    Status and Stats side by side, then the full-width Topics/Machines panel.
    Names and the rest of the vocabulary are in TERMS.md at the project root.

    On a terminal too short for that there is no honest way to slice a panel in
    half - the border is cut off and the Progress panel never appears at all -
    so the compact form drops the detail and keeps the bar and the menu.

    The repository is not on the dashboard: it is a reference you open when you
    want it, not a figure to glance at. It stays one keypress away at [3]."""
    # An explicit height everywhere, for the same reason: measured with none, a
    # Panel returns the height it was offered rather than the height it wants.
    progress = inner_panel(progress_block(),
                           panel_title(store.dashboard_panel()),
                           height=_natural_height(progress_block()) + 2)
    if compact:
        return progress
    top = Table.grid(expand=True, padding=(0, 2))
    top.add_column(ratio=1)
    top.add_column(ratio=1)
    top.add_row(inner_panel(status_table(), panel_title("Status")),
                inner_panel(stats_table(), panel_title("Stats")))
    body = Group(top, "", progress)
    # An explicit height: left to itself a Panel fills the screen it is given,
    # which pushed the menu off the bottom of a short terminal.
    height = len(_rendered(top)) + 1 + _natural_height(progress) + 2
    return rounded(body,
                   title=f"[bold {bright()}]Dashboard[/]",
                   title_align="center",
                   border_style=accent(),
                   height=height)


def build_layout(message=None, hovered=None, compact=False):
    """The dashboard, then the menu, then any message.

    hovered defaults to the menu highlight last set - the item whose panel is
    open - so every picker and editor that redraws this layout keeps the box
    on its parent rather than resetting to [1] Project."""
    if hovered is None:
        hovered = highlight()
    parts = [body(compact), "", menu_panel(hovered)]
    # A sentinel means a screen was cancelled and the caller is still climbing
    # back out. Rendering one used to raise, taking the program with it, so
    # only real text is ever shown here.
    if isinstance(message, str) and message:
        parts.append(Text(message, style="green"))
    return Group(*parts)


def detail_panel(title, body, note=None):
    """A titled panel of text, held open until a key is pressed."""
    content = body if note is None else Group(body, "", f"[dim]{note}[/]")
    return inner_panel(content, title)


HINT_TEXT = "\u23ce mark/unmark"


def hint_line(text=HINT_TEXT):
    """The dim one-liner under a detail panel telling you the keys."""
    return f"[dim]{text}[/]"


# Formerly private: screens outside ui.py size their own panels with it.
_content_height = content_height


def render(renderable, width=100):
    """Plain text of any renderable, for tests and for checking a layout.

    The app's console is narrowed to match first: parts of the layout choose
    how to arrange themselves from that width - the menu lays itself out in
    columns or as one, and the lists pick a window size - so rendering at 60
    columns while the app still thought it was 100 produced a menu arranged
    for the wrong terminal, which is exactly what it looked like."""
    was = console._width            # private, but it is the only way back to
    console.width = width            # "follow the terminal again"
    try:
        test_console = Console(width=width, force_terminal=False, no_color=True)
        with test_console.capture() as captured:
            test_console.print(renderable)
        return captured.get()
    finally:
        console._width = was


def show_dashboard():
    console.print(build_layout())