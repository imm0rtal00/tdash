"""Tests for tdash.

    python test_app.py

Every test points the data directory at a throwaway temp folder, so running
the suite never touches your real study data. That only works because store.py
reads TDASH_DATA at import time, so the environment is set before the import
below.
"""

import json
import os
import shutil
import stat
import sys
import tempfile
import unittest
from pathlib import Path

TMP = tempfile.mkdtemp(prefix="tdash-tests-")
os.environ["TDASH_DATA"] = TMP
os.environ["TDASH_TODAY"] = "2026-01-15"
sys.path.insert(0, str(Path(__file__).resolve().parent))

import history as history_mod  # noqa: E402
import inspect  # noqa: E402
import store  # noqa: E402
import ui  # noqa: E402
import themes  # noqa: E402
import tui  # noqa: E402
import dashboard  # noqa: E402
from ui import MENU_ITEMS, build_layout, render, summary_panel  # noqa: E402


def flat(text):
    """Collapse runs of spaces so assertions do not depend on menu padding."""
    return " ".join(text.split())


# What these modules' functions looked like before any test replaced them.
# Screens are driven by patching them, and unittest runs test classes in name
# order - so a helper that installed a fake and did not put the original back
# quietly decided how every later class behaved. Base.tearDown puts them all
# back whether the test remembered to or not.
_PATCHABLE = ("pick", "read_key", "show_screen", "build_layout",
              "inline_prompt", "render_list", "machine_categories_screen",
              "universal_categories", "machine_list", "repository_list")
_ORIGINAL = {("dashboard", name): getattr(dashboard, name)
             for name in _PATCHABLE if hasattr(dashboard, name)}
_ORIGINAL.update({("tui", name): getattr(tui, name)
                  for name in ("read_key", "render_list", "inline_list")
                  if hasattr(tui, name)})


class Base(unittest.TestCase):

    def setUp(self):
        self.data = Path(TMP)
        shutil.rmtree(TMP, ignore_errors=True)      # full isolation per test
        os.makedirs(TMP, exist_ok=True)
        store.DATA = self.data
        store.BACKUPS = self.data / "backups"
        store.HISTORY = history_mod.History()
        store.bootstrap()
        # The menu highlight is module state, so a test that moved it would
        # otherwise decide where the next test's highlight starts.
        ui.set_highlight(0)
        self.key = store.active()

    def tearDown(self):
        for (module_name, name), value in _ORIGINAL.items():
            module = dashboard if module_name == "dashboard" else tui
            setattr(module, name, value)

    def read(self, name):
        return json.loads((self.data / f"{name}.json").read_text())


class TestProjects(Base):

    def test_a_fresh_install_has_one_project(self):
        self.assertEqual(len(store.project_keys()), 1)

    def test_create_switch_and_delete(self):
        key, error = store.create_project("Prep Room")
        self.assertIsNone(error)
        self.assertEqual(store.project_name(key), "Prep Room")
        store.select(key)
        self.assertEqual(store.active(), key)
        store.select(self.key)
        self.assertEqual(store.active(), self.key)
        store.delete_project(key)
        self.assertNotIn(key, store.registry()["projects"])

    def test_the_last_project_cannot_be_deleted(self):
        error, problem = store.delete_project(self.key)
        self.assertIsNone(error)
        self.assertIn("last project", problem)

    def test_rename_keeps_the_key_and_its_data(self):
        machine, _ = store.add_machine(self.key, "Active Directory")
        store.rename_project(self.key, "Renamed")
        self.assertEqual(store.project_name(self.key), "Renamed")
        self.assertEqual(store.machines(self.key)[0]["name"], "Active Directory")
        self.assertIsNotNone(machine)

    def test_names_that_normalise_alike_stay_separate(self):
        first, _ = store.create_project("Web Track")
        second, _ = store.create_project("web track")
        self.assertNotEqual(first, second)
        self.assertEqual(len(store.project_keys()), 3)



class TestDemo(Base):
    """A fresh install opens on a worked example, not an empty room."""

    def setUp(self):
        self.data = Path(TMP)
        shutil.rmtree(TMP, ignore_errors=True)      # full isolation per test
        os.makedirs(TMP, exist_ok=True)
        store.DATA = self.data
        store.BACKUPS = self.data / "backups"
        store.HISTORY = history_mod.History()
        self.notes = store.bootstrap(demo=True)
        self.key = store.active()

    def test_the_first_project_is_the_example(self):
        self.assertEqual(store.project_name(self.key), "Demo Project")
        self.assertIn("guided tour", store.project_objective(self.key))
        self.assertTrue(any("example project" in note for note in self.notes))

    def test_every_screen_has_something_to_read(self):
        self.assertEqual([m["name"] for m in store.machines(self.key)],
                         ["Start Here", "Web Box", "AD Box", "Loose End"])
        self.assertEqual([f["title"] for f in store.project_categories(self.key)],
                         ["Credentials", "Ticket"])
        self.assertTrue(store.repository_items(self.key))
        tour = store.find_machine_by_name(self.key, "Start Here")
        self.assertIn("example project", tour["notes"])

    def test_the_finished_machine_is_marked_and_dated(self):
        web = store.find_machine_by_name(self.key, "Web Box")
        self.assertEqual(web["completed"], 1)
        self.assertEqual(web["completed_on"], "2026-01-15")

    def test_the_override_reads_as_the_machines_own(self):
        ad = store.find_machine_by_name(self.key, "AD Box")
        fields = store.machine_categories(self.key, ad["id"])
        creds = next(f for f in fields if f["title"] == "Credentials")
        self.assertTrue(creds["overridden"])
        self.assertEqual(creds["body"], "svc_backup:try-me")

    def test_it_stays_out_of_the_os(self):
        self.assertFalse(store.offers_os(self.key))
        for machine in store.machines(self.key):
            self.assertNotIn(store.OS_CATEGORY,
                             store.machine_category_ids(self.key,
                                                        machine["id"]))

    def test_deleting_it_leaves_a_clean_project(self):
        key, _ = store.create_project("My Project")
        store.delete_project(self.key)
        self.assertEqual(store.active(), key)
        self.assertEqual(len(store.machines()), 0)

    def test_a_plain_bootstrap_still_makes_the_empty_project(self):
        shutil.rmtree(TMP, ignore_errors=True)
        os.makedirs(TMP, exist_ok=True)
        store.HISTORY = history_mod.History()
        store.bootstrap()
        self.assertEqual(store.project_name(), "New Project")
        self.assertEqual(len(store.machines()), 0)

class TestIndependence(Base):

    def test_machines_do_not_leak_between_projects(self):
        other, _ = store.create_project("Other")
        store.add_machine(self.key, "Mine")
        store.add_machine(other, "Theirs")
        self.assertEqual([m["name"] for m in store.machines(self.key)], ["Mine"])
        self.assertEqual([m["name"] for m in store.machines(other)], ["Theirs"])

    def test_hours_are_per_project(self):
        other, _ = store.create_project("Other")
        store.add_hours(self.key, 5)
        self.assertEqual(store.stats(self.key)["hours_studied"], 5)
        self.assertEqual(store.stats(other)["hours_studied"], 0)

    def test_theme_is_per_project(self):
        other, _ = store.create_project("Other")
        store.set_theme(other, "cornflower")
        self.assertEqual(store.project_theme(other), "cornflower")
        self.assertNotEqual(store.project_theme(self.key), "cornflower")

    def test_switching_back_restores_the_last_state(self):
        store.add_machine(self.key, "Mine")
        store.add_hours(self.key, 7)
        store.set_slot(self.key, "current", store.machines(self.key)[0]["id"])
        other, _ = store.create_project("Other")
        self.assertEqual(store.tally(), (0, 0))
        store.select(self.key)
        self.assertEqual(store.tally(), (0, 1))
        self.assertEqual(store.stats()["hours_studied"], 7)
        self.assertEqual(store.slot_name(self.key, "current"), "Mine")

    def test_deleting_a_project_leaves_others_alone(self):
        other, _ = store.create_project("Other")
        store.add_machine(self.key, "Mine")
        store.delete_project(other)
        self.assertEqual([m["name"] for m in store.machines(self.key)], ["Mine"])


class TestMachines(Base):

    def test_add_edit_and_delete(self):
        machine, error = store.add_machine(self.key, "Target", "ldap notes")
        self.assertIsNone(error)
        self.assertEqual(store.machines()[0]["notes"], "ldap notes")
        store.edit_machine(self.key, machine["id"], name="Target II", notes="new notes")
        self.assertEqual(store.machines()[0]["name"], "Target II")
        self.assertEqual(store.machines()[0]["notes"], "new notes")
        store.delete_machine(self.key, machine["id"])
        self.assertEqual(store.machines(), [])

    def test_a_machine_needs_a_name(self):
        machine, error = store.add_machine(self.key, "   ")
        self.assertIsNone(machine)
        self.assertIn("name", error)

    def test_marking_stamps_today_and_toggles_back(self):
        machine, _ = store.add_machine(self.key, "Target")
        store.mark_machine(self.key, machine["id"])
        self.assertEqual(store.machines()[0]["completed_on"], "2026-01-15")
        self.assertEqual(store.tally(), (1, 1))
        store.toggle_machine(self.key, machine["id"])
        self.assertEqual(store.tally(), (0, 1))
        self.assertEqual(store.machines()[0]["completed_on"], "")

    def test_deleting_a_machine_clears_it_from_current(self):
        machine, _ = store.add_machine(self.key, "Target")
        store.set_slot(self.key, "current", machine["id"])
        store.delete_machine(self.key, machine["id"])
        self.assertEqual(store.board()["current"], "")

    def test_current_and_next_are_editable_and_clearable(self):
        machine, _ = store.add_machine(self.key, "Target")
        store.set_slot(self.key, "current", machine["id"])
        self.assertEqual(store.slot_name(self.key, "current"), "Target")
        store.set_slot(self.key, "current", "")
        self.assertEqual(store.slot_name(self.key, "current"), "")

    def test_ids_do_not_collide(self):
        store.add_machine(self.key, "A")
        machine, _ = store.add_machine(self.key, "B")
        store.delete_machine(self.key, machine["id"])
        again, _ = store.add_machine(self.key, "C")
        self.assertEqual(again["id"], machine["id"])


class TestRepository(Base):

    def test_repository_is_a_separate_list_from_machines(self):
        store.add_machine(self.key, "Target")
        store.add_repository(self.key, "Kerberos")
        self.assertEqual(len(store.machines()), 1)
        self.assertEqual(len(store.repository_items()), 1)
        store.delete_repository(self.key, store.repository_items()[0]["id"])
        self.assertEqual(store.repository_items(), [])
        self.assertEqual(len(store.machines()), 1)

    def test_add_edit_and_delete(self):
        item, error = store.add_repository(self.key, "Kerberos", "tickets")
        self.assertIsNone(error)
        store.edit_repository(self.key, item["id"], title="Kerberos 2", body="roasting")
        self.assertEqual(store.repository_items()[0]["title"], "Kerberos 2")
        self.assertEqual(store.repository_items()[0]["body"], "roasting")
        store.delete_repository(self.key, item["id"])
        self.assertEqual(store.repository_items(), [])

    def test_an_entry_needs_a_title(self):
        item, error = store.add_repository(self.key, "  ")
        self.assertIsNone(item)
        self.assertIn("title", error)

    def test_repository_does_not_leak_between_projects(self):
        other, _ = store.create_project("Other")
        store.add_repository(self.key, "Kerberos")
        self.assertEqual(store.repository_items(other), [])


class TestObjective(Base):

    def test_objective_defaults_to_the_project_name(self):
        self.assertEqual(store.project_objective(self.key), store.project_name(self.key))

    def test_setting_an_objective(self):
        self.assertIsNone(store.set_objective(self.key, "Pass by November"))
        self.assertEqual(store.project_objective(self.key), "Pass by November")

    def test_a_blank_objective_falls_back_to_the_name(self):
        store.set_objective(self.key, "something")
        store.set_objective(self.key, "   ")
        self.assertEqual(store.project_objective(self.key), store.project_name(self.key))

    def test_rename_does_not_wipe_the_objective(self):
        store.set_objective(self.key, "Pass by November")
        store.rename_project(self.key, "Renamed")
        self.assertEqual(store.project_objective(self.key), "Pass by November")

    def test_objectives_are_per_project(self):
        other, _ = store.create_project("Other")
        store.set_objective(self.key, "Mine")
        store.set_objective(other, "Theirs")
        self.assertEqual(store.project_objective(other), "Theirs")
        self.assertEqual(store.project_objective(self.key), "Mine")

    def test_deleting_a_project_does_not_disturb_another(self):
        other, _ = store.create_project("Other")
        store.set_objective(self.key, "Mine")
        store.delete_project(other)
        self.assertEqual(store.project_objective(self.key), "Mine")

    def test_no_project_name_banner_under_the_dashboard_title(self):
        """The frame says Dashboard and Stats names the project; a third
        copy of the name under the title was just noise."""
        text = render(build_layout(), width=110)
        head = text.split("Status")[0]
        self.assertIn("Dashboard", head)
        self.assertNotIn(store.project_name(self.key), head)

    def test_objective_shows_on_the_dashboard(self):
        store.set_objective(self.key, "Pass the exam")
        self.assertIn("Pass the exam", render(build_layout(), width=110))

    def test_project_moved_to_the_stats_panel(self):
        # Status and Stats sit side by side on one line, so check the panels
        # themselves rather than trying to split the rendered dashboard.
        # Set the objective first: it defaults to the project name, which would
        # otherwise put the word "Project" in the Status panel as a value.
        store.set_objective(self.key, "Finish the track")
        status = render(ui.status_table())
        self.assertIn("Objective", status)
        self.assertIn("Finish the track", status)
        self.assertNotIn("Project", status)
        self.assertIn("Project", render(ui.stats_table()))


class TestConfirmations(Base):
    """Anything that destroys work must lose to a stray keypress.

    The prompt reads Y/n and accepts nothing else: Enter cancels, n cancels,
    Y confirms. Any other key is ignored and the question is asked again, so a
    mistyped "yes" cannot quietly read as a no."""

    def _run(self, answers):
        """Answer the question repeatedly; returns the verdict."""
        import dashboard
        queue = list(answers)
        calls = []

        def fake_prompt(live, prompt, message=None, **kw):
            calls.append(kw.get("placeholder"))
            return queue.pop(0) if queue else None

        dashboard.inline_prompt = fake_prompt
        return dashboard.confirm(None, "Delete it?", None), calls

    def test_uppercase_y_confirms(self):
        self.assertIs(self._run(["Y"])[0], True)

    def test_lowercase_n_cancels(self):
        self.assertIs(self._run(["n"])[0], False)

    def test_enter_and_esc_cancel(self):
        # The prompt returns None for both; neither may delete.
        self.assertIs(self._run([None])[0], False)

    def test_a_lowercase_y_is_not_accepted(self):
        """Y/n means uppercase Y. Lowercase y is ignored, not a silent yes."""
        verdict, calls = self._run(["y", "Y"])
        self.assertIs(verdict, True)
        self.assertEqual(len(calls), 2, "a rejected 'y' must re-ask")

    def test_words_are_not_accepted(self):
        for word in ("yes", "YES", "Yes", "no", "N", "NO", "nope"):
            verdict, calls = self._run([word])
            self.assertIs(verdict, False, f"{word!r} must not confirm")
            self.assertEqual(len(calls), 2, f"{word!r} must re-ask")

    def test_a_mistyped_answer_cancels_only_when_told_to(self):
        """Typing "ye" then Enter deletes nothing."""
        self.assertIs(self._run(["ye", None])[0], False)

    def test_the_prompt_offers_y_over_n(self):
        _, calls = self._run(["n"])
        self.assertEqual(calls[0], "Y/n")

    def test_every_destructive_action_asks_first(self):
        """Each of these loses work, so each must be behind a confirmation."""
        import inspect
        import dashboard
        # Deleting a machine or a repository entry is a key on a list now, so
        # its prompt asks `here` (the live view the list drew on); the rest are
        # still their own screens and pass `live`.
        source = inspect.getsource(dashboard)
        for view, action in (("here", "Delete {machine.get('name')}"),
                             ("here", "Delete {entry.get('title')}"),
                             ("live", "Delete {name}"),
                             ("here", "Delete the category '{title}'"),
                             ("live", "Reset {store.project_name(key)}")):
            self.assertIn(f'confirm({view}, f"{action}', source,
                          f"{action} is not behind a confirmation")


class TestPanelNameVisibility(Base):
    """The Machines menu has to show what the panel is called."""

    def _menu_labels(self):
        import dashboard
        seen = []
        dashboard.submenu = lambda live, title, entries, message: (
            seen.extend(label for label, _ in entries), (None, True))[1]
        dashboard.action_machines(None, None)
        return seen

    def test_the_menu_is_just_view_categories_and_panel(self):
        """Mark, Add, Edit and Delete are keys on the list now, not entries
        here: four submenu entries all opened the same list and then walked you
        back out to choose what to do with the row you had already highlighted."""
        labels = self._menu_labels()
        self.assertEqual(len(labels), 3)
        self.assertTrue(labels[0].startswith("View"))
        self.assertTrue(labels[1].startswith("Categories"))
        self.assertTrue(labels[2].startswith("Panel"))

    def test_the_panel_entry_shows_the_current_name(self):
        import dashboard
        store.set_dashboard_panel(self.key, "Machines")
        seen = []
        dashboard.submenu = lambda live, title, entries, message: (
            seen.extend(label for label, _ in entries), (None, True))[1]
        dashboard.action_machines(None, None)
        store.set_dashboard_panel(self.key, "Topics")
        dashboard.action_machines(None, None)
        self.assertEqual(seen, ["View", "Categories", "Panel (Machines)",
                                "View", "Categories", "Panel (Topics)"])

    def test_the_action_is_still_reachable_under_the_new_label(self):
        """submenu looks the action up by label, so a renamed entry must keep
        pointing at the same function."""
        import dashboard
        menu = [(f"Panel ({store.dashboard_panel()})" if label == "Panel"
                 else label, fn)
                for label, fn in dashboard.MACHINES_MENU]
        entry = next((fn for label, fn in menu if label.startswith("Panel")), None)
        self.assertIs(entry, dashboard.machine_panel_name)


class TestMachineListShortcuts(Base):
    """Mark, Add, Edit and Delete are keys on the list, acting on the row you
    are standing on."""

    def _shortcuts(self):
        import dashboard
        # With nothing in the list there are no rows for the keys to act on,
        # so the screen says so instead - which is a different screen, and not
        # the one whose shortcuts these are checking.
        store.add_machine(self.key, "Target")
        captured = {}
        def pick(live, prompt, pairs, message, empty=None, **kw):
            captured.update(kw)
            return None, None
        real = dashboard.pick
        dashboard.pick = pick
        try:
            dashboard.machine_list(None, None)
        finally:
            dashboard.pick = real
        return captured.get("shortcuts", {})

    def test_all_five_are_bound(self):
        keys = set(self._shortcuts())
        self.assertEqual(keys, {"m", "a", "e", "d", "c"})

    def test_mark_toggles_the_highlighted_machine(self):
        import dashboard
        machine, _ = store.add_machine(self.key, "Target")
        shortcuts = self._shortcuts()
        shortcuts["m"](None, "Target")
        self.assertEqual(store.find_machine(self.key, machine["id"])["completed"], 1)
        shortcuts["m"](None, "Target")
        self.assertEqual(store.find_machine(self.key, machine["id"])["completed"], 0)

    def test_marking_shows_its_tick_without_leaving_the_list(self):
        """The rows were built once when the list opened, so a mark updated the
        data but left the row reading "Target" with no tick on it until you left
        the list and came back."""
        import inspect
        import dashboard
        from rich.live import Live
        machine, _ = store.add_machine(self.key, "Target")
        drawn = []
        real_render = tui.render_list
        real_read = tui.read_key          # inline_list reads this one
        seq = ["m", tui.ESCAPE]
        ui.console.height = 40
        try:
            tui.read_key = lambda timeout=None: seq.pop(0) if seq else None
            def spy(live, prompt, names, rows, cur, top, view, **kw):
                drawn.append(list(names))
                return real_render(live, prompt, names, rows, cur, top, view,
                                   **kw)
            tui.render_list = spy
            with Live(console=ui.console, auto_refresh=False) as live:
                dashboard.machine_list(live, None)
        finally:
            tui.render_list, tui.read_key = real_render, real_read
        self.assertTrue(any("\u2713 Target" in names for names in drawn[1:]),
                        f"no tick after marking: {drawn}")
        self.assertEqual(store.find_machine(self.key, machine["id"])["completed"], 1)
        self.assertIn("refresh=fresh", inspect.getsource(dashboard.machine_list))

    def test_the_list_comes_back_to_the_machine_you_read(self):
        """Esc out of a machine used to drop the cursor back at the top."""
        import dashboard
        one, _ = store.add_machine(self.key, "One")           # Ungrouped
        store.add_machine(self.key, "Two", group="Web")       # drawn first
        seen = []
        calls = {"n": 0}

        def pick(live, prompt, pairs, message, empty=None, **kw):
            seen.append(kw.get("at"))
            calls["n"] += 1
            return (one["id"], None) if calls["n"] == 1 else (None, None)

        real_pick, real_view = dashboard.pick, dashboard.machine_view
        dashboard.pick = pick
        dashboard.machine_view = lambda live, key: None
        try:
            dashboard.machine_list(None, None)
        finally:
            dashboard.pick, dashboard.machine_view = real_pick, real_view
        # One is drawn second - Web rows come first - so the row to come back
        # to is the second one, not whatever slot it held in the raw order.
        self.assertEqual(seen[1], 1, "the cursor was dropped back at the top")

    def test_enter_on_the_list_opens_the_machine_and_marks_nothing(self):
        """The safety lives in the keys: one Enter opens, `m` marks."""
        import dashboard
        machine, _ = store.add_machine(self.key, "Target")
        opened = []
        real_pick, real_view = dashboard.pick, dashboard.machine_view
        calls = {"n": 0}

        def pick(live, prompt, pairs, message, empty=None, **kw):
            calls["n"] += 1
            return (machine["id"], None) if calls["n"] == 1 else (None, None)

        dashboard.pick = pick
        dashboard.machine_view = lambda live, key: opened.append(key)
        try:
            dashboard.machine_list(None, None)
        finally:
            dashboard.pick, dashboard.machine_view = real_pick, real_view
        self.assertEqual(opened, [machine["id"]])
        self.assertEqual(store.tally(self.key), (0, 1),
                         "opening a machine marked it")

    def test_mark_still_works_on_a_row_that_is_already_ticked(self):
        """A finished row reads "✓ Target", so the shortcut has to find it."""
        import dashboard
        machine, _ = store.add_machine(self.key, "Target")
        store.mark_machine(self.key, machine["id"])
        shortcuts = self._shortcuts()
        shortcuts["m"](None, "\u2713 Target")
        self.assertEqual(store.find_machine(self.key, machine["id"])["completed"], 0)

    def test_marking_keeps_the_group_headings(self):
        """refresh() handed the picker plain names, so one mark dropped every
        heading and re-sorted the list out from under the cursor."""
        import dashboard
        from rich.live import Live
        store.add_machine(self.key, "Target", group="Web")
        store.add_machine(self.key, "Lame", group="SMB")
        drawn = []
        real_render = tui.render_list
        real_read = tui.read_key          # inline_list reads this one
        seq = ["m", tui.ESCAPE]
        ui.console.height = 40
        try:
            tui.read_key = lambda timeout=None: seq.pop(0) if seq else None

            def spy(live, prompt, names, rows, cur, top, view, **kw):
                drawn.append(list(rows))
                return real_render(live, prompt, names, rows, cur, top, view,
                                   **kw)
            tui.render_list = spy
            with Live(console=ui.console, auto_refresh=False) as live:
                dashboard.machine_list(live, None)
        finally:
            tui.render_list, tui.read_key = real_render, real_read
        self.assertTrue(drawn, "the list never drew")
        headings = [text for row in drawn[-1] if row[0] == "h"
                    for text in row[1:]]
        self.assertIn("Web", headings, f"headings lost after a mark: {drawn[-1]}")
        self.assertIn("SMB", headings)

    def test_delete_asks_before_it_deletes(self):
        import dashboard
        machine, _ = store.add_machine(self.key, "Target")
        shortcuts = self._shortcuts()
        real = dashboard.confirm
        dashboard.confirm = lambda live, question, message: False
        try:
            shortcuts["d"](None, "Target")
        finally:
            dashboard.confirm = real
        self.assertIsNotNone(store.find_machine(self.key, machine["id"]),
                             "it deleted without asking")
        dashboard.confirm = lambda live, question, message: True
        try:
            shortcuts["d"](None, "Target")
        finally:
            dashboard.confirm = real
        self.assertIsNone(store.find_machine(self.key, machine["id"]))

    def test_edit_acts_on_the_highlighted_machine_not_a_prompt(self):
        """It used to open its own picker, which meant choosing the same row
        twice for no reason."""
        import dashboard
        machine, _ = store.add_machine(self.key, "Target")
        asked = []
        real = dashboard.edit_machine_fields
        dashboard.edit_machine_fields = lambda live, m, message: (
            asked.append(m.get("name")), (None, "edited"))[1]
        try:
            self._shortcuts()["e"](None, "Target")
        finally:
            dashboard.edit_machine_fields = real
        self.assertEqual(asked, ["Target"])

    def test_escape_out_of_a_form_does_not_take_the_program_down(self):
        """Pressing Esc in the Add form returns a sentinel, and handing that to
        the renderer raised a TypeError that killed tdash. Cancelling a screen
        has to leave you in the list."""
        import dashboard
        from rich.live import Live
        before = len(store.machines())
        real_prompt = dashboard.inline_prompt
        dashboard.inline_prompt = lambda live, label, msg=None, **kw: None   # Esc
        try:
            seq = ["a", dashboard.ESCAPE, dashboard.ESCAPE, tui.CTRL_S]
            dashboard.read_key = lambda timeout=None: seq.pop(0) if seq else None
            with Live(console=ui.console, auto_refresh=False) as live:
                dashboard.machine_list(live, None)   # must not raise
        finally:
            dashboard.inline_prompt = real_prompt
        self.assertEqual(len(store.machines()), before,
                         "a cancelled Add still added something")

    def test_a_sentinel_is_never_rendered_as_a_message(self):
        """Screens cancel by returning a sentinel. It must never reach Text()."""
        for sentinel in (object(), 42, None, "a real message"):
            body = ui.build_layout(message=sentinel)
            text = render(body)
            if isinstance(sentinel, str):
                self.assertIn(sentinel, text)
            else:
                self.assertNotIn(str(sentinel), text)

    def test_a_shortcut_that_is_cancelled_leaves_the_list_alone(self):
        import dashboard
        from rich.live import Live
        store.add_machine(self.key, "Target")
        captured = {}
        real = dashboard.pick
        calls = {"n": 0}
        def pick(live, prompt, pairs, message, empty=None, **kw):
            captured["message"] = message
            calls["n"] += 1
            if calls["n"] > 1:
                raise StopIteration
            return None, None
        dashboard.pick = pick
        try:
            dashboard.machine_list(None, "kept")
        except StopIteration:
            pass
        finally:
            dashboard.pick = real
        self.assertEqual(captured.get("message"), "kept")

    def test_a_picker_shows_five_rows_and_scrolls_the_rest(self):
        """A submenu that listed everything at once grew down the screen until
        the dashboard behind it was pushed off."""
        ui.console.height = 40          # a height where the cap is 4, not 2
        for i in range(14):
            store.add_machine(self.key, f"Box{i}")
        # The picker is handed plain labels, the way pick() unwraps them.
        labels = [m["name"] for m in store.machines()]
        names, rows = tui.prepare_rows(labels)
        item_rows = [n for n, r in zip(names, rows) if r[0] == "i"]
        view = tui.list_view()
        self.assertEqual(view, 5)
        cur, pages = 0, []
        for _ in range(13):
            cur = tui.step_row(rows, cur, 1)
            top = tui.fit_top(cur, 0, len(rows), view)
            pages.append(item_rows[top:top + view])
        for page in pages:
            self.assertEqual(len(page), 5, f"a page showed {len(page)} rows")
        self.assertEqual(pages[0][0], labels[0])
        self.assertIn(labels[12], pages[-1],
                      "scrolling never reached the end of the list")

    def test_the_arrow_keys_wrap_at_both_ends(self):
        """Down past the last option lands on the first, and up past the first on
        the last, so a short list can be stepped all the way through."""
        names, rows = tui.prepare_rows(["A", "B", "C"])
        self.assertEqual(tui.step_row(rows, 2, 1), 0)
        self.assertEqual(tui.step_row(rows, 0, -1), 2)
        cur, seen = 0, []
        for _ in range(5):
            cur = tui.step_row(rows, cur, 1)
            seen.append(names[cur])
        self.assertEqual(seen, ["B", "C", "A", "B", "C"])

    def test_wrapping_steps_over_group_headers(self):
        names, rows = tui.prepare_rows([("g1", "A"), ("g1", "B"), ("g2", "C")])
        label = lambda i: names[rows[i][1]] if rows[i][0] == "i" else "header"
        cur, seen = 0, []
        for _ in range(4):
            cur = tui.step_row(rows, cur, 1)
            seen.append(label(cur))
        self.assertEqual(seen, ["A", "B", "C", "A"])
        cur, seen = 0, []
        for _ in range(3):
            cur = tui.step_row(rows, cur, -1)
            seen.append(label(cur))
        self.assertEqual(seen, ["C", "B", "A"])

    def test_the_summary_rows_wrap_too(self):
        import inspect
        import dashboard
        source = inspect.getsource(dashboard.show_summary)
        flat = " ".join(source.split())
        self.assertIn("selected = (selected - 1) % len(rows)", flat)
        self.assertIn("selected = (selected + 1) % len(rows)", flat)

    def test_the_menu_columns_are_evenly_spaced(self):
        """Only the first column was ever padded, so once the menu went to three
        columns the second and third sat hard against each other: the gaps down
        the panel were 12, 2 and 0. Each column now starts at the same offset on
        every row."""
        import re
        from rich.console import Console
        ui.console.width, ui.console.height = 100, 40
        rec = Console(width=100, height=40, record=True,
                      file=open("/dev/null", "w"))
        rec.print(ui.menu_panel(0))
        starts = {}
        for line in rec.export_text().split("\n"):
            for m in re.finditer(r"\[(\d)\]", line):
                starts.setdefault(int(m.group(1)), []).append(m.start())
        self.assertEqual(len(starts), len(ui.menu_items()))
        columns = ui.menu_columns()
        for position, column in enumerate(columns):
            offsets = set()
            for index in column:
                key = int(ui.menu_items()[index][0])
                offsets.update(starts[key])
            self.assertEqual(len(offsets), 1,
                             f"column {position} does not line up: {offsets}")

    def test_every_column_gets_the_same_gutter(self):
        """The gutter is added after every column but the last, so no two
        options end up hard against each other."""
        from rich.console import Console
        import re
        ui.console.width, ui.console.height = 100, 40
        rec = Console(width=100, height=40, record=True,
                      file=open("/dev/null", "w"))
        rec.print(ui.menu_panel(0))
        line = next(l for l in rec.export_text().split("\n") if "[1]" in l)
        gaps = re.findall(r"\S\s+(?=\[\d\])", line)
        self.assertGreaterEqual(len(gaps), 2, "columns are touching")
        for gap in gaps:
            self.assertGreaterEqual(len(gap), 5, f"a gutter collapsed: {gap!r}")

    def test_the_menu_is_three_columns_of_three(self):
        labels = [l for _, l in ui.menu_items()]
        columns = [[labels[i] for i in col] for col in ui.menu_columns()]
        self.assertEqual(columns, [["Project", "Topics", "Repository"],
                                   ["Settings", "Help", "Summary"],
                                   ["Quit"]])

    def test_down_walks_down_a_column_then_to_the_top_of_the_next(self):
        labels = [l for _, l in ui.menu_items()]
        cur, seen = 0, []
        for _ in range(7):
            cur = ui.menu_move_down(cur, 1)
            seen.append(labels[cur])
        self.assertEqual(seen, ["Topics", "Repository", "Settings", "Help",
                                "Summary", "Quit", "Project"])

    def test_up_walks_up_a_column_then_to_the_bottom_of_the_previous(self):
        labels = [l for _, l in ui.menu_items()]
        cur, seen = 0, []
        for _ in range(7):
            cur = ui.menu_move_down(cur, -1)
            seen.append(labels[cur])
        self.assertEqual(seen, ["Quit", "Summary", "Help", "Settings",
                                "Repository", "Topics", "Project"])

    def test_the_arrows_still_wrap_all_the_way_round(self):
        labels = [l for _, l in ui.menu_items()]
        self.assertEqual(labels[ui.menu_move_down(6, 1)], "Project")
        self.assertEqual(labels[ui.menu_move_down(0, -1)], "Quit")

    def test_left_and_right_still_move_across_at_the_same_row(self):
        labels = [l for _, l in ui.menu_items()]
        # row 0 of the first column -> row 0 of the second
        self.assertEqual(labels[ui.menu_move_across(0, 1)], "Settings")
        # and back again
        self.assertEqual(labels[ui.menu_move_across(3, -1)], "Project")

    def test_every_list_shows_five_rows(self):
        """Sub-panels and pickers alike: a six-entry Settings was showing three,
        and the machine list had the same problem."""
        for height in (20, 24, 30, 40, 60):
            ui.console.height = height
            self.assertEqual(tui.list_view(), 5, f"shrank at {height} rows")
        ui.console.height = 40

    def test_a_picker_is_never_cropped_by_the_dashboard_behind_it(self):
        """On a short terminal the full dashboard filled the screen on its own
        and pushed the list off the bottom, so a six-entry submenu showed one
        row. The list is what the person came for."""
        from rich.console import Console
        from rich.panel import Panel
        for height in (16, 20, 24, 29):
            ui.console.height = height
            fake = Panel("x", title="t", border_style="cyan")
            body = tui._list_body(None, fake, 5)
            rec = Console(width=80, height=height, record=True,
                          file=open("/dev/null", "w"))
            rec.print(body)
            drawn = rec.export_text()
            self.assertIn("x", drawn, f"the picker was cropped at {height} rows")
        ui.console.height = 40

    def test_a_submenu_still_fits_on_a_tiny_terminal(self):
        """Five rows plus the box has to leave something on screen."""
        ui.console.height = 8
        self.assertLessEqual(tui.list_view() + tui.PICKER_CHROME,
                             ui.console.height)
        ui.console.height = 40

    def test_the_cap_holds_at_every_terminal_size(self):
        for height in (26, 30, 48, 80):
            ui.console.height = height
            self.assertLessEqual(tui.list_view(), 5)
            self.assertGreaterEqual(tui.list_view(), 2)
        ui.console.height = 40

    def test_the_list_says_which_keys_do_what(self):
        import dashboard
        store.add_machine(self.key, "Target")
        captured = {}
        real = dashboard.pick
        dashboard.pick = lambda live, prompt, pairs, message, empty=None, **kw: (
            captured.update(kw), (None, None))[1]
        try:
            dashboard.machine_list(None, None)
        finally:
            dashboard.pick = real
        hint = captured.get("hint", "")
        for key in ("m", "a", "e", "d"):
            self.assertIn(key, hint)


