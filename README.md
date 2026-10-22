# tdash — a terminal study dashboard

A small terminal app for tracking what you are studying: which box you are on,
what is next, what you finished, and how far through the material you are.
Built for study tracks — labs, boxes, exercises — where the material is a list
of machines you mark off as you get through them.

Runs on Linux, macOS and Windows. Plain Python, `rich` for the interface, JSON
for storage. One dependency.

## Requirements

- A terminal 80×24 or larger. The interface uses colours and box-drawing
  characters; smaller terminals adapt rather than break. On Windows use
  Windows Terminal or the built-in console (Windows 10 1809+ or Windows 11) —
  an older console gets a message instead of a broken screen.
- Python 3.8+. Written and tested against 3.13 on Linux and Windows.
- `rich`, the single dependency. `setup.py` installs it into a `.venv` for you.

## Install

Unzip the folder anywhere, run the two commands for your platform, then
`tdash` works from any directory. **The folder you unzipped can be deleted
afterwards.**

### Linux and macOS

```sh
cd <the folder you unzipped>
python setup.py      # once: creates .venv/ and installs rich
python install.py    # installs the app and the tdash command
```

If `python` is not found but `python3` is, use that instead.

Open a new terminal (shells only read PATH at start), then:

```sh
tdash
```

`install.py` copies the program to `~/.local/share/tdash/app` (or
`$XDG_DATA_HOME/tdash/app`) with your data in `app/data`, and writes a real
launcher file to `~/.local/bin/tdash` — not a symlink, so it survives zipping
and copying. Add `~/.local/bin` to your PATH if `tdash` is not found; most
distributions already have it.

### Windows

Native — no WSL or Docker. In Windows Terminal or `cmd.exe`, install Python
if you do not have it:

```cmd
winget install -e --id Python.Python.3.13
```

Or install from python.org and tick **Add python.exe to PATH**. Open a new
terminal so `python` is picked up, then:

```cmd
cd <the folder you unzipped>
python setup.py
python install.py
```

`install.py` copies the app to `%LOCALAPPDATA%\tdash\app` (data in `app\data`)
and adds `%LOCALAPPDATA%\tdash\bin` to your user PATH by itself — no admin
rights, no System Properties walk. Open another new terminal and run:

```cmd
tdash
```

If a brand-new terminal still cannot find `tdash`, sign out and back in once
(Windows caches the environment) or run `%LOCALAPPDATA%\tdash\bin\tdash.cmd`
directly. If `python` opens the Microsoft Store or is not found after
installing, switch off the Store's *App execution aliases* under
**Settings → Apps → Advanced app settings → App execution aliases**.

### Upgrading

Run `python install.py` from a newer copy: the installed virtualenv and your
data are kept. `setup.py` is only needed the first time.

### Running without installing

```sh
./tdash              # Linux, macOS, WSL
python tdash.py      # any platform, including Windows
```

This runs the copy in the folder, with its own `data/` beside it — handy for a
look around before installing.

## First run: the demo project

The first run creates **Demo Project**, an example with every screen filled
in: a group per platform, one box already finished — dated today, so the
Summary opens on a win — one category answered for a single machine only
(marked `*`), twelve hours on the clock with a deadline six weeks out, and a
repository with entries under two headings. Its first machine, `Start Here`,
is a short tour.

Make it yours: `[1] Project` > `Create` to make a project of your own (it is
created and switched to), then `[1] Project` > `Delete` to remove
`Demo Project`. A project cannot be deleted while it is the last one, so
create yours first.

## Using tdash

The top of the screen is the **dashboard**: the project's objective, current
and next machine, days left to your deadline, study hours, and a **Topics**
(or **Machines**) progress panel with a bar, a percentage and how many are
done. Below it is the **menu**:

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

`↑↓` read down a column and continue into the next, `←→` jump between
columns, and an option's number runs it directly.

| entry | what it does |
| --- | --- |
| `[1] Project` | switch, create, rename, delete projects; each shows `[done/total]` or `[empty]` |
| `[2] Topics` | view, add, edit, delete machines; categories; panel name |
| `[3] Repository` | the project's reference list — commands, snippets, links |
| `[4] Settings` | objective, current, next, hours, deadline, themes, reset |
| `[5] Help` | the full key list, in the app, paged on short terminals |
| `[6] Summary` | everything finished; edit notes, unmark, choose columns |
| `[0] Quit` | leave (also `ctrl+x q` or `Ctrl+C`) |

