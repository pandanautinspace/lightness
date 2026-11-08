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
    assert "(the clock moved 5 s and the app's timers ran; the app read the clock" in out
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


def test_start_check_warns_when_an_awaited_push_screen_value_is_used(tmp_path):
    from lightness.kits.smoke import screen_results

    (tmp_path / "app.py").write_text(
        "class A:\n"
        "    async def action_add(self):\n"
        "        result = await self.push_screen(Ask())\n"
        "        if await self.app.push_screen(Ask()):\n"
        "            pass\n"
        "    async def fine(self):\n"
        "        await self.push_screen(Ask())\n"
        "        self.push_screen(Ask(), self.done)\n"
        "        x = await self.push_screen(Ask(), wait_for_dismiss=True)\n")
    warn = screen_results(tmp_path, {"module": "app"})
    assert len(warn) == 1 and "(line 3, 4)" in warn[0] and "self.push_screen(screen, callback)" in warn[0]
    for name in SHELL_NAMES:
        (tmp_path / "app.py").write_text(render_shell(load_kit("tui"), SHELL_NAMES[name]))
        assert screen_results(tmp_path, {"module": "app"}) == [], name
    for p in load_kit("tui").parts:
        (tmp_path / "app.py").write_text(p.path.read_text())
        assert screen_results(tmp_path, {"module": "app"}) == [], p.name


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
    assert "FAIL quotes\n    not run: can't split the line into steps" in out
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
    assert "not selectors" in expectation("expect", "#cell-0-1.cursor", state, {})
    assert expectation("expect", ".limits.burst", state, {}) == "not on the screen"  # a JSON path, not a class
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


def test_empty_expect_is_an_error():
    from lightness.kits.tui.try_app import expectation

    assert "needs the text" in expectation("expect", "", {"w": ["x"]}, {})
    assert "needs the text" in expectation("expect-not", "  ", {"w": ["x"]}, {})


def test_try_app_says_when_a_click_would_miss(tmp_path):
    (tmp_path / "dlg.py").write_text(
        "from textual.app import App\nfrom textual.containers import Horizontal\nfrom textual.screen import ModalScreen\n"
        "from textual.widgets import Button, Static\n\n\nclass Ask(ModalScreen):\n"
        "    DEFAULT_CSS = 'Ask { align: center middle; } Ask > Horizontal { width: 20; height: auto; }'\n\n"
        "    def compose(self):\n        with Horizontal():\n"
        "            yield Button('Save', id='save')\n            yield Button('Cancel', id='cancel')\n\n"
        "    def on_button_pressed(self, e):\n        self.dismiss(e.button.id)\n\n\n"
        "class D(App):\n    BINDINGS = [('q', 'ask', 'Ask')]\n\n    def compose(self):\n        yield Static('main', id='st')\n\n"
        "    def action_ask(self):\n        self.push_screen(Ask(), lambda r: self.query_one('#st', Static).update(f'got {r}'))\n")
    names = {"module": "dlg", "app_class": "D", "params": []}
    out = try_app(tmp_path, names, "press:q", "click:#cancel")
    assert "#cancel can't be clicked" in out and "cut off by its container" in out
    out = try_app(tmp_path, names, "press:q", "click:#save")
    assert "got save" in out


def test_checks_file_rejects_duplicate_names(tmp_path):
    (tmp_path / "both.py").write_text(TWO_FILES)
    (tmp_path / "places.csv").write_text("ams\n")
    (tmp_path / "checks.txt").write_text("CHECK: press:a\nCHECK: press:b\nother: press:a\n")
    names = {"module": "both", "app_class": "Both",
             "params": params("places_path:input:places.csv", "saved_path:data:saved.json")}
    out = try_app(tmp_path, names, "--checks", "checks.txt")
    assert "FAIL line 2\n    the name 'CHECK' is already used on line 1" in out
    assert "PASS CHECK" in out and "PASS other" in out and "of 3 checks pass" in out