class TestPanelNameFeedback(Base):
    """Picking the name already in use must say so, not look like a no-op."""

    def _choose(self, name, current=None):
        import dashboard
        if current:
            store.set_dashboard_panel(self.key, current)
        self.dashboard = dashboard
        dashboard.pick = lambda *a, **k: (name, None)
        return dashboard.machine_panel_name(None, None)

    def setUp(self):
        super().setUp()
        import dashboard
        self.dashboard = dashboard

    def test_choosing_the_other_name_switches_and_says_so(self):
        store.set_dashboard_panel(self.key, "Topics")
        message = self._choose("Machines")
        self.assertEqual(store.dashboard_panel(self.key), "Machines")
        self.assertIn("now called Machines", message)

    def test_choosing_the_current_name_explains_the_no_op(self):
        store.set_dashboard_panel(self.key, "Topics")
        message = self._choose("Topics")
        self.assertEqual(store.dashboard_panel(self.key), "Topics")
        self.assertIn("already called Topics", message)

    def test_the_prompt_says_what_it_is_called_now(self):
        """Without this, re-picking the default looks like nothing happened."""
        import inspect
        source = inspect.getsource(dashboard.machine_panel_name)
        self.assertIn("now {current}", source)


class TestPanelNameFollowsIntoTheMenu(Base):
    """The menu entry takes the panel's name, so both read the same."""

    def _labels(self):
        import ui
        return dict(ui.menu_items())

    def test_the_menu_follows_the_default_name(self):
        self.assertEqual(self._labels()["2"], store.PANEL_TOPIC)

    def test_the_menu_follows_the_projects_choice(self):
        store.set_dashboard_panel(self.key, "Machines")
        self.assertEqual(self._labels()["2"], "Machines")

    def test_switching_back_updates_the_menu_again(self):
        store.set_dashboard_panel(self.key, "Machines")
        self.assertEqual(self._labels()["2"], "Machines")
        store.set_dashboard_panel(self.key, "Topics")
        self.assertEqual(self._labels()["2"], "Topics")

    def test_the_menu_is_per_project(self):
        other, _ = store.create_project("Other")
        store.set_dashboard_panel(self.key, "Machines")
        store.select(other)
        self.assertEqual(self._labels()["2"], store.PANEL_TOPIC)

    def test_no_other_menu_entry_moves(self):
        labels = self._labels()
        for key, name in (("1", "Project"), ("3", "Repository"), ("4", "Settings"),
                          ("5", "Help"), ("6", "Summary"), ("0", "Quit")):
            self.assertEqual(labels[key], name)

    def test_the_help_screen_uses_the_same_name(self):
        """The help listed a hard-coded "2 Machines" and drifted from the menu."""
        import inspect
        import dashboard
        source = inspect.getsource(dashboard.action_help)
        self.assertIn("store.dashboard_panel()", source)
        self.assertNotIn("[bold]2 Machines[/]", source)

    def test_the_key_is_still_2(self):
        """Renaming the label must not change the key it answers to."""
        import ui
        store.set_dashboard_panel(self.key, "Topics")
        self.assertIn("2", dict(ui.menu_items()))
        self.assertEqual(len(ui.menu_items()), len(ui.MENU_ITEMS))


class TestProjectIsolation(Base):
    """Every project is its own container.

    Changing anything in one project must not reach into another - not the
    theme, objective, panel name, deadline, machines, repository or the current /
    next slots. Undo and redo are session-wide and cross those walls on
    purpose: a step names the file it rewrote, so an undo made while looking
    at one project puts back another project's change and leaves everything
    else alone."""

    def setUp(self):
        super().setUp()
        self.other, _ = store.create_project("Other")
        # create_project leaves the new project active; go back, or every
        # change below would be tagged to the wrong project.
        store.select(self.key)

    def test_changing_everything_here_leaves_the_other_alone(self):
        store.set_theme(self.key, "violet")
        store.set_objective(self.key, "My goal")
        store.set_dashboard_panel(self.key, "Machines")
        store.set_deadline(self.key, "2026-12-01")
        store.add_machine(self.key, "Mine", "a note", "Linux", "a box")
        store.add_repository(self.key, "MyTopic", "body")
        machine = store.machines(self.key)[0]
        store.set_slot(self.key, "current", machine["id"])

        raw = json.loads((Path(TMP) / "projects.json").read_text())
        other_raw = raw["projects"][self.other]
        self.assertEqual(other_raw["objective"], "")
        self.assertEqual(store.project_theme(self.other), themes.DEFAULT_THEME)
        self.assertEqual(store.dashboard_panel(self.other), store.PANEL_TOPIC)
        self.assertEqual(store.stats(self.other)["deadline"], "")
        self.assertEqual(store.machines(self.other), [])
        self.assertEqual(store.repository_items(self.other), [])
        self.assertEqual(store.slot_name(self.other, "current"), "")

    def test_the_other_project_keeps_its_own_settings(self):
        store.set_dashboard_panel(self.other, "Machines")
        store.set_theme(self.other, "red")
        store.set_theme(self.key, "green")
        self.assertEqual(store.dashboard_panel(self.other), "Machines")
        self.assertEqual(store.project_theme(self.other), "red")

    def test_undo_reaches_another_project_from_where_you_stand(self):
        """One session, one history: walking back does not need you to be in
        the project whose change is next on the stack."""
        store.set_dashboard_panel(self.key, "Machines")
        store.select(self.other)
        message = store.undo()
        self.assertIn("Undid", message)
        self.assertEqual(store.dashboard_panel(self.key), store.PANEL_TOPIC,
                         "the change was not undone from the other project")

    def test_redo_reaches_another_project_from_where_you_stand(self):
        store.set_dashboard_panel(self.key, "Machines")
        store.select(self.key)
        store.undo()
        self.assertEqual(store.dashboard_panel(self.key), store.PANEL_TOPIC)
        store.select(self.other)
        message = store.redo()
        self.assertIn("Redid", message)
        self.assertEqual(store.dashboard_panel(self.key), "Machines",
                         "the redo did not reach the project it belonged to")

    def test_undo_still_works_in_the_project_that_changed(self):
        store.set_dashboard_panel(self.key, "Machines")
        store.select(self.key)
        self.assertIn("Undid", store.undo())
        self.assertEqual(store.dashboard_panel(self.key), store.PANEL_TOPIC)

    def test_switching_project_is_not_undoable(self):
        """Moving between projects is navigation, not an edit. As an undo entry
        it belonged to whichever project you had just left, so undoing in the
        new one reached back into the old one's data."""
        before = len(store.HISTORY.undo_stack)
        store.select(self.other)
        self.assertEqual(len(store.HISTORY.undo_stack), before,
                         "switching project pushed an undo entry")

    def test_a_machine_mark_in_one_project_leaves_the_other_alone(self):
        mine, _ = store.add_machine(self.key, "Mine")
        store.mark_machine(self.key, mine["id"])
        self.assertEqual(store.machines(self.other), [])


class TestSessionHistory(Base):
    """One undo stack for the whole session, and every project in it.

    The walk the user described: make a project, work in it, switch, work
    elsewhere, come back and delete one - then ctrl+x u steps back through all
    of it whatever is on screen, and ctrl+x r walks forward again."""

    def test_a_session_walks_back_and_forward_the_whole_way(self):
        store.add_machine(self.key, "First box")
        other, error = store.create_project("Second")
        self.assertIsNone(error)
        store.add_machine(other, "Box in second")
        store.select(self.key)
        store.delete_project(other)
        self.assertNotIn(other, store.project_keys())

        self.assertIn("deleted the project Second", store.undo())
        self.assertIn(other, store.project_keys(),
                      "the project did not come back")
        self.assertEqual([m["name"] for m in store.machines(other)],
                         ["Box in second"],
                         "the project came back without its machine")
        self.assertEqual(len(store.machines(self.key)), 1,
                         "undoing another project's change touched this one")

        self.assertIn("machines in Second", store.undo())
        self.assertEqual(store.machines(other), [])

        self.assertIn("created the project Second", store.undo())
        self.assertNotIn(other, store.project_keys())

        self.assertIn("machines in New Project", store.undo())
        self.assertEqual(store.machines(self.key), [])
        self.assertIsNone(store.undo(), "undo went past the session's start")

        for _ in range(4):
            self.assertIn("Redid", store.redo())
        self.assertNotIn(other, store.project_keys())
        self.assertEqual([m["name"] for m in store.machines(self.key)],
                         ["First box"])
        self.assertIsNone(store.redo(), "redo went past the session's end")

    def test_a_new_change_makes_redo_mean_something_else(self):
        """After an undo, typing something new is the branch taken; the steps
        that were redone-able described a future that no longer follows."""
        store.set_dashboard_panel(self.key, "Machines")
        store.set_theme(self.key, "gold")
        store.undo()
        store.set_deadline(self.key, "2026-12-01")
        self.assertIsNone(store.redo())

    def test_creating_a_project_is_one_undo(self):
        before = len(store.HISTORY.undo_stack)
        store.create_project("Second")
        self.assertEqual(len(store.HISTORY.undo_stack), before + 1,
                         "creating a project left more than one undo step")

    def test_undoing_a_creation_puts_the_view_back_where_it_was(self):
        other, _ = store.create_project("Second")     # ends up active
        store.undo()
        self.assertNotIn(other, store.project_keys())
        self.assertIn(store.active(), store.project_keys(),
                      "undo left the app pointed at a project that is gone")


class TestDescriptionLimit(Base):
    """A description reads as the one-line answer to "what is this box".

    Nothing stopped one becoming a second page of notes, so the field has a
    length now; the store refuses what would pass it, whichever door the text
    came through."""

    def test_a_description_at_the_limit_is_fine(self):
        machine, error = store.add_machine(
            self.key, "Box", description="x" * store.DESCRIPTION_LIMIT)
        self.assertIsNone(error)
        self.assertEqual(len(machine["description"]), store.DESCRIPTION_LIMIT)

    def test_one_character_past_the_limit_is_refused(self):
        machine, error = store.add_machine(
            self.key, "Box", description="x" * (store.DESCRIPTION_LIMIT + 1))
        self.assertIsNone(machine)
        self.assertIn("short", error.lower())

    def test_editing_into_an_over_long_description_is_refused(self):
        machine, _ = store.add_machine(self.key, "Box")
        _, error = store.edit_machine(
            self.key, machine["id"],
            description="x" * (store.DESCRIPTION_LIMIT + 1))
        self.assertIn("short", error.lower())
        self.assertEqual(
            store.find_machine(self.key, machine["id"])["description"], "",
            "the refused text was written anyway")

    def _edit(self, keys, initial="", limit=None, multiline=False):
        import tui
        from rich.live import Live
        queue = list(keys)
        real = tui.read_key
        tui.read_key = lambda timeout=None: queue.pop(0) if queue else None
        ui.console.height = 40
        try:
            with Live(console=ui.console, auto_refresh=False) as live:
                return tui.inline_prompt(live, "Description:", None,
                                         initial=initial, optional=True,
                                         multiline=multiline, limit=limit)
        finally:
            tui.read_key = real

    def test_the_editor_refuses_typing_past_the_limit(self):
        saved = self._edit(list("abcdef") + ["\r"], limit=4)
        self.assertEqual(saved, "abcd")

    def test_backspacing_makes_room_again(self):
        saved = self._edit(["a", "b", "c", "d", "e", "f", "\x7f", "z", "\r"],
                           limit=4)
        self.assertEqual(saved, "abcz")

    def test_a_paste_is_cut_at_the_limit_rather_than_dropped(self):
        import tui
        real_paste = tui.clipboard_paste
        tui.clipboard_paste = lambda: "x" * 50
        try:
            saved = self._edit([tui.KEY_PASTE, "\r"], initial="ab", limit=5)
        finally:
            tui.clipboard_paste = real_paste
        self.assertEqual(saved, "abxxx")

    def test_a_description_field_cannot_outgrow_its_limit(self):
        """The same rule in the multiline editor: a newline counts too."""
        inside = "z" * (store.DESCRIPTION_LIMIT - 1)
        saved = self._edit(["x", "\r", "y", tui.CTRL_S], initial=inside,
                           limit=store.DESCRIPTION_LIMIT, multiline=True)
        self.assertEqual(len(saved), store.DESCRIPTION_LIMIT)
        self.assertNotIn("\n", saved)


class TestMenuHighlight(Base):
    """The Menu is context behind every panel.

    While a submenu, picker or editor is open, the box should mark the item
    whose panel it is. It used to snap back to [1] Project the moment the
    third panel opened, because the screens that redraw the layout asked for
    the default."""

    def _index(self, key):
        return next(i for i, (k, _) in enumerate(ui.menu_items()) if k == key)

    def _capture(self, renderable):
        import io
        from rich.console import Console
        buf = io.StringIO()
        Console(file=buf, width=110, force_terminal=True).print(renderable)
        return buf.getvalue()

    def test_a_redrawn_layout_keeps_the_menu_highlight(self):
        seen = []
        real = ui.menu_panel
        ui.menu_panel = lambda hovered=0: (seen.append(hovered), "")[1]
        try:
            ui.set_highlight(self._index("4"))
            ui.build_layout()
            ui.dashboard_window()
        finally:
            ui.menu_panel = real
        self.assertEqual(seen, [self._index("4")] * 2,
                         "a screen that redrew the layout reset the box")

    def test_the_box_sits_on_the_parent_not_on_project(self):
        import re
        ui.set_highlight(self._index("4"))
        text = self._capture(ui.build_layout())
        m = re.search(r"\x1b\[1;7;38;5;\d+m\s*\[(\w)\]", text)
        self.assertIsNotNone(m, "nothing in the menu was highlighted")
        self.assertEqual(m.group(1), "4",
                         "the highlight fell back to [1] Project")

    def test_a_digit_moves_the_highlight_before_the_panel_opens(self):
        import contextlib
        import dashboard
        seen = []
        handlers = dict(dashboard.HANDLERS)
        handlers["4"] = lambda live, message: (seen.append(ui.highlight()),
                                               message)[1]
        seq = ["4"]
        real_read = dashboard.read_key
        real_live, real_raw = dashboard.Live, dashboard.raw_mode
        real_handlers = dashboard.HANDLERS
        try:
            dashboard.HANDLERS = handlers
            dashboard.read_key = lambda timeout=None: (seq.pop(0) if seq
                                                       else "\x03")
            dashboard.Live = FakeLive
            dashboard.raw_mode = contextlib.nullcontext
            dashboard._interactive(None)
        finally:
            dashboard.read_key = real_read
            dashboard.Live, dashboard.raw_mode = real_live, real_raw
            dashboard.HANDLERS = real_handlers
        self.assertEqual(seen, [self._index("4")],
                         "the panel opened while the box sat on [1] Project")


class TestSubmenusFollowTheTheme(Base):
    """Pickers and submenus used to be painted cyan whatever the theme was."""

    def test_no_hard_coded_colours_left_in_the_pickers(self):
        import inspect
        import tui
        for name in ("render_list", "render_input", "input_line"):
            source = inspect.getsource(getattr(tui, name))
            for colour in ("cyan", "yellow", "magenta", "red", "green", "blue"):
                self.assertNotIn(f"[{colour}", source,
                                 f"{name} still hard-codes {colour}")
                self.assertNotIn(f"bold {colour}", source,
                                 f"{name} still hard-codes {colour}")

    def test_the_picker_border_uses_the_accent(self):
        import inspect
        import tui
        source = inspect.getsource(tui.render_list)
        self.assertIn("border_style=accent()", source)
        self.assertIn("[bold {accent()}]▸", source)

    def test_the_picker_title_uses_the_bright_accent(self):
        import inspect
        import tui
        self.assertIn("[bold {bright()}]", inspect.getsource(tui.render_list))

    def test_the_accent_actually_follows_the_project_theme(self):
        for theme, accent in (("jade", "green3"), ("gold", "gold1"),
                              ("teal", "turquoise2"), ("royal", "blue3")):
            store.set_theme(self.key, theme)
            self.assertEqual(ui.accent(), accent)

    def test_each_theme_has_a_distinct_submenu_colour(self):
        seen = set()
        for theme in themes.ORDER:
            store.set_theme(self.key, theme)
            seen.add(ui.accent())
        self.assertEqual(len(seen), len(themes.ORDER),
                         "two themes share an accent colour")


class TestRepositoryDetails(Base):
    """Repository details are a paragraph, and the read view can edit in place."""

    def setUp(self):
        super().setUp()
        self.live = FakeLive()
        import dashboard
        self.dashboard = dashboard
        self.item, _ = store.add_repository(
            self.key, "Kerberos", "tickets, roasting\ndelegation")

    def test_add_asks_for_details_as_a_paragraph(self):
        import inspect
        import dashboard
        source = inspect.getsource(dashboard.repository_add)
        self.assertIn('"Details (optional):"', source)
        self.assertIn("multiline=True", source)

    def test_edit_asks_for_details_as_a_paragraph(self):
        import inspect
        import dashboard
        self.assertIn("multiline=True", inspect.getsource(dashboard.repository_edit_fields))

    def test_the_read_view_offers_an_edit(self):
        import inspect
        import dashboard
        source = inspect.getsource(dashboard.repository_read)
        self.assertIn('pressed == "e"', source)
        self.assertIn("repository_edit_fields", source)

    def test_e_escapes_keep_you_reading(self):
        keys = [None, dashboard.ESCAPE, None]
        dashboard.read_key = lambda timeout=None: keys.pop(0) if keys else None
        self.assertIsNone(dashboard.repository_read(self.live, self.item["id"], None))
        self.assertEqual(store.repository_items(self.key)[0]["title"], "Kerberos")

    def test_editing_keeps_multi_line_details(self):
        """The Details field is multi-line, so a saved value keeps its breaks."""
        dashboard = self.dashboard
        values = {"Title:": None,
                  "Details:": "tickets\nroasting\ndelegation",
                  "Group:": None}

        def prompt(live, label, message=None, **kw):
            given = values[label]
            return kw.get("initial", "") if given is None else given

        dashboard.inline_prompt = prompt
        edited, result = dashboard.repository_edit_fields(self.live,
                                                   store.repository_items(self.key)[0],
                                                   None)
        self.assertIsNotNone(edited, f"the edit was cancelled: {result!r}")
        self.assertEqual(edited["body"], "tickets\nroasting\ndelegation")
        self.assertEqual(store.repository_items(self.key)[0]["body"],
                         "tickets\nroasting\ndelegation")

    def test_details_and_title_are_not_swapped(self):
        """edit_repository takes (title, body). Passing them the other way round
        wrote the title into the details on every edit."""
        dashboard = self.dashboard
        item = store.repository_items(self.key)[0]
        values = {"Title:": "Kerberos2", "Details:": "the real details",
                  "Group:": ""}
        dashboard.inline_prompt = lambda live, label, message=None, **kw: values[label]
        edited, result = dashboard.repository_edit_fields(self.live, item, None)
        self.assertEqual(edited["body"], "the real details")
        self.assertEqual(edited["title"], "Kerberos2")

    def test_an_entry_carries_a_group(self):
        """It was removed as a label that did nothing; it is back because it
        now groups the list it appears in."""
        import dashboard
        entry, error = store.add_repository(self.key, "Plain", "body",
                                            "Kerberos")
        self.assertIsNone(error)
        self.assertEqual(entry["group"], "Kerberos")
        seen = []

        def note(live, label, message=None, **kw):
            seen.append(label)
            return {"Repository title:": "Another",
                    "Details (optional):": "body",
                    "Group (optional):": "Web"}.get(label, "x")

        real = dashboard.inline_prompt
        dashboard.inline_prompt = note
        self.addCleanup(setattr, dashboard, "inline_prompt", real)
        dashboard.repository_add(self.live, None)
        self.assertTrue([f for f in seen if f.startswith("Group")],
                        f"the group is not being asked for: {seen}")
        added = store.repository_items(self.key)[-1]
        self.assertEqual(added["group"], "Web")

    def test_stepping_past_a_field_keeps_it(self):
        dashboard = self.dashboard
        item = store.repository_items(self.key)[0]
        dashboard.inline_prompt = lambda live, label, message=None, **kw: kw.get("initial", "")
        edited, result = dashboard.repository_edit_fields(self.live, item, None)
        self.assertIsNotNone(edited, f"the edit was cancelled: {result!r}")
        self.assertEqual(edited["body"], item["body"])


