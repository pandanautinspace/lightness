"""Kits must not rot: every shell renders and starts, every part runs and does what it says."""

import asyncio
import json
import subprocess
import importlib.util
import sys
from pathlib import Path

import pytest

from lightness.kits import KITS_DIR, load_kit, render_shell

TUI = KITS_DIR / "tui"


def part(name: str):
    spec = importlib.util.spec_from_file_location(f"kitpart_{name}", TUI / "parts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def drive(app, steps):
    """Run the app headless; steps(app, pilot) is an async function doing the checks."""
    async def run():
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            await steps(app, pilot)
    asyncio.run(run())


def labels(app, selector):
    from textual.widgets import Label, ListView
    return [str(i.query_one(Label).content) for i in app.query_one(selector, ListView).children]


def test_every_listed_part_exists_and_parses():
    kit = load_kit("tui")
    names = [p.name for p in kit.parts]
    assert set(kit.meta["always"]) <= set(names)
    files = {p.stem for p in (TUI / "parts").glob("*.py")}
    assert set(names) == files


def test_list_actions():
    mod = part("list_actions")

    async def steps(app, pilot):
        from textual.widgets import ListView
        await pilot.click("#new-item")
        await pilot.press(*"textual.io", "enter")
        await pilot.pause()
        assert app.focused.id == "new-item"
        assert [i["url"] for i in app.items] == ["example.org", "python.org", "textual.io"]
        app.query_one("#items", ListView).focus()
        await pilot.press("up", "s")  # highlighted was the new item; up = python.org
        await pilot.pause()
        assert app.items[1]["starred"] is True
        assert labels(app, "#items")[1].startswith("★")
        await pilot.press("x")
        await pilot.pause()
        assert [i["url"] for i in app.items] == ["example.org", "textual.io"]
        assert labels(app, "#items")[1].endswith("textual.io")

    drive(mod.ListActionsApp(), steps)


def test_input_form():
    mod = part("input_form")

    async def steps(app, pilot):
        from textual.widgets import Static
        await pilot.click("#amount")
        await pilot.press(*"2")
        await pilot.pause()
        assert str(app.query_one("#result", Static).content) == "2000 m"
        app.query_one("#unit").value = "mi"
        await pilot.pause()
        assert str(app.query_one("#result", Static).content) == "3219 m"
        await pilot.press("home", "-")
        await pilot.pause()
        assert str(app.query_one("#result", Static).content) == ""
        assert str(app.query_one("#error", Static).content)

    drive(mod.ConverterApp(), steps)


def test_modal_edit_and_confirm():
    mod = part("modal")

    async def steps(app, pilot):
        from textual.widgets import Static
        await pilot.press("e")
        await pilot.pause()
        app.screen.query_one("#edit-value").value = ""
        await pilot.press(*"hello", "enter")
        await pilot.pause()
        assert app.title_text == "hello"
        await pilot.press("e")
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        assert app.title_text == "hello"
        await pilot.press("x")
        await pilot.pause()
        await pilot.click("#yes")
        await pilot.pause()
        assert app.title_text == "" and str(app.query_one("#title", Static).content) == ""

    drive(mod.ModalApp(), steps)


def test_data_table():
    mod = part("data_table")

    async def steps(app, pilot):
        from textual.widgets import DataTable, Static
        table = app.query_one("#table", DataTable)
        table.focus()
        await pilot.press("s")  # sort by name: apple, fig, pear
        await pilot.pause()
        assert app.selected()["name"] == "apple"
        await pilot.press("down", "enter")
        await pilot.pause()
        assert str(app.query_one("#detail", Static).content) == "fig: 7"
        await pilot.press("q")  # by qty: 3, 7, 10
        await pilot.pause()
        assert [table.get_row_at(i)[1] for i in range(3)] == [3, 7, 10]

    drive(mod.TableApp(), steps)


def test_filter():
    mod = part("filter")

    async def steps(app, pilot):
        from textual.widgets import Static
        await pilot.click("#query")
        await pilot.press(*"ap")
        await pilot.pause()
        assert labels(app, "#results") == ["apple", "apricot", "grape"]
        assert str(app.query_one("#count", Static).content) == "3 of 6"
        await pilot.press("backspace", "backspace", *"zzz")
        await pilot.pause()
        assert labels(app, "#results") == [] and app.matches == []

    drive(mod.FilterApp(), steps)


def params(*specs: str) -> list[dict]:
    """params("data_path:data:notes.json", "now:clock") → the kit's params list."""
    out = []
    for spec in specs:
        name, role, *file = spec.split(":")
        out.append({"name": name, "role": role, "file": file[0] if file else ""})
    return out


SHELL_NAMES = {
    "json": {"module": "notes", "app_class": "NotesApp", "title": "Notes",
             "params": params("data_path:data:notes.json"), "empty_value": "[]", "sample_data": ""},
    "other": {"module": "ledger", "app_class": "LedgerApp", "title": "Ledger",
              "params": params("db_path:data:ledger.db"), "empty_value": "[]", "sample_data": ""},
    "none": {"module": "calc", "app_class": "CalcApp", "title": "Calc", "params": [], "empty_value": "[]",
             "sample_data": ""},
    "mixed": {"module": "lookup", "app_class": "LookupApp", "title": "Lookup",
              "params": params("places_path:input:places.csv", "saved_path:data:saved.json", "now:clock",
                               "seed:seed", "size:other"), "empty_value": "{}", "sample_data": ""},
}


@pytest.mark.parametrize("kind", list(SHELL_NAMES))
def test_shell_renders_and_starts(kind, tmp_path):
    names = SHELL_NAMES[kind]
    text = render_shell(load_kit("tui"), names)
    keeps_json = kind in ("json", "mixed")
    assert ("import json" in text) == keeps_json
    assert ("from pathlib import Path" in text) == (kind != "none")
    path = tmp_path / f"{names['module']}.py"
    path.write_text(text)
    spec = importlib.util.spec_from_file_location(f"shell_{kind}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    app_cls = getattr(mod, names["app_class"])
    files = [p for p in names["params"] if p["role"] in ("data", "input")]
    app = app_cls(*[str(tmp_path / p["file"]) for p in files])  # positional, in the contract's order

    async def steps(app, pilot):
        if keeps_json:
            assert app.data == json.loads(names["empty_value"])
            app.data = {"x": 1}
            app.save()

    drive(app, steps)
    if kind == "mixed":
        assert callable(app.now) and hasattr(app.rng, "random") and app.size_arg is None  # App has .size
        assert mod.load_data(tmp_path / "saved.json") == {"x": 1}
        assert "Run: python lookup.py [PLACES_PATH] [SAVED_PATH]" in text
    if kind == "json":
        assert mod.load_data(tmp_path / "notes.json") == {"x": 1}


def test_shell_main_passes_paths_by_parameter(tmp_path, monkeypatch):
    path = tmp_path / "lookup.py"
    path.write_text(render_shell(load_kit("tui"), SHELL_NAMES["mixed"]))
    spec = importlib.util.spec_from_file_location("shell_main", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    made = []
    monkeypatch.setattr(mod.LookupApp, "run", lambda self: made.append(self))
    mod.main(["a.csv", "b.json"])
    mod.main([])
    assert (str(made[0].places_path), str(made[0].saved_path)) == ("a.csv", "b.json")
    assert (str(made[1].places_path), str(made[1].saved_path)) == ("places.csv", "saved.json")


def test_shell_rejects_bad_names():
    with pytest.raises((ValueError, KeyError)):
        render_shell(load_kit("tui"), {"module": "x", "params": []})
    with pytest.raises(ValueError):
        render_shell(load_kit("tui"), {**SHELL_NAMES["none"], "params": params("a:data", "a:input")})


def test_periodic_refresh_with_fake_clock():
    mod = part("periodic_refresh")
    clock = [100.0]

    async def steps(app, pilot):
        await pilot.press("space")  # start at t=100
        clock[0] = 107.5
        app.tick()
        await pilot.pause()
        assert round(app.elapsed, 1) == 7.5
        await pilot.press("space")  # stop: banked 7.5
        clock[0] = 200.0
        app.tick()
        assert round(app.elapsed, 1) == 7.5
        await pilot.press("r")
        assert app.elapsed == 0.0

    drive(mod.StopwatchApp(now=lambda: clock[0]), steps)


def test_worker(tmp_path):
    mod = part("worker")
    (tmp_path / "a.txt").write_text("hello world\nnothing\n")
    (tmp_path / "b.txt").write_text("Hello again\n")

    async def steps(app, pilot):
        from textual.widgets import Static
        await pilot.click("#query")
        await pilot.press(*"hello", "enter")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert app.hits == ["a.txt:1: hello world", "b.txt:1: Hello again"]
        assert str(app.query_one("#status", Static).content) == "2 matches"

    drive(mod.GrepApp(str(tmp_path)), steps)


def test_tree_detail():
    mod = part("tree_detail")

    async def steps(app, pilot):
        from textual.widgets import Static, Tree
        tree = app.query_one("#tree", Tree)
        tree.focus()
        labels_seen = []
        for _ in range(5):
            await pilot.press("down")
            await pilot.pause()
            labels_seen.append(str(tree.cursor_node.label))
        assert "owner" in labels_seen
        tree.select_node(next(n for n in tree.root.children if str(n.label) == "owner"))
        tree.move_cursor(next(n for n in tree.root.children if str(n.label) == "owner"))
        await pilot.pause()
        assert '"email": "x@example.com"' in str(app.query_one("#detail", Static).content)

    drive(mod.JsonTreeApp(), steps)


def test_screens_tabs():
    mod = part("screens_tabs")

    async def steps(app, pilot):
        from textual.widgets import Static, TabbedContent
        await pilot.press("2")
        await pilot.pause()
        assert app.query_one("#tabs", TabbedContent).active == "about"
        await pilot.press("1", "s")
        await pilot.pause()
        app.screen.query_one("#name").value = ""
        await pilot.press(*"Ada", "enter")
        await pilot.pause()
        assert app.user_name == "Ada"
        assert str(app.query_one("#greeting", Static).content) == "Hello, Ada!"
        await pilot.press("s", "escape")
        await pilot.pause()
        assert app.user_name == "Ada"

    drive(mod.TabsApp(), steps)


def test_grid_game():
    mod = part("grid_game")

    async def steps(app, pilot):
        from textual.widgets import Static
        await pilot.press("right", "down", "space")  # centre
        await pilot.pause()
        assert app.board == [[False, True, False], [True, True, True], [False, True, False]]
        assert app.query_one("#cell-1-1", Static).has_class("on", "cursor")
        assert str(app.query_one("#status", Static).content) == "Moves: 1"

    drive(mod.LightsApp(), steps)


def test_text_editor(tmp_path):
    mod = part("text_editor")
    path = tmp_path / "n.txt"
    path.write_text("one\n")

    async def steps(app, pilot):
        from textual.widgets import Static, TextArea
        assert app.dirty is False and app.query_one("#editor", TextArea).text == "one\n"
        app.query_one("#editor", TextArea).focus()
        await pilot.press("end", *"!")
        await pilot.pause()
        assert app.dirty is True and str(app.query_one("#status", Static).content).endswith("*")
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert app.dirty is False and path.read_text() == "one!\n"

    drive(mod.EditorApp(str(path)), steps)


def test_sqlite_store(tmp_path):
    mod = part("sqlite_store")
    store = mod.Store(tmp_path / "x.db")
    a, b = store.add("a"), store.add("b")
    store.set_favourite(a, True)
    store.delete(b)
    store.close()
    assert mod.Store(tmp_path / "x.db").all() == [{"id": a, "name": "a", "favourite": 1}]


def test_file_loader(tmp_path):
    mod = part("file_loader")
    csv_path = tmp_path / "d.csv"
    csv_path.write_text("﻿name,qty\npear,3\n", encoding="utf-8")

    async def ok(app, pilot):
        from textual.widgets import DataTable
        assert app.records == [{"name": "pear", "qty": "3"}]
        assert app.query_one("#records", DataTable).row_count == 1

    async def missing(app, pilot):
        from textual.widgets import Static
        assert app.records == [] and "not found" in str(app.query_one("#status", Static).content)

    drive(mod.LoaderApp(str(csv_path)), ok)
    drive(mod.LoaderApp(str(tmp_path / "nope.json")), missing)


def test_cheatsheet_claims():
    """Claims in kits/tui/cheatsheet.md that the parts' tests don't already cover."""
    from textual.app import App
    from textual.containers import Vertical
    from textual.css.query import NoMatches
    from textual.widget import MountError
    from textual.widgets import Input, Label, ListItem, ListView, Static

    class A(App):
        CSS = "ListItem.-highlight { color: red; } Input:focus { color: blue; }"

        def compose(self):
            yield Input(id="inp")
            yield ListView(ListItem(Label("a")), ListItem(Label("b")), id="lv")

    async def steps(app, pilot):
        with pytest.raises(AttributeError, match="focusable"):
            app.set_focus("#inp")
        with pytest.raises(NoMatches):
            app.query_one("#missing")
        lv = app.query_one("#lv", ListView)
        lv.focus()
        await pilot.press("down")
        await pilot.pause()
        assert lv.highlighted_child.has_class("-highlight")
        await lv.clear()
        await lv.extend([ListItem(Label("c"))])
        assert lv.index is None
        with pytest.raises(MountError):
            await Vertical().mount(Static("x"))

    drive(A(), steps)

    class BadCss(App):
        CSS = "Input:focused { color: red; }"

    with pytest.raises(Exception):
        drive(BadCss(), lambda app, pilot: asyncio.sleep(0))


def try_app(ws: Path, names: dict, *args: str) -> str:
    kit = load_kit("tui")
    (ws / ".lightness" / "kit").mkdir(parents=True, exist_ok=True)
    (ws / ".lightness" / "kit" / "try_app.py").write_text(kit.try_tool.read_text())
    (ws / ".lightness" / "kit" / "try_app.json").write_text(json.dumps(names))
    proc = subprocess.run([sys.executable, ".lightness/kit/try_app.py", *args], cwd=ws, capture_output=True,
                          text=True, timeout=60, check=False)
    return proc.stdout + proc.stderr


def test_try_app_shows_list_highlight_and_data_file(tmp_path):
    (tmp_path / "bookmarks.py").write_text((KITS_DIR / "tui" / "parts" / "list_actions.py").read_text())
    out = try_app(tmp_path, {"module": "bookmarks", "app_class": "ListActionsApp", "params": []},
                  "focus:#items", "press:down,s", "press:x")
    assert "#items list, highlighted=0:\n    [0] example.org\n    [1] python.org" in out
    assert "after press:down,s:\n  #items list, highlighted=1:\n    [0] example.org\n    [1] ★ python.org" in out
    assert "after press:x:\n  #items list, highlighted=0:\n    [0] example.org\n" in out


def test_try_app_data_file_restart_and_quit(tmp_path):
    names = SHELL_NAMES["json"]
    (tmp_path / "notes.py").write_text(render_shell(load_kit("tui"), names))
    out = try_app(tmp_path, names, "--data", '[{"x": 1}]', "restart", "press:ctrl+q")
    assert 'data_path file: [{"x": 1}]' in out
    assert "after restart (same files):" in out
    assert "the app exited" in out
    assert not list((tmp_path / ".lightness").glob("try-*"))  # temp data cleaned up


def test_try_app_grid_modal_and_crash(tmp_path):
    parts = KITS_DIR / "tui" / "parts"
    (tmp_path / "lights.py").write_text((parts / "grid_game.py").read_text())
    out = try_app(tmp_path, {"module": "lights", "app_class": "LightsApp", "params": []}, "press:space")
    assert "#board grid 3 wide:\n    cursor+on on        .\n    on        .         ." in out
    (tmp_path / "titles.py").write_text((parts / "modal.py").read_text())
    out = try_app(tmp_path, {"module": "titles", "app_class": "ModalApp", "params": []}, "press:e")
    assert "(now on EditScreen)" in out and "#edit-value input: 'untitled'" in out
    (tmp_path / "broken.py").write_text("from textual.app import App\nclass B(App):\n    def on_mount(self):\n"
                                        "        raise RuntimeError('boom')\n")
    out = try_app(tmp_path, {"module": "broken", "app_class": "B", "params": []})
    assert "CRASH:" in out and "RuntimeError: boom" in out and "broken.py" in out


def test_try_app_unknown_widget_is_not_a_crash(tmp_path):
    (tmp_path / "bookmarks.py").write_text((KITS_DIR / "tui" / "parts" / "list_actions.py").read_text())
    out = try_app(tmp_path, {"module": "bookmarks", "app_class": "ListActionsApp", "params": []},
                  "focus:#nope", "focus:#items")
    assert "no widget matches '#nope' on this screen; ids here: #items, #new-item" in out
    assert "CRASH" not in out and "focus: #items" in out


def test_try_app_documented_input_replace_works(tmp_path):
    assert "press:end,ctrl+u" in (KITS_DIR / "tui" / "try.md").read_text()
    (tmp_path / "conv.py").write_text((KITS_DIR / "tui" / "parts" / "input_form.py").read_text())
    out = try_app(tmp_path, {"module": "conv", "app_class": "ConverterApp", "params": []},
                  "type:12", "focus:#amount", "press:end,ctrl+u", "type:3")
    assert "after type:3:\n  #amount input: '3'" in out


TWO_FILES = """\
import json
from pathlib import Path
from textual.app import App
from textual.widgets import Static


class Both(App):
    BINDINGS = [("a", "add", "Add")]

    def __init__(self, places_path="places.csv", saved_path="saved.json"):
        super().__init__()
        self.places = Path(places_path).read_text().split()
        self.saved_path = Path(saved_path)

    def compose(self):
        yield Static(" ".join(self.places), id="places")

    def action_add(self):
        self.saved_path.write_text(json.dumps(self.places[:1]))
"""


def test_try_app_gives_a_two_file_app_both_files(tmp_path):
    (tmp_path / "both.py").write_text(TWO_FILES)
    (tmp_path / "places.csv").write_text("ams\nber\n")  # the project's input file: copied by default
    names = {"module": "both", "app_class": "Both",
             "params": params("places_path:input:places.csv", "saved_path:data:saved.json")}
    out = try_app(tmp_path, names, "press:a")
    assert "places_path: a copy of the project's places.csv; saved_path: no file yet" in out
    assert "#places: 'ams ber'" in out and "saved_path file: (not created)" in out
    assert 'after press:a:\n  saved_path file: ["ams"]' in out
    out = try_app(tmp_path, names, "--file-text", "places_path=osl", "--file-text", 'saved_path=["x"]')
    assert "#places: 'osl'" in out and 'saved_path file: ["x"]' in out
    out = try_app(tmp_path, names, "--data", "x")
    assert "--data/--data-from need exactly one file parameter" in out and "--file NAME=PATH" in out
    out = try_app(tmp_path, names, "--file", "nope=x")
    assert "NAME one of the App's file parameters: places_path, saved_path" in out


def test_try_app_data_param_starts_from_the_projects_file(tmp_path):
    """A model may label a provided, read-only file as data: it still starts as the project's copy
    (as `python app.py` would read it), except under --empty (the harness's own no-file check)."""
    (tmp_path / "both.py").write_text(TWO_FILES)
    (tmp_path / "places.csv").write_text("ams\nber\n")
    names = {"module": "both", "app_class": "Both",
             "params": params("places_path:data:places.csv", "saved_path:data:saved.json")}
    out = try_app(tmp_path, names)
    assert "places_path: a copy of the project's places.csv" in out and "#places: 'ams ber'" in out
    assert "saved_path: no file yet" in out
    out = try_app(tmp_path, names, "--empty")
    assert "places_path: no file yet" in out
    out = try_app(tmp_path, names, "--file-text", r"places_path=osl\nrom")  # one-line text: \n is a line break
    assert "#places: 'osl rom'" in out


def test_try_app_gives_an_input_only_app_its_file(tmp_path):
    (tmp_path / "viewer.py").write_text(
        "from pathlib import Path\nfrom textual.app import App\nfrom textual.widgets import Static\n\n\n"
        "class V(App):\n    def __init__(self, json_path='doc.json'):\n        super().__init__()\n"
        "        self.text = Path(json_path).read_text()\n\n"
        "    def compose(self):\n        yield Static(self.text, id='body')\n")
    (tmp_path / "in.json").write_text('{"a": 1}')
    names = {"module": "viewer", "app_class": "V", "params": params("json_path:input:doc.json")}
    out = try_app(tmp_path, names, "--data-from", "in.json")
    assert "#body: '{\"a\": 1}'" in out and "json_path file" not in out  # input files aren't data files
    out = try_app(tmp_path, names, "--file", "json_path=in.json")
    assert "#body: '{\"a\": 1}'" in out


def test_try_app_fake_clock_and_advance(tmp_path):
    (tmp_path / "watch.py").write_text((KITS_DIR / "tui" / "parts" / "periodic_refresh.py").read_text())
    names = {"module": "watch", "app_class": "StopwatchApp", "params": params("now:clock")}
    out = try_app(tmp_path, names, "press:space", "advance:5", "press:space", "advance:3")
    assert "now: a fake clock" in out
    assert "after advance:5:\n  #display digits: '00:05.0'" in out
    assert "after advance:3:\n  (nothing changed)" in out  # paused: time doesn't count
    out = try_app(tmp_path, {**names, "params": []}, "advance:5")
    assert "advance needs a clock parameter, and StopwatchApp has none" in out


CLASHING = """\
from textual import widgets
from textual.app import App, ComposeResult
from textual.reactive import reactive
from textual.widgets import Static


class Cell(widgets.Static):
    def __init__(self) -> None:
        super().__init__()
        self.visible = True


class TimerApp(App):
    BINDINGS = [("space", "toggle", "Start/stop")]
    CSS = "Static { height: 1; }"
    elapsed = reactive(0.0)

    def __init__(self) -> None:
        super().__init__()
        self._running = False
        self.title = "Timer"
        self.laps = []

    def compose(self) -> ComposeResult:
        yield Static(id="time")

    def on_mount(self) -> None:
        self.elapsed = 0.0

    def action_toggle(self) -> None:
        self._running = not self._running
"""


def test_start_check_warns_about_names_textual_already_uses(tmp_path):
    from lightness.kits.smoke import clashes

    (tmp_path / "timer.py").write_text(CLASHING)
    warnings = clashes(tmp_path, {"module": "timer"})
    assert warnings == [
        "warning: Cell sets self.visible, which Textual's Static already uses; rename it (e.g. self.my_visible).",
        "warning: TimerApp sets self._running, which Textual's App already uses; rename it (e.g. self.my_running).",
    ]  # not compose, on_mount, BINDINGS, CSS, a reactive of its own, or App's title reactive


def test_start_check_has_no_warnings_for_the_shell_and_parts(tmp_path):
    from lightness.kits.smoke import clashes

    for name in SHELL_NAMES:
        (tmp_path / "app.py").write_text(render_shell(load_kit("tui"), SHELL_NAMES[name]))
        assert clashes(tmp_path, {"module": "app"}) == [], name
    for p in load_kit("tui").parts:
        (tmp_path / "app.py").write_text(p.path.read_text())
        assert clashes(tmp_path, {"module": "app"}) == [], p.name


def test_headless_test_part_passes_its_own_tests():
    proc = subprocess.run([sys.executable, "-m", "pytest", str(TUI / "parts" / "headless_test.py"), "-q",
                           "-p", "no:cacheprovider"], capture_output=True, text=True, timeout=120, check=False)
    assert proc.returncode == 0, proc.stdout[-2000:]


CHECKED = """\
import json
from pathlib import Path

from textual.app import App
from textual.widgets import Input, Static


class Counter(App):
    BINDINGS = [("plus", "bump", "Add"), ("d", "boom", "Delete"), ("ctrl+q", "quit", "Quit")]

    def __init__(self, path="count.json", now=None):
        super().__init__()
        self.path, self.now = Path(path), now
        self.n = json.loads(self.path.read_text()) if self.path.exists() else 0
        self.path.write_text(json.dumps(self.n + START))  # START=1: overwrites the saved file on start

    def compose(self):
        if WITH_INPUT:  # focused from the start: typed keys go into it
            yield Input(id="name")
        yield Static(id="shown")

    def on_mount(self):
        self.query_one("#shown", Static).update(f"count {self.n}")

    def action_bump(self):
        self.n += 1
        self.path.write_text(json.dumps(self.n))
        self.query_one("#shown", Static).update(f"count {self.n}")

    def action_boom(self):
        if BOOM:
            1 / 0
"""
COUNTER = {"module": "counter", "app_class": "Counter", "sample_data": "3",
           "params": [{"name": "path", "role": "data", "file": "count.json"}, {"name": "now", "role": "clock", "file": ""}]}


def counter(start=0, boom=False, with_input=False) -> str:
    """The Counter app; start=1 overwrites its file on start, boom makes d crash."""
    return CHECKED.replace("START", str(start)).replace("BOOM", str(boom)).replace("WITH_INPUT", str(with_input))


def test_try_app_expect_steps(tmp_path):
    (tmp_path / "counter.py").write_text(counter())
    out = try_app(tmp_path, COUNTER, "--data", "3", "expect:count 3", "expect-not:count 4", "expect-file:path=3",
                  "press:plus", "expect:count 5", "expect-file:path=4")
    assert "ok: expect:count 3\nok: expect-not:count 4\nok: expect-file:path=3" in out
    assert "FAILED expect:count 5: not on the screen. Screen now:\n" in out and "#shown: 'count 4'" in out
    assert "ok: expect-file:path=4" in out  # without --checks a failed expect doesn't stop the run


def test_try_app_checks_file(tmp_path):
    (tmp_path / "counter.py").write_text(counter())
    (tmp_path / "checks.txt").write_text(
        "# comment\n\n"
        "bump: --file-text path=3 press:plus expect:\"count 4\" expect-file:path=4 restart expect:\"count 4\"\n"
        "wrong: press:plus expect:\"count 9\" press:plus\n"
        "no name here\n"
        "quotes: expect:\"oops\n"
        "bad option: --nope expect:x\n")
    out = try_app(tmp_path, COUNTER, "--checks", "checks.txt")
    assert "PASS bump\n" in out
    assert "FAIL wrong\n" in out and "FAILED expect:count 9" in out and "after press:plus:\n      #shown: 'count 1'" in out
    assert "FAIL line 5\n    not a check:" in out
    assert "FAIL quotes\n    can't split the line into steps" in out
    assert "FAIL bad option\n" in out
    assert out.strip().endswith("1 of 5 checks pass")


def test_try_app_builtin_checks(tmp_path):
    (tmp_path / "counter.py").write_text(counter(with_input=True))
    out = try_app(tmp_path, COUNTER, "--builtin")
    assert out.splitlines() == ["PASS harness: every key works, starting with no data file",
                                "PASS harness: every key works, starting with the sample path file",
                                "PASS harness: time moves (an hour on the fake clock)", "3 of 3 checks pass"]
    (tmp_path / "counter.py").write_text(counter(boom=True, with_input=True))  # starts in the Input: keys type text
    out = try_app(tmp_path, COUNTER, "--builtin")
    assert ("FAIL harness: every key works, starting with no data file\n"
            "    pressing plus, d with nothing focused crashes on d:") in out
    assert "ZeroDivisionError" in out
    (tmp_path / "counter.py").write_text(counter(start=1))
    out = try_app(tmp_path, COUNTER, "--builtin")
    assert "after pressing plus, d the path file held 1; starting the app again changed it to 2" in out


def test_checks_example_uses_the_apps_file_params():
    from lightness.kits import checks_example

    given = checks_example({"params": [{"name": "json_path", "role": "input", "file": "input.json"}]})
    assert "--file-text json_path=" in given and "expect-file" not in given and "PARAM" not in given
    data = checks_example({"params": [{"name": "data_path", "role": "data", "file": "notes.json"}]})
    assert "expect-file:data_path=" in data and "--file-text data_path=" in data
    assert "--file-text" not in checks_example({"params": []})


def test_fill_input_files_uses_the_projects_data_file(tmp_path):
    from lightness.kits import fill_input_files

    (tmp_path / "books.csv").write_text("a\n")
    (tmp_path / "browse.py").write_text("")
    names = {"params": [{"name": "csv_path", "role": "input", "file": ""}]}
    assert fill_input_files(names, tmp_path)["params"][0]["file"] == "books.csv"
    names = {"params": [{"name": "csv_path", "role": "input", "file": "data.csv"}]}  # missing default, same ext
    assert fill_input_files(names, tmp_path)["params"][0]["file"] == "books.csv"
    (tmp_path / "other.json").write_text("{}")
    names = {"params": [{"name": "p", "role": "input", "file": ""}]}  # two candidates: leave it
    assert fill_input_files(names, tmp_path)["params"][0]["file"] == ""
    names = {"params": [{"name": "p", "role": "data", "file": "saved.json"}]}  # data files are the app's own
    assert fill_input_files(names, tmp_path)["params"][0]["file"] == "saved.json"


DIALOG_DB = '''
import sqlite3
from textual.app import App
from textual.screen import ModalScreen
from textual.widgets import Input, Static


class Ask(ModalScreen):
    def compose(self):
        yield Input(id="title")

    def on_input_submitted(self, event):
        self.dismiss(event.value)


class Db(App):
    BINDINGS = [("a", "add", "Add")]

    def __init__(self, db_path="items.db"):
        super().__init__()
        self.con = sqlite3.connect(db_path)
        self.con.execute("CREATE TABLE IF NOT EXISTS items (title TEXT)")

    def compose(self):
        yield Static(id="list")

    def on_mount(self):
        self.show()

    def show(self):
        self.query_one("#list", Static).update(" ".join(r[0] for r in self.con.execute("SELECT title FROM items")))

    def action_add(self):
        def done(title):
            self.con.execute("INSERT INTO items VALUES (?)", (title,))
            self.con.commit()
            self.show()
        self.push_screen(Ask(), done)
'''


def test_try_app_focuses_dialog_widgets_and_shows_sqlite(tmp_path):
    (tmp_path / "db.py").write_text(DIALOG_DB)
    names = {"module": "db", "app_class": "Db", "params": params("db_path:data:items.db")}
    out = try_app(tmp_path, names, "press:a", "focus:#title", "type:milk", "press:enter", "restart", "expect:milk")
    assert "CRASH" not in out and "ok: expect:milk" in out
    assert "SQLite: table items: ('milk',)" in out
    out = try_app(tmp_path, names, "--file-text", "db_path=[]")
    assert "db_path is a SQLite database: --file-text can't fill it" in out


def test_checks_file_rejects_steps_written_as_the_name(tmp_path):
    (tmp_path / "both.py").write_text(TWO_FILES)
    (tmp_path / "checks.txt").write_text("type:hello world: expect:modified\ntype: again: expect:x\nok one: press:a\n")
    names = {"module": "both", "app_class": "Both",
             "params": params("places_path:input:places.csv", "saved_path:data:saved.json")}
    out = try_app(tmp_path, names, "--checks", "checks.txt")
    assert out.count("not a check:") == 2 and "typing marks it modified: type:hello" in out
    assert "FAIL line 1\n" in out and "FAIL line 2\n" in out and "line 3" not in out  # a real check runs


def test_expect_failures_explain_case_and_selectors():
    from lightness.kits.tui.try_app import expectation

    state = {"w": ["#moves: 'Moves: 0'"]}
    assert "different case: 'Moves: 0'" in expectation("expect", "moves: 0", state, {})
    assert "not a selector" in expectation("expect", "#cell-0-1.cursor", state, {})
    assert expectation("expect", "Moves: 0", state, {}) is None


def test_start_check_shows_css_errors_plainly(tmp_path):
    from lightness.kits import smoke

    (tmp_path / "bad.py").write_text(
        "from textual.app import App\nfrom textual.widgets import Static\n\n\nclass Bad(App):\n"
        "    CSS = \"#board { grid-size: 5 5; colr: red; }\"\n\n    def compose(self):\n"
        "        yield Static('x', id='board')\n")
    bad = [r for r in smoke.tui(tmp_path, {"module": "bad", "app_class": "Bad", "params": []}, None) if not r.ok]
    text = smoke.summarize(bad, "bad.py")
    assert "at CSS line: 1 #board { grid-size: 5 5; colr: red; }" in text
    assert "Did you mean 'color'?" in text and "StylesheetErrors object" not in text and "╭" not in text