def test_check_lines_are_linted_before_running(tmp_path):
    (tmp_path / "both.py").write_text(TWO_FILES)
    (tmp_path / "places.csv").write_text("ams\n")
    (tmp_path / "checks.txt").write_text(
        'bad: type:two words press:#save expect:#c.on expect:""\ngood: press:a\n')
    names = {"module": "both", "app_class": "Both",
             "params": params("places_path:input:places.csv", "saved_path:data:saved.json")}
    out = try_app(tmp_path, names, "--checks", "checks.txt")
    assert "FAIL bad\n    not run: 'words' is not a step" in out
    assert "press takes key names; to press a button, click:#save" in out
    assert "expect matches text on the screen, not a CSS selector" in out and "has no text to look for" in out
    assert "PASS good" in out


def test_try_app_grid_lists_a_class_only_one_cell_has(tmp_path):
    (tmp_path / "g.py").write_text(
        "from textual.app import App\nfrom textual.widgets import Static\n\n\nclass G(App):\n"
        "    CSS = '#board { layout: grid; grid-size: 2; }'\n    BINDINGS = [('right', 'go')]\n\n"
        "    def compose(self):\n        from textual.containers import Container\n"
        "        with Container(id='board'):\n            for i in range(4):\n"
        "                yield Static('#' if i % 2 else '.', id=f'c{i}', classes='cell cursor' if i == 0 else 'cell')\n\n"
        "    def action_go(self):\n        self.query_one('#c0').remove_class('cursor')\n"
        "        self.query_one('#c1').add_class('cursor')\n")
    out = try_app(tmp_path, {"module": "g", "app_class": "G", "params": []}, "press:right", "expect:class cursor: #c1")
    assert "class cursor: #c0 (row 0, col 0)" in out and "ok: expect:class cursor: #c1" in out
    assert "cells #c0 … #c3 (4, row by row)" in out  # every cell id is checkable, not only ones with a class


def test_try_app_grid_of_same_text_cells_is_drawn_by_class(tmp_path):
    (tmp_path / "g.py").write_text(
        "from textual.app import App\nfrom textual.widgets import Static\n\n\nclass G(App):\n"
        "    CSS = '#board { layout: grid; grid-size: 2; }'\n\n"
        "    def compose(self):\n        from textual.containers import Container\n"
        "        with Container(id='board'):\n            for i in range(4):\n"
        "                yield Static('.', id=f'c{i}', classes='cell on' if i < 3 else 'cell off')\n")
    out = try_app(tmp_path, {"module": "g", "app_class": "G", "params": []}, "expect:class on: #c2")
    assert "(every cell shows '.'; drawn by CSS class instead)\n    on  on\n    on  off" in out
    assert "class on: #c0 (row 0, col 0)\n    class on: #c1 (row 0, col 1)" in out and "ok: expect:class on: #c2" in out
    (tmp_path / "h.py").write_text((tmp_path / "g.py").read_text().replace("'cell on' if i < 3 else 'cell off'", "'cell on'")
                                   .replace("class G", "class H"))
    out = try_app(tmp_path, {"module": "h", "app_class": "H", "params": []})
    assert "every cell has class: cell, on" in out  # an all-lit board still says it is lit


def test_try_app_tabs_line_names_how_to_switch(tmp_path):
    (tmp_path / "t.py").write_text(
        "from textual.app import App\nfrom textual.widgets import Static, TabbedContent, TabPane\n\n\nclass T(App):\n"
        "    def compose(self):\n        with TabbedContent(id='tabs'):\n"
        "            with TabPane('One', id='one'):\n                yield Static('first', id='a')\n"
        "            with TabPane('Two', id='two'):\n                yield Static('second', id='b')\n")
    out = try_app(tmp_path, {"module": "t", "app_class": "T", "params": []}, "click:#--content-tab-two", "expect:second")
    assert "#tabs tabs, active='one'; switch: click:#--content-tab-two" in out and "ok: expect:second" in out