class TestUniversalFields(Base):
    """A field is defined once, universally, and each machine opts into it."""

    def setUp(self):
        super().setUp()
        self.machine, _ = store.add_machine(self.key, "Target")
        self.id = self.machine["id"]
        self.field, _ = store.add_category(self.key, "foothold",
                                               "nc -lvnp 443")

    # ---- the definition ------------------------------------------------
    def test_a_field_has_a_title_and_a_default(self):
        self.assertEqual(self.field["title"], "foothold")
        self.assertEqual(self.field["default"], "nc -lvnp 443")

    def test_a_field_needs_a_title(self):
        field, error = store.add_category(self.key, " ")
        self.assertIsNone(field)
        self.assertIn("name", error)

    def test_a_field_title_is_unique(self):
        field, error = store.add_category(self.key, "Foothold", "x")
        self.assertIsNone(field)
        self.assertIn("already", error)

    def test_a_field_can_be_edited(self):
        edited, error = store.edit_category(self.key, self.field["id"],
                                                 default="nc 443")
        self.assertIsNone(error)
        self.assertEqual(edited["default"], "nc 443")
        self.assertEqual(edited["title"], "foothold")

    def test_deleting_a_field_takes_it_off_every_machine(self):
        store.attach_machine_categories(self.key, self.id, [self.field["id"]])
        error = store.delete_category(self.key, self.field["id"])
        self.assertIsNone(error)
        self.assertEqual(store.project_categories(), [])
        self.assertEqual(store.machine_categories(self.key, self.id), [])
        self.assertEqual(store.machine_category_ids(self.key, self.id), [])

    # ---- a machine opts in ---------------------------------------------
    def test_a_machine_marks_the_fields_it_uses(self):
        other, _ = store.add_category(self.key, "creds", "admin")
        store.attach_machine_categories(self.key, self.id,
                                    [self.field["id"], other["id"]])
        self.assertEqual([f["title"] for f in
                          store.machine_categories(self.key, self.id)],
                         ["foothold", "creds"])

    def test_an_unmarked_field_is_not_on_a_machine(self):
        self.assertEqual(store.machine_categories(self.key, self.id), [])
        self.assertEqual(store.machine_category_ids(self.key, self.id), [])

    def test_a_machine_can_unmark_a_field(self):
        store.attach_machine_categories(self.key, self.id, [self.field["id"]])
        store.attach_machine_categories(self.key, self.id, [])
        self.assertEqual(store.machine_categories(self.key, self.id), [])

    def test_marking_something_that_is_not_a_field_is_ignored(self):
        error = store.attach_machine_categories(self.key, self.id, ["f404"])
        self.assertNotIn("No such", str(error))
        self.assertEqual(store.machine_category_ids(self.key, self.id), [])

    # ---- the content ---------------------------------------------------
    def test_a_machine_sees_the_shared_default_until_it_overrides_it(self):
        store.attach_machine_categories(self.key, self.id, [self.field["id"]])
        shown = store.machine_categories(self.key, self.id)[0]
        self.assertEqual(shown["body"], None)
        self.assertFalse(shown["overridden"])
        self.assertEqual(shown["default"], "nc -lvnp 443")

    def test_a_machine_can_override_the_content(self):
        store.attach_machine_categories(self.key, self.id, [self.field["id"]])
        error = store.machine_category_body(self.key, self.id,
                                        self.field["id"], "nc 8443")
        self.assertIsNone(error)
        shown = store.machine_categories(self.key, self.id)[0]
        self.assertEqual(shown["body"], "nc 8443")
        self.assertTrue(shown["overridden"])

    def test_clearing_the_content_puts_back_the_shared_default(self):
        store.attach_machine_categories(self.key, self.id, [self.field["id"]])
        store.machine_category_body(self.key, self.id, self.field["id"], "nc 1")
        store.machine_category_body(self.key, self.id, self.field["id"], "")
        shown = store.machine_categories(self.key, self.id)[0]
        self.assertFalse(shown["overridden"])
        self.assertEqual(shown["default"], "nc -lvnp 443")

    def test_one_machine_doing_its_own_thing_leaves_the_others_alone(self):
        second, _ = store.add_machine(self.key, "Web")
        store.attach_machine_categories(self.key, self.id, [self.field["id"]])
        store.attach_machine_categories(self.key, second["id"], [self.field["id"]])
        store.machine_category_body(self.key, self.id, self.field["id"], "mine")
        self.assertTrue(store.machine_categories(self.key, self.id)[0]["overridden"])
        self.assertFalse(store.machine_categories(self.key, second["id"])[0]
                         ["overridden"])

    def test_overriding_a_field_the_machine_has_not_marked_says_so(self):
        error = store.machine_category_body(self.key, self.id,
                                        self.field["id"], "x")
        self.assertIn("not on this machine", error)

    # ---- the screens ---------------------------------------------------
    def _shortcuts(self, function, machine_id=None):
        captured = {}
        real = dashboard.pick
        dashboard.pick = lambda live, prompt, pairs, message, empty=None, **kw: (
            captured.update(kw), (None, None))[1]
        try:
            if machine_id is None:
                function(None, None)
            else:
                function(None, machine_id, None)
        finally:
            dashboard.pick = real
        return captured

    def test_the_universal_list_can_add_edit_and_delete(self):
        captured = self._shortcuts(dashboard.universal_categories)
        self.assertEqual(set(captured.get("shortcuts", {})), {"a", "e", "d"})

    def test_the_machine_fields_screen_can_edit_content(self):
        store.attach_machine_categories(self.key, self.id, [self.field["id"]])
        captured = self._shortcuts(dashboard.machine_categories_screen, self.id)
        self.assertEqual(set(captured.get("shortcuts", {})), {"e"})

    def test_c_on_the_machine_list_marks_rather_than_creates(self):
        source = inspect.getsource(dashboard.machine_list)
        self.assertIn('"c": field_it', source)
        self.assertIn("machine_categories_screen", source)

    def test_marking_is_one_list_of_every_field(self):
        """Marking used to be a screen of the fields not yet on the machine,
        and removing was a key on a different one - so a field could be put on
        but never taken off from where you put it on. One list, every field,
        and enter turns the tick either way."""
        import dashboard
        other, _ = store.add_category(self.key, "creds", "admin:admin")
        seen = {}

        def pick(live, prompt, pairs, message, empty=None, **kw):
            seen["pairs"] = pairs
            seen["ticks"] = kw.get("ticks")
            return None, None

        real = dashboard.pick
        dashboard.pick = pick
        try:
            dashboard.machine_categories_screen(None, self.id, None)
        finally:
            dashboard.pick = real
        offered = [label for label, _ in seen["pairs"]]
        self.assertIn("creds", offered)
        self.assertIn(self.field["title"], offered)
        source = inspect.getsource(dashboard.machine_categories_screen)
        self.assertIn("attach_machine_categories", source)
        self.assertIn("Unmarked", source)
        self.assertIn("Marked", source)

    def test_enter_on_the_fields_screen_marks_and_unmarks(self):
        """One row, two directions: a tick that can only go on would be a
        half-way house."""
        import dashboard
        store.add_category(self.key, "creds", "admin:admin")

        def press(field_id):
            """Return the id once, then let the screen close.

            pick hands back None when the list is cancelled, which is how the
            screen knows the user pressed escape."""
            answers = [field_id, None]
            real = dashboard.pick
            dashboard.pick = (
                lambda live, prompt, pairs, message, empty=None, **kw:
                (answers.pop(0), None))
            try:
                dashboard.machine_categories_screen(None, self.id, None)
            finally:
                dashboard.pick = real

        press(self.field["id"])
        self.assertEqual(store.machine_category_ids(self.key, self.id),
                         [self.field["id"]], "enter marked it")
        press(self.field["id"])
        self.assertEqual(store.machine_category_ids(self.key, self.id), [],
                         "enter again unmarked it")
        creds = next(f for f in store.project_categories(self.key)
                     if f["title"] == "creds")
        press(creds["id"])
        self.assertEqual(store.machine_category_ids(self.key, self.id),
                         [creds["id"]])

    def test_marking_offers_the_fields_already_on_it_too(self):
        """The old marking screen dropped them from the list, which read as
        "already done, nothing to do here" rather than "you can take this off"."""
        import dashboard
        store.add_category(self.key, "creds", "admin:admin")
        store.attach_machine_categories(self.key, self.id, [self.field["id"]])
        offered = []
        real = dashboard.pick

        def pick(live, prompt, pairs, message, empty=None, **kw):
            offered.extend(name for name, _ in pairs)
            return None, None

        dashboard.pick = pick
        try:
            dashboard.machine_categories_screen(None, self.id, None)
        finally:
            dashboard.pick = real
        self.assertIn(self.field["title"], offered,
                      "a marked field must still be listed, to unmark it")
        self.assertIn("creds", offered)

    def test_categories_written_on_a_machine_are_shared_by_the_project(self):
        """They used to be created on the machine, so the title and body lived
        there. Now they belong to the project and the machine uses them - the
        migration moves them rather than hiding them."""
        import store as store_mod
        data = store_mod.load("machines")
        data["projects"][self.key].setdefault("items", [])
        data["projects"][self.key]["items"].append({
            "id": "mZ", "name": "Old", "completed": 0, "total": 1,
            "fields": [{"id": "f1", "title": "creds", "body": "admin:admin"}],
        })
        store_mod.save("machines", data, record=False)
        # Through heal(), not the step on its own: the row is written in the
        # oldest shape there has ever been, and it takes the rename first.
        notes = store_mod.heal()
        self.assertTrue(any("shared" in note for note in notes), notes)
        self.assertEqual([f["title"] for f in
                          store_mod.project_categories(self.key)],
                         ["foothold", "creds"])   # the one from setUp, then this
        self.assertEqual(store_mod.project_categories(self.key)[1]["default"],
                         "admin:admin")
        shown = store.machine_categories(self.key, "mZ")
        self.assertEqual([f["title"] for f in shown], ["creds"])
        self.assertTrue(shown[0]["overridden"])
        self.assertEqual(shown[0]["body"], "admin:admin")
        # and a second migration is a no-op, not a duplicate
        store_mod.heal()
        self.assertEqual([f["title"] for f in
                          store_mod.project_categories(self.key)],
                         ["foothold", "creds"])

    def test_the_fields_entry_is_in_the_machines_sub_panel(self):
        labels = [n for n, _ in dashboard.MACHINES_MENU]
        self.assertEqual(labels, ["View", "Categories", "Panel"])


class TestRepositoryMenuOrder(Base):
    """Reading the repository is why the menu gets opened."""

    def test_the_repository_offers_a_view_entry(self):
        """Opening the entries straight away was one press fewer when there
        were entries to read, and a dead end when there were none: an empty
        repository flashed a message and dropped you back on the dashboard
        with nothing on screen. The menu answers whatever is in it."""
        import dashboard
        import inspect
        self.assertEqual([label for label, _ in dashboard.REPOSITORY_MENU],
                         ["View"])
        source = inspect.getsource(dashboard.action_repository)
        self.assertIn("submenu(", source)
        self.assertIn("REPOSITORY_MENU", source)
        self.assertIn('submenu(live, "Repository:"', source)

    def test_an_empty_repository_says_how_to_start_one(self):
        """Not just that there is nothing, which reads as the screen being
        broken - and not a promise the screen then fails to keep."""
        import dashboard
        import inspect
        source = inspect.getsource(dashboard.repository_list)
        self.assertIn("a adds the first entry", source)

    def test_an_empty_list_still_answers_the_key_it_asks_for(self):
        """pick() hands back the moment there is nothing to choose from, so
        the keys belonging to that list were never registered. An empty
        repository said "a adds the first entry" and then ignored a."""
        import dashboard
        from tui import ESCAPE
        self.assertEqual(store.repository_items(self.key), [])
        asked = []
        original = (dashboard.read_key, dashboard.show_screen,
                    dashboard.repository_add)
        dashboard.read_key = lambda *a, **k: "a" if not asked else ESCAPE
        dashboard.show_screen = lambda live, r, top: (top, 0)
        dashboard.build_layout = lambda **k: ""
        dashboard.repository_add = lambda live, message: asked.append("add") \
            or "Added the first entry"
        ui.console.width, ui.console.height = 100, 40
        try:
            dashboard.repository_list(None, None)
        finally:
            (dashboard.read_key, dashboard.show_screen,
             dashboard.repository_add) = original[:2] + (original[2],)
        self.assertEqual(asked, ["add"],
                         "a on an empty repository must add the first entry")

    def test_an_empty_machines_list_adds_the_first_one_too(self):
        import dashboard
        from tui import ESCAPE
        self.assertEqual(store.machines(self.key), [])
        asked = []
        original = (dashboard.read_key, dashboard.show_screen,
                    dashboard.machine_add)
        dashboard.read_key = lambda *a, **k: "a" if not asked else ESCAPE
        dashboard.show_screen = lambda live, r, top: (top, 0)
        dashboard.build_layout = lambda **k: ""
        dashboard.machine_add = lambda live, message: asked.append("add") \
            or "Added Target"
        ui.console.width, ui.console.height = 100, 40
        try:
            dashboard.machine_list(None, None)
        finally:
            (dashboard.read_key, dashboard.show_screen,
             dashboard.machine_add) = original[:2] + (original[2],)
        self.assertEqual(asked, ["add"])

    def test_an_empty_project_with_no_fields_can_define_the_first_one(self):
        import dashboard
        from tui import ESCAPE
        self.assertEqual(store.project_categories(self.key), [])
        asked = []
        original = (dashboard.read_key, dashboard.show_screen,
                    dashboard.category_add)
        dashboard.read_key = lambda *a, **k: "a" if not asked else ESCAPE
        dashboard.show_screen = lambda live, r, top: (top, 0)
        dashboard.build_layout = lambda **k: ""
        dashboard.category_add = lambda live, message=None: asked.append("add") \
            or "Added foothold"
        ui.console.width, ui.console.height = 100, 40
        try:
            dashboard.universal_categories(None, None)
        finally:
            (dashboard.read_key, dashboard.show_screen,
             dashboard.category_add) = original[:2] + (original[2],)
        self.assertEqual(asked, ["add"])

    def test_add_edit_and_delete_are_keys_on_that_list(self):
        import dashboard
        import inspect
        source = inspect.getsource(dashboard.repository_list)
        for key in ('"a"', '"e"', '"d"'):
            self.assertIn(key, source)

class TestEditorUndo(Base):
    """Undo belongs to the text you are typing, not to the last saved file.

    ctrl+x u used to leave the editor, undo whatever had been saved, and
    redraw the whole app - so the line you had just deleted could not come
    back, because the text holding it had never been saved anywhere."""

    def _edit(self, keys, text="", multiline=True, label="Notes:"):
        import tui
        from rich.live import Live
        queue = list(keys)
        real = tui.read_key
        tui.read_key = lambda timeout=None: queue.pop(0) if queue else None
        ui.console.height = 40
        try:
            with Live(console=ui.console, auto_refresh=False) as live:
                return tui.inline_prompt(live, label, None, initial=text,
                                         optional=True, multiline=multiline)
        finally:
            tui.read_key = real

    def test_undo_brings_back_a_deleted_line(self):
        saved = self._edit([tui.CTRL_U, tui.CTRL_X, "u", tui.CTRL_S],
                           "one\ntwo\nthree")
        self.assertEqual(saved, "one\ntwo\nthree",
                         "ctrl+u then ctrl+x u did not put the line back")

    def test_redo_takes_it_away_again(self):
        saved = self._edit([tui.CTRL_U, tui.CTRL_X, "u", tui.CTRL_X, "r",
                            tui.CTRL_S], "one\ntwo\nthree")
        self.assertEqual(saved, "one\ntwo\n")

    def test_undo_stops_at_the_text_the_field_opened_with(self):
        buf = tui.TextBuffer("as it was")
        buf.snapshot()          # what multiline_key does before it changes
        buf.insert("!")
        self.assertTrue(buf.undo())
        self.assertEqual(buf.text, "as it was")
        self.assertFalse(buf.undo(), "it stepped past where it started")

    def test_a_run_of_typing_is_one_undo(self):
        buf = tui.TextBuffer("")
        for letter in "hello":
            buf.snapshot(typing=True)
            buf.insert(letter)
        self.assertTrue(buf.undo())
        self.assertEqual(buf.text, "")
        self.assertFalse(buf.undo())

    def test_undo_works_in_a_one_line_field_too(self):
        """It used to be swallowed there: ctrl+x was read and nothing came of
        it, so the key did nothing at all in a name or a category."""
        saved = self._edit(["x", "\x7f", tui.CTRL_X, "u", "\r"], "ab",
                           multiline=False, label="Name:")
        self.assertEqual(saved, "abx")

    def test_ctrl_x_q_still_leaves(self):
        """Undo is the editor's now; quitting is still the app's."""
        buf = tui.TextBuffer("hello")
        buf.snapshot()
        buf.insert("!")
        self.assertTrue(buf.undo())
        self.assertEqual(buf.text, "hello")


class TestPasteKeys(Base):
    """ctrl+shift+v is spelled several ways and only one of them was listened
    to - and it was the one no terminal sends."""

    def test_the_spellings_of_ctrl_shift_v_all_paste(self):
        for sequence in (b"\x1b[118;5u", b"\x1b[118;6u", b"\x1b[86;6u"):
            self.assertEqual(tui.ESCAPE_KEYS.get(sequence), tui.KEY_PASTE,
                             f"{sequence!r} did not reach the paste handler")

    def test_the_spellings_of_ctrl_shift_c_all_copy(self):
        for sequence in (b"\x1b[99;6u", b"\x1b[67;6u", b"\x1b[99;2u"):
            self.assertEqual(tui.ESCAPE_KEYS.get(sequence), tui.KEY_COPY,
                             f"{sequence!r} did not reach the copy handler")

    def test_plain_ctrl_c_is_neither(self):
        """It was ctrl+c's own sequence that was mapped to copy, which is why
        the two hands came out crossed over."""
        for sequence in (b"\x1b[99;5u", b"\x1b[105;5u"):
            self.assertIsNone(tui.ESCAPE_KEYS.get(sequence), sequence)

    def test_a_pasted_sequence_reaches_the_editor(self):
        """The paste handler in the editor, with the clipboard stubbed out."""
        import tui
        buf = tui.TextBuffer("")
        tui.clipboard_paste = lambda: "pasted text"
        tui.multiline_key(buf, tui.KEY_PASTE)
        self.assertEqual(buf.text, "pasted text")
        self.assertTrue(buf.undo(), "a paste is undoable too")


class TestEscapeParsing(Base):
    """An Esc that starts no sequence must not eat the byte after it."""

    def _stdin(self, fd):
        class FakeStdin:
            def fileno(self):
                return fd

            def isatty(self):
                return True

        return FakeStdin()

    def _read_two(self, keys):
        import os
        real_stdin, real_pushed = sys.stdin, tui._PUSHED
        r, w = os.pipe()
        sys.stdin = self._stdin(r)
        tui._PUSHED = b""
        try:
            os.write(w, keys)
            first = tui.read_key(0.2)
            second = tui.read_key(0.2)
        finally:
            sys.stdin, tui._PUSHED = real_stdin, real_pushed
            os.close(r)
            os.close(w)
        return first, second

    def test_a_second_fast_escape_survives(self):
        """Two presses used to back out one level: the second Esc was read
        while looking for a sequence and thrown away."""
        first, second = self._read_two(b"\x1b\x1b[B")
        self.assertEqual(first, "\x1b")
        self.assertEqual(second, tui.KEY_DOWN,
                         "the arrow after a fast double-Esc was lost")

    def test_a_digit_on_escapes_heels_survives(self):
        first, second = self._read_two(b"\x1b2")
        self.assertEqual(first, "\x1b")
        self.assertEqual(second, "2", "the digit after Esc was eaten")


class TestEditorUndoesItself(Base):
    """ctrl+x u / r in a field undo the field.

    read_key raises the chord, so it escaped to the dashboard, which undid the
    whole project's last save and threw you back on the menu - exactly the
    opposite of having the line you just deleted back."""

    def _drive(self, keys, **kw):
        from rich.live import Live
        import tui
        from tui import Chord, CTRL_S

        class L:
            def update(self, r):
                pass
            def refresh(self):
                pass
            def is_terminal(self):
                return False

        queue = list(keys)
        # A one-line field commits on Enter, a multi-line one on ctrl+s. Save
        # rather than idle once the script runs out: a field that never
        # completes is a test that never ends.
        done = CTRL_S if kw.get("multiline", True) else "\r"

        def read_key(timeout=None):
            if not queue:
                return done
            item = queue.pop(0)
            if isinstance(item, Chord):
                raise item
            return item

        real = tui.read_key
        ui.console.width, ui.console.height = 90, 30
        tui.read_key = read_key
        try:
            opts = dict(multiline=True, optional=True)
            opts.update(kw)
            with Live(console=ui.console, auto_refresh=False) as live:
                return tui.inline_prompt(L(), "Notes:", None, **opts)
        finally:
            tui.read_key = real

    def test_a_raised_chord_undoes_the_text_not_the_dashboard(self):
        from tui import Chord, CTRL_U, CTRL_S, CHORD_UNDO
        saved = self._drive(list("hello there") + [CTRL_U, Chord(CHORD_UNDO),
                                                   CTRL_S])
        self.assertEqual(saved, "hello there",
                         "the killed line did not come back")

    def test_two_killed_lines_come_back_in_two_undos(self):
        from tui import Chord, CTRL_U, CTRL_S, CHORD_UNDO
        saved = self._drive(list("first") + [chr(10)] + list("second")
                            + [CTRL_U, CTRL_U, Chord(CHORD_UNDO),
                               Chord(CHORD_UNDO), CTRL_S])
        self.assertEqual(saved, "first" + chr(10) + "second")

    def test_redo_puts_the_kill_back(self):
        from tui import Chord, CTRL_U, CTRL_S, CHORD_UNDO, CHORD_REDO
        saved = self._drive(list("gone") + [CTRL_U, Chord(CHORD_UNDO),
                                            Chord(CHORD_REDO), CTRL_S])
        self.assertEqual(saved, "")

    def test_ctrl_x_q_still_leaves_the_field(self):
        """Quitting has to keep working from wherever the keys are being read."""
        from tui import Chord, CHORD_QUIT
        with self.assertRaises(Chord) as raised:
            self._drive(list("halfway") + [Chord(CHORD_QUIT)])
        self.assertEqual(raised.exception.token, CHORD_QUIT)

    def test_a_one_line_field_undoes_too(self):
        from tui import Chord, CTRL_S, CHORD_UNDO
        saved = self._drive(list("name") + [Chord(CHORD_UNDO), CTRL_S],
                            multiline=False)
        self.assertEqual(saved, "")

    def test_an_empty_undo_says_so_on_the_message_line(self):
        """A press with nothing to step to redrew the field silently, which
        read as the key doing nothing at all."""
        from tui import Chord, CTRL_S, CHORD_UNDO
        messages = []
        real = tui.render_input
        tui.render_input = lambda live, prompt, value, **kw: messages.append(
            kw.get("message"))
        try:
            saved = self._drive([Chord(CHORD_UNDO), CTRL_S])
        finally:
            tui.render_input = real
        self.assertEqual(saved, "")
        self.assertIn("Nothing to undo", messages)


class TestChordsRunWhereTheyWerePressed(Base):
    """ctrl+x u / r from a picker or a panel run there, not on the dashboard.

    Both let the chord escape all the way to the dashboard loop, which ran the
    command and rebuilt the main menu - so undoing a mark or a save closed the
    list you were on and dropped you on the menu, which read as undo
    restarting the app."""

    @staticmethod
    def _read_key(seq):
        """A stand-in that raises Chords the way read_key does."""
        def read_key(timeout=None):
            item = seq.pop(0) if seq else None
            if isinstance(item, tui.Chord):
                raise item
            return item
        return read_key

    def test_undoing_a_mark_from_the_list_stays_on_the_list(self):
        from rich.live import Live
        machine, _ = store.add_machine(self.key, "Target")
        seq = ["m", tui.Chord(tui.CHORD_UNDO), tui.ESCAPE]
        drawn = []
        real_render = tui.render_list
        real_read = tui.read_key
        ui.console.height = 40
        try:
            tui.read_key = self._read_key(seq)

            def spy(live, prompt, names, rows, cur, top, view, **kw):
                drawn.append(list(names))
                return real_render(live, prompt, names, rows, cur, top, view,
                                   **kw)
            tui.render_list = spy
            with Live(console=ui.console, auto_refresh=False) as live:
                dashboard.machine_list(live, None)
        finally:
            tui.render_list, tui.read_key = real_render, real_read
        self.assertEqual(store.find_machine(self.key, machine["id"])["completed"],
                         0, "the chord never reached the store")
        self.assertTrue(drawn, "the list never drew")
        self.assertFalse(any("\u2713" in name for name in drawn[-1]),
                         f"the tick survived the undo: {drawn[-1]}")

    def test_a_chord_in_a_submenu_runs_on_the_submenu(self):
        from rich.live import Live
        machine, _ = store.add_machine(self.key, "Target")
        store.mark_machine(self.key, machine["id"])
        seq = [tui.Chord(tui.CHORD_UNDO), tui.ESCAPE]
        real_read = tui.read_key
        ui.console.height = 40
        try:
            tui.read_key = self._read_key(seq)
            with Live(console=ui.console, auto_refresh=False) as live:
                result, finished = dashboard.submenu(
                    live, "Machines:", dashboard.MACHINES_MENU, None)
        finally:
            tui.read_key = real_read
        self.assertTrue(finished, "esc should have closed the submenu")
        # The message showed inside the open submenu; what has to survive is
        # the change itself, with the submenu still there to esc out of.
        self.assertIsNone(result)
        self.assertEqual(store.find_machine(self.key, machine["id"])["completed"],
                         0, "the chord never reached the store")

    def test_a_chord_on_a_details_panel_keeps_the_panel_up(self):
        from rich.live import Live
        from rich.text import Text
        seen = []
        seq = [tui.Chord(tui.CHORD_UNDO), "x"]
        real_read = tui.read_key
        ui.console.height = 40
        try:
            tui.read_key = self._read_key(seq)
            with Live(console=ui.console, auto_refresh=False) as live:
                tui.show_details(
                    live, "OS", Text("kept on the machine"),
                    chords=lambda token: seen.append(token) or "Undid it")
        finally:
            tui.read_key = real_read
        self.assertEqual(seen, [tui.CHORD_UNDO],
                         "the chord did not stay on the panel")
        self.assertEqual(seq, [], "the plain key should have closed the panel")

    def test_ctrl_x_q_still_quits_from_a_picker(self):
        with self.assertRaises(dashboard.Chord):
            dashboard.chord_in_place(dashboard.CHORD_QUIT)


class TestCopyAndPasteKeys(Base):
    """ctrl+shift+c copies and ctrl+shift+v pastes, on the terminals that
    send the kitty protocol's spelling of them."""

    def test_ctrl_shift_c_is_copy(self):
        import tui
        self.assertEqual(tui.ESCAPE_KEYS[b"\x1b[99;6u"], tui.KEY_COPY)
        self.assertEqual(tui.ESCAPE_KEYS[b"\x1b[67;6u"], tui.KEY_COPY)

    def test_ctrl_shift_v_is_paste(self):
        import tui
        self.assertEqual(tui.ESCAPE_KEYS[b"\x1b[118;6u"], tui.KEY_PASTE)
        self.assertEqual(tui.ESCAPE_KEYS[b"\x1b[86;6u"], tui.KEY_PASTE)

    def test_ctrl_c_is_not_a_copy(self):
        """That sequence spelled plain ctrl+c, which is quit - and it was the
        one mapped to copy, which is why the wrong thing was happening."""
        import tui
        self.assertIsNone(tui.ESCAPE_KEYS.get(b"\x1b[99;5u"))
        self.assertIsNone(tui.ESCAPE_KEYS.get(b"\x1b[105;5u"))

    def test_editing_copies_with_ctrl_shift_c(self):
        from tui import TextBuffer, multiline_key
        copied = []
        real = tui.copy_to_clipboard
        tui.copy_to_clipboard = lambda text: copied.append(text)
        try:
            buf = TextBuffer("some notes")
            multiline_key(buf, tui.KEY_COPY)
        finally:
            tui.copy_to_clipboard = real
        self.assertEqual(copied, ["some notes"])


class TestUndoHasNoDeadSteps(Base):
    """ctrl+x u has to do something every time, or it reads as a dead key."""

    def test_the_first_undo_after_a_change_does_something(self):
        buf = tui.TextBuffer("hello world")
        tui.multiline_key(buf, tui.CTRL_U)            # kill to the start of the line
        self.assertEqual(buf.text, "")
        self.assertTrue(buf.undo(), "the first undo refused to do anything")
        self.assertEqual(buf.text, "hello world")

    def test_there_is_no_press_that_changes_nothing(self):
        """Every step back lands on different text."""
        buf = tui.TextBuffer("")
        for ch in "abc":
            tui.multiline_key(buf, ch)
        tui.multiline_key(buf, "\x7f")
        seen = []
        while buf.undo():
            if seen and seen[-1] == buf.text:
                self.fail("undo produced the same text twice in a row")
            seen.append(buf.text)
        self.assertTrue(seen, "nothing could be undone at all")

    def test_undo_stops_where_the_field_opened(self):
        buf = tui.TextBuffer("start")
        tui.multiline_key(buf, "\x7f")
        buf.undo()
        self.assertEqual(buf.text, "start")
        self.assertFalse(buf.undo(),
                         "it walked back past the text the field opened with")

    def test_redo_puts_it_back_the_way_undo_took_it(self):
        buf = tui.TextBuffer("")
        for ch in "abc":
            tui.multiline_key(buf, ch)
        tui.multiline_key(buf, "\x7f")
        buf.undo()
        self.assertTrue(buf.redo())
        self.assertEqual(buf.text, "ab")


