# tdash — a terminal study dashboard

A small terminal app for tracking what you are studying: which box you are on,
what is next, what you finished, and how far through the material you are.
Built for study tracks — labs, boxes, exercises — where the material is a list
of machines you mark off as you get through them.

Plain Python, `rich` for the interface, JSON for storage. One dependency.

## Requirements

- A terminal. Any modern one works: the interface uses colours and box-drawing
  characters, and needs a font with box-drawing glyphs (most default fonts).
  On Windows, use Windows Terminal or the built-in console (Windows 10 1809+
  or Windows 11); an older console gets a message saying so instead of a
  broken screen.
- Python 3.8+. Written and tested against 3.13 on Linux and Windows; no syntax
  newer than 3.8 is used, so treat 3.8+ as expected rather than proven.
- `rich`, the single dependency. `setup.py` installs it into a `.venv` for you.

Sized for 80×24 and up. Smaller terminals adapt rather than break: the menu
drops to a single column, lists cap their rows, the dashboard gives way to the
menu, and the Help text pages itself.

## Install

Unzip the folder anywhere, then:

```sh
cd <the folder you unzipped>
python setup.py      # once: creates .venv/ and installs rich
python install.py    # installs the app and the tdash command
```

If `python` is not found but `python3` is, use that.

`install.py` copies the program into a per-user folder
(`~/.local/share/tdash/app` on Linux and macOS, `%LOCALAPPDATA%\tdash\app` on
Windows) and writes a small launcher next to it (not a symlink, so it survives
zipping, copying and Windows checkouts): `~/.local/bin/tdash`, or
`%LOCALAPPDATA%\tdash\bin\tdash.cmd` on Windows. On Windows it also adds that
folder to your PATH itself — no admin rights, no System Properties walk. On
Linux, add `~/.local/bin` to your PATH if `tdash` is not found (most
distributions already have it).

**The folder you installed from is now disposable**: delete it, move it, keep
it. The app runs from the installed copy, and your data lives with it
(`…/tdash/app/data`), not in the download.

To **upgrade**, run `python install.py` from a newer copy: the installed
virtualenv and your data are kept. `setup.py` is only needed the first time.

Open a new terminal — command shells only re-read PATH at start — then:

```sh
tdash
```

### Running without installing

```sh
./tdash                # Linux, macOS, WSL; runs from the folder
python tdash.py        # from the folder, including Windows
```

This runs the copy in the folder, with its own `data/` beside it — handy for a
look around before installing.

## First run: the demo project

The first run creates **Demo Project**, an example with every screen filled in,
and opens on it. The notes of its first machine, `Start Here`, are a short
tour, and the rest shows the features off: a group per platform, one box
already finished — dated today, so the Summary opens on a win — one category
answered for a single machine only (its page carries a `*`), twelve hours on
the clock with a deadline six weeks out, and a repository with entries under
two headings.

When you have looked around, make it yours:

1. `[1] Project` > `Create` — name a project of your own; it is created and
   switched to.
2. `[1] Project` > `Delete` — select `Demo Project` and confirm.

A project cannot be deleted while it is the last one — the app always needs
somewhere to put things — so create yours first, then remove the demo.

## The screen

Two areas. On top, the **dashboard**:

- **Status** — the project's objective, the current machine, the next one, and
  the days left if a deadline is set.
- **Stats** — project name, study hours, deadline, theme.
- **the progress panel**, headed **Topics** by default (renameable to
  **Machines** under `[2]` > `Panel`): a bar, a percentage, and how many
  machines are done. Empty, it reads `No topics yet - add some with [2] Topics`.

Below it, the **Menu**:

```
╭─ Menu ─────────────────────────────────────────────────────────────────────────────────────────────────────╮
│                                                                                                            │
│     [1]  Project            [4]  Settings         [0]  Quit                                                │
│     [2]  Topics             [5]  Help                                                                      │
│     [3]  Repository         [6]  Summary                                                                   │
│                                                                                                            │
│   ↑↓ column  ←→ columns  ↵ select  ctrl+x u undo  ctrl+x r redo  ctrl+x q quit                             │
│                                                                                                            │
╰────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
```

`↑↓` read down a column and continue into the next, wrapping at the ends;
`←→` jump between columns on the same row; you can also press an option's
number. The option under the cursor is highlighted.

## The menu, entry by entry

### `[1]` Project

Switch, create, rename or delete projects. The pickers mark the active project
with `(here)` and show each one at a glance: `[1/4]` is machines done,
`[empty]` is nothing in it yet. Creating a project switches to it; deleting one
asks first, and the last project cannot be deleted.

### `[2]` Topics (or Machines)

The panel's name follows the project, and this menu entry carries it:
`Panel (Topics)` renames the panel; the sub-menu is `View`, `Categories`,
`Panel`.

**View** opens the list. Keys act on the highlighted row:

| key | does |
| --- | --- |
| `↑` `↓` | move |
| `↵` | open the machine to read it |
| `m` | mark it finished, or unmark it |
| `a` | add one |
| `e` | edit it |
| `d` | delete it (asks `Delete <name>?` first) |
| `c` | choose which categories this machine shows |
| `Esc` | back to the sub-menu |

Marking is this one key, on the row you are standing on — opening a machine to
read it cannot complete it, so a stray `↵` while reading costs nothing.

A machine opens as pages, one category at a time. The first page is its
description in the box at the top; then Notes, the OS where the project keeps
it, and whatever else the machine has written, each on its own page.
`↵` is **Next** — page after page — and on the last page `↵` leaves the view.
A `State:` line (`not complete`, or `complete on <date>`) sits under every
page, `c` is the categories screen and `Esc` goes back. When you come back
from a page, the list reopens on the same row.

A category answered for this machine only, overriding the project's shared
default, is marked with a `*`.

**Adding and editing.** `a` asks Name, then Description, Notes and Group (all
optional except the name); `e` asks the same for the highlighted machine.
Description and notes hold several lines: `↵` inserts a line break, `ctrl+s`
saves, `Esc` cancels. Everything is editable afterwards.

**Categories.** `[2]` > `Categories` is the one place a field is defined for
the whole project: created, renamed, given a shared default, put in a group,
deleted. Every machine then ticks the ones it uses with `c`, and can override
the body for itself; a blank override puts the shared default back.

Two categories are permanent and always on: **Description** (what the box is)
and **Notes** (what you worked out). They lead every machine's list, and `e`
on them edits that machine's own copy. The description is the one-line summary
you see at the top of a machine's page, kept to 160 characters so it stays one;
the notes are your own writing and what the Summary lists.

**Groups.** Machines, categories and repository entries each carry a group,
typed when added or edited. Lists are drawn in sections by it, named groups
first in the order they were first seen, with everything ungrouped in a
section at the end. Groups are optional.

### `[3]` Repository

A project's own reference list — commands, snippets, links, anything worth
keeping. `View` opens the entries:

| key | does |
| --- | --- |
| `↑` `↓` | move |
| `↵` | read the highlighted entry |
| `a` `e` `d` | add, edit, delete (delete asks first) |
| `Esc` | back |

The title and details of an entry can both hold several lines (`↵` new line,
`ctrl+s` save). While reading an entry, `e` edits it in place. An entry with no
title still exists and reads as `(untitled)`.

### `[4]` Settings

Seven entries, each one press away from its change:

| entry | does |
| --- | --- |
| Objective | the text in the Status panel |
| Current | which machine you are on (`— clear —` puts it back to nothing) |
| Next | which machine is next |
| Hours | study hours so far |
| Deadline | the date the days-left counter counts to |
| Themes | the project's colour theme — twenty-one of them, starting with `teal`, the default, and `jade` |
| Reset | clears the project's progress and hours (asks first) |

Everything here belongs to the project, so another project keeps its own.

### `[5]` Help

The same key list you are reading, in the app. On a short terminal it pages —
any key shows the next page.

### `[6]` Summary

Two views:

**Show Summary** — the record of what you have finished. `Total (n)`,
`Done (n)` and `Completed Today (n)` across the top, then the finished
machines: name, status, date, notes. On a day with no completions it shows
your most recent wins instead, dated so it is clear they are not from today.
It is editable in place: `↑`/`↓` move, `↵` edits the highlighted machine's
notes, `x` unmarks it.

**Summary Settings** — what that table shows. Its own screen, not a picker,
because every row is on or off and shows its own state:

- the panel-names column (`✓ Topics` / `✓ Machines`) — `↵` hides it
- `Categories` — how many fields are in the summary; `↵` steps down to them
- one row per category — `↵` shows it in the summary or takes it out
- `Status wording` — `↵` toggles between `Done` and `pwned`
- **Always shown** — Status, Date and Notes; the cursor never stops on them

There is no save button: every press writes straight through.

## Keys everywhere

| key | does |
| --- | --- |
| `ctrl+x u` | undo |
| `ctrl+x r` | redo |
| `ctrl+x q` | quit (`0` on the menu and `Ctrl+C` also quit) |
| `ctrl+x m` | mouse tracking on/off |
| `Esc` | back one level |
| `page up` / `page down`, wheel | scroll a screen taller than the terminal |
| `home` / `end` | jump to the ends |

Undo inside a field edits the field; in a list, a panel or the dashboard it
rolls back the session's last change — whichever project it was made in — and
stays on the screen you are on. Both stack in memory only, and are gone when
you exit.

**Confirmations** ask `Delete <name>?` and answer **`Y/n`**: `Y` confirms, `n`
cancels, `↵` cancels, and any other key is ignored and the question re-asked.
Lowercase `y` is not accepted — a destructive action loses to a stray keypress
rather than winning by default.

**Lists** show five rows at a time (group headings count as rows) and scroll
with the arrows, the wheel or `page up`/`page down`. Numbers jump in a
sub-menu: press the option's number.

## Editing text