def test_a_failing_expect_only_check_says_it_saw_a_fresh_app(tmp_path):
    (tmp_path / "both.py").write_text(TWO_FILES)
    (tmp_path / "places.csv").write_text("ams\n")
    (tmp_path / "checks.txt").write_text("after a: expect:\"nothing like this\"\n")
    names = {"module": "both", "app_class": "Both",
             "params": params("places_path:input:places.csv", "saved_path:data:saved.json")}
    out = try_app(tmp_path, names, "--checks", "checks.txt")
    assert "it looked at a freshly started app" in out


def test_file_option_with_text_instead_of_a_path_fails_only_that_check(tmp_path):
    (tmp_path / "both.py").write_text(TWO_FILES)
    (tmp_path / "places.csv").write_text("ams\n")
    (tmp_path / "checks.txt").write_text("text not path: --file places_path='a,b' expect:x\nfine: press:a\n")
    names = {"module": "both", "app_class": "Both",
             "params": params("places_path:input:places.csv", "saved_path:data:saved.json")}
    out = try_app(tmp_path, names, "--checks", "checks.txt")
    assert "there is no file 'a,b'. To give the contents, use --file-text places_path=" in out
    assert "PASS fine" in out and "could not run" not in out


def test_lint_rejects_unknown_keys_and_glued_steps():
    import shlex

    from lightness.kits.tui.try_app import lint

    assert "'bm-save' is not a key" in " ".join(lint(shlex.split("press:bm-save")))
    assert "a new step starts a new word" in " ".join(lint(shlex.split("type:A,type:B")))
    assert "a new step starts a new word" in " ".join(lint(shlex.split("press:down,down,press:enter")))
    assert lint(shlex.split('press:ctrl+s,enter press:comma press:shift+tab type:"a,b" press:down,space')) == []
    assert lint(shlex.split("press:down*15,enter press:asterisk")) == []
    assert "types the word 'enter'; to press the key, press:enter" in " ".join(lint(shlex.split("type:enter")))
    assert "not a Python literal once the line is split" in " ".join(lint(shlex.split('--kw board=["#.","..",]')))
    assert lint(shlex.split("""--kw 'board=["#.", ".."]' --kw seed=3 --kw "items=['a', 'b']" """)) == []
    assert lint(shlex.split('type:"enter the code" type:Tabby')) == []
    assert "'nokey' is not a key" in " ".join(lint(shlex.split("press:nokey*3")))


def test_try_app_press_repeats_a_key(tmp_path):
    from lightness.kits.tui.try_app import keys_of

    assert keys_of("down*3,enter") == ["down", "down", "down", "enter"] and keys_of("*") == ["*"]
    (tmp_path / "c.py").write_text(
        "from textual.app import App\nfrom textual.widgets import Static\n\n\nclass C(App):\n"
        "    BINDINGS = [('down', 'inc')]\n    n = 0\n\n    def compose(self):\n        yield Static('0', id='n')\n\n"
        "    def action_inc(self):\n        self.n += 1\n        self.query_one('#n').update(str(self.n))\n")
    out = try_app(tmp_path, {"module": "c", "app_class": "C", "params": []}, "press:down*7", "expect:7")
    assert "ok: expect:7" in out


def test_lint_rejects_file_names_where_parameter_names_go():
    import shlex

    from lightness.kits.tui.try_app import lint

    assert "db_path is a file parameter, and every check already gets a fresh file" in " ".join(
        lint(shlex.split("--kw db_path=/tmp/x.db expect:a"), ["db_path"]))
    problems = " ".join(lint(shlex.split("--file-text trip.json='{}' expect-file:trip.json='{}'"), ["data_path"]))
    assert "'trip.json' is not a file parameter of the App (they are: data_path)" in problems
    assert "expect-file takes a file parameter's name" in problems
    assert lint(shlex.split("--file-text data_path='{}' expect-file:data_path='{}'"), ["data_path"]) == []