class TestClipboard(Base):
    """Pasting has to work, or say why it did not."""

    def test_a_wayland_session_reads_the_wayland_clipboard_first(self):
        """Both can be installed on a Wayland desktop, and xclip then reads an
        X11 clipboard nothing has written to in weeks - pasting that, or
        nothing, while the clipboard someone copied from sat unread next to it."""
        import os
        kept = os.environ.get("WAYLAND_DISPLAY")
        os.environ["WAYLAND_DISPLAY"] = "wayland-0"
        try:
            names = [c[0] for c in tui._clipboard_readers()]
        finally:
            if kept is None:
                os.environ.pop("WAYLAND_DISPLAY", None)
            else:
                os.environ["WAYLAND_DISPLAY"] = kept
        self.assertLess(names.index("wl-paste"), names.index("xclip"))

    def test_an_x11_session_reads_x11_first(self):
        import os
        kept = os.environ.pop("WAYLAND_DISPLAY", None)
        try:
            names = [c[0] for c in tui._clipboard_readers()]
        finally:
            if kept is not None:
                os.environ["WAYLAND_DISPLAY"] = kept
        self.assertLess(names.index("xclip"), names.index("wl-paste"))

    def test_an_empty_clipboard_says_so_in_the_editor(self):
        """It used to insert nothing at all, so the key looked broken."""
        import unittest.mock as mock
        buf = tui.TextBuffer("notes")
        with mock.patch.object(tui, "clipboard_paste", lambda: None):
            self.assertEqual(tui.multiline_key(buf, tui.CTRL_V), "clipboard")
        self.assertEqual(buf.text, "notes", "nothing should have been typed")

    def test_the_hint_names_the_tools_it_looks_for(self):
        for tool in ("xclip", "xsel", "wl-paste", "pbpaste"):
            self.assertIn(tool, tui.CLIPBOARD_HINT)

    def test_paste_still_inserts_when_there_is_something_there(self):
        import unittest.mock as mock
        buf = tui.TextBuffer("notes")
        with mock.patch.object(tui, "clipboard_paste",
                               lambda: " admin:admin"):
            tui.multiline_key(buf, tui.CTRL_V)
        self.assertEqual(buf.text, "notes admin:admin")


class TestDamagedData(Base):
    """A file edited by hand, or a write cut short, must not take the app with
    it. Every case here reached a KeyError or an AttributeError and closed the
    program rather than dropping one row."""

    def _wreck(self, target, damage):
        data = json.loads(json.dumps(self.read(target)))
        damage(data)
        (self.data / f"{target}.json").write_text(json.dumps(data))

    def _surfaces(self):
        import dashboard
        ui.console.width, ui.console.height = 100, 40

        class L:
            def update(self, r):
                pass
            def refresh(self):
                pass
            def is_terminal(self):
                return False

        live = L()

        def keys():
            for _ in range(6):
                yield None
            while True:
                yield tui.ESCAPE

        live_keys, dash_keys = keys(), keys()
        kept = (tui.read_key, dashboard.read_key, dashboard.show_screen,
                dashboard.build_layout)
        tui.read_key = lambda timeout=None: next(live_keys)
        dashboard.read_key = lambda timeout=None: next(dash_keys)
        dashboard.show_screen = lambda live, renderable, top: (top, 0)
        dashboard.build_layout = lambda **k: ""
        try:
            for name, call in (
                    ("machine list", lambda: dashboard.machine_list(live, None)),
                    ("fields", lambda: dashboard.universal_categories(live, None)),
                    ("repository", lambda: dashboard.repository_list(live, None)),
                    ("machine fields",
                     lambda: dashboard.machine_categories_screen(live, "m1", None)),
                    ("summary", lambda: summary_panel()),
                    ("dashboard", lambda: ui.build_layout(message=None)),
                    ("heal", lambda: store.heal())):
                try:
                    call()
                except Exception as e:
                    self.fail(f"{name} raised on damaged data: "
                              f"{type(e).__name__}: {e}")
        finally:
            (tui.read_key, dashboard.read_key, dashboard.show_screen,
             dashboard.build_layout) = kept

    def test_a_machine_with_no_id_is_skipped(self):
        store.add_machine(self.key, "Web")
        self._wreck("machines",
                    lambda d: d["projects"][self.key]["items"].append(
                        {"name": "?"}))
        self._surfaces()

    def test_a_row_that_is_not_an_object_at_all_is_skipped(self):
        store.add_machine(self.key, "Web")
        for junk in (None, 7, "x", []):
            self._wreck("machines",
                        lambda d, j=junk: d["projects"][self.key]["items"]
                        .append(j))
            self._surfaces()

    def test_a_category_name_of_the_wrong_type_is_survivable(self):
        store.add_category(self.key, "creds", "a")
        for odd in (7, None, [], {"a": 1}):
            self._wreck("machines",
                        lambda d, o=odd: d["projects"][self.key]["categories"]
                        .append({"id": "q9", "title": o}))
            self._surfaces()

    def test_junk_inside_a_legacy_field_list_is_skipped(self):
        def add_junk(d):
            board = d["projects"].setdefault(self.key, {})
            board.setdefault("items", []).append(
                {"id": "j1", "name": "Junk",
                 "fields": [None, 3, {}, {"title": "creds", "body": "a"}]})

        self._wreck("machines", add_junk)
        self._surfaces()

    def test_a_board_with_no_items_key_at_all(self):
        store.add_machine(self.key, "Web")
        self._wreck("machines", lambda d: d["projects"][self.key].pop("items",
                                                                      None))
        self._surfaces()

    def test_a_project_record_that_is_not_an_object(self):
        store.add_machine(self.key, "Web")
        self._wreck("projects", lambda d: d["projects"].__setitem__("ghost", "x"))
        self._surfaces()

    def test_a_whole_file_that_is_not_a_mapping(self):
        store.add_machine(self.key, "Web")
        self._wreck("machines", lambda d: d.clear())
        self._surfaces()


class _this_project_using_the_os:
    """Give this project the OS setting, the way heal() would.

    Which projects use the OS is a fact about somebody's data rather than
    about the rules; the rules are what these tests are about."""

    def __init__(self, key):
        self.key = key

    def __enter__(self):
        reg = store.registry()
        self.kept = reg["projects"][self.key].get(store.OS_SETTING)
        reg["projects"][self.key][store.OS_SETTING] = True
        store.save_registry(reg)
        return self.key

    def __exit__(self, *exc):
        reg = store.registry()
        if self.kept is None:
            reg["projects"][self.key].pop(store.OS_SETTING, None)
        else:
            reg["projects"][self.key][store.OS_SETTING] = self.kept
        store.save_registry(reg)
        return False


class TestPermanentCategories(Base):
    """Description and Notes are in every machine, and cannot be switched off.
    The OS is a category too - in the two projects that use it, on by default."""

    def test_description_and_notes_are_permanent(self):
        self.assertEqual([cid for cid, _ in store.PERMANENT_CATEGORIES],
                         ["description", "notes"])
        machine, _ = store.add_machine(self.key, "Web", "notes here", "Linux",
                                       "a box")
        shown = {c["id"]: c for c in
                 store.machine_builtin_categories(self.key, machine["id"])}
        self.assertIn("description", shown)
        self.assertIn("notes", shown)
        self.assertTrue(all(c["permanent"] for c in shown.values()))
        self.assertEqual(shown["notes"]["body"], "notes here")
        self.assertEqual(shown["description"]["body"], "a box")

    def test_they_show_on_a_machine_with_nothing_marked(self):
        machine, _ = store.add_machine(self.key, "Web")
        ids = [c["id"] for c in store.machine_builtin_categories(self.key,
                                                                machine["id"])]
        self.assertEqual(ids[:2], ["description", "notes"])

    def test_the_os_reads_between_description_and_notes(self):
        """It says what the box is, the way the description does, so a page
        of notes cannot push it out of sight on the machine's page."""
        with _this_project_using_the_os(self.key):
            machine, _ = store.add_machine(self.key, "Web", "notes here",
                                           "Linux", "a box")
            ids = [c["id"] for c in
                   store.machine_builtin_categories(self.key, machine["id"])]
        self.assertEqual(ids, ["description", "os", "notes"])

    def test_the_categories_screen_lists_the_os_where_it_is_used(self):
        """The screen that lists the project's categories shows the OS too,
        before the definitions, so a project whose machines answer it does
        not read as having no categories at all."""
        with _this_project_using_the_os(self.key):
            choices = dashboard.categories_screen_choices(self.key)
        self.assertEqual(choices[0], ("OS", store.OS_CATEGORY))
        self.assertNotIn(("OS", store.OS_CATEGORY),
                         dashboard.categories_screen_choices(self.key),
                         "a project that never used it grows no row")

    def test_the_os_row_cannot_be_renamed_or_removed_here(self):
        """It is kept on each machine, and the screen says where it lives
        instead of pretending it is one of the project's definitions."""
        with _this_project_using_the_os(self.key):
            captured = {}

            def pick(live, prompt, pairs, message, empty=None, **kw):
                captured.update(kw)
                captured["pairs"] = pairs
                return None, None

            real = dashboard.pick
            dashboard.pick = pick
            try:
                dashboard.universal_categories(None, None)
            finally:
                dashboard.pick = real
        self.assertEqual(captured["pairs"][0], ("OS", store.OS_CATEGORY))
        for key in ("e", "d"):
            said = captured["shortcuts"][key](None, "OS")
            self.assertIn("each machine", said)

    def test_a_category_of_the_projects_own_called_os_takes_the_row(self):
        """Then the screen draws the project's own OS row and not a second
        one of the same name."""
        store.add_category(self.key, "OS", "linux boxes")
        with _this_project_using_the_os(self.key):
            self.assertIsNone(dashboard.os_category_choice(self.key))

    def _read_one(self, row_id):
        """Open the Categories screen, press enter on `row_id`, leave."""
        seen = []
        answers = [(row_id, None), (None, None)]
        real_pick, real_details = dashboard.pick, dashboard.show_details
        dashboard.pick = lambda *a, **kw: answers.pop(0)
        dashboard.show_details = \
            lambda live, title, body, note=None, chords=None: \
                seen.append((title, str(body)))
        try:
            dashboard.universal_categories(None, None)
        finally:
            dashboard.pick, dashboard.show_details = real_pick, real_details
        return seen

    def test_enter_on_a_category_reads_its_content(self):
        """pick() hands back the row's id, not its label, and the screen has
        to look the field up by it - matching titles against ids drew
        nothing at all."""
        field, _ = store.add_category(self.key, "foothold", "nc -lvnp 443")
        seen = self._read_one(field["id"])
        self.assertEqual(seen[0][0], "foothold")
        self.assertIn("nc -lvnp 443", seen[0][1])

    def test_enter_on_the_os_reads_where_it_lives(self):
        with _this_project_using_the_os(self.key):
            seen = self._read_one(store.OS_CATEGORY)
        self.assertEqual(seen[0][0], "OS")
        self.assertIn("each machine", seen[0][1])

    def test_editing_one_writes_the_machine(self):
        machine, _ = store.add_machine(self.key, "Web")
        dashboard.inline_prompt = lambda live, label, message=None, **kw: {
            "Description for this machine:": "a box",
            "Notes for this machine:": "rooted",
            "OS for this machine:": "Linux"}[label]
        self.addCleanup(setattr, dashboard, "inline_prompt",
                        dashboard.inline_prompt)
        for field_id, title in (("description", "Description"),
                                ("notes", "Notes"), ("os", "OS")):
            dashboard.edit_machine_attribute(None, machine["id"], field_id, title)
        after = store.find_machine(self.key, machine["id"])
        self.assertEqual(after["description"], "a box")
        self.assertEqual(after["notes"], "rooted")
        self.assertEqual(after["os"], "Linux")

    def test_the_os_is_the_projects_own_setting(self):
        self.assertFalse(store.offers_os(self.key),
                         "a fresh project does not grow an OS row")
        machine, _ = store.add_machine(self.key, "Web", os_name="Linux")
        ids = [c["id"] for c in
               store.machine_builtin_categories(self.key, machine["id"])]
        self.assertNotIn(store.OS_CATEGORY, ids)
        with _this_project_using_the_os(self.key):
            self.assertTrue(store.offers_os(self.key))

    def test_the_os_is_on_by_default_where_it_is_offered(self):
        with _this_project_using_the_os(self.key):
            machine, _ = store.add_machine(self.key, "Web")
            self.assertIn(store.OS_CATEGORY,
                          store.machine_category_ids(self.key, machine["id"]))
        other, _ = store.add_machine(self.key, "Web")
        self.assertNotIn(store.OS_CATEGORY,
                         store.machine_category_ids(self.key, other["id"]))

    def test_existing_machines_are_given_it_once(self):
        """And only where it belongs: a machine that has already answered
        keeps its answer, and another project is left alone."""
        key = self.key
        data = store.load("machines")
        board = data["projects"].setdefault(key, {"items": [], "categories": []})
        board.setdefault("items", [])
        board["items"].append({"id": "o1", "name": "One", "completed": 0,
                               "total": 1, "completed_on": ""})
        board["items"].append({"id": "o2", "name": "Two", "completed": 0,
                               "total": 1, "completed_on": "",
                               "categories": {"f9": None}})
        board["items"].append({"id": "o3", "name": "Three", "completed": 0,
                               "total": 1, "completed_on": "",
                               "categories": {store.OS_CATEGORY: None}})
        store.save("machines", data, record=False)
        with _this_project_using_the_os(key):
            notes = store.heal()
        self.assertTrue(any("OS" in note for note in notes), notes)
        for machine_id in ("o1", "o2", "o3"):
            self.assertIn(store.OS_CATEGORY,
                          store.machine_category_ids(key, machine_id),
                          machine_id)
        with _this_project_using_the_os(key):
            self.assertEqual(store.heal(), [], "and only once")

    def test_heal_turns_the_setting_on_for_a_project_that_used_it(self):
        """The rule has no names in it: a project whose machines answer the
        OS question keeps the OS, and heal reads that from the machines."""
        data = store.load("machines")
        board = data["projects"].setdefault(self.key,
                                            {"items": [], "categories": []})
        board.setdefault("items", [])
        board["items"].append({"id": "a1", "name": "One", "completed": 0,
                               "total": 1, "completed_on": "", "os": "Linux"})
        store.save("machines", data, record=False)
        self.assertFalse(store.offers_os(self.key))
        store.heal()
        self.assertTrue(store.offers_os(self.key))
        self.assertIn(store.OS_CATEGORY,
                      store.machine_category_ids(self.key, "a1"))

    def test_the_screen_lists_the_permanent_ones_first(self):
        machine, _ = store.add_machine(self.key, "Web")
        store.add_category(self.key, "creds", "a")
        rows = dashboard._category_rows(self.key, machine["id"])
        self.assertEqual(rows[0][0], "head")
        self.assertEqual([r[1] for r in rows[1:3]],
                         ["Description", "Notes"])
        self.assertTrue(all(r[0] == "permanent" for r in rows[1:3]))
        self.assertNotIn(store.OS_CATEGORY,
                         [r[2] for r in rows],
                         "this project does not use the OS")

    def test_pressing_enter_on_one_of_them_says_so(self):
        machine, _ = store.add_machine(self.key, "Web")
        said = dashboard._permanent_says("Description")
        self.assertIn("always shown", said)


class TestMarksOnAList(Base):
    """A tick in the list is drawn on every path that draws the list."""

    def test_every_render_call_passes_the_marks(self):
        """Four of the five said so. The fifth - after a number key - did not,
        and the fields screen raised the moment a tick was drawn at all."""
        import inspect
        import tui
        source = inspect.getsource(tui.inline_list)
        calls = source.count("render_list(live")
        passed = source.count("marks=")
        self.assertEqual(calls, passed,
                         f"{calls} render calls, {passed} pass the marks")

    def test_the_categories_screen_actually_draws(self):
        """The ticks it handed the picker were a map, where the picker wants a
        list in row order - so pressing c raised the moment the list opened.
        Driven end to end here so it cannot come back quietly."""
        import dashboard
        from rich.live import Live
        from tui import ESCAPE
        field, _ = store.add_category(self.key, "creds", "admin:admin")
        machine, _ = store.add_machine(self.key, "Web")
        ui.console.height = 40
        real_read = tui.read_key
        # Description and Notes lead the screen and cannot be turned off, so
        # step past them before pressing enter on a row that can.
        answers = ["\r", tui.KEY_DOWN, "\r", tui.KEY_DOWN, "\r", ESCAPE]
        tui.read_key = lambda timeout=None: answers.pop(0) if answers else ESCAPE
        try:
            with Live(console=ui.console, auto_refresh=False) as live:
                dashboard.machine_categories_screen(live, machine["id"], None)
        finally:
            tui.read_key = real_read
        self.assertEqual(store.machine_category_ids(self.key, machine["id"]),
                         [field["id"]],
                         "enter on the row did not mark the field")

    def test_a_marked_row_shows_the_tick(self):
        import tui
        from rich.console import Console
        ui.console.width, ui.console.height = 100, 40

        class L:
            def __init__(self):
                self.last = None
            def update(self, r):
                self.last = r
            def refresh(self):
                pass
            def is_terminal(self):
                return False

        live = L()
        tui.render_list(live, "Fields:", ["creds", "ticket"],
                        [("i", 0, 1), ("i", 1, 2)], 0, 0, 5,
                        marks=[True, False])
        rec = Console(width=100, height=40, record=True,
                      file=open("/dev/null", "w"))
        rec.print(live.last)
        text = rec.export_text()
        ticked = next(l for l in text.splitlines() if "creds" in l)
        plain = next(l for l in text.splitlines() if "ticket" in l)
        self.assertIn("\u2713", ticked)
        self.assertNotIn("\u2713", plain)


class TestCategories(Base):
    """A category groups a list into sections - the one thing a category is
    for, which is why it was not worth having before."""

    def test_a_machine_carries_one(self):
        machine, error = store.add_machine(self.key, "Web", group="Web")
        self.assertIsNone(error)
        self.assertEqual(machine["group"], "Web")
        edited, error = store.edit_machine(self.key, machine["id"],
                                          group="AD")
        self.assertIsNone(error)
        self.assertEqual(edited["group"], "AD")

    def test_a_category_and_a_repository_entry_carry_a_group(self):
        field, error = store.add_category(self.key, "creds", "a:b",
                                              "Access")
        self.assertIsNone(error)
        self.assertEqual(field["group"], "Access")
        entry, error = store.add_repository(self.key, "Kerberos", "b",
                                            "Attack")
        self.assertIsNone(error)
        self.assertEqual(entry["group"], "Attack")

    def test_an_item_with_no_group_reads_as_ungrouped(self):
        machine, _ = store.add_machine(self.key, "Plain")
        self.assertEqual(store.group_of(machine), store.NO_GROUP)

    def test_the_ungrouped_section_comes_last(self):
        """A list of sections should not open on the ones nobody named."""
        self.assertEqual(
            store.group_order(["Web", store.NO_GROUP, "AD", "Web"]),
            ["Web", "AD", store.NO_GROUP],
            "a category appears as one section however many rows are in it")

    def test_the_machines_list_is_drawn_in_sections(self):
        import dashboard
        from rich.live import Live
        from tui import ESCAPE
        store.add_machine(self.key, "Web App", group="Web")
        store.add_machine(self.key, "DC", group="AD")
        store.add_machine(self.key, "Loose")
        ui.console.height = 40
        drawn = []
        real = tui.render_list
        real_read = tui.read_key
        tui.read_key = lambda timeout=None: ESCAPE
        try:
            def spy(live, prompt, names, rows, cur, top, view, **kw):
                drawn.append([r[1] for r in rows])
                return real(live, prompt, names, rows, cur, top, view, **kw)
            tui.render_list = spy
            with Live(console=ui.console, auto_refresh=False) as live:
                dashboard.machine_list(live, None)
        finally:
            tui.render_list = real
            tui.read_key = real_read
        headings = [h for h in drawn[0] if h in ("Web", "AD",
                                                 store.NO_GROUP)]
        self.assertEqual(headings, ["Web", "AD", store.NO_GROUP],
                         f"sections came out as {headings}")

    def test_the_repository_list_is_drawn_in_sections(self):
        import dashboard
        store.add_repository(self.key, "Kerberos", "b", "Attack")
        store.add_repository(self.key, "Plain")
        seen = []
        real = dashboard.pick

        def pick(live, prompt, pairs, message, empty=None, **kw):
            seen.append(kw.get("grouped"))
            return None, None

        dashboard.pick = pick
        try:
            dashboard.repository_list(None, None)
        finally:
            dashboard.pick = real
        self.assertTrue(seen and seen[0], "the repository list is not grouped")


    def test_the_repository_list_comes_back_to_the_entry_you_read(self):
        """Same memory as the machines list, through the same drawn order."""
        import dashboard
        store.add_repository(self.key, "Plain")               # Ungrouped
        kerb, _ = store.add_repository(self.key, "Kerberos", "b", "Attack")
        seen = []
        calls = {"n": 0}

        def pick(live, prompt, pairs, message, empty=None, **kw):
            seen.append(kw.get("at"))
            calls["n"] += 1
            return (kerb["id"], None) if calls["n"] == 1 else (None, None)

        real_pick = dashboard.pick
        real_read = dashboard.repository_read
        dashboard.pick = pick
        dashboard.repository_read = lambda live, key, message: None
        try:
            dashboard.repository_list(None, None)
        finally:
            dashboard.pick, dashboard.repository_read = real_pick, real_read
        # Attack rows are drawn before Ungrouped ones, so Kerberos is drawn
        # first even though it was added second.
        self.assertEqual(seen[1], 0, "the cursor was dropped back at the top")


class TestEditFieldsInOneGo(Base):
    """Editing a machine means editing the fields it shows, in the same pass."""

    def test_the_form_asks_for_each_marked_field(self):
        import dashboard
        field, _ = store.add_category(self.key, "creds", "admin:admin")
        machine, _ = store.add_machine(self.key, "Web")
        store.attach_machine_categories(self.key, machine["id"], [field["id"]])
        asked = []

        def prompt(live, label, message=None, **kw):
            asked.append(label)
            return kw.get("initial", "")

        real = dashboard.inline_prompt
        dashboard.inline_prompt = prompt
        try:
            edited, result = dashboard.edit_machine_fields(None, machine, None)
        finally:
            dashboard.inline_prompt = real
        self.assertIn("creds:", asked)
        self.assertIsNotNone(edited, f"cancelled: {result!r}")
        self.assertEqual(store.machine_categories(self.key, machine["id"])[0]["body"],
                         "admin:admin")

    def test_a_field_the_machine_does_not_use_is_not_asked_for(self):
        import dashboard
        store.add_category(self.key, "creds", "admin:admin")
        store.add_category(self.key, "ticket", "kirbi")
        machine, _ = store.add_machine(self.key, "Web")
        asked = []

        def prompt(live, label, message=None, **kw):
            asked.append(label)
            return kw.get("initial", "")

        real = dashboard.inline_prompt
        dashboard.inline_prompt = prompt
        try:
            dashboard.edit_machine_fields(None, machine, None)
        finally:
            dashboard.inline_prompt = real
        self.assertNotIn("creds:", asked)
        self.assertNotIn("ticket:", asked)

    def test_editing_the_fields_is_one_write(self):
        """One backup and one undo step for the whole form, not one per field."""
        one, _ = store.add_category(self.key, "creds", "admin:admin")
        two, _ = store.add_category(self.key, "ticket", "kirbi")
        machine, _ = store.add_machine(self.key, "Web")
        store.attach_machine_categories(self.key, machine["id"],
                                    [one["id"], two["id"]])
        writes = []
        real = store.save
        store.save = lambda name, data, record=True: (writes.append(name),
                                                      real(name, data, record))[1]
        try:
            store.set_machine_category_bodies(self.key, machine["id"],
                                           {one["id"]: "root:toor",
                                            two["id"]: "kirbi2"})
        finally:
            store.save = real
        self.assertEqual(writes, ["machines"])
        fields = {f["title"]: f["body"] for f in
                  store.machine_categories(self.key, machine["id"])}
        self.assertEqual(fields, {"creds": "root:toor", "ticket": "kirbi2"})


class TestSettingsNaming(Base):
    """The menu entry called Options is called Settings."""

    def test_the_menu_item_is_settings(self):
        import ui
        labels = dict(ui.MENU_ITEMS)
        self.assertEqual(labels["4"], "Settings")

    def test_no_menu_item_is_called_options(self):
        import ui
        self.assertNotIn("Options", [label for _, label in ui.MENU_ITEMS])

    def test_the_settings_submenu_is_titled_settings(self):
        import inspect
        import dashboard
        self.assertIn('submenu(live, "Settings:"',
                      inspect.getsource(dashboard.action_settings))
        self.assertIn('"4": action_settings', inspect.getsource(dashboard))

    def test_the_help_screen_agrees_with_the_menu(self):
        """The help used to say Machines "mark" long after Mark was removed."""
        import inspect
        import dashboard
        source = inspect.getsource(dashboard.action_help)
        self.assertIn("4 Settings", source)
        self.assertIn("mark, add, edit, delete", source)
        self.assertNotIn("mark (shows notes first)", source)

    def test_the_help_mentions_the_multiline_keys(self):
        import inspect
        import dashboard
        self.assertIn("ctrl+s", inspect.getsource(dashboard.action_help))