A field that can hold several lines opens full screen, with the dashboard out
of the way:

| key | does |
| --- | --- |
| `↵` | insert a line break |
| `ctrl+s` | save |
| `Esc` | cancel |
| `ctrl+u` / `ctrl+k` | cut to the start / end of the line; press again to take the line above / join the next line |
| `ctrl+a` | select all; typing replaces it |
| `←` `→` `Home` `End` `↑` `↓` | move the cursor |
| `ctrl+←` / `ctrl+→` | a word at a time; with `shift`, select |
| `ctrl+shift+↑` / `ctrl+shift+↓` | select a line at a time |
| `Backspace` / `Delete` | delete, joining lines where they meet |

A long field scrolls to follow the cursor and marks `… more above` /
`… more below`. `ctrl+v` pastes the system clipboard
(`xclip`, `wl-paste`, `xsel`, `pbpaste`, or PowerShell on Windows);
`ctrl+shift+c` copies the highlighted row of a list. While a field is open the
mouse is handed back to the terminal, so you can select and copy text normally
— `ctrl+x m` toggles that everywhere.

## Your data

Everything lives inside a **project**, and every value is stored under that
project's own key: theme, objective, panel name, deadline, hours, machines,
categories, repository and the current/next slots. Nothing you do in one
project affects another.

Data sits in `data/` beside the copy you are running — the unzipped folder
when you run from it, the installed copy (`~/.local/share/tdash/app/data`, or
`%LOCALAPPDATA%\tdash\app\data`) when you installed — as plain JSON you can
read, back up and edit:

| file | holds |
| --- | --- |
| `projects.json` | the project list, the active one, and each project's name, theme, objective and summary settings |
| `machines.json` | each project's machines, its categories, and the current/next slots |
| `repository.json` | each project's repository entries |
| `progress.json` | each project's hours, deadline and panel name |

These files hold your notes, so they are kept to their owner: `data/` is
`0700` and every file inside it is `0600` where the filesystem supports it.
Nothing in a data file is taken as instructions by the terminal: control
characters are dropped as files are read, and text is always drawn as typed.

**Nothing is lost.** Writes are atomic (a temporary file renamed into place),
the previous version of each file is kept in `data/backups` (the newest ten
per file), and an unreadable file is restored from the newest good backup at
start-up, telling you it did so. Undo/redo live in memory only.

**Starting over:** empty the `data/` folder. The next run creates fresh files
and, finding no projects, seeds the demo project again.

### Environment variables

| variable | effect |
| --- | --- |
| `TDASH_DATA` | keep data somewhere else (for a read-only install) |
| `TDASH_TODAY` | pin today's date (`YYYY-MM-DD`), used by the Summary |

```sh
TDASH_DATA=~/.local/share/tdash ./tdash
```

## Command line

Everyday actions work without the interface:

```sh
tdash dashboard                                   # print the dashboard once
tdash projects                                    # list projects
tdash use "My Lab"                                # switch project
tdash machine add "Box 1" --notes "found the way in"
tdash machine mark "Box 1"                        # also: unmark, remove
tdash repository add Kerberos --details "tickets, delegation"
tdash hours 2                                     # negative subtracts
tdash themes teal
tdash help
```

## Tests

```sh
python3 test_app.py
```

Runs against a temporary data directory, never your real progress.

## Moving to another machine

Take your `data/` folder — from the unzipped folder or from the installed
copy. On the new machine: unzip tdash, run `python setup.py` and
`python install.py`, then copy your `data/` over the new copy's `data/`
(`…/tdash/app/data` if you installed). There are no absolute paths and no
state kept anywhere else; your data is JSON.

## Windows

Everything above works in Windows Terminal or the built-in console (`cmd.exe`)
on Windows 10 1809+ and Windows 11. From a fresh machine, in `cmd.exe`:

```cmd
winget install -e --id Python.Python.3.13
```

Or install Python from python.org and tick **Add python.exe to PATH** in the
installer. Open a new terminal so `python` is picked up, then:

```cmd
cd <the folder you unzipped>
python setup.py
python install.py
```

Open another new terminal and run `tdash`. `install.py` puts the launcher in
`%LOCALAPPDATA%\tdash\bin` and adds that folder to your PATH by itself, so no
admin rights and no System Properties walk are needed. If a brand-new terminal
still cannot find `tdash`, sign out and back in once — Windows caches the
environment — or run `%LOCALAPPDATA%\tdash\bin\tdash.cmd` directly.

If `python` opens the Microsoft Store or is not found after installing, the
Store's *App execution aliases* are in the way: switch the `python.exe`
aliases off under **Settings → Apps → Advanced app settings → App execution
aliases**.

The folder you unzipped can be deleted afterwards; the app runs from
`%LOCALAPPDATA%\tdash\app` and keeps its data in `%LOCALAPPDATA%\tdash\app\data`.

## License

MIT — see `LICENSE`. The repository ships no study data: `data/` is created on
first run, and is ignored by git.