def test_try_app_tree_rows_are_numbered_and_follow_the_cursor(tmp_path):
    (tmp_path / "t.py").write_text(
        "from textual.app import App\nfrom textual.widgets import Tree\n\n\nclass T(App):\n"
        "    def compose(self):\n        yield Tree('root', id='tree')\n\n    def on_mount(self):\n"
        "        t = self.query_one(Tree)\n        for i in range(40):\n            t.root.add_leaf(f'n{i}')\n"
        "        t.root.expand()\n        t.focus()\n")
    out = try_app(tmp_path, {"module": "t", "app_class": "T", "params": []}, "press:" + ",".join(["down"] * 30))
    assert "#tree tree, 41 rows (up/down move one row, space opens/closes its node, left/right do nothing; press:down*K moves K rows):" in out
    assert "[30]     n29 ◀ cursor" in out and "rows above" in out


def test_try_app_input_line_shows_its_classes(tmp_path):
    (tmp_path / "v.py").write_text(
        "from textual.app import App\nfrom textual.widgets import Input\n\n\nclass V(App):\n"
        "    def compose(self):\n        yield Input(id='n')\n\n    def on_input_changed(self, event):\n"
        "        event.input.set_class(not event.value.isdigit(), '-invalid')\n")
    out = try_app(tmp_path, {"module": "v", "app_class": "V", "params": []}, "focus:#n", "type:x", "expect:-invalid")
    assert "#n input: 'x' classes: -invalid" in out and "ok: expect:-invalid" in out


def test_try_app_shows_the_title_when_there_is_a_header(tmp_path):
    (tmp_path / "h.py").write_text(
        "from textual.app import App\nfrom textual.widgets import Header, Static\n\n\nclass H(App):\n"
        "    TITLE = 'Bookmark Manager'\n\n    def compose(self):\n        yield Header()\n        yield Static('x', id='s')\n")
    out = try_app(tmp_path, {"module": "h", "app_class": "H", "params": []}, "expect:Bookmark Manager")
    assert "title: Bookmark Manager" in out and "ok: expect:Bookmark Manager" in out


def test_start_check_names_close_attributes_for_an_attribute_error(tmp_path):
    from lightness.kits import smoke

    (tmp_path / "attr.py").write_text(
        "from textual.app import App\nfrom textual.widgets import Tree\n\n\nclass A(App):\n"
        "    def compose(self):\n        yield Tree('root', id='t')\n\n    def on_mount(self):\n"
        "        self.query_one(Tree).root.children_count\n")
    bad = [r for r in smoke.tui(tmp_path, {"module": "attr", "app_class": "A", "params": []}, None) if not r.ok]
    text = smoke.summarize(bad, "attr.py")
    assert "hint: TreeNode has no 'children_count'. Closest names on TreeNode: children" in text
    assert "<string>" not in text


def test_try_app_shows_an_empty_widget_that_has_an_id(tmp_path):
    (tmp_path / "e.py").write_text(
        "from textual.app import App\nfrom textual.widgets import Static\n\n\nclass E(App):\n"
        "    def compose(self):\n        yield Static('', id='detail')\n        yield Static('')\n")
    out = try_app(tmp_path, {"module": "e", "app_class": "E", "params": []})
    assert "#detail: (empty)" in out and out.count("(empty)") == 1


def test_lint_accepts_lines_copied_from_the_dump():
    import shlex

    from lightness.kits.tui.try_app import lint

    assert lint(shlex.split("""expect:"#path: '$'" expect:"#detail:" expect:#bm-title""")) == []
    assert all(lint([t]) for t in ["expect:#c.on", "expect:#a:focus", "expect:#a > b"])