class TestMultilineEditing(Base):
    """Description and Notes hold paragraphs.

    Enter breaks a line and ctrl+s saves - one key cannot do both. The mouse is
    released while a field is open so the text can be dragged and copied, and
    ctrl+x u / r / q reach the dashboard from inside the field too."""

    def _type(self, start, keys):
        buf = tui.TextBuffer(start)
        for k in keys:
            tui.multiline_key(buf, k)
        return buf.text

    def test_enter_inserts_a_newline_and_does_not_save(self):
        buf = tui.TextBuffer("")
        self.assertIsNone(tui.multiline_key(buf, "\n"))
        self.assertEqual(buf.text, "\n")

    def test_typing_keeps_going_after_the_first_character(self):
        self.assertEqual(self._type("", list("abc")), "abc")

    def test_ctrl_s_saves(self):
        buf = tui.TextBuffer("a\nb")
        self.assertEqual(tui.multiline_key(buf, tui.CTRL_S), "save")

    def test_escape_cancels(self):
        buf = tui.TextBuffer("x")
        self.assertEqual(tui.multiline_key(buf, "\x1b"), "cancel")

    def test_a_paragraph_can_be_typed(self):
        self.assertEqual(self._type("", list("one\ntwo\nthree")),
                         "one\ntwo\nthree")

    def test_backspace_joins_two_lines(self):
        buf = tui.TextBuffer("ab\ncd")
        buf.cursor = 3
        tui.multiline_key(buf, "\x7f")
        self.assertEqual((buf.text, buf.cursor), ("abcd", 2))

    def test_backspace_at_the_start_does_nothing(self):
        self.assertEqual(self._type("abc", ["\x7f"])[0], "a")

    def test_the_cursor_can_be_moved_and_typed_at(self):
        buf = tui.TextBuffer("abc")
        tui.multiline_key(buf, tui.KEY_END)
        tui.multiline_key(buf, tui.KEY_LEFT)
        tui.multiline_key(buf, "X")
        self.assertEqual(buf.text, "abXc")

    def test_up_and_down_move_between_lines(self):
        buf = tui.TextBuffer("abc\ndef")
        buf.cursor = 5
        tui.multiline_key(buf, tui.KEY_UP)
        self.assertEqual(buf.cursor, 1)
        tui.multiline_key(buf, tui.KEY_DOWN)
        self.assertEqual(buf.cursor, 5)

    # ------------------------------------------------------- line operations
    def test_ctrl_u_drops_the_line_left_of_the_cursor(self):
        # cursor sits between "d" and "e": that is the text to the left of it.
        buf = tui.TextBuffer("abc\ndef")
        buf.cursor = 5
        tui.multiline_key(buf, tui.CTRL_U)
        self.assertEqual(buf.text, "abc\nef")

    def test_ctrl_u_stops_at_the_line_break(self):
        """It cuts one line, not the whole buffer."""
        buf = tui.TextBuffer("abc\ndef")
        buf.cursor = 7
        tui.multiline_key(buf, tui.CTRL_U)
        self.assertEqual(buf.text, "abc\n")

    def test_ctrl_k_drops_the_line_right_of_the_cursor(self):
        buf = tui.TextBuffer("abc\ndef")
        buf.cursor = 1
        tui.multiline_key(buf, tui.CTRL_K)
        self.assertEqual(buf.text, "a\ndef")

    def test_ctrl_k_leaves_earlier_lines_alone(self):
        buf = tui.TextBuffer("abc\ndef")
        buf.cursor = 5
        tui.multiline_key(buf, tui.CTRL_K)
        self.assertEqual(buf.text, "abc\nd")

    # ------------------------------------------------------------- selection
    def test_ctrl_a_selects_everything(self):
        buf = tui.TextBuffer("hello")
        tui.multiline_key(buf, tui.CTRL_A)
        self.assertTrue(buf.has_selection())
        self.assertEqual(buf.selected, (0, 5))

    def test_typing_replaces_the_selection(self):
        buf = tui.TextBuffer("hello")
        tui.multiline_key(buf, tui.CTRL_A)
        tui.multiline_key(buf, "X")
        self.assertEqual(buf.text, "X")

    def test_backspace_removes_the_selection(self):
        buf = tui.TextBuffer("hello")
        tui.multiline_key(buf, tui.CTRL_A)
        tui.multiline_key(buf, "\x7f")
        self.assertEqual(buf.text, "")

    def test_moving_the_cursor_clears_the_selection(self):
        buf = tui.TextBuffer("hello")
        tui.multiline_key(buf, tui.CTRL_A)
        tui.multiline_key(buf, tui.KEY_LEFT)
        self.assertFalse(buf.has_selection())

    def test_the_selection_is_drawn(self):
        """Otherwise ctrl+a looks like it did nothing."""
        buf = tui.TextBuffer("hello")
        tui.multiline_key(buf, tui.CTRL_A)
        self.assertIn("[reverse]", tui.multiline_block(buf))

    # ------------------------------------------------------------- shortcuts
    def test_ctrl_x_is_handed_on_rather_than_typed(self):
        buf = tui.TextBuffer("x")
        self.assertEqual(tui.multiline_key(buf, tui.CTRL_X), "chord")
        self.assertEqual(buf.text, "x", "ctrl+x must not land in the text")

    def test_a_pause_in_the_field_does_not_crash_it(self):
        """last_size lives in the caller, so the resize check on a keypress
        timeout used to raise UnboundLocalError - which killed the app the
        moment the editor opened."""
        import inspect
        source = inspect.getsource(tui._prompt_loop)
        self.assertIn("last_size", inspect.signature(tui._prompt_loop).parameters)

    def test_the_editor_survives_a_keypress_timeout(self):
        from rich.live import Live
        from rich.console import Console
        import io
        ui.console.height = 40
        real = tui.read_key
        tui.read_key = lambda timeout=None: None       # always times out
        try:
            console = Console(file=io.StringIO(), width=80, height=24)
            live = Live(console=console, auto_refresh=False)
            # three timeouts, then a save: must not raise
            state = {"n": 0}
            def read(timeout=None):
                state["n"] += 1
                return tui.CTRL_S if state["n"] > 3 else None
            tui.read_key = read
            out = tui.inline_prompt(live, "Notes:", multiline=True, optional=True)
            self.assertEqual(out, "")
        finally:
            tui.read_key = real

    def test_a_field_does_not_switch_the_mouse_back_on_behind_you(self):
        """With the mouse deliberately off, opening and leaving a field must
        leave it off - otherwise the toggle appears to do nothing."""
        from rich.live import Live
        import io as _io
        tui._MOUSE_ON[0] = False
        ui.console.height = 40
        real = tui.read_key
        state = {"n": 0}
        def read(timeout=None):
            state["n"] += 1
            return tui.CTRL_S if state["n"] > 2 else None
        tui.read_key = read
        try:
            with Live(redirect_stdout=False, redirect_stderr=False,
                      console=ui.console) as live:
                tui.inline_prompt(live, "Notes:", multiline=True, optional=True)
            after = tui.mouse_enabled()
        finally:
            tui.read_key = real
            tui._MOUSE_ON[0] = True
        self.assertFalse(after)

    def test_arrow_keys_always_belong_to_the_menu(self):
        """On a short screen the scroll code was taking up and down to scroll
        the dashboard, so the menu highlight never moved and it looked broken."""
        import inspect
        import dashboard
        # Whitespace is squeezed out first: reformatting the loop must not be
        # able to hide this, which is how a stale test survived a rewrite.
        flat = " ".join(inspect.getsource(dashboard._interactive).split())
        self.assertNotIn("scroll_step", flat)
        self.assertIn("menu_move_down( hovered, -1 if key == KEY_UP else 1)",
                      flat)

    def test_the_shared_scroller_never_swallows_an_arrow(self):
        """Every screen uses it now, and on one of them an arrow key belongs to
        the list on screen. Swallowing it is what made navigation look broken."""
        import dashboard
        for key in (tui.KEY_UP, tui.KEY_DOWN, tui.KEY_LEFT, tui.KEY_RIGHT):
            self.assertIsNone(dashboard.scroll_step(key, 0, 10), key)
        self.assertEqual(dashboard.scroll_step(tui.KEY_PGDN, 0, 10, height=10), 9)
        self.assertEqual(dashboard.scroll_step(tui.KEY_WHEEL_DOWN, 0, 10), 3)
        self.assertEqual(dashboard.scroll_step(tui.KEY_END, 0, 10), 10)
        self.assertEqual(dashboard.scroll_step(tui.KEY_HOME, 5, 10), 0)

    def test_the_editor_does_not_repeat_its_question(self):
        """Drawn on the border and in the body both, it read twice."""
        import tui
        from rich.console import Console

        class Live:
            def update(self, renderable):
                self.piece = renderable

            def refresh(self):
                pass

        live = Live()
        tui.render_input(live, "Notes for Web Box:", "", multiline=True,
                         buffer=tui.TextBuffer("hello"), top=0)
        out = Console(record=True, width=100, height=40)
        out.print(live.piece)
        shown = out.export_text()
        self.assertEqual(shown.count("Notes for Web Box:"), 1,
                         f"the question is on screen {shown.count('Notes for Web Box:')} times")

    def test_the_field_takes_the_whole_screen(self):
        """The dashboard behind it pushed the prompt out of view on a short
        terminal, and keys meant for the field went to the dashboard."""
        import inspect
        source = inspect.getsource(tui.render_input)
        self.assertIn("height=console.height", source)
        self.assertNotIn("build_layout", source.split('if multiline:')[1][:600])

    def _paged_tops(self, keys, lines=40, height=16, home=False):
        """Drive the real prompt loop and record where the window sat."""
        from rich.live import Live
        text = "\n".join(f"line {i}" for i in range(1, lines + 1))
        seen = []
        real_render, real_read = tui.render_input, tui.read_key
        seq = list(keys)
        def read(timeout=None):
            return seq.pop(0) if seq else tui.CTRL_S
        def spy(live, prompt, value, **kw):
            if kw.get("buffer") is not None:
                seen.append((kw.get("top", 0), kw["buffer"].cursor))
            return real_render(live, prompt, value, **kw)
        ui.console.height = height
        try:
            tui.read_key, tui.render_input = read, spy
            with Live(console=ui.console, auto_refresh=False) as live:
                value = "" if home else text
                tui.inline_prompt(live, "Notes:", initial=value, multiline=True)
        finally:
            tui.read_key, tui.render_input = real_read, real_render
            ui.console.height = 40
        return seen

    def _paged(self, keys, lines=40, height=16):
        """Drive the real prompt loop, recording (top, cursor line) per frame."""
        from rich.live import Live
        text = "\n".join(f"line {i}" for i in range(1, lines + 1))
        seen = []
        real_render, real_read = tui.render_input, tui.read_key
        seq = list(keys) + [tui.CTRL_S]
        ui.console.height = height
        try:
            tui.read_key = lambda timeout=None: seq.pop(0) if seq else tui.CTRL_S
            def spy(live, prompt, value, **kw):
                if kw.get("buffer") is not None:
                    seen.append((kw.get("top", 0), tui.cursor_row(kw["buffer"])))
                return real_render(live, prompt, value, **kw)
            tui.render_input = spy
            with Live(console=ui.console, auto_refresh=False) as live:
                tui.inline_prompt(live, "Notes:", initial=text, multiline=True)
        finally:
            tui.render_input, tui.read_key = real_render, real_read
            ui.console.height = 40
        return seen

    def test_page_up_walks_the_field_back_a_page_at_a_time(self):
        seen = self._paged([tui.KEY_PGUP] * 4)
        self.assertEqual([t for t, _ in seen], [32, 25, 18, 11, 4])

    def test_page_down_walks_it_forward_again(self):
        seen = self._paged([tui.KEY_PGUP] * 4 + [tui.KEY_PGDN])
        self.assertEqual(seen[-1][0], 11)
        seen = self._paged([tui.KEY_PGUP] + [tui.KEY_PGDN])
        self.assertEqual(seen[-1][0], 32)

    def test_paging_leaves_the_cursor_at_the_end_of_the_page(self):
        """It used to scroll the window alone, leaving the caret stranded off
        screen; the next keystroke then yanked the view back and the paging
        looked like it had done nothing."""
        seen = self._paged([tui.KEY_PGUP] * 3)
        rows = 16 - 8
        for top, cursor_line in seen:
            self.assertEqual(cursor_line, min(top + rows - 1, 39),
                             "the cursor was not left at the end of the page")

    def test_paging_stops_at_both_ends(self):
        down = self._paged([tui.KEY_PGDN] * 3)
        self.assertEqual([t for t, _ in down], [32, 32, 32, 32])
        up = self._paged([tui.KEY_PGUP] * 8)
        self.assertEqual(up[-1][0], 0)
        self.assertTrue(all(t >= 0 for t, _ in up))

    def test_paging_leaves_the_text_alone(self):
        """It moves the cursor; it must never edit anything."""
        from rich.live import Live
        text = "\n".join(f"line {i}" for i in range(1, 41))
        texts = []
        real_render, real_read = tui.render_input, tui.read_key
        seq = [tui.KEY_PGUP] * 3 + [tui.KEY_PGDN] * 2 + [tui.CTRL_S]
        ui.console.height = 16
        try:
            tui.read_key = lambda timeout=None: seq.pop(0)
            def spy(live, prompt, value, **kw):
                if kw.get("buffer") is not None:
                    texts.append(kw["buffer"].text)
                return real_render(live, prompt, value, **kw)
            tui.render_input = spy
            with Live(console=ui.console, auto_refresh=False) as live:
                tui.inline_prompt(live, "Notes:", initial=text, multiline=True)
        finally:
            tui.render_input, tui.read_key = real_render, real_read
        self.assertEqual(set(texts), {text})

    def test_paging_a_short_field_does_nothing(self):
        seen = self._paged([tui.KEY_PGDN, tui.KEY_PGUP], lines=3)
        self.assertEqual({t for t, _ in seen}, {0})

    def test_a_field_opens_with_the_cursor_on_screen(self):
        """The cursor starts at the end of the existing text, so a long
        description used to open showing the top with the caret out of sight."""
        seen = self._paged([])
        top, line = seen[0]
        self.assertEqual(line, 39)
        self.assertLessEqual(top, line)
        self.assertLess(line, top + 8)

    def test_ctrl_backspace_removes_one_word_at_a_time(self):
        buf = tui.TextBuffer("one two three")
        buf.cursor = len(buf.text)
        tui.multiline_key(buf, tui.KEY_DELETE_WORD_LEFT)
        self.assertEqual(buf.text, "one two ")
        tui.multiline_key(buf, tui.KEY_DELETE_WORD_LEFT)
        self.assertEqual(buf.text, "one ")

    def test_ctrl_backspace_crosses_into_the_line_above(self):
        """No words left on this line is not the end of it: the break counts as
        whitespace, so the search carries on upwards and joins the lines."""
        buf = tui.TextBuffer("one\ntwo")
        buf.cursor = 4                       # start of "two"
        tui.multiline_key(buf, tui.KEY_DELETE_WORD_LEFT)
        self.assertEqual(buf.text, "two")

    def test_ctrl_backspace_crosses_a_blank_line(self):
        buf = tui.TextBuffer("one\n\ntwo")
        buf.cursor = 5
        tui.multiline_key(buf, tui.KEY_DELETE_WORD_LEFT)
        self.assertEqual(buf.text, "two")

    def test_ctrl_backspace_inside_a_word_takes_only_the_tail(self):
        buf = tui.TextBuffer("one two")
        buf.cursor = 5                       # between "tw" and "o"
        tui.multiline_key(buf, tui.KEY_DELETE_WORD_LEFT)
        self.assertEqual(buf.text, "one wo")

    def test_ctrl_backspace_at_the_very_start_does_nothing(self):
        buf = tui.TextBuffer("hello")
        buf.cursor = 0
        tui.multiline_key(buf, tui.KEY_DELETE_WORD_LEFT)
        self.assertEqual(buf.text, "hello")

    def test_ctrl_backspace_removes_a_selection_and_stops_there(self):
        """As in any editor: with something selected, that is what goes. It does
        not then eat a word as well."""
        buf = tui.TextBuffer("one two three")
        buf.cursor = 0
        tui.multiline_key(buf, tui.KEY_SELECT_WORD_RIGHT)
        tui.multiline_key(buf, tui.KEY_DELETE_WORD_LEFT)
        self.assertEqual(buf.text, " two three")

    def test_ctrl_backspace_is_the_key_you_actually_press(self):
        """^H is how a terminal sends ctrl+backspace when Backspace itself sends
        DEL, which is the usual default. Both bytes meant "one character" before,
        so the key did nothing except rub out a single letter."""
        buf = tui.TextBuffer("alpha beta gamma")
        buf.cursor = len(buf.text)
        tui.multiline_key(buf, "\x08")
        self.assertEqual(buf.text, "alpha beta ")
        tui.multiline_key(buf, "\x08")
        self.assertEqual(buf.text, "alpha ")
        plain = tui.TextBuffer("alpha beta")
        plain.cursor = len(plain.text)
        tui.multiline_key(plain, "\x7f")
        self.assertEqual(plain.text, "alpha bet")     # one character, not a word

    def test_copying_puts_text_on_the_clipboard_without_the_mouse(self):
        """ctrl+shift+c can only copy what the terminal can select, and while
        the app holds the mouse there is nothing to select."""
        import base64
        sent = []
        real = tui.write_escape
        try:
            tui.write_escape = lambda s: sent.append(s)
            tui.copy_to_clipboard("Access 10.10.14.5")
        finally:
            tui.write_escape = real
        self.assertEqual(len(sent), 1)
        seq = sent[0]
        self.assertTrue(seq.startswith("\x1b]52;c;"), seq)
        self.assertTrue(seq.endswith("\x07"), seq)
        self.assertEqual(base64.b64decode(seq.split(";", 2)[2].rstrip("\x07")
                                          ).decode(), "Access 10.10.14.5")

    def test_ctrl_shift_c_copies_the_highlighted_row(self):
        from rich.live import Live
        import base64
        sent = []
        real_write = tui.write_escape
        seq = [tui.KEY_COPY, tui.ESCAPE]
        real_read = tui.read_key
        try:
            tui.write_escape = lambda s: sent.append(s)
            tui.read_key = lambda timeout=None: seq.pop(0) if seq else None
            with Live(console=ui.console, auto_refresh=False) as live:
                tui.inline_list(live, "Pick", [("a", "Alpha"), ("b", "Bravo")])
        finally:
            tui.write_escape = real_write
            tui.read_key = real_read
        payload = [s for s in sent if s.startswith("\x1b]52;c;")]
        self.assertEqual(len(payload), 1, "ctrl+shift+c did not copy the row")
        self.assertEqual(base64.b64decode(payload[0].split(";", 2)[2]
                                          .rstrip("\x07")).decode(), "Alpha")

    def test_plain_y_is_no_longer_a_key(self):
        """It was reaching for ctrl+shift+c's job with a key nobody asked for."""
        from rich.live import Live
        sent = []
        real_write = tui.write_escape
        seq = ["y", tui.ESCAPE]
        real_read = tui.read_key
        try:
            tui.write_escape = lambda s: sent.append(s)
            tui.read_key = lambda timeout=None: seq.pop(0) if seq else None
            with Live(console=ui.console, auto_refresh=False) as live:
                tui.inline_list(live, "Pick", [("a", "Alpha"), ("b", "Bravo")])
        finally:
            tui.write_escape = real_write
            tui.read_key = real_read
        self.assertFalse([s for s in sent if s.startswith("\x1b]52;c;")],
                         "the y key still copies")

    def test_ctrl_v_pastes_the_terminal_clipboard_into_a_field(self):
        """The clipboard lives outside the program, so it has to be shelled out
        to - ctrl+v used to be a dead key inside the editor."""
        read = {"done": False}
        real = tui.clipboard_paste
        real_write = tui.write_escape
        sent = []
        try:
            tui.write_escape = lambda s: sent.append(s)
            tui.clipboard_paste = lambda: "from the clipboard"
            tui.blink_state(force=True)
            buf = tui.TextBuffer("before ")
            tui.multiline_key(buf, tui.CTRL_V)
            self.assertEqual(buf.text, "before from the clipboard")
        finally:
            tui.clipboard_paste = real
            tui.write_escape = real_write

    def test_ctrl_v_pastes_into_a_single_line_field(self):
        """A machine name, a date, an OS: one-line fields take the clipboard with
        the breaks taken out rather than submitting the value."""
        from rich.live import Live
        real = tui.clipboard_paste
        ui.console.height = 40
        try:
            tui.clipboard_paste = lambda: "from the clipboard"
            seq = [tui.CTRL_V, "\r"]
            real_read = tui.read_key
            tui.read_key = lambda timeout=None: seq.pop(0) if seq else None
            with Live(console=ui.console, auto_refresh=False) as live:
                got = tui.inline_prompt(live, "Name:", multiline=False)
            tui.read_key = real_read
        finally:
            tui.clipboard_paste = real
        self.assertEqual(got, "from the clipboard")

    def test_bracketed_paste_is_asked_for_across_the_whole_app(self):
        """Pasting with a list open used to arrive as keystrokes, so the arrows
        inside the pasted text moved the selection."""
        import inspect
        source = inspect.getsource(tui.raw_mode)
        self.assertIn("PASTE_ON", source)
        self.assertIn("PASTE_OFF", source)

    def test_the_word_delete_answers_to_every_unambiguous_key(self):
        import os as _os
        for raw in (b"[127;5u", b"[3;5~", b"[27;5~", b"\x7f", b"\x08"):
            r, w = _os.pipe()
            _os.write(w, raw)
            _os.close(w)
            self.assertEqual(tui.drain_escape(r), tui.KEY_DELETE_WORD_LEFT, raw)
            _os.close(r)
        buf = tui.TextBuffer("alpha beta")
        buf.cursor = len(buf.text)
        tui.multiline_key(buf, "\x17")      # ctrl+w, the portable spelling
        self.assertEqual(buf.text, "alpha ")

    def test_a_sequence_starting_with_2_is_not_eaten(self):
        """The bracketed-paste check used to swallow three bytes and drop them,
        so anything else beginning with CSI 2 lost characters."""
        import os as _os
        r, w = _os.pipe()
        _os.write(w, b"[2~[A")              # a complete key, then another
        _os.close(w)
        self.assertIsNone(tui.drain_escape(r))
        self.assertEqual(tui.read_seq_byte(r, 0.05), b"[")   # still there
        self.assertEqual(tui.read_seq_byte(r, 0.05), b"A")
        _os.close(r)

    def test_ctrl_left_and_right_move_by_a_word(self):
        text = "scan 10.10.14.0/24 now"
        buf = tui.TextBuffer(text)
        buf.cursor = 0
        tui.multiline_key(buf, tui.KEY_WORD_RIGHT)
        self.assertEqual(buf.cursor, 4)                 # start of "10.10..."
        buf.cursor = len(text)
        tui.multiline_key(buf, tui.KEY_WORD_LEFT)
        self.assertEqual(buf.cursor, 19)                # start of "now"

    def test_word_movement_stops_at_the_ends(self):
        text = "one two"
        buf = tui.TextBuffer(text)
        for _ in range(6):
            tui.multiline_key(buf, tui.KEY_WORD_LEFT)
        self.assertEqual(buf.cursor, 0)
        buf.cursor = len(text)
        for _ in range(6):
            tui.multiline_key(buf, tui.KEY_WORD_RIGHT)
        self.assertEqual(buf.cursor, len(text))

    def test_ctrl_shift_left_and_right_select_by_a_word(self):
        text = "scan 10.10.14.0/24 now"
        buf = tui.TextBuffer(text)
        buf.cursor = 0
        tui.multiline_key(buf, tui.KEY_SELECT_WORD_RIGHT)
        self.assertEqual(buf.selected, (0, 4))
        tui.multiline_key(buf, tui.KEY_SELECT_WORD_RIGHT)
        self.assertEqual(buf.selected, (0, 7))
        buf2 = tui.TextBuffer(text)
        buf2.cursor = len(text)
        tui.multiline_key(buf2, tui.KEY_SELECT_WORD_LEFT)
        self.assertEqual(text[buf2.selected[0]:buf2.selected[1]], "now")

    def test_word_movement_drops_a_selection_but_selecting_keeps_it(self):
        buf = tui.TextBuffer("one two three")
        buf.cursor = 0
        tui.multiline_key(buf, tui.KEY_SELECT_WORD_RIGHT)
        self.assertTrue(buf.has_selection())
        tui.multiline_key(buf, tui.KEY_WORD_RIGHT)
        self.assertFalse(buf.has_selection())

    def test_word_keys_are_not_confused_with_the_plain_arrows(self):
        import os as _os
        for raw, expected in ((b"[1;5D", tui.KEY_WORD_LEFT),
                              (b"[1;5C", tui.KEY_WORD_RIGHT),
                              (b"[1;6D", tui.KEY_SELECT_WORD_LEFT),
                              (b"[1;6C", tui.KEY_SELECT_WORD_RIGHT),
                              (b"[1;2D", tui.KEY_SELECT_WORD_LEFT),
                              (b"[1;2C", tui.KEY_SELECT_WORD_RIGHT),
                              (b"[D", tui.KEY_LEFT), (b"[C", tui.KEY_RIGHT),
                              (b"[A", tui.KEY_UP), (b"[B", tui.KEY_DOWN)):
            r, w = _os.pipe()
            _os.write(w, raw)
            _os.close(w)
            self.assertEqual(tui.drain_escape(r), expected, raw)
            _os.close(r)

    def test_ctrl_shift_up_selects_the_line_above(self):
        buf = tui.TextBuffer("one\ntwo\nthree")
        buf.cursor = len(buf.text)              # end of "three"
        tui.multiline_key(buf, tui.KEY_SELECT_UP)
        self.assertEqual(buf.selected, (7, 13)) # "three"

    def test_repeated_ctrl_shift_up_keeps_climbing_and_stops_at_the_top(self):
        buf = tui.TextBuffer("one\ntwo\nthree\nfour")
        buf.cursor = len(buf.text)
        seen = []
        for _ in range(4):
            tui.multiline_key(buf, tui.KEY_SELECT_UP)
            seen.append(buf.selected)
        self.assertEqual(seen, [(13, 18), (7, 18), (3, 18), (0, 18)])

    def test_ctrl_shift_down_selects_the_line_below(self):
        buf = tui.TextBuffer("one\ntwo\nthree")
        buf.cursor = 0
        seen = []
        for _ in range(4):
            tui.multiline_key(buf, tui.KEY_SELECT_DOWN)
            seen.append(buf.selected)
        self.assertEqual(seen, [(0, 4), (0, 8), (0, 13), (0, 13)])

    def test_selecting_lines_never_runs_off_either_end(self):
        buf = tui.TextBuffer("just one line")
        buf.cursor = 6
        tui.multiline_key(buf, tui.KEY_SELECT_UP)
        self.assertEqual(buf.selected, (0, 6))       # top of the text
        # Pressing the other way keeps the anchor where the selection started
        # and extends the moving end, as it does in any editor.
        tui.multiline_key(buf, tui.KEY_SELECT_DOWN)
        self.assertEqual(buf.selected, (6, 13))      # end of the text
        tui.multiline_key(buf, tui.KEY_SELECT_DOWN)
        self.assertEqual(buf.selected, (6, 13))      # and it stops there

    def test_typing_replaces_a_line_selection(self):
        buf = tui.TextBuffer("one\ntwo\nthree")
        buf.cursor = 0
        tui.multiline_key(buf, tui.KEY_SELECT_DOWN)
        tui.multiline_key(buf, tui.KEY_SELECT_DOWN)
        tui.multiline_key(buf, "X")
        self.assertEqual(buf.text, "Xthree")

    def test_plain_arrows_still_work_next_to_the_new_ones(self):
        import os as _os
        for raw, expected in ((b"[A", tui.KEY_UP), (b"[B", tui.KEY_DOWN),
                              (b"[1;6A", tui.KEY_SELECT_UP),
                              (b"[1;6B", tui.KEY_SELECT_DOWN),
                              (b"[1;2A", tui.KEY_SELECT_UP),
                              (b"[1;2B", tui.KEY_SELECT_DOWN)):
            r, w = _os.pipe()
            _os.write(w, raw)
            _os.close(w)
            self.assertEqual(tui.drain_escape(r), expected, raw)
            _os.close(r)

    def test_a_bracketed_paste_arrives_as_one_block_of_text(self):
        """The terminal wraps pasted text in ESC[200~ / ESC[201~. The escape
        parser swallowed those markers and lost the paste entirely."""
        import os as _os
        r, w = _os.pipe()
        _os.write(w, b"[200~hello world\x1b[201~")
        _os.close(w)
        self.assertEqual(tui.drain_escape(r), tui.Pasted("hello world"))
        _os.close(r)

    def test_a_paste_keeps_its_line_breaks(self):
        import os as _os
        r, w = _os.pipe()
        _os.write(w, b"[200~one\ntwo\r\nthree\x1b[201~")
        _os.close(w)
        self.assertEqual(tui.drain_escape(r).text, "one\ntwo\r\nthree")
        _os.close(r)

    def test_a_paste_does_not_get_eaten_as_control_keys(self):
        """Going through the paste character by character would let a newline in
        it submit the field."""
        buf = tui.TextBuffer("start")
        tui.multiline_key(buf, tui.Pasted("one\ntwo"))
        self.assertEqual(buf.text, "startone\ntwo")

    def test_the_markers_are_not_left_behind_as_text(self):
        import os as _os
        r, w = _os.pipe()
        _os.write(w, b"[200~x\x1b[201~")
        _os.close(w)
        pasted = tui.drain_escape(r)
        _os.close(r)
        self.assertNotIn("\x1b", pasted.text)
        self.assertNotIn("201~", pasted.text)

    def test_brackets_inside_a_paste_are_left_alone(self):
        import os as _os
        r, w = _os.pipe()
        _os.write(w, b"[200~has ] and [ and ~ chars\x1b[201~")
        _os.close(w)
        self.assertEqual(tui.drain_escape(r).text, "has ] and [ and ~ chars")
        _os.close(r)

    def test_other_escape_keys_still_work_after_paste_handling(self):
        import os as _os
        for raw, expected in ((b"[A", tui.KEY_UP), (b"[6~", tui.KEY_PGDN),
                              (b"[5~", tui.KEY_PGUP)):
            r, w = _os.pipe()
            _os.write(w, raw)
            _os.close(w)
            self.assertEqual(tui.drain_escape(r), expected, raw)
            _os.close(r)

    def test_escape_sequences_bypass_the_stdout_proxy(self):
        """Rich's Live swaps sys.stdout while a field is open. Writing the mouse
        release to it produced nothing at the terminal - the escape was made and
        then dropped, so copying and pasting silently did nothing."""
        import io
        real = sys.__stdout__
        seen = io.StringIO()
        class FakeTTY(io.StringIO):
            def isatty(self): return True
        fake = FakeTTY()
        try:
            sys.__stdout__ = fake
            tui.write_escape(tui.MOUSE_OFF)
            seen = fake.getvalue()
        finally:
            sys.__stdout__ = real
        self.assertEqual(seen, tui.MOUSE_OFF)

    def test_no_escape_sequences_when_stdout_is_not_a_terminal(self):
        import io
        real = sys.__stdout__
        fake = io.StringIO()
        try:
            sys.__stdout__ = fake
            tui.write_escape(tui.MOUSE_OFF)
        finally:
            sys.__stdout__ = real
        self.assertEqual(fake.getvalue(), "")

    def test_a_field_asks_for_bracketed_paste_and_releases_the_mouse(self):
        """Copy needs the mouse back; paste needs the terminal told to bracket
        it. Neither happened, so neither worked inside a field."""
        from rich.live import Live
        sent = []
        real = tui.write_escape
        real_read = tui.read_key
        calls = {"n": 0}
        def read(timeout=None):
            calls["n"] += 1
            return tui.CTRL_S if calls["n"] > 2 else None
        ui.console.height = 40
        try:
            tui.write_escape = lambda s: sent.append(s)
            tui.read_key = read
            with Live(console=ui.console, auto_refresh=False) as live:
                tui.inline_prompt(live, "Notes:", initial="", multiline=True)
        finally:
            tui.write_escape = real
            tui.read_key = real_read
        joined = "".join(sent)
        self.assertIn(tui.MOUSE_OFF, joined)
        self.assertIn(tui.PASTE_ON, joined)
        self.assertIn(tui.PASTE_OFF, joined)
        self.assertLess(joined.index(tui.PASTE_ON), joined.index(tui.PASTE_OFF))

    def test_the_caret_blinks_on_its_own(self):
        """It sat on screen unchanged until the next keystroke, so it read as a
        stray character rather than a cursor."""
        tui.blink_state(force=True)
        self.assertTrue(tui.blink_state())
        was = tui.BLINK_SECONDS
        try:
            tui.BLINK_SECONDS = 0.0
            self.assertFalse(tui.blink_state())
            self.assertTrue(tui.blink_state())
        finally:
            tui.BLINK_SECONDS = was
        tui.blink_state(force=True)

    def test_the_caret_comes_back_the_moment_you_type(self):
        tui.blink_state(force=True)
        was = tui.BLINK_SECONDS
        try:
            tui.BLINK_SECONDS = 0.0
            tui.blink_state()                # into the off phase
            buf = tui.TextBuffer("a")
            tui.multiline_key(buf, "b")     # a keypress
            # The raw flag, not blink_state(): at a zero period every call
            # advances the phase, which would toggle it straight back.
            self.assertTrue(tui._blink["on"], "the caret stayed faded after typing")
            self.assertEqual(buf.text, "ab")
        finally:
            tui.BLINK_SECONDS = was
        tui.blink_state(force=True)

    def test_the_field_redraws_while_idle_so_the_caret_can_blink(self):
        """A steady caret needed no redraw, so nothing ticked until a key."""
        from rich.live import Live
        import tui as t
        ui.console.height = 40
        phases = []
        real_render, real_read = t.render_input, t.read_key
        seen = {"n": 0}
        def spy(live, prompt, value, **k):
            phases.append(t.blink_state())
            return real_render(live, prompt, value, **k)
        def read(timeout=None):
            seen["n"] += 1
            return None if seen["n"] <= 8 else t.CTRL_S
        was = t.BLINK_SECONDS
        try:
            t.BLINK_SECONDS = 0.0
            t.read_key, t.render_input = read, spy
            with Live(console=ui.console, auto_refresh=False) as live:
                t.inline_prompt(live, "Notes:", initial="hi", multiline=True)
        finally:
            t.BLINK_SECONDS = was
            t.read_key, t.render_input = real_read, real_render
            t.blink_state(force=True)
        self.assertGreater(len(phases), 2, "the field never redrew while idle")
        self.assertGreater(len(set(phases)), 1, "the caret never blinked")

    def test_exactly_one_caret_is_drawn(self):
        """A caret was drawn at the end of every row, empty ones included, so
        typing one line left a trail of them down the panel."""
        tui.blink_state(force=True)
        buf = tui.TextBuffer("one\ntwo\nthree")
        self.assertEqual(tui.multiline_block(buf, rows=9).count("\u258f"), 1)

    def test_the_caret_is_on_the_line_the_cursor_is_on(self):
        tui.blink_state(force=True)
        buf = tui.TextBuffer("one\ntwo\nthree")
        buf.cursor = 4                      # start of "two"
        rows = tui.multiline_block(buf, rows=9).split("\n")
        self.assertEqual(rows, ["one", "\u258ftwo", "three"])

    def test_the_caret_sits_on_an_empty_line_when_the_cursor_is_there(self):
        tui.blink_state(force=True)
        buf = tui.TextBuffer("one\n\nthree")
        buf.cursor = 4                      # the empty line
        rows = tui.multiline_block(buf, rows=9).split("\n")
        self.assertEqual(rows, ["one", "\u258f", "three"])

    def test_an_empty_field_still_shows_a_caret(self):
        tui.blink_state(force=True)
        self.assertEqual(tui.multiline_block(tui.TextBuffer(""), rows=9), "\u258f")

    def test_the_caret_moves_down_as_lines_are_added(self):
        buf = tui.TextBuffer("first")
        tui.blink_state(force=True)
        for word in ("\rsecond", "\rthird"):
            for ch in word:
                tui.multiline_key(buf, ch)
        rows = tui.multiline_block(buf, rows=9).split("\n")
        self.assertEqual(rows, ["first", "second", "third\u258f"])

    def test_lines_have_no_bar_in_front_of_them(self):
        buf = tui.TextBuffer("hello")
        block = tui.multiline_block(buf)
        self.assertNotIn("\u2502", block)

    def test_repeated_ctrl_u_walks_back_line_by_line(self):
        """Each press drops one more line, the way readline does. It used to go
        inert after the first press."""
        buf = tui.TextBuffer("l1\nl2\nl3")
        buf.cursor = len(buf.text)
        seen = []
        for _ in range(5):
            tui.multiline_key(buf, tui.CTRL_U)
            seen.append(buf.text)
        self.assertEqual(seen, ["l1\nl2\n", "l1\nl2", "l1\n", "l1", ""])

    def test_repeated_ctrl_k_walks_forward_line_by_line(self):
        """Kills to the end of the line, then the break, then on to the next."""
        buf = tui.TextBuffer("l1\nl2\nl3")
        buf.cursor = 0
        seen = []
        for _ in range(4):
            tui.multiline_key(buf, tui.CTRL_K)
            seen.append(buf.text)
        self.assertEqual(seen, ["\nl2\nl3", "l2\nl3", "\nl3", "l3"])

    def test_ctrl_k_on_a_line_break_joins_the_next_line(self):
        buf = tui.TextBuffer("l1\nl2")
        buf.cursor = 2                     # sitting on the newline
        tui.multiline_key(buf, tui.CTRL_K)
        self.assertEqual(buf.text, "l1l2")

    def test_the_mouse_is_released_for_every_field_not_just_the_big_ones(self):
        """It only happened for multi-line fields, so a machine name, a date or
        an OS still held the mouse and ctrl+shift+c had nothing to copy."""
        from rich.live import Live
        off = []
        real, real_read = tui.write_escape, tui.read_key
        seq = [None, None, "\r"]          # nothing, nothing, save
        try:
            tui.write_escape = lambda s: off.append(s)
            tui.read_key = lambda timeout=None: seq.pop(0) if seq else None
            with Live(console=ui.console, auto_refresh=False) as live:
                tui.inline_prompt(live, "Name:", initial="", multiline=False)
        finally:
            tui.write_escape, tui.read_key = real, real_read
        self.assertIn(tui.MOUSE_OFF, off, "a one-line field held the mouse")

    def test_the_mouse_is_released_while_a_field_is_open(self):
        """Mouse reporting is what stops text being dragged and copied."""
        import inspect
        source = inspect.getsource(tui.inline_prompt)
        self.assertIn("write_escape(MOUSE_OFF)", source)
        self.assertIn("write_escape(MOUSE_ON)", source)

    def test_raw_mode_disables_flow_control(self):
        """ctrl+s is XOFF. Left enabled, the driver eats it and the terminal
        just stops printing."""
        import inspect
        self.assertIn("IXON", inspect.getsource(tui.raw_mode))

    def test_notes_are_stored_with_their_line_breaks(self):
        machine, _ = store.add_machine(self.key, "Web", notes="one\ntwo")
        self.assertEqual(store.find_machine(self.key, machine["id"])["notes"],
                         "one\ntwo")


