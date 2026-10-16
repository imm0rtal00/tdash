# What the parts of tdash are called

A glossary for talking about the app — in issues, in conversation, in code
comments — so a screen can be named without describing it.

## "The dashboard area" — also "the first panel"

The upper part of the screen: the **Status** panel (objective, current, next,
days left), the **Stats** panel (project, hours, deadline, theme) and the
full-width panel headed **Topics** or **Machines** (the name is a per-project
setting, shown in the menu as `[2]` and in the sub-menu as
`Panel (Topics)` / `Panel (Machines)`).

- Code: `ui.dashboard_body()` builds it, `ui.build_layout()` puts the menu
  under it.
- It shrinks rather than scrolls: the Status and Stats detail is dropped on
  short terminals, keeping the progress bar, then the menu is shown alone.

## "The Menu" — also "the second panel"

The bordered box under the dashboard area with the numbered options:

```
[1] Project     [4] Settings    [0] Quit
[2] Topics      [5] Help
[3] Repository  [6] Summary
```

- Code: `ui.menu_panel()`, the options in `ui.MENU_ITEMS`.
- `↑`/`↓` read down a column and continue into the next, wrapping round at the
  ends; `←`/`→` jump between columns on the same row. Numbers run their option.

## "The sub-menu"

The panel that opens when you pick something from the Menu. Its rows are the
sub-menu options: opening `Project` gives `Switch / Create / Rename / Delete`,
opening `[2]` gives `View / Categories / Panel`.

- Code: `dashboard.submenu()`.
- Shows **five** rows before it scrolls. Numbers jump without running.

## "The list" / "the picker"

A list of actual items: the machines under `[2]` > `View`, the repository
entries, the projects, the themes.

- Code: `dashboard.pick()` on top of `tui.inline_list`.
- Five rows at a time, scrolled with the arrows, the wheel or
  `page up`/`page down`. Group headings count as rows.

## "A screen"

Anything that takes the whole lower area and is read rather than picked from:
a machine's page (`dashboard.machine_view`), the Summary
(`dashboard.show_summary`), Summary Settings (`dashboard.summary_settings`),
a repository entry (`dashboard.repository_read`), the Help text
(`dashboard.action_help`, drawn as a note).

## Saying things unambiguously

| If they say | they mean | code |
| --- | --- | --- |
| "the dashboard area" / "first panel" | Status, Stats, the progress panel | `ui.dashboard_body`, `ui.build_layout` |
| "the menu" / "second panel" | the numbered options box | `ui.menu_panel`, `ui.MENU_ITEMS` |
| "the sub-menu" | what opens from a menu option | `dashboard.submenu` |
| "the list" / "the picker" | a list of real items | `tui.inline_list`, `dashboard.pick` |
| "a screen" | a read-only full view | `dashboard.machine_view`, `show_summary`, `summary_settings`, `repository_read` |
| "an entry" | one repository record | `store.repository_items` |
| "a machine" / "a box" | one item in the study track | `store.machines` |
| "a category" | a project-defined field machines can show | `store.project_categories` |
| "the demo" | the example project of the first run | `store._seed_demo` |