def test_try_app_says_when_only_the_cursor_moved(tmp_path):
    (tmp_path / "t.py").write_text(
        "from textual.app import App\nfrom textual.widgets import Static, Tree\n\n\nclass T(App):\n"
        "    def compose(self):\n        yield Tree('root', id='tree')\n        yield Static('$', id='path')\n\n"
        "    def on_mount(self):\n        t = self.query_one(Tree)\n        t.root.add_leaf('a')\n        t.root.expand()\n"
        "        t.focus()\n")
    out = try_app(tmp_path, {"module": "t", "app_class": "T", "params": []}, "press:down")
    assert "(only the cursor in #tree moved; no other widget changed)" in out


def test_undefined_names_listed_at_once(tmp_path):
    from lightness.kits import smoke

    (tmp_path / "m.py").write_text("from textual.app import App\n\n\nclass A(App):\n    @on(Input.Submitted)\n"
                                   "    def f(self):\n        return Select([])\n")
    warn = smoke.undefined_names(tmp_path, {"module": "m"})
    assert warn and "on (line 5), Input (line 5), Select (line 7)" in warn[0]
    (tmp_path / "ok.py").write_text("import os\nprint(os.sep)\n")
    assert smoke.undefined_names(tmp_path, {"module": "ok"}) == []


def test_try_app_select_line_lists_its_options(tmp_path):
    (tmp_path / "s.py").write_text(
        "from textual.app import App\nfrom textual.widgets import Select\n\n\nclass S(App):\n"
        "    def compose(self):\n        yield Select([('Alice', 'a'), ('Bob', 'b')], prompt='Payer', id='payer')\n")
    out = try_app(tmp_path, {"module": "s", "app_class": "S", "params": []}, "expect:Bob")
    assert "#payer select: Select.NULL, options: Alice, Bob" in out and "ok: expect:Bob" in out


def test_a_check_that_hangs_the_app_fails_alone(tmp_path, monkeypatch):
    (tmp_path / "h.py").write_text(
        "from textual.app import App\nfrom textual.widgets import Static\n\n\nclass H(App):\n"
        "    BINDINGS = [('x', 'spin')]\n\n    def compose(self):\n        yield Static('ok', id='s')\n\n"
        "    def action_spin(self):\n        while True:\n            pass\n")
    (tmp_path / "checks.txt").write_text("spins: press:x expect:ok\nfine: expect:ok\n")
    monkeypatch.setenv("TRY_CHECK_SECONDS", "3")
    out = try_app(tmp_path, {"module": "h", "app_class": "H", "params": []}, "--checks", "checks.txt")
    assert "FAIL spins" in out and "did not finish within" in out and "PASS fine" in out


def run_edit(tmp_path, name, text, blocks):
    import subprocess
    import sys

    (tmp_path / name).write_text(text)
    proc = subprocess.run([sys.executable, str(KITS_DIR / "tui" / "edit.py"), name], input=blocks, text=True,
                          capture_output=True, cwd=tmp_path)
    return proc.returncode, proc.stdout, (tmp_path / name).read_text()


def block(old, new):
    return f"<<<<<<< SEARCH\n{old}\n=======\n{new}\n>>>>>>> REPLACE\n"


def test_edit_tool_replaces_each_block_once(tmp_path):
    src = "def f():\n    return 1\n\n\ndef g():\n    return 2\n"
    rc, out, text = run_edit(tmp_path, "a.py", src, block("    return 1", "    return 10") + block("def g():", "def h():"))
    assert rc == 0 and text == "def f():\n    return 10\n\n\ndef h():\n    return 2\n" and "Edited a.py" in out