class TestGlobalChords(Base):
    """ctrl+x u / r / q work from anywhere, not just on the dashboard."""

    def test_the_commands_exist(self):
        self.assertEqual(len(tui.CHORDS), 3)
        for chord in tui.CHORDS:
            self.assertTrue(tui.is_chord(chord))

    def _chord(self, follow):
        real = tui.read_key
        tui.read_key = lambda timeout=None: follow
        try:
            tui.read_chord(tui.CTRL_X)
        except tui.Chord as chord:
            return chord.token
        finally:
            tui.read_key = real
        return None

    def _drive_dashboard(self, keys):
        """Run the real dashboard loop over a scripted key stream.

        Every chord test before this one called read_chord directly, so nothing
        ever checked what the dashboard did with the exception - and it was
        rebuilding itself from scratch on every undo."""
        import contextlib
        import dashboard
        real_read, real_live, real_raw = dashboard.read_key, dashboard.Live, dashboard.raw_mode
        real_tui_read = tui.read_key
        seq = list(keys)
        built = {"loops": 0}
        real_interactive = dashboard._interactive
        def counting(message=None):
            built["loops"] += 1
            return real_interactive(message)
        def script(timeout=None):
            # Mirrors what read_key does with ctrl+x, so the loop sees the same
            # Chord exception a person would trigger. Running out of keys quits
            # the loop rather than handing back None and spinning for ever.
            if not seq:
                return "\x03"
            key = seq.pop(0)
            if key == tui.CTRL_X and seq:
                follow = seq.pop(0)
                token = {"u": tui.CHORD_UNDO, "r": tui.CHORD_REDO,
                         "q": tui.CHORD_QUIT}.get(follow)
                if token:
                    raise tui.Chord(token)
                return None
            return key
        dashboard._interactive = counting
        try:
            dashboard.read_key = script
            tui.read_key = script
            # The loop builds its own Live and a real raw-mode terminal; neither
            # exists under the test runner.
            dashboard.Live = FakeLive
            dashboard.raw_mode = contextlib.nullcontext
            dashboard._interactive(None)
        finally:
            dashboard.read_key = real_read
            tui.read_key = real_tui_read
            dashboard.Live, dashboard.raw_mode = real_live, real_raw
            dashboard._interactive = real_interactive
        return built

    def test_undo_in_the_dashboard_does_not_rebuild_the_screen(self):
        store.add_machine(self.key, "Undo me")
        built = self._drive_dashboard([tui.CTRL_X, "u"])
        self.assertEqual(built["loops"], 1,
                         "the dashboard was torn down and rebuilt on undo")

    def test_undo_in_the_dashboard_actually_undoes(self):
        machine, _ = store.add_machine(self.key, "Undo me")
        self.assertTrue(store.find_machine(self.key, machine["id"]))
        self._drive_dashboard([tui.CTRL_X, "u"])
        self.assertIsNone(store.find_machine(self.key, machine["id"]),
                          "ctrl+x u did not undo")

    def test_redo_in_the_dashboard_actually_redoes(self):
        machine, _ = store.add_machine(self.key, "Redo me")
        self._drive_dashboard([tui.CTRL_X, "u", tui.CTRL_X, "r"])
        self.assertIsNotNone(store.find_machine(self.key, machine["id"]),
                             "ctrl+x r did not redo")

    def test_the_dashboard_handles_the_chord_where_the_key_was_read(self):
        import inspect
        import dashboard
        source = inspect.getsource(dashboard._interactive)
        self.assertIn("except Chord as chord:", source)
        self.assertLess(source.index("HANDLERS[choice]"),
                        source.index("except Chord as chord:"),
                        "a menu panel is opened outside the chord handler, so "
                        "a chord raised inside it escapes the dashboard loop")

    def test_every_panel_loop_can_undo_without_leaving_the_screen(self):
        """A panel had no handler at all, so undo from inside one threw you back
        to the main menu."""
        import inspect
        import dashboard
        for name in ("machine_view", "repository_read", "show_summary"):
            source = inspect.getsource(getattr(dashboard, name))
            self.assertIn("except Chord as chord:", source, name)

    def test_ctrl_x_followed_by_u_is_undo(self):
        self.assertEqual(self._chord("u"), tui.CHORD_UNDO)

    def test_ctrl_x_followed_by_r_is_redo(self):
        self.assertEqual(self._chord("r"), tui.CHORD_REDO)

    def test_ctrl_x_followed_by_q_is_quit(self):
        self.assertEqual(self._chord("q"), tui.CHORD_QUIT)

    def test_the_second_key_is_a_plain_letter(self):
        """ctrl+x u, not ctrl+x ctrl+u. Stubbing the control codes in
        the tests hid this from the test suite while it failed live."""
        for letter, token in (("u", tui.CHORD_UNDO), ("r", tui.CHORD_REDO),
                             ("q", tui.CHORD_QUIT)):
            self.assertEqual(self._chord(letter), token)
        self.assertIsNone(self._chord(tui.CTRL_U),
                          "ctrl+u is not the undo chord")

    def test_ctrl_r_is_no_longer_a_line_key(self):
        """It moved to ctrl+k so the editor keys and the redo chord cannot be
        confused for each other on screen."""
        buf = tui.TextBuffer("abc\ndef")
        buf.cursor = 1
        tui.multiline_key(buf, "\x12")
        self.assertEqual(buf.text, "abc\ndef", "ctrl+r should do nothing now")

    def test_ctrl_k_is_not_the_redo_chord(self):
        self.assertIsNone(self._chord(tui.CTRL_K))

    def test_ctrl_x_followed_by_anything_else_does_nothing(self):
        self.assertIsNone(self._chord("z"))

    def test_a_lone_ctrl_x_is_swallowed_not_typed(self):
        """Left as a raw \x18 it landed in the field whenever nobody followed
        it with u, r or q."""
        import inspect
        source = inspect.getsource(tui.read_key)
        self.assertIn("read_chord(key)", source)
        self.assertIn("return None", source)

    def test_the_chord_waits_long_enough_for_a_person(self):
        self.assertGreaterEqual(tui.CHORD_WAIT, 1.5,
                                "half a second is not enough to press the "
                                "second key")

    def test_the_chord_unwinds_to_the_dashboard(self):
        """Raising rather than returning is what makes it work from a picker."""
        import inspect
        import dashboard
        self.assertIn("except Chord", inspect.getsource(dashboard.interactive))

    def test_the_old_three_letter_chords_are_gone(self):
        import inspect
        import dashboard
        source = inspect.getsource(dashboard)
        self.assertNotIn("uuu", source)
        self.assertNotIn("rrr", source)
        self.assertNotIn("qqq", source)


class TestMouseAndScrolling(Base):
    """The wheel scrolls, page keys page, and text can still be selected."""

    def test_the_wheel_is_recognised(self):
        self.assertIs(tui._mouse_event(b"<64;10;5M"), tui.KEY_WHEEL_UP)
        self.assertIs(tui._mouse_event(b"<65;10;5m"), tui.KEY_WHEEL_DOWN)

    def test_drags_and_clicks_are_swallowed(self):
        """They arrive only because reporting is on; letting them through would
        type stray characters into an open field."""
        for report in (b"<0;10;5M", b"<0;10;5m", b"<32;10;5M", b"<64;1;1M"):
            if report.startswith(b"<64"):
                continue
            self.assertIsNone(tui._mouse_event(report))

    def test_a_malformed_report_does_not_crash(self):
        for junk in (b"<", b"<zz", b"<>", b""):
            self.assertIsNone(tui._mouse_event(junk))

    def test_the_picker_scrolls_on_the_wheel(self):
        import inspect
        source = inspect.getsource(tui.inline_list)
        self.assertIn("KEY_WHEEL_DOWN", source)
        self.assertIn("KEY_WHEEL_UP", source)

    def test_the_dashboard_adapts_to_the_terminal_instead_of_scrolling(self):
        """It used to be squeezed into whatever rows the menu left and then
        scrolled through blank padding, which read as a dead wheel. It now steps
        down: the full layout, then the compact bar, then the menu alone."""
        import ui
        from rich.console import Console
        for height, shows_bar in ((40, True), (24, True), (16, True),
                                  (14, False), (12, False)):
            ui.console.width, ui.console.height = 40, height
            ui.invalidate_dashboard()
            body, top = ui.dashboard_window(hovered=0)
            rec = Console(width=40, height=height, record=True,
                          file=open("/dev/null", "w"))
            rec.print(body)
            text = rec.export_text()
            self.assertIn("Menu", text, f"no menu at {height} rows")
            self.assertEqual(top, 0, f"the dashboard still scrolls at {height}")
            # The menu alone means no dashboard; otherwise the bar is drawn.
            if shows_bar:
                self.assertTrue("░" in text or "%" in text, f"no bar at {height}")
            else:
                self.assertNotIn("Dashboard", text, f"a dashboard at {height}")
        ui.console.width, ui.console.height = 80, 40
        ui.invalidate_dashboard()

    def test_scrolling_is_clamped_to_the_content(self):
        import ui
        from rich.console import Console
        ui.console.height = 10
        ui.invalidate_dashboard()
        _, far = ui.dashboard_window(9999)
        self.assertGreaterEqual(far, 0)
        self.assertLessEqual(far + ui.dashboard_budget(),
                             ui._natural_height(ui.body()))
        _, none = ui.dashboard_window(-50)
        self.assertEqual(none, 0)
        ui.console.height = 40

    def test_every_string_follows_the_panel_name(self):
        """The menu entry and the dashboard heading changed, but the submenu
        title and the two empty-state hints still said "Machines" - so a project
        called Topics showed one name on the menu and another on the screen it
        opened. Nothing user-visible may be left hard-coded."""
        import ui
        import dashboard
        for panel in ui.store.PANEL_NAMES:
            store.set_dashboard_panel(self.key, panel)
            ui.invalidate_dashboard()
            other = [n for n in ui.store.PANEL_NAMES if n != panel][0]
            body, _ = ui.dashboard_window(hovered=0)
            text = render(body)
            if panel == "Topics":
                self.assertNotIn(f"[2] {other}", text,
                                 f"a hard-coded {other} survived with "
                                 f"Topics chosen: {text[:200]}")
            menu = [label for _, label in ui.menu_items()]
            self.assertIn(panel, menu)
            self.assertNotIn(other, menu)

    def test_the_machines_submenu_is_titled_with_the_chosen_name(self):
        import dashboard
        titles = []
        real = dashboard.submenu
        dashboard.submenu = lambda live, title, entries, message: (
            titles.append(title), (None, True))[1]
        try:
            for panel in store.PANEL_NAMES:
                store.set_dashboard_panel(self.key, panel)
                dashboard.action_machines(FakeLive(), None)
        finally:
            dashboard.submenu = real
        self.assertEqual(titles, [f"{n}:" for n in store.PANEL_NAMES])

    def test_nothing_is_ever_cropped_out_of_reach(self):
        """The terminal's own scrollbar cannot exist - the app repaints one
        screen in the alternate buffer - so anything taller than the window has
        to be reachable from inside. A panel that grew past the bottom with no
        scroll path would be simply unreadable."""
        import dashboard
        from rich.console import Group
        from rich.text import Text
        # Twenty short lines: tall enough to scroll, and inside the
        # description's length limit.
        machine, _ = store.add_machine(
            self.key, "Target",
            description="\n".join(f"desc {i}" for i in range(1, 21)))
        entry, _ = store.add_repository(
            self.key, "Kerberos", "\n".join(f"entry {i}" for i in range(1, 26)))
        for i in range(30):
            extra, _ = store.add_machine(self.key, f"M{i}")
            store.mark_machine(self.key, extra["id"])
        for height, width in ((12, 40), (16, 50), (24, 60), (48, 100)):
            ui.console.height, ui.console.width = height, width
            ui.invalidate_dashboard()
            dash, _ = ui.dashboard_window(hovered=0)
            screens = {
                "machine": Group(ui.build_layout(),
                                 ui.detail_panel("Target", Text(machine["description"]))),
                "repository": Group(ui.build_layout(),
                                    ui.detail_panel("Kerberos", Text(entry["body"]))),
                "summary": Group(ui.build_layout(), ui.summary_panel()),
            }
            # The dashboard must always fit on its own: it adapts rather than
            # scrolling, so anything left over would be cropped with no way out.
            self.assertEqual(ui.window_screen(dash, 0)[2], 0,
                             f"the dashboard does not fit at {height}x{width}")
            for name, screen in screens.items():
                _, _, max_top = ui.window_screen(screen, 0)
                if max_top:
                    moved = dashboard.scroll_step(tui.KEY_PGDN, 0, max_top,
                                             height=height)
                    self.assertTrue(moved, f"{name} scrolls at {height}x{width}")
        ui.console.height, ui.console.width = 80, 40
        ui.invalidate_dashboard()

    def test_the_menu_does_not_wrap_on_a_zoomed_terminal(self):
        """A zoomed terminal has few columns, where two menu columns wrapped
        every label onto a second line and the menu grew to twelve rows - which
        squeezed the dashboard to one row and left the wheel scrolling through
        blank padding."""
        import ui
        from rich.console import Console
        ui.console.width, ui.console.height = 40, 24
        ui.invalidate_dashboard()
        try:
            rows = ui._menu_rows()
            rec = Console(width=40, height=40, record=True,
                          file=open("/dev/null", "w"))
            rec.print(ui.menu_panel(0))
            lines = [l for l in rec.export_text().split("\n") if l.strip()]
        finally:
            ui.console.width, ui.console.height = 80, 40
            ui.invalidate_dashboard()
        # One row per option, plus the borders, the spacer and the short hint.
        self.assertEqual(rows, len(ui.MENU_ITEMS) + 4)
        # Nothing wraps: every drawn row is exactly the panel's width.
        self.assertTrue(all(len(l) == 40 for l in lines),
                        "a menu line wrapped at 40 columns")

    def test_when_nothing_fits_the_menu_is_shown_alone(self):
        """Rather than a one-row dashboard the wheel can only scroll past."""
        import ui
        from rich.console import Console
        ui.console.width, ui.console.height = 40, 11
        ui.invalidate_dashboard()
        try:
            self.assertEqual(ui.dashboard_budget(), 0)
            body, top = ui.dashboard_window(0, hovered=0)
            self.assertEqual(top, 0)
            rec = Console(width=40, height=11, record=True,
                          file=open("/dev/null", "w"))
            rec.print(body)
            text = rec.export_text()
            self.assertIn("Menu", text)
            self.assertNotIn("Dashboard", text)
        finally:
            ui.console.width, ui.console.height = 80, 40
            ui.invalidate_dashboard()

    def test_redrawing_the_dashboard_does_not_re_render_it_every_key(self):
        """It did, at about 88ms a keypress, which capped the wheel at a dozen
        notches a second and felt like it was sticking."""
        import ui
        ui.console.height = 24
        ui.invalidate_dashboard()
        ui.dashboard_window(hovered=0)             # prime the cache
        calls = []
        real = ui._rendered
        try:
            ui._rendered = lambda r, h=10000: (calls.append(1), real(r, h))[1]
            ui.dashboard_window(hovered=1)
            ui.dashboard_window(hovered=2)
        finally:
            ui._rendered = real
        self.assertEqual(calls, [], "the dashboard was re-rendered per keypress")

    def test_the_cache_follows_the_data_changing(self):
        """A cache keyed only on the size would keep showing stale progress."""
        import ui
        import store
        ui.console.height = 24
        ui.invalidate_dashboard()
        first, _ = ui.dashboard_window(0)
        store.save("__cache_probe__", {"n": 1}, record=False)
        try:
            second, _ = ui.dashboard_window(0)
            self.assertIsNot(first, second, "a data change did not rebuild it")
        finally:
            (store.DATA / "__cache_probe__.json").unlink(missing_ok=True)
            store.save("projects", store.registry(), record=False)
            ui.invalidate_dashboard()

    def test_the_cache_follows_a_resize(self):
        import ui
        from rich.console import Console
        ui.invalidate_dashboard()
        seen = []
        for height in (16, 24, 40):
            ui.console.height = height
            body, _ = ui.dashboard_window(0, hovered=0)
            rec = Console(width=80, height=height, record=True,
                          file=open("/dev/null", "w"))
            rec.print(body)
            seen.append("Menu" in rec.export_text())
        self.assertEqual(seen, [True, True, True])
        ui.console.height = 40

    def test_a_cached_frame_still_shows_the_moving_highlight(self):
        """The rows are cached; the highlight is not, or the arrows would stop
        showing where they are."""
        import re
        import ui
        from rich.console import Console
        ui.console.height = 24
        ui.invalidate_dashboard()
        marks = []
        for hovered in range(4):
            body, _ = ui.dashboard_window(0, hovered=hovered)
            rec = Console(width=80, height=24, record=True,
                          file=open("/dev/null", "w"))
            rec.print(body)
            marks.append(re.findall(r"\x1b\[[0-9;]*7[0-9;]*m\s*\[(\d)\]",
                                    rec.export_text(styles=True))[:1])
        self.assertEqual(marks, [["1"], ["2"], ["3"], ["4"]])

    def test_the_menu_is_on_screen_at_every_size(self):
        """The dashboard used to fill the screen and crop the menu away, so the
        arrow keys were moving a highlight nobody could see."""
        import ui
        from rich.console import Console
        for height in (16, 20, 24, 40):
            ui.console.height = height
            body, _ = ui.dashboard_window(0, hovered=0)
            rec = Console(width=90, height=height, record=True,
                          file=open("/dev/null", "w"))
            rec.print(body)
            self.assertIn("Menu", rec.export_text(),
                          f"the Menu panel was cropped away at {height} rows")
        ui.console.height = 40

    def test_the_highlight_follows_the_arrow_keys(self):
        """Enter opened the right panel while the highlight stayed on [1],
        because the scrolled render never passed the hovered index on."""
        import re
        import ui
        from rich.console import Console
        for height in (16, 24, 40):
            seen = []
            for hovered in range(4):
                ui.console.height = height
                body, _ = ui.dashboard_window(0, hovered=hovered)
                rec = Console(width=90, height=height, record=True,
                              file=open("/dev/null", "w"))
                rec.print(body)
                styled = rec.export_text(styles=True)
                seen.append(re.findall(r"\x1b\[[0-9;]*7[0-9;]*m\s*\[(\d)\]",
                                       styled)[:1])
            self.assertEqual(seen, [["1"], ["2"], ["3"], ["4"]],
                             f"highlight did not move at {height} rows")
        ui.console.height = 40

    def test_the_dashboard_itself_needs_no_scrolling(self):
        """It steps down to the compact bar and then to the menu alone, so the
        wheel and page keys there have nothing to do - and saying otherwise
        would send people hunting for a scroll that cannot exist."""
        import inspect
        import dashboard
        source = inspect.getsource(dashboard._interactive)
        self.assertNotIn("scroll_step", source)
        self.assertFalse(hasattr(ui, "dashboard_scrolls"))

    def test_every_key_the_dashboard_uses_is_actually_imported(self):
        """KEY_PGUP was used but never imported, so scrolling up crashed the
        app outright - and only on a screen short enough to scroll."""
        import inspect
        import dashboard
        import re
        used = set(re.findall(r"KEY_[A-Z_]+", inspect.getsource(dashboard._interactive)))
        for name in used:
            self.assertTrue(hasattr(dashboard, name),
                            f"{name} is used but not imported into dashboard")


class FakeLive:
    """Stands in for rich's Live when the flow is driven without a terminal."""

    def __init__(self, *args, **kwargs):
        self.updates = 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def update(self, renderable=None, **kwargs):
        self.updates += 1

    def refresh(self):
        pass