**Topics list** — `↑`/`↓` move, `↵` opens a machine to read (one page per
category), `m` marks it finished or unmarks it, `a` add, `e` edit, `d` delete
(asks first), `c` choose its categories, `Esc` back. Marking is one key on the
highlighted row, and reading a machine cannot complete it. A category answered
for one machine only is marked `*`.

**Adding and editing** — `a`/`e` ask Name, then Description, Notes and Group
(all optional except the name). Multi-line fields open full screen: `↵` adds
a line, `ctrl+s` saves, `Esc` cancels. **Categories** (`[2]` > `Categories`)
defines a project's fields once — create, rename, default, group, delete — and
every machine can override the default for itself. **Groups** organize
machines, categories and repository entries into named sections; they are
optional.

**Repository** — `↵` reads, `a`/`e`/`d` add, edit, delete; `e` also edits
while reading.

**Settings** — every entry is one press away from its change:

| entry | does |
| --- | --- |
| Objective / Current / Next | what the dashboard shows |
| Hours | study hours so far |
| Deadline | the date the days-left counter counts to |
| Themes | 21 colour themes; `teal` is the default |
| Reset | clears the project's progress and hours (asks first) |

**Summary** — the record of what you finished: total, done and completed-today
counts, then finished machines with status, date and notes (on a day with none
it shows your most recent wins instead). Editable in place: `↵` edits notes,
`x` unmarks. **Summary Settings** toggles the panel column, the categories and
the status wording (`Done` / `pwned`); the cursor never stops on the
always-shown Status, Date and Notes.

**Keys everywhere** — `ctrl+x u` undo, `ctrl+x r` redo (session only),
`ctrl+x q` quit, `ctrl+x m` mouse tracking on/off, `Esc` back,
`page up`/`page down`/wheel scroll, `home`/`end` jump. Confirmations ask
`Delete <name>?` and take **`Y`** or `n`; `↵` cancels, and lowercase `y` is
not accepted, so a stray key cannot destroy anything.

**Editing text** — multi-line fields open full screen: `↵` new line,
`ctrl+s` save, `Esc` cancel; `ctrl+u` / `ctrl+k` cut to the start / end of the
line, `ctrl+a` select all, `ctrl+v` paste, `ctrl+shift+c` copy the highlighted
row. While a field is open the mouse goes back to the terminal for normal
selection. The full key list is always in `[5] Help`.

## Your data

Everything belongs to a **project**: theme, objective, panel name, deadline,
hours, machines, categories, repository and the current/next slots. Nothing
you do in one project affects another.

Data lives in `data/` beside the copy you are running — the unzipped folder
when running from it, or the installed copy (`~/.local/share/tdash/app/data`
on Linux and macOS, `%LOCALAPPDATA%\tdash\app\data` on Windows) — as plain
JSON you can read, back up and edit:

| file | holds |
| --- | --- |
| `projects.json` | project list, the active project, names, themes, objectives, summary settings |
| `machines.json` | machines, categories, current/next slots |
| `repository.json` | repository entries |
| `progress.json` | hours, deadline, panel name |

The folder is kept `0700` and its files `0600` where the filesystem supports
it. Writes are atomic, the previous version of each file is kept in
`data/backups` (the newest ten per file), and an unreadable file is restored
from the newest good backup at start-up. **Starting over:** empty `data/` —
the next run creates fresh files and seeds the demo again.

| variable | effect |
| --- | --- |
| `TDASH_DATA` | keep data somewhere else (e.g. a read-only install) |
| `TDASH_TODAY` | pin today's date (`YYYY-MM-DD`) for the Summary |

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

## Moving to another machine

Take your `data/` folder from the unzipped folder or the installed copy. On
the new machine, install tdash, then copy `data/` into the installed app
(`…/tdash/app/data`; on Windows `%LOCALAPPDATA%\tdash\app\data`). There are no
absolute paths and no other state — your data is JSON.

## Tests

```sh
python3 test_app.py
```

Runs against a temporary data directory, never your real progress.

## License

MIT — see `LICENSE`. The public repository ships no study data: `data/` is
created on first run and ignored by git.
