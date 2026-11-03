"""Kits must not rot: every shell renders and starts, every part runs and does what it says."""

import asyncio
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
        await pilot.press(*"third", "enter")
        await pilot.pause()
        assert app.focused.id == "new-item"
        assert [i["title"] for i in app.items] == ["first", "second", "third"]
        app.query_one("#items", ListView).focus()
        await pilot.press("up", "space")  # highlighted was the new item; up = second
        await pilot.pause()
        assert app.items[1]["done"] is True
        assert labels(app, "#items")[1].startswith("✓")
        await pilot.press("d")
        await pilot.pause()
        assert [i["title"] for i in app.items] == ["first", "third"]
        await pilot.press("enter")  # Selected -> toggle the highlighted one
        await pilot.pause()
        assert sum(i["done"] for i in app.items) == 1

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


SHELL_NAMES = {
    "json": {"module": "notes", "app_class": "NotesApp", "title": "Notes", "storage": "json",
             "data_arg": "data_path", "data_default": "notes.json", "empty_value": "[]"},
    "other": {"module": "ledger", "app_class": "LedgerApp", "title": "Ledger", "storage": "other",
              "data_arg": "db_path", "data_default": "ledger.db", "empty_value": "[]"},
    "none": {"module": "calc", "app_class": "CalcApp", "title": "Calc", "storage": "none",
             "data_arg": "", "data_default": "", "empty_value": "[]"},
}


@pytest.mark.parametrize("storage", list(SHELL_NAMES))
def test_shell_renders_and_starts(storage, tmp_path):
    names = SHELL_NAMES[storage]
    text = render_shell(load_kit("tui"), names)
    assert ("import json" in text) == (storage == "json")
    assert ("DEFAULT_DATA" in text) == (storage != "none")
    path = tmp_path / f"{names['module']}.py"
    path.write_text(text)
    spec = importlib.util.spec_from_file_location(f"shell_{storage}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    app_cls = getattr(mod, names["app_class"])
    app = app_cls(str(tmp_path / names["data_default"])) if names["data_arg"] else app_cls()

    async def steps(app, pilot):
        if storage == "json":
            assert app.data == []
            app.data.append({"x": 1})
            app.save()

    drive(app, steps)
    if storage == "json":
        assert mod.load_data(tmp_path / "notes.json") == [{"x": 1}]


def test_shell_rejects_unfilled_names():
    with pytest.raises((ValueError, KeyError)):
        render_shell(load_kit("tui"), {"module": "x", "storage": "none"})


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
    store.set_done(a, True)
    store.delete(b)
    store.close()
    assert mod.Store(tmp_path / "x.db").all() == [{"id": a, "title": "a", "done": 1}]


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