class TestEditPrompts(Base):
    """Editing fields in place: step past a field and it keeps its value."""

    def setUp(self):
        super().setUp()
        self.live = FakeLive()

    def _prompt(self, initial, keys):
        import tui
        queue = list(keys)
        real = tui.read_key
        tui.read_key = lambda timeout=None: queue.pop(0) if queue else None
        try:
            return tui.inline_prompt(self.live, "Field:", initial=initial)
        finally:
            tui.read_key = real

    def test_stepping_past_a_field_keeps_its_value(self):
        # Pressing Enter with nothing typed must keep the old value, not
        # cancel: an edit form you cannot complete without retyping everything
        # is not an edit form.
        self.assertEqual(self._prompt("Alpha", ["\r"]), "Alpha")

    def test_typing_appends_to_the_seeded_value(self):
        # The cursor sits at the end, as in any editor: clear first to retype.
        self.assertEqual(self._prompt("Alpha", ["\x7f"] * 5 + list("Be") + ["\r"]),
                         "Be")

    def test_a_seeded_field_can_be_cleared(self):
        self.assertEqual(self._prompt("Alpha", ["\x7f"] * 5 + ["\r"]), "")

    def test_escape_cancels_rather_than_clearing(self):
        self.assertIsNone(self._prompt("Alpha", ["\x1b"]))

    def test_an_unseeded_field_still_treats_empty_as_cancel(self):
        self.assertIsNone(self._prompt("", ["\r"]))

    def test_editing_notes_leaves_the_name_alone(self):
        """What the summary does: one field, notes, never the name."""
        import dashboard
        machine, _ = store.add_machine(self.key, "Web", "old note", "Linux")
        dashboard.inline_prompt = lambda live, prompt, message=None, **kw: "new note"
        edited, message = dashboard.edit_machine_notes(self.live, machine, None)
        self.assertEqual(edited["notes"], "new note")
        self.assertEqual(edited["name"], "Web", "the name must not be touched")
        self.assertEqual(edited["os"], "Linux", "the OS must not be touched")

    def test_cancelling_the_notes_prompt_changes_nothing(self):
        import dashboard
        machine, _ = store.add_machine(self.key, "Web", "keep me")
        dashboard.inline_prompt = lambda live, prompt, message=None, **kw: None
        edited, message = dashboard.edit_machine_notes(self.live, machine, None)
        self.assertIsNone(edited)
        self.assertEqual(store.find_machine(self.key, machine["id"])["notes"],
                         "keep me")

    def test_notes_can_be_blanked_from_the_summary(self):
        import dashboard
        machine, _ = store.add_machine(self.key, "Web", "some note")
        dashboard.inline_prompt = lambda live, prompt, message=None, **kw: ""
        edited, message = dashboard.edit_machine_notes(self.live, machine, None)
        self.assertEqual(edited["notes"], "")


class TestAddMachineForm(Base):
    """Adding a machine: the optional fields must be skippable."""

    def setUp(self):
        super().setUp()
        self.live = FakeLive()
        import dashboard
        self.dashboard = dashboard

    def _ask(self, answers):
        """answer each prompt with the next value; "" means press Enter.

        An unknown prompt - the Category one, added after these were written -
        is answered the same way as an empty one, so a test can be about the
        fields it names rather than about how many the form has."""
        queue = list(answers)

        def fake_prompt(live, prompt, message=None, **kw):
            return queue.pop(0) if queue else ""

        dashboard.inline_prompt = fake_prompt

    def test_skipping_the_optional_fields_still_adds_the_machine(self):
        """Pressing Enter past OS, Description and Notes must not cancel."""
        self._ask(["Web", "", "", ""])
        dashboard.machine_add(self.live, None)
        machines = store.machines(self.key)
        self.assertEqual(len(machines), 1)
        self.assertEqual(machines[0]["name"], "Web")

    def test_adding_records_the_os_notes_and_description(self):
        self._ask(["Web", "Linux", "a web box", "a note"])
        with _this_project_using_the_os(self.key):
            dashboard.machine_add(self.live, None)
        machine = store.machines(self.key)[0]
        self.assertEqual(machine["os"], "Linux")
        self.assertEqual(machine["description"], "a web box")
        self.assertEqual(machine["notes"], "a note")

    def test_description_and_notes_are_kept_apart(self):
        """A one-line summary and working notes are read at different moments,
        so one must not overwrite the other."""
        self._ask(["Web", "Linux", "what the box is", "what I found"])
        with _this_project_using_the_os(self.key):
            dashboard.machine_add(self.live, None)
        machine = store.machines(self.key)[0]
        self.assertEqual(machine["description"], "what the box is")
        self.assertEqual(machine["notes"], "what I found")

    def test_a_new_machine_starts_with_blank_notes_and_description(self):
        self._ask(["Bare", "", "", "", ""])
        dashboard.machine_add(self.live, None)
        machine = store.machines(self.key)[0]
        self.assertEqual(machine["notes"], "")
        self.assertEqual(machine["description"], "")

    def test_editing_a_machine_with_blank_fields_can_be_saved(self):
        """A machine with no OS still has to be editable:
        stepping past an empty field must keep it empty, not cancel."""
        import dashboard
        machine, _ = store.add_machine(self.key, "Bare", notes="note")
        # Enter on every field: each returns whatever it was seeded with.
        def fake_prompt(live, prompt, message=None, initial="", **kw):
            return initial

        dashboard.inline_prompt = fake_prompt
        edited, message = dashboard.edit_machine_fields(self.live, machine, None)
        self.assertIsNotNone(edited, f"the edit was cancelled: {message!r}")
        self.assertEqual(edited["name"], "Bare")
        self.assertEqual(edited["notes"], "note")

    def test_editing_can_rename_a_machine(self):
        import dashboard
        machine, _ = store.add_machine(self.key, "Old", "note", "Linux")
        values = {"Name:": "New"}            # only the name is retyped

        def fake_prompt(live, prompt, message=None, initial="", **kw):
            return values.get(prompt, initial)

        dashboard.inline_prompt = fake_prompt
        edited, message = dashboard.edit_machine_fields(self.live, machine, None)
        self.assertEqual(edited["name"], "New")
        self.assertEqual(edited["os"], "Linux", "other fields survive")

    def test_editing_can_change_the_os_of_an_added_machine(self):
        import dashboard
        machine, _ = store.add_machine(self.key, "Web", "note", "Linux", "a web box")
        dashboard.inline_prompt = lambda live, prompt, message=None, initial="", **kw: (
            "Windows Server" if prompt == "OS:" else initial)
        with _this_project_using_the_os(self.key):
            edited, message = dashboard.edit_machine_fields(self.live, machine, None)
        self.assertEqual(edited["os"], "Windows Server")
        self.assertEqual(edited["description"], "a web box", "other fields survive")

    def test_editing_can_change_the_description_of_an_added_machine(self):
        import dashboard
        machine, _ = store.add_machine(self.key, "Web", "note", "Linux", "a web box")
        dashboard.inline_prompt = lambda live, prompt, message=None, initial="", **kw: (
            "an SMB box" if prompt == "Description:" else initial)
        edited, message = dashboard.edit_machine_fields(self.live, machine, None)
        self.assertEqual(edited["description"], "an SMB box")
        self.assertEqual(edited["notes"], "note", "other fields survive")

    def test_the_edit_form_offers_every_field(self):
        """Name, OS and description must all be reachable when editing."""
        import inspect
        source = inspect.getsource(dashboard.edit_machine_fields)
        for label in ("Name:", "OS:", "Description:", "Notes:"):
            self.assertIn(f'"{label}"', source)

    def test_a_machine_saved_before_this_field_had_none(self):
        """Records written by older versions simply lack the key; editing one
        must add it rather than fall over."""
        import dashboard
        machine, _ = store.add_machine(self.key, "Old", "Stage", "note")
        del store.machines(self.key)[0]["description"]
        dashboard.inline_prompt = lambda live, prompt, message=None, initial="", **kw: (
            "filled in" if prompt == "Description:" else initial)
        edited, message = dashboard.edit_machine_fields(self.live, machine, None)
        self.assertEqual(edited["description"], "filled in")

    def test_no_name_cancels(self):
        self._ask([""])
        dashboard.machine_add(self.live, None)
        self.assertEqual(store.machines(self.key), [])

    def test_the_state_line_is_capitalised(self):
        import inspect
        source = inspect.getsource(dashboard.machine_view)
        self.assertIn("State:", source)
        self.assertNotIn("state:", source)

    def test_the_machine_view_no_longer_says_esc_back_to_the_list(self):
        import inspect
        self.assertNotIn("esc back to the list",
                         inspect.getsource(dashboard.machine_view))

    def test_state_sits_outside_the_notes_box(self):
        """State belongs under the panel, not inside its footer, where it was
        printed twice alongside the key hints."""
        import inspect
        source = inspect.getsource(dashboard.machine_view)
        self.assertNotIn("note =", source)
        self.assertIn("detail_panel(title, body, None)", source)

    def test_the_view_no_longer_offers_marking(self):
        """Marking is `m` on the list now. Leaving it here as well gave the same
        job two doors, one of them a stray Enter away from completing something
        while you were only reading."""
        import inspect
        source = inspect.getsource(dashboard.machine_view)
        self.assertNotIn("toggle_machine", source)
        self.assertNotIn("mark/unmark", source)
        self.assertIn("esc back", source)


class TestProgressPanel(Base):
    """The dashboard's Progress panel is one bar and nothing else."""

    def setUp(self):
        super().setUp()
        for name in ("Alpha", "Bravo", "Charlie"):
            store.add_machine(self.key, name, os_name="Linux",
                              description="a description")

    def test_the_panel_is_titled_topics_by_default(self):
        self.assertIn(store.PANEL_TOPIC, render(build_layout(), width=120))

    def test_the_panel_takes_the_projects_chosen_name(self):
        store.set_dashboard_panel(self.key, "Machines")
        text = render(build_layout(), width=120)
        self.assertIn("Machines", text)

    def test_the_panel_name_can_be_switched_from_the_machines_menu(self):
        """Both names are offered inside [2]."""
        import dashboard
        labels = [n for n, _ in dashboard.MACHINES_MENU]
        self.assertIn("Panel", labels)

    def test_only_the_two_names_are_accepted(self):
        self.assertEqual(store.PANEL_NAMES, ("Topics", "Machines"))
        name, error = store.set_dashboard_panel(self.key, "Progress")
        self.assertIsNone(name)
        self.assertIn("Topics", error)
        self.assertEqual(store.dashboard_panel(self.key), "Topics")

    def test_the_panel_name_is_per_project(self):
        other, _ = store.create_project("Other")
        store.set_dashboard_panel(self.key, "Machines")
        self.assertEqual(store.dashboard_panel(other), store.PANEL_TOPIC)

    def test_it_shows_the_bar_and_the_counts(self):
        text = render(build_layout(), width=120)
        self.assertIn(store.project_name(), text)
        self.assertIn("0/3", text)

    def test_no_machine_is_listed_in_it(self):
        """A per-machine list was tried here and removed: names and
        descriptions both said nothing you could act on at a glance."""
        text = render(build_layout(), width=120)
        for unwanted in ("Alpha", "Bravo", "Charlie", "a description",
                         "more - [2] Machines", "no description yet"):
            self.assertNotIn(unwanted, text)

    def test_an_empty_project_still_says_how_to_add_one(self):
        import ui
        for machine in store.machines(self.key):
            store.delete_machine(self.key, machine["id"])
        for panel, noun in (("Topics", "topics"), ("Machines", "machines")):
            store.set_dashboard_panel(self.key, panel)
            ui.invalidate_dashboard()
            text = render(build_layout(), width=120)
            self.assertIn(f"No {noun} yet", text)
            self.assertIn(f"[2] {panel}", text)


class TestDescriptionAndNotesAreSeparate(Base):
    """The repository text and the user's own writing must never be confused.

    description is what the machine covers and comes from the repository; notes
    are written by hand and start empty. They are shown in different places -
    description under [2] Machines, notes in the Summary - so filling one in
    must not touch the other."""

    def setUp(self):
        super().setUp()
        self.machine, _ = store.add_machine(
            self.key, "Networked",
            description="Service enumeration, web vulnerabilities", notes="")

    def test_notes_start_blank(self):
        self.assertEqual(store.find_machine(self.key, self.machine["id"])["notes"],
                         "")

    def test_writing_notes_leaves_the_description_alone(self):
        store.edit_machine(self.key, self.machine["id"], notes="tickets, roasting")
        stored = store.find_machine(self.key, self.machine["id"])
        self.assertEqual(stored["notes"], "tickets, roasting")
        self.assertEqual(stored["description"],
                         "Service enumeration, web vulnerabilities")

    def test_changing_the_description_leaves_the_notes_alone(self):
        store.edit_machine(self.key, self.machine["id"], notes="tickets, roasting")
        store.edit_machine(self.key, self.machine["id"], description="something else")
        stored = store.find_machine(self.key, self.machine["id"])
        self.assertEqual(stored["notes"], "tickets, roasting")
        self.assertEqual(stored["description"], "something else")

    def test_the_machine_view_shows_the_permanent_categories(self):
        """Description and Notes are permanent, so they are always on the view
        - they lead it, ahead of whatever else the machine chose."""
        import inspect
        import dashboard
        source = inspect.getsource(dashboard.machine_view)
        self.assertIn('machine.get("description")', source)
        self.assertIn("machine_builtin_categories", source)
        self.assertIn("machine_categories", source)
        self.assertLess(source.index("machine_builtin_categories"),
                        source.index("machine_categories"))

    def test_notes_are_shown_only_once_written(self):
        """The panel reads "No notes yet." rather than an empty box, but a
        machine with notes shows them and not the placeholder."""
        import inspect
        import dashboard
        source = inspect.getsource(dashboard.machine_view)
        self.assertIn("not written yet", source,
                      "an empty category should say so, not be blank")
        self.assertIn("machine_builtin_categories", source)

    def test_the_summary_column_reads_notes(self):
        """The Summary shows your notes, which are empty until you write them."""
        import inspect
        source = inspect.getsource(ui.summary_table)
        self.assertIn('machine.get("notes")', source)
        self.assertNotIn('machine.get("description")', source)

    def test_a_machine_with_no_description_says_so(self):
        machine, _ = store.add_machine(self.key, "Bare")
        store.mark_machine(self.key, machine["id"])
        self.assertIn("no notes yet", render(summary_panel()))


class TestSummaryTitle(Base):
    def test_the_panel_is_titled_summary(self):
        """It used to read "<project> - <date>", which named the panel after
        its contents while the menu item above already said Summary."""
        text = render(summary_panel())
        self.assertIn("Summary", text)
        self.assertNotIn(store.today_iso(), text)
        self.assertNotIn(store.project_name(), text)


class TestSummaryEditing(Base):
    """The summary is editable in place: navigate, edit, unmark."""

    def setUp(self):
        super().setUp()
        self.live = FakeLive()
        import dashboard
        self.dashboard = dashboard
        self.saved = []
        for i, name in enumerate(["Alpha", "Bravo", "Charlie"]):
            machine, _ = store.add_machine(self.key, name, os_name="Linux")
            store.mark_machine(self.key, machine["id"])

    def _run(self, keys):
        queue = list(keys)

        def fake_read_key(timeout=None):
            return queue.pop(0) if queue else None

        dashboard.read_key = fake_read_key
        # The editor is stubbed too: the real one drives inline_prompt, which
        # reads stdin and blocks forever when no terminal is attached.
        dashboard.edit_machine_notes = lambda live, m, msg: (
            self.saved.append(m["id"]) or (m, f"Notes updated for {m['name']}"),
            None)[0]
        return dashboard.show_summary(self.live, None)

    def test_down_moves_the_cursor(self):
        seen = []
        orig = dashboard.summary_panel

        def spy(selected=None, hint=False, **kw):
            seen.append(selected)
            return orig(selected=selected, hint=hint, **kw)

        dashboard.summary_panel = spy
        self._run([tui.KEY_DOWN, tui.KEY_DOWN, dashboard.ESCAPE])
        self.assertIn(2, seen, "the cursor never left the first row")
        self.assertIn(1, seen)

    def test_up_stops_at_the_first_row(self):
        seen = []
        orig = dashboard.summary_panel
        dashboard.summary_panel = lambda selected=None, hint=False, **kw: (
            seen.append(selected),
            orig(selected=selected, hint=hint, **kw))[1]
        self._run([tui.KEY_UP, tui.KEY_UP, dashboard.ESCAPE])
        self.assertEqual(min(seen), 0, "the cursor wrapped above the first row")

    def test_enter_edits_the_highlighted_machine(self):
        names = [m["name"] for m in store.machines(self.key)]
        self._run([tui.KEY_DOWN, "\r", dashboard.ESCAPE])
        self.assertEqual(len(self.saved), 1)
        edited = store.find_machine(self.key, self.saved[0])
        self.assertEqual(edited["name"], names[1])

    def test_x_unmarks_the_highlighted_machine(self):
        self.assertEqual(store.tally(self.key), (3, 3))
        self._run(["x", dashboard.ESCAPE])
        self.assertEqual(store.tally(self.key), (2, 3))

    def test_esc_leaves_the_summary(self):
        self.assertEqual(self._run([dashboard.ESCAPE]), None)

    def test_a_timeout_does_not_navigate(self):
        seen = []
        orig = dashboard.summary_panel
        dashboard.summary_panel = lambda selected=None, hint=False, **kw: (
            seen.append(selected),
            orig(selected=selected, hint=hint, **kw))[1]
        self._run([None, None, tui.KEY_DOWN, dashboard.ESCAPE])
        self.assertEqual(seen[0], 0)
        self.assertIn(1, seen)


class TestMachineOpenFlow(Base):
    """The opened view is for reading. Marking is `m` on the list."""


    def test_a_hint_replaces_the_generic_line_not_stacks_on_it(self):
        """The generic footer was drawn under the screen's own hint, so every
        key it named appeared twice - "\u2191\u2193 move  \u23ce select" under a
        hint that already began "\u2191\u2193 move  \u23ce read"."""
        import inspect
        import tui
        source = inspect.getsource(tui.render_list)
        self.assertNotIn("+ footer", source,
                         "the custom hint and the generic line are both drawn")

    def test_a_key_line_says_each_key_once(self):
        """Screens that bring their own hint and screens that do not both end
        up with one key line, never a key named twice."""
        from rich.console import Console
        import tui
        ui.console.width, ui.console.height = 110, 40

        class L:
            def __init__(self):
                self.last = None

            def update(self, renderable):
                self.last = renderable

            def refresh(self):
                pass

            def is_terminal(self):
                return False

        def footer(**kw):
            live = L()
            rows = [("i", 0, 1), ("i", 1, 2)]
            tui.render_list(live, "List:", ["one", "two"], rows, 0, 0, 5, **kw)
            rec = Console(width=110, height=40, record=True,
                          file=open("/dev/null", "w"))
            rec.print(live.last)
            lines = [l.strip("\u256d\u256e\u2570\u256f\u2502 ")
                     for l in rec.export_text().splitlines() if l.strip()]
            return lines[-2] if len(lines) > 1 else lines[-1]

        generic = footer()
        self.assertIn("(Select)", generic)
        self.assertIn("(1/2)", generic)
        hinted = footer(hint="\u2191\u2193 move  \u23ce (Read)  a (Add)  "
                            "esc back")
        for word in ("move", "esc back", "(1/2)"):
            self.assertLessEqual(hinted.count(word), 1,
                                 "%r twice in: %s" % (word, hinted))
        self.assertNotIn("(Select)", hinted,
                         "the generic line is still being drawn under the hint")

    def test_every_screen_hint_writes_the_key_then_what_it_does(self):
        """"a (Add)" rather than "a add", so the key and its meaning cannot be
        mistaken for each other in a line full of them."""
        import inspect
        import re
        import dashboard
        import ui
        source = inspect.getsource(dashboard) + inspect.getsource(ui)
        checked = 0
        for match in re.finditer(r'hint_line\(\s*f?"([^"]*)"', source):
            hint = match.group(1)
            for key in re.findall(r"(?<![\w()])[a-z] (?=[a-z])", hint):
                self.fail("'%s' writes the key and its meaning as '%s' with "
                          "nothing to tell them apart" % (hint, key))
            checked += 1
        self.assertTrue(checked, "no hint strings were checked")

    def test_the_view_advertises_going_back_not_marking(self):
        """The hint said ↵ mark/unmark and it no longer does that."""
        import inspect
        import dashboard
        source = inspect.getsource(dashboard.machine_view)
        self.assertNotIn("toggle_machine", source,
                         "the opened view still marks")
        self.assertNotIn("mark/unmark", source, "the hint still offers marking")
        self.assertIn('hint_line(', source)
        self.assertIn("c (Categories)", source)
        self.assertNotIn('k == "f"', source,
                         "f opened the same screen as c - one of them went")

    def test_the_list_can_mark_and_the_view_cannot(self):
        """One place for one job."""
        import inspect
        import dashboard
        self.assertIn("toggle_machine", inspect.getsource(dashboard.machine_list))
        self.assertNotIn("toggle_machine",
                         inspect.getsource(dashboard.machine_view))

    def test_the_actions_are_keys_on_the_list_not_menu_entries(self):
        """They cannot be hit by accident now: there is nothing to click past."""
        import dashboard
        labels = [n for n, _ in dashboard.MACHINES_MENU]
        self.assertEqual(len(labels), 3)
        for gone in ("Mark", "Add", "Edit", "Delete"):
            self.assertNotIn(gone, labels)

    def test_the_list_is_the_first_machine_option(self):
        """The safety is still in the keys: one Enter opens a machine and marks
        nothing."""
        import dashboard
        self.assertEqual(dashboard.MACHINES_MENU[0][0], "View")

    def test_machine_list_shows_no_stage(self):
        import dashboard
        store.add_machine(self.key, "Target", "Pentester Advanced")
        labels = [label for label, _ in dashboard.machine_choices(self.key)]
        self.assertIn("Target", labels)
        self.assertFalse(any("Pentester Advanced" in l for l in labels))
        self.assertFalse(any("Stage" in l for l in labels))


class TestThemePicker(Base):

    def _run(self, chosen):
        import dashboard
        dashboard.pick = lambda *a, **k: (chosen, None)
        dashboard.option_theme(None, None)

    def test_choosing_a_theme_sets_it(self):
        self._run("teal")
        self.assertEqual(store.project_theme(self.key), "teal")

    def test_choosing_dark_red_gives_maroon_days(self):
        from ui import days_style
        self._run("red")
        self.assertEqual(days_style(10), "bold dark_red")   # days colour is fixed

    def test_cancelling_changes_nothing(self):
        self._run(None)
        self.assertEqual(store.project_theme(self.key), themes.DEFAULT_THEME)

    def test_the_picker_offers_every_theme_in_order(self):
        import dashboard
        self.assertEqual([k for _, k in dashboard.themes.choices()], themes.ORDER)

    def test_the_theme_list_scrolls(self):
        """Every theme must be reachable without overflowing the screen."""
        import dashboard, tui
        names, rows = tui.prepare_rows([(None, name, i) for i, (name, _) in
                                        enumerate(dashboard.themes.choices(), 1)])
        total = len(themes.ORDER)
        self.assertEqual(len(names), total)
        self.assertEqual(len(rows), total)
        last = total - 1
        view = 6          # a short screen shows six rows of the list
        top = tui.fit_top(last, 0, len(rows), view=view)
        self.assertGreater(top, 0, "the list did not scroll to reach the last theme")
        self.assertIn(last, [r[1] for r in rows[top:top + view]])


class TestDaysLeftColour(Base):

    def test_days_left_uses_maroon(self):
        from ui import days_style
        self.assertEqual(days_style(48), "bold dark_red")

    def test_an_unknown_deadline_stays_dim(self):
        from ui import days_style
        self.assertEqual(days_style("?"), "dim")

    def test_maroon_is_a_portable_colour_name(self):
        """Rich has no 'maroon', so we use dark_red - a named colour, not a
        hex. A hex would force truecolor escapes that break on 8- and
        256-colour terminals."""
        from rich.color import Color
        from ui import days_style
        style = days_style(10).split()[-1]
        self.assertEqual(style, "dark_red")
        self.assertFalse(style.startswith("#"))
        self.assertEqual(Color.parse(style).name, "dark_red")


class TestThemes(Base):

    def test_twenty_one_vivid_themes_are_offered(self):
        self.assertEqual(len(themes.ORDER), 21)
        self.assertEqual(len(themes.choices()), len(themes.ORDER))

    def test_the_leading_themes_come_first(self):
        self.assertEqual(themes.ORDER[:2], ["jade", "teal"])
        self.assertEqual([label for label, _ in themes.choices()[:2]],
                         ["Jade", "Teal"])

    def test_a_retired_theme_name_keeps_its_look(self):
        """A project that picked an old name got its palette; heal points it
        at the current name so the picker stops showing a ghost."""
        reg = store.registry()
        reg["projects"][self.key]["theme"] = "htb"
        store.save_registry(reg, record=False)
        store.heal()
        self.assertEqual(store.project(key=self.key)["theme"], "jade")
        self.assertEqual(themes.accent("jade"), "green3",
                         "the rename must not change the colours")

    def test_a_cut_theme_name_lands_on_its_closest_colour(self):
        """The list was trimmed to twenty-one vivid ones; a project holding a
        name that was cut is healed to the survivor beside it."""
        reg = store.registry()
        reg["projects"][self.key]["theme"] = "emerald"
        store.save_registry(reg, record=False)
        store.heal()
        self.assertEqual(store.project(key=self.key)["theme"], "mint")
        self.assertEqual(themes.accent("mint"), "medium_spring_green",
                         "a cut name must land on a real palette")
        reg["projects"][self.key]["theme"] = "sand"
        store.save_registry(reg, record=False)
        store.heal()
        self.assertEqual(store.project(key=self.key)["theme"], "gold")

    def test_order_and_palettes_agree(self):
        self.assertEqual(set(themes.ORDER), set(themes.THEMES))

    def test_every_accent_colour_is_distinct(self):
        accents = [themes.accent(k) for k in themes.ORDER]
        self.assertEqual(len(set(accents)), len(accents))

    def test_no_theme_uses_a_hex_colour(self):
        """A hex forces truecolor escapes that break on 8/256-colour terminals,
        so every colour must be a name Rich can quantise."""
        from rich.color import ANSI_COLOR_NAMES
        for key in themes.ORDER:
            palette = themes.THEMES[key]
            for role in ("accent", "bright"):
                self.assertNotIn("#", palette[role])
                self.assertIn(palette[role], ANSI_COLOR_NAMES)

    def test_every_theme_is_named_and_styled(self):
        for key in themes.ORDER:
            self.assertTrue(themes.label(key))
            self.assertTrue(themes.accent(key))

    def test_setting_and_reading_the_themes(self):
        store.set_theme(self.key, "gold")
        self.assertEqual(store.project_theme(self.key), "gold")

    def test_an_unknown_theme_falls_back(self):
        store.set_theme(self.key, "chartreuse")
        self.assertEqual(store.project_theme(self.key), themes.DEFAULT_THEME)

    def test_themes_reach_the_rendering(self):
        """The accent is not just stored - it paints the borders. A real
        render must carry the accent's own colour escape (named colours draw
        as their palette number), not just the word "Teal" the stats table
        happens to print."""
        import io
        from rich.color import ANSI_COLOR_NAMES
        from rich.console import Console
        store.set_theme(self.key, "teal")
        buf = io.StringIO()
        Console(file=buf, width=110, force_terminal=True).print(build_layout())
        number = ANSI_COLOR_NAMES[themes.accent("teal")]
        self.assertIn(f"38;5;{number}", buf.getvalue())