def test_edit_tool_changes_nothing_when_a_block_is_ambiguous_or_missing(tmp_path):
    src = "x = 1\ny = 1\nz = 1\n"
    rc, out, text = run_edit(tmp_path, "a.py", src, block("x = 1", "x = 2") + block("= 1", "= 3"))
    assert rc == 1 and text == src and "block 2: SEARCH matches nothing" in out  # "= 1" is not a whole line
    rc, out, text = run_edit(tmp_path, "b.txt", "a\nb\na\n", block("a", "c"))
    assert rc == 1 and text == "a\nb\na\n" and "matches 2 places (lines 1, 3)" in out
    rc, out, text = run_edit(tmp_path, "c.py", "def f():\n    return 1\n", block("    return 7", "    return 2"))
    assert rc == 1 and "Closest lines now in the file:" in out and "   2|     return 1" in out


def test_edit_tool_refuses_an_edit_that_breaks_compiling_python(tmp_path):
    src = "def f():\n    return 1\n"
    rc, out, text = run_edit(tmp_path, "a.py", src, block("def f():", "def f(:"))
    assert rc == 1 and text == src and "would not compile" in out


def test_edit_tool_ignores_trailing_spaces_and_works_on_checks(tmp_path):
    rc, out, text = run_edit(tmp_path, "checks.txt", "one: expect:\"a\"   \ntwo: expect:\"b\"\n",
                             block("one: expect:\"a\"", "one: expect:\"A\""))
    assert rc == 0 and text == "one: expect:\"A\"\ntwo: expect:\"b\"\n"


def test_edit_section_only_with_the_experiment_switch(monkeypatch):
    from lightness import kits

    kit = kits.load_kit("tui")
    names = {"module": "notes", "app_class": "NotesApp", "title": "Notes",
             "params": [{"name": "data_path", "role": "data", "file": "notes.json"}], "empty_value": "[]", "sample_data": ""}
    monkeypatch.delenv("LIGHTNESS_EDIT", raising=False)
    off = kits.context(kit, names, ".lightness/kit/parts", [], "checks")
    assert "## Changing a file" not in off and "(e.g. with sed)" in off
    monkeypatch.setenv("LIGHTNESS_EDIT", "1")
    on = kits.context(kit, names, ".lightness/kit/parts", [], "checks")
    assert "## Changing a file" in on and "(with the edit_file tool)" in on and "(e.g. with sed)" not in on


def run_edit_json(tmp_path, name, text, old, new):
    import json
    import subprocess
    import sys

    if text is not None:
        (tmp_path / name).write_text(text)
    proc = subprocess.run([sys.executable, str(KITS_DIR / "tui" / "edit.py"), "--json"], text=True, capture_output=True,
                          cwd=tmp_path, input=json.dumps({"path": name, "old_text": old, "new_text": new}))
    path = tmp_path / name
    return proc.returncode, proc.stdout, path.read_text() if path.exists() else None


def test_edit_json_replaces_one_exact_occurrence(tmp_path):
    rc, out, text = run_edit_json(tmp_path, "a.py", "x = 1\ny = 2\n", "y = 2", "y = 3\nz = 4")
    assert rc == 0 and text == "x = 1\ny = 3\nz = 4\n" and "Edited a.py: lines 2-3" in out
    rc, out, text = run_edit_json(tmp_path, "b.py", "a = 1\na = 1\n", "a = 1", "a = 2")
    assert rc == 1 and text == "a = 1\na = 1\n" and "occurs 2 times in b.py (lines 1, 2)" in out
    rc, out, text = run_edit_json(tmp_path, "c.py", "def f():\n    return 1\n", "    return 9", "    return 2")
    assert rc == 1 and "not in c.py" in out and "   2|     return 1" in out
    rc, out, text = run_edit_json(tmp_path, "d.py", "def f():\n    return 1\n", "def f():", "def f(:")
    assert rc == 1 and "would not compile" in out and text == "def f():\n    return 1\n"
    rc, out, text = run_edit_json(tmp_path, "new.txt", None, "", "hello\n")
    assert rc == 0 and text == "hello\n" and "Created new.txt" in out