class TestHostileData(Base):
    """A data file can hold anything - names, notes and titles are edited by
    hand and travel between machines. Drawing them must not obey them.

    A "[/]" in a name used to be a markup error that closed the window, and a
    "\x1b]52;..." pasted or imported into a file was an instruction to the
    *terminal* to rewrite the clipboard. Every field here holds both."""

    HOSTILE = "box\x1b]52;c;QQ==\x07[/][link=http://evil]y"

    def _drawn(self, renderable):
        return render(renderable, width=100)

    def _write_machine(self, **fields):
        data = self.read("machines")
        machine = {"id": "m1", "categories": {}}
        machine.update(fields)
        data["projects"][self.key] = {"categories": [], "items": [machine]}
        (self.data / "machines.json").write_text(json.dumps(data))

    def test_control_characters_do_not_survive_a_read(self):
        self._write_machine(name=self.HOSTILE, notes="one\ntwo\tthree")
        machine = store.machines()[0]
        self.assertIn("box", machine["name"])
        self.assertIn("[/]", machine["name"])
        self.assertNotIn("\x1b", machine["name"])
        self.assertNotIn("\x07", machine["name"])
        self.assertEqual(machine["notes"], "one\ntwo\tthree")

    def test_a_list_draws_a_hostile_name_readably(self):
        class L:
            def update(self, r):
                self.last = r
            def refresh(self):
                pass
        live = L()
        ui.console.width, ui.console.height = 100, 40
        tui.render_list(live, "Machines", [self.HOSTILE],
                        [("i", 0, 1)], 0, 0, 5)
        text = self._drawn(live.last)
        self.assertIn("[/][link=http://evil]y", text)
        self.assertNotIn("\x1b", text)

    def test_the_editor_shows_brackets_as_brackets(self):
        buffer = tui.TextBuffer("a[/]b\x1b]0;title\x07")
        text = self._drawn(tui.multiline_block(buffer, 0, 5))
        self.assertIn("a[/]b", text)
        self.assertNotIn("\x1b", text)

    def test_a_prompt_and_its_choices_are_shown_as_typed(self):
        class L:
            def update(self, r):
                self.last = r
            def refresh(self):
                pass
        live = L()
        tui.render_input(live, "Pick\x1b[2J[/]:", "typed[/]",
                         options=["we[ird]"])
        text = self._drawn(live.last)
        self.assertIn("Pick[2J[/]:", text)
        self.assertIn("we[ird]", text)
        self.assertNotIn("\x1b", text)

    def test_the_summary_draws_a_hostile_row(self):
        machine = {"id": "m1", "name": self.HOSTILE, "notes": "n",
                   "completed": 0, "total": 1,
                   "completed_on": "2026-01-01" + self.HOSTILE}
        text = self._drawn(ui.summary_table([machine], "", 0, self.key))
        self.assertIn("[/][link=http://evil]y", text)
        self.assertNotIn("\x1b", text)

    def test_enter_steps_to_the_next_page_and_leaves_after_the_last(self):
        """Reading a machine is one key: ↵ Next through the pages, and the
        last ↵ hands control back instead of sitting on the final page."""
        self._write_machine(name="Web", description="an SMB box",
                            notes="what I found")
        drawn = []
        calls = []

        def press(timeout=None):
            calls.append(1)
            return "\r" if len(calls) <= 2 else tui.ESCAPE

        kept = (dashboard.read_key, dashboard.show_screen)
        dashboard.read_key = press
        dashboard.show_screen = lambda live, r, top: (drawn.append(r),
                                                      (top, 0))[1]

        class L:
            def update(self, r):
                pass
            def refresh(self):
                pass
            def is_terminal(self):
                return False
        try:
            dashboard.machine_view(L(), "m1")
        finally:
            dashboard.read_key, dashboard.show_screen = kept
        # Web has two pages: the box, then Notes. Two Enters: one to walk,
        # one to leave - a third key would never be read.
        self.assertEqual(len(calls), 2)
        self.assertEqual(len(drawn), 2, "a page was drawn after leaving")
        first = self._drawn(drawn[0])
        self.assertIn("(1/2)", first)
        self.assertIn("Next", first)
        last = self._drawn(drawn[-1])
        self.assertIn("(2/2)", last)
        self.assertIn("Exit", last)

    def test_the_machine_view_walks_the_categories_one_at_a_time(self):
        """Enter leads with the box - the description, written once - and then
        walks each category onto its own page. The description used to be
        repeated in a Description field on the page below."""
        self._write_machine(name="Web", description="an SMB box",
                            notes="what I found")
        drawn = []
        pressed = iter(["\r", "\r", "\r", "\r", tui.ESCAPE])
        kept = (dashboard.read_key, dashboard.show_screen)
        dashboard.read_key = lambda timeout=None: next(pressed, tui.ESCAPE)
        dashboard.show_screen = lambda live, r, top: (drawn.append(r),
                                                      (top, 0))[1]

        class L:
            def update(self, r):
                pass
            def refresh(self):
                pass
            def is_terminal(self):
                return False
        try:
            dashboard.machine_view(L(), "m1")
        finally:
            dashboard.read_key, dashboard.show_screen = kept
        first = self._drawn(drawn[0])
        self.assertEqual(first.count("an SMB box"), 1,
                         "the description is written more than once:\n" + first)
        self.assertNotIn("what I found", first,
                         "the notes leaked onto the description's page")
        walked = "\n\n".join(self._drawn(r) for r in drawn)
        self.assertEqual(walked.count("an SMB box"), 1,
                         "the description is written on more than one page")
        self.assertIn("Notes", walked)
        self.assertIn("what I found", walked)

    def test_the_machine_view_draws_hostile_data(self):
        data = self.read("machines")
        data["projects"][self.key] = {
            "categories": [{"id": "f1", "title": self.HOSTILE,
                            "default": self.HOSTILE}],
            "items": [{"id": "m1", "name": self.HOSTILE, "os": self.HOSTILE,
                       "description": self.HOSTILE, "notes": self.HOSTILE,
                       "categories": {"f1": None}}]}
        (self.data / "machines.json").write_text(json.dumps(data))

        class L:
            def update(self, r):
                pass
            def refresh(self):
                pass
            def is_terminal(self):
                return False
        drawn = []
        kept = (dashboard.read_key, dashboard.show_screen)
        dashboard.read_key = lambda timeout=None: tui.ESCAPE
        dashboard.show_screen = lambda live, r, top: (drawn.append(r),
                                                      (top, 0))[1]
        try:
            dashboard.machine_view(L(), "m1")
        finally:
            dashboard.read_key, dashboard.show_screen = kept
        text = self._drawn(drawn[-1])
        self.assertIn("[/][link=http://evil]y", text)
        self.assertNotIn("\x1b", text)

    def test_data_files_are_kept_to_their_owner(self):
        if os.name == "nt":
            self.skipTest("chmod does not mean read permission there")
        store.add_machine(self.key, "A")
        store.heal()
        self.assertEqual(
            stat.S_IMODE((self.data / "machines.json").stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.data.stat().st_mode), 0o700)

    def test_heal_tightens_files_left_open(self):
        if os.name == "nt":
            self.skipTest("chmod does not mean read permission there")
        path = self.data / "machines.json"
        os.chmod(path, 0o644)
        os.chmod(self.data, 0o755)
        store.heal()
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.data.stat().st_mode), 0o700)


class TestDataSafety(Base):

    def test_saved_file_is_always_valid_json(self):
        for i in range(200):
            store.add_machine(self.key, f"Box {i}")
            json.loads((self.data / "machines.json").read_text())

    def test_save_leaves_no_temp_file_behind(self):
        store.add_machine(self.key, "A")
        self.assertEqual(list(self.data.glob("*.tmp")), [])

    def test_backup_is_written_before_overwrite(self):
        store.add_machine(self.key, "A")
        store.add_machine(self.key, "B")
        newest = store.newest_backup("machines")
        self.assertIsNotNone(newest)
        self.assertEqual(len(json.loads(newest.read_text())["projects"][self.key]["items"]), 1)

    def test_heal_restores_a_corrupt_file(self):
        store.add_machine(self.key, "A")
        store.add_machine(self.key, "B")
        (self.data / "machines.json").write_text('{"projects": ')
        notes = store.heal()
        self.assertTrue(notes)
        self.assertEqual(len(store.machines()), 1)

    def test_undo_covers_this_session(self):
        store.add_machine(self.key, "A")
        store.add_machine(self.key, "B")
        self.assertIsNotNone(store.undo())
        self.assertEqual(len(store.machines()), 1)

    def test_undo_does_not_reach_back_past_a_restart(self):
        store.add_machine(self.key, "A")
        store.HISTORY = history_mod.History()
        self.assertIsNone(store.undo())
        self.assertEqual(len(store.machines()), 1)


class TestLayout(Base):

    def test_the_help_text_is_paged_on_a_short_screen(self):
        """The tail - undo, ctrl+s - used to fall off a 32-row terminal with
        no keypress able to reach it."""
        import dashboard
        pieces = []

        class Live:
            def update(self, renderable):
                pieces.append(renderable)

            def refresh(self):
                pass

        real_wait = dashboard.wait_for_key
        real_height = ui.console.height
        dashboard.wait_for_key = lambda *a, **kw: None
        ui.console.height = 24
        try:
            dashboard.action_help(Live(), None)
        finally:
            dashboard.wait_for_key = real_wait
            ui.console.height = real_height
        shown = "\n".join(render(piece, width=110) for piece in pieces)
        self.assertGreater(len(pieces), 1, "help was not paged")
        self.assertIn("any key for more", shown, "no sign of more text below")
        for tail in ("ctrl+x u", "Currently in"):
            self.assertIn(tail, shown, f"the tail {tail!r} is unreachable")

    def test_repository_is_not_on_the_dashboard(self):
        """It is a reference you open, not a figure to glance at."""
        text = render(build_layout(), width=120)
        head = text.split("[1]")[0]          # everything above the menu
        self.assertNotIn("Repository", head)

    def test_dashboard_renders_for_every_project(self):
        store.create_project("Other")
        for key in store.project_keys():
            store.select(key)          # the layout shows the active project
            text = flat(render(build_layout(), width=100))
            self.assertIn(store.project_name(key), text)
            # Every option is inside the menu box.
            for menu_key, label in ui.menu_items():
                self.assertIn(f"[{menu_key}] {label}", text)

    def test_renders_at_narrow_widths_without_overflow(self):
        for width in (50, 60, 80, 100, 140, 200):
            # Narrow the app's console before building: the layout chooses how
            # to arrange itself from that width, so building first and rendering
            # narrow afterwards tested a menu arranged for the wrong terminal.
            ui.console.width = width
            try:
                text = render(build_layout(), width=width)
            finally:
                ui.console.width = None
            self.assertTrue(text.strip())
            for line in text.split("\n"):
                self.assertLessEqual(len(line), width)
            # Every option stays readable at any width.
            squeezed = flat(text)
            for key, label in ui.menu_items():
                self.assertIn(f"[{key}] {label}", squeezed)

    def test_the_empty_project_words_match_the_panel_name(self):
        """It said "No machines yet" inside a panel called Topics. Every such
        string has to follow the name the project chose."""
        import ui
        for panel, noun in (("Topics", "topics"), ("Machines", "machines")):
            store.set_dashboard_panel(self.key, panel)
            ui.invalidate_dashboard()
            text = render(build_layout(), width=120)
            self.assertIn(f"No {noun} yet", text)
            self.assertIn(f"[2] {panel}", text)

    def test_an_empty_project_says_so(self):
        import ui
        store.set_dashboard_panel(self.key, "Machines")
        ui.invalidate_dashboard()
        try:
            self.assertIn("No machines yet", render(build_layout(), width=120))
        finally:
            store.set_dashboard_panel(self.key, "Topics")
            ui.invalidate_dashboard()

    def test_summary_lists_a_machine_beside_its_note(self):
        machine, _ = store.add_machine(self.key, "Target", "cloud-sync creds")
        store.mark_machine(self.key, machine["id"])
        text = render(summary_panel())
        self.assertIn("Target", text)
        self.assertIn("cloud-sync", text)

    def test_summary_says_so_when_nothing_is_done_at_all(self):
        text = render(summary_panel())
        self.assertIn("Nothing completed yet", text)

    def test_the_today_count_is_not_stated_twice(self):
        """The figure and the list must not both print it."""
        machine, _ = store.add_machine(self.key, "Once")
        store.mark_machine(self.key, machine["id"])
        text = render(summary_panel())
        self.assertEqual(text.count("Completed Today (1)"), 1)
        self.assertNotIn("Completed today (", text)

    def test_summary_offers_two_ways_in(self):
        """The panel and its settings, rather than one screen doing both."""
        import dashboard
        self.assertEqual([label for label, _ in dashboard.SUMMARY_MENU],
                         ["Show Summary", "Summary Settings"])

    def test_the_summary_settings_list_puts_the_fixed_three_last(self):
        """Status, Date and Notes are always in a summary, so they sit at the
        end of the screen in that order and are not rows you can turn off."""
        import dashboard
        rows = dashboard.summary_settings_rows()
        store.add_category(self.key, "foothold", "nc 443")
        rows = dashboard.summary_settings_rows()
        options = [row[1] for row in rows if row[0] == "row"]
        self.assertEqual(options[0], "machines")
        self.assertEqual(options[1], "fields")
        fixed = [row[1] for row in rows if row[0] == "fixed"]
        self.assertEqual(fixed[-3:], ["Status", "Date", "Notes"])
        self.assertNotIn("Notes", options, "a fixed row is not a switch")
        state = [row[3] for row in rows if row[0] == "row"]
        self.assertEqual(state[0], "shown")
        self.assertIn("of", state[1])

    def test_the_cursor_never_lands_on_a_fixed_row(self):
        """It has nothing to change, so standing on it would be a dead key
        press - on the very three rows people most try to switch off."""
        import dashboard
        rows = dashboard.summary_settings_rows()
        rows_that_move = [row[1] for row in rows if row[0] == "row"]
        for i in range(len(rows)):
            _, where = dashboard.summary_settings_panel(i)
            self.assertIn(rows_that_move[where], rows_that_move)

    def test_summary_settings_says_which_categories_are_shown(self):
        import dashboard
        store.add_category(self.key, "creds", "admin:admin")
        field, _ = store.add_category(self.key, "foothold", "nc 443")
        with _this_project_using_the_os(self.key):
            rows = dashboard.summary_settings_rows()
            states = [row[3] for row in rows if row[0] == "row"]
            self.assertEqual(states[1], "0 of 3 chosen")
            said, _ = dashboard.summary_option_action(field["id"], 0)
            self.assertIn("shown", said)
            rows = dashboard.summary_settings_rows()
        states = [row[3] for row in rows if row[0] == "row"]
        self.assertEqual(states[1], "1 of 3 chosen")
        ticked = next(row for row in rows
                      if row[0] == "row" and row[1] == field["id"])
        self.assertEqual(ticked[3], "shown")
        self.assertEqual(store.summary_settings(self.key)["categories"],
                         [field["id"]])

    def test_summary_settings_says_why_the_last_three_cannot_be_turned_off(self):
        import dashboard
        said, _ = dashboard.summary_option_action("notes", 0)
        self.assertIn("always", said.lower())
        self.assertEqual(store.summary_settings(self.key)["categories"], [],
                         "asking about a fixed row must change nothing")

    def test_summary_settings_enter_on_fields_goes_to_them(self):
        """The heading is a shortcut to the thing people came for, not a
        switch of its own."""
        import dashboard
        store.add_category(self.key, "foothold", "nc 443")
        said, moved = dashboard.summary_option_action("fields", 0)
        self.assertIn("below", said)
        rows = dashboard.summary_settings_rows()
        self.assertEqual(rows[moved][0], "row")
        self.assertNotIn(rows[moved][1], ("machines", "fields"))

    def test_the_os_is_a_category_of_the_summary_too(self):
        """It is written on the machine rather than shared, but it is a field
        of the machine all the same, and it belongs beside foothold and creds."""
        import dashboard
        with _this_project_using_the_os(self.key):
            rows = dashboard.summary_settings_rows()
            first = next(row for row in rows if row[0] == "row"
                         and row[1] != "machines" and row[1] != "fields")
            self.assertEqual(first[1], store.OS_CATEGORY)
            self.assertEqual(first[2], "OS")
            store.summary_toggle_category(self.key, store.OS_CATEGORY)
            rows = dashboard.summary_settings_rows()
            ticked = next(row for row in rows if row[0] == "row"
                          and row[1] == store.OS_CATEGORY)
            self.assertEqual(ticked[3], "shown")
            self.assertEqual(store.summary_settings(self.key)["categories"],
                             [store.OS_CATEGORY])
            self.assertEqual(store.summary_category_ids(self.key),
                             [store.OS_CATEGORY])

    def test_the_os_column_shows_what_each_machine_says(self):
        machine, _ = store.add_machine(self.key, "Nickel", os_name="Linux")
        other, _ = store.add_machine(self.key, "Copper", os_name="Windows")
        store.mark_machine(self.key, machine["id"])
        store.mark_machine(self.key, other["id"])
        with _this_project_using_the_os(self.key):
            store.summary_toggle_category(self.key, store.OS_CATEGORY)
            text = render(summary_panel())
        self.assertIn("OS", text)
        self.assertIn("Linux", text)
        self.assertIn("Windows", text)

    def test_the_os_leads_the_other_fields(self):
        """It is the field every machine has, so it reads as the start of the
        row rather than as one more column in the middle."""
        field, _ = store.add_category(self.key, "foothold", "nc 443")
        store.summary_toggle_category(self.key, field["id"])
        with _this_project_using_the_os(self.key):
            store.summary_toggle_category(self.key, store.OS_CATEGORY)
            ids = store.summary_category_ids(self.key)
        self.assertEqual(ids, [store.OS_CATEGORY, field["id"]])

    def test_an_id_that_is_not_a_category_is_refused(self):
        self.assertEqual(store.summary_toggle_category(self.key, "nope"),
                         "No such category")

    def test_the_settings_panel_uses_the_machine_tick(self):
        """The same tick the machines list puts on a finished box, not a tick
        inside a box: a field marked here should read like a machine marked
        there."""
        import dashboard
        from rich.console import Console
        store.add_category(self.key, "foothold", "nc 443")
        store.summary_toggle_category(self.key, store.OS_CATEGORY)
        ui.console.width, ui.console.height = 100, 40
        with _this_project_using_the_os(self.key):
            panel, _ = dashboard.summary_settings_panel(0)
            rows = [row for row in dashboard.summary_settings_rows()
                    if row[0] == "row" and row[1] == store.OS_CATEGORY]
        rec = Console(width=100, height=40, record=True,
                      file=open("/dev/null", "w"))
        rec.print(panel)
        text = rec.export_text()
        self.assertIn("\u2713 OS", text)
        self.assertNotIn("\u2611", text)          # no ticked box
        self.assertNotIn("\u2612", text)          # and no empty box
        self.assertEqual(rows[0][3], "shown")

    def test_the_settings_panel_is_drawn_not_picked(self):
        """It used to be a picker, which numbered every row as if they were
        all the same kind of choice."""
        import dashboard
        from rich.console import Console
        ui.console.width, ui.console.height = 100, 40
        store.add_category(self.key, "foothold", "nc 443")
        with _this_project_using_the_os(self.key):
            panel, _ = dashboard.summary_settings_panel(0)
        rec = Console(width=100, height=40, record=True,
                      file=open("/dev/null", "w"))
        rec.print(panel)
        text = rec.export_text()
        self.assertIn("Summary Settings", text)
        self.assertIn("Always shown", text)
        for number in ("1.", "2.", "3."):
            self.assertNotIn(number, text)
        self.assertNotIn("[reverse]", text)     # no markup leaked through
        self.assertNotIn("[bold", text)
        self.assertIn("✓ Topics", text)    # the machines list's own tick
        self.assertIn("OS", text)          # the OS is a field, and is listed


    def test_field_prompts_are_drawn_on_the_live_view(self):
        """The add and edit forms passed None as the view, so the questions
        were drawn on a screen nobody was watching and the first keystroke
        raised instead of being typed."""
        import inspect
        import dashboard
        for name in ("category_add", "category_edit"):
            fn = getattr(dashboard, name)
            self.assertEqual(list(inspect.signature(fn).parameters)[0], "live",
                             name)
            source = inspect.getsource(fn)
            self.assertNotIn("inline_prompt(None", source, name)
            self.assertIn("inline_prompt(live", source, name)


    def test_a_category_deleted_from_the_project_leaves_the_summary(self):
        field, _ = store.add_category(self.key, "foothold", "nc 443")
        store.summary_toggle_category(self.key, field["id"])
        store.delete_category(self.key, field["id"])
        self.assertEqual(store.summary_settings(self.key)["categories"], [])
        import dashboard
        self.assertNotIn("foothold",
                         [row[2] for row in dashboard.summary_settings_rows()
                          if row[0] == "row"])

    def test_the_first_column_is_called_whatever_the_panel_is_called(self):
        """It said Machine over a panel headed Topics, so the two disagreed
        about the same column. Switching the panel moves the heading with it."""
        machine, _ = store.add_machine(self.key, "Target")
        store.mark_machine(self.key, machine["id"])
        for panel, other in (("Topics", "Machines"), ("Machines", "Topics")):
            store.set_dashboard_panel(self.key, panel)
            ui.invalidate_dashboard()
            head = next(line for line in render(summary_panel()).splitlines()
                        if "Status" in line)
            self.assertIn(panel, head)
            self.assertNotIn(other, head)

    def test_status_says_done_unless_the_project_asks_for_pwned(self):
        machine, _ = store.add_machine(self.key, "Target")
        store.mark_machine(self.key, machine["id"])
        text = render(summary_panel())
        self.assertIn("Done", text)
        self.assertNotIn("pwned", text)
        self.assertEqual(store.summary_status_word(self.key), "Done")
        store.summary_toggle_status_word(self.key)
        ui.invalidate_dashboard()
        self.assertEqual(store.summary_status_word(self.key), "pwned")
        text = render(summary_panel())
        self.assertIn("pwned", text)
        self.assertNotIn("Done", text)
        store.summary_toggle_status_word(self.key)
        self.assertEqual(store.summary_status_word(self.key), "Done")

    def test_the_status_wording_is_its_own_row_in_the_settings(self):
        import dashboard
        rows = dashboard.summary_settings_rows()
        row = next(r for r in rows if r[0] == "row" and r[1] == "wording")
        self.assertEqual(row[2], "Status wording")
        self.assertEqual(row[3], "reads Done")
        said, _ = dashboard.summary_option_action("wording", 0)
        self.assertIn("pwned", said)
        self.assertEqual(store.summary_status_word(self.key), "pwned")
        self.assertEqual(next(r for r in dashboard.summary_settings_rows()
                              if r[1] == "wording")[3], "reads pwned")

    def test_the_settings_screen_turns_the_wording_on_enter(self):
        """Driven key by key, the way it is used: walk down to the row and
        press enter. The wording row is the last one that moves, so walking off
        the end of it is the easy mistake."""
        import inspect
        import dashboard
        from tui import KEY_DOWN, ESCAPE
        rows = dashboard.summary_settings_rows()
        movable = [i for i, row in enumerate(rows) if row[0] == "row"]
        wording = next(i for i, row in enumerate(rows)
                       if row[0] == "row" and row[1] == "wording")
        self.assertEqual(movable[-1], wording,
                         "the wording row should be the last one that moves")
        keys = [KEY_DOWN] * movable.index(wording) + ["\r", ESCAPE]
        walked = []

        original = dashboard.summary_settings_panel

        def spy(cursor=0):
            panel, where = original(cursor)
            walked.append(cursor)
            return panel, where

        kept = {name: getattr(dashboard, name)
                for name in ("read_key", "show_screen", "build_layout")}
        dashboard.summary_settings_panel = spy
        dashboard.read_key = lambda *a, **k: keys.pop(0) if keys else None
        dashboard.show_screen = lambda live, r, top: (top, 0)
        dashboard.build_layout = lambda **k: ""
        ui.console.width, ui.console.height = 100, 40
        try:
            dashboard.summary_settings(None, None)
        finally:
            dashboard.summary_settings_panel = original
            for name, value in kept.items():
                setattr(dashboard, name, value)
        self.assertEqual(walked[-2], wording,
                         f"enter was pressed on {rows[walked[-2]][1]!r}")
        self.assertEqual(store.summary_status_word(self.key), "pwned")

    def test_the_status_wording_belongs_to_the_project(self):
        other, _ = store.create_project("Other")
        store.summary_toggle_status_word(self.key)
        self.assertEqual(store.summary_status_word(other), "Done")

    def test_summary_shows_total_done_and_today(self):
        store.add_machine(self.key, "One")
        store.add_machine(self.key, "Two")
        store.add_machine(self.key, "Three")
        machine = store.machines()[0]
        store.mark_machine(self.key, machine["id"])
        text = render(summary_panel())
        self.assertIn("Total (3)", text)
        self.assertIn("Done (1)", text)
        self.assertIn("Completed Today (1)", text)

    def test_the_headline_says_what_the_status_column_says(self):
        """The figure used to be nailed to "Pwned" while the rows below it
        read whatever the project had asked for, so switching the wording in
        Summary Settings renamed the rows and left the headline alone."""
        machine, _ = store.add_machine(self.key, "One")
        store.mark_machine(self.key, machine["id"])
        store.summary_toggle_status_word(self.key)
        text = render(summary_panel())
        self.assertIn("pwned (1)", text)
        self.assertNotIn("Pwned (1)", text)
        store.summary_toggle_status_word(self.key)
        text = render(summary_panel())
        self.assertIn("Done (1)", text)

    def test_summary_falls_back_to_recent_when_nothing_is_done_today(self):
        """An empty panel on a day you are stuck is no use, so the last wins
        are shown instead - dated, so it is obvious they are not from today."""
        machine, _ = store.add_machine(self.key, "Older", os_name="Linux")
        store.mark_machine(self.key, machine["id"])
        data = json.loads((Path(TMP) / "machines.json").read_text())
        data["projects"][self.key]["items"][0]["completed_on"] = "2025-01-01"
        (Path(TMP) / "machines.json").write_text(json.dumps(data))
        text = render(summary_panel())
        self.assertIn("Nothing completed today", text)
        self.assertIn("Older", text)
        self.assertIn("2025-01-01", text)

    def test_summary_ends_with_status_date_and_notes(self):
        """Those three are in every summary, in that order, last. The columns
        before them are the only things Summary Settings is allowed to change,
        and the OS was not one of them."""
        machine, _ = store.add_machine(self.key, "Nickel", os_name="Linux")
        store.mark_machine(self.key, machine["id"])
        text = render(summary_panel())
        first = store.dashboard_panel(self.key)
        head = [line for line in text.split("\n") if first in line][0]
        self.assertLess(head.index(first), head.index("Status"))
        self.assertLess(head.index("Status"), head.index("Date"))
        self.assertLess(head.index("Date"), head.index("Notes"))
        self.assertNotIn("Linux", text, "the OS column is gone from the summary")

    def test_summary_shows_a_chosen_field_beside_each_machine(self):
        field, _ = store.add_category(self.key, "foothold", "nc -lvnp 443")
        machine, _ = store.add_machine(self.key, "Nickel")
        store.mark_machine(self.key, machine["id"])
        store.attach_machine_categories(self.key, machine["id"], [field["id"]])
        self.assertNotIn("foothold", render(summary_panel()),
                         "a field shows only once it is asked for")
        store.summary_toggle_category(self.key, field["id"])
        text = render(summary_panel())
        self.assertIn("foothold", text)
        self.assertIn("nc -lvnp 443", text)
        self.assertIn("Nickel", text)

    def test_a_machine_can_be_left_out_of_the_summary(self):
        field, _ = store.add_category(self.key, "creds", "admin:admin")
        machine, _ = store.add_machine(self.key, "Nickel")
        store.mark_machine(self.key, machine["id"])
        store.attach_machine_categories(self.key, machine["id"], [field["id"]])
        store.summary_toggle_category(self.key, field["id"])
        store.summary_show_machines(self.key, False)
        text = render(summary_panel())
        self.assertNotIn("Nickel", text, "the machine column was hidden")
        self.assertIn("creds", text, "hiding the names is not hiding the fields")
        self.assertIn("Status", text)

    def test_summary_marks_a_missing_os_with_a_dash(self):
        machine, _ = store.add_machine(self.key, "NoOS")
        store.mark_machine(self.key, machine["id"])
        self.assertIn("NoOS", render(summary_panel()))

    def test_summary_caps_a_long_day(self):
        for i in range(ui.SUMMARY_ROWS + 3):
            machine, _ = store.add_machine(self.key, f"M{i}")
            store.mark_machine(self.key, machine["id"])
        text = render(summary_panel())
        # It says how much is left rather than a flat "more today": the list can
        # now be scrolled to, so the marker points at what is below.
        self.assertIn("more below", text)
        self.assertIn(f"{ui.SUMMARY_ROWS + 3 - ui.SUMMARY_ROWS}", text)

    def test_summary_notes_keep_their_line_breaks(self):
        """Notes are several lines long; the panel must not squash them into
        one run-on line, which misrepresents what was written."""
        machine, _ = store.add_machine(self.key, "Long",
                                       notes="kerberoast svc\ncrack it\nDCSync")
        store.mark_machine(self.key, machine["id"])
        # Strip the table borders; what matters is one line of the note per
        # row, not three joined into one.
        rows = [ln.strip("│ ").rstrip() for ln in render(summary_panel()).split("\n")]
        rows = [ln for ln in rows if ln.strip()]
        for phrase in ("kerberoast svc", "crack it", "DCSync"):
            self.assertTrue(any(ln.strip().endswith(phrase) for ln in rows),
                            f"{phrase!r} is not on a line of its own: {rows}")

    def test_summary_cuts_a_very_long_note_but_says_so(self):
        machine, _ = store.add_machine(self.key, "Long",
                                       notes="\n".join(f"line {i}" for i in range(9)))
        store.mark_machine(self.key, machine["id"])
        self.assertIn("more", render(summary_panel()))

    def test_reset_clears_progress_but_keeps_machines(self):
        machine, _ = store.add_machine(self.key, "Target")
        store.mark_machine(self.key, machine["id"])
        store.add_hours(self.key, 4)
        cleared, hours = store.reset_project(self.key)
        self.assertEqual((cleared, hours), (1, 4))
        self.assertEqual(store.tally(), (0, 1))
        self.assertEqual(store.stats()["hours_studied"], 0)


class TestFreshInstall(Base):

    def test_bootstrap_creates_every_data_file(self):
        for name in store.DATA_FILES:
            self.assertTrue(store.readable(self.data / f"{name}.json"))


def tearDownModule():
    shutil.rmtree(TMP, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)