def test_edit_json_refuses_deleting_most_of_a_file(tmp_path):
    src = "".join(f"line{i} = {i}\n" for i in range(20))
    rc, out, text = run_edit_json(tmp_path, "a.py", src, src, "")
    assert rc == 1 and text == src and "would delete 20 of the 20 lines" in out
    rc, out, text = run_edit_json(tmp_path, "b.py", src, "line3 = 3\n", "")
    assert rc == 0 and "line3" not in text  # deleting a few lines is fine


def test_try_app_says_when_bracketed_text_was_read_as_markup(tmp_path):
    (tmp_path / "m.py").write_text(
        "from textual.app import App\nfrom textual.widgets import Static\n\n\nclass M(App):\n"
        "    def compose(self):\n        yield Static('[modified]', id='status')\n"
        "        yield Static('[b]bold[/b]', id='b')\n        yield Static('[x] done', id='x', markup=False)\n")
    out = try_app(tmp_path, {"module": "m", "app_class": "M", "params": []})
    assert "#status: (empty) (its text '[modified]' was read as markup" in out
    assert "#x: '[x] done'\n" in out  # markup=False: shown as is, no note
    assert "#b: 'bold'\n" in out  # intended markup: no note


def test_try_app_says_a_letter_key_went_into_a_focused_input(tmp_path):
    (tmp_path / "f.py").write_text(
        "from textual.app import App\nfrom textual.widgets import Input, Static\n\n\nclass F(App):\n"
        "    BINDINGS = [('a', 'add')]\n\n    def compose(self):\n        yield Input(id='search')\n"
        "        yield Static('', id='out')\n\n    def action_add(self):\n        self.query_one('#out').update('added')\n")
    out = try_app(tmp_path, {"module": "f", "app_class": "F", "params": []}, "focus:#search", "press:a")
    assert "('a' went into #search as text: an Input has focus" in out
    (tmp_path / "g.py").write_text((tmp_path / "f.py").read_text().replace("class F(App):\n", "class G(App):\n    AUTO_FOCUS = None\n"))
    out = try_app(tmp_path, {"module": "g", "app_class": "G", "params": []}, "press:a")
    assert "went into" not in out and "#out: 'added'" in out  # nothing focused: the binding fires


def test_try_app_header_shows_kw_values_with_their_type_and_exact_text_expects_work(tmp_path):
    (tmp_path / "k.py").write_text(
        "from textual.app import App\nfrom textual.widgets import Static\n\n\nclass K(App):\n"
        "    def __init__(self, board=None):\n        super().__init__()\n        self.board = board\n\n"
        "    def compose(self):\n        yield Static('Path: $.a', id='path')\n")
    names = {"module": "k", "app_class": "K", "params": [{"name": "board", "role": "other", "file": ""}]}
    out = try_app(tmp_path, names, "--kw", "board=.....,.....", "expect:#path: '$.a'", "expect:$.a")
    assert "board='.....,.....' (str)" in out
    assert "FAILED expect:#path: '$.a'" in out and "ok: expect:$.a" in out
    out = try_app(tmp_path, names, "expect:#path 'Path: $.a'")
    assert "not on the screen as written (the screen has #path: 'Path: $.a' with a colon after the id)" in out


def test_try_app_says_an_input_dropped_typed_keys(tmp_path):
    (tmp_path / "n.py").write_text(
        "from textual.app import App\nfrom textual.widgets import Input\n\n\nclass N(App):\n"
        "    def compose(self):\n        yield Input(id='years', type='integer')\n        yield Input(id='name')\n")
    out = try_app(tmp_path, {"module": "n", "app_class": "N", "params": []}, "focus:#years", "type:3.5",
                  "focus:#name", "type:3.5")
    assert "(#years is an Input with type='integer': it dropped the keys that don't fit, so it holds '35'" in out
    assert out.count("dropped the keys") == 1  # a plain text Input takes anything
