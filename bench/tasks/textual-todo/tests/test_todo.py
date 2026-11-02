import asyncio
import json
from pathlib import Path

import pytest

from lightness.bench.testkit import import_from_workspace


@pytest.fixture
def data(tmp_path: Path) -> Path:
    return tmp_path / "todos.json"


def seed(path: Path, todos: list[tuple[str, bool]]) -> None:
    path.write_text(json.dumps([{"title": t, "done": d} for t, d in todos]))


def saved(path: Path) -> list[dict]:
    return json.loads(path.read_text())


def saved_set(path: Path) -> set[tuple[str, bool]]:
    return {(t["title"], t["done"]) for t in saved(path)}


def run(path: Path, scenario):
    """Run `scenario(app, pilot)` inside a headless TodoApp session."""
    todo = import_from_workspace("todo")

    async def main():
        app = todo.TodoApp(path)
        async with app.run_test(size=(100, 40)) as pilot:
            await pilot.pause()
            result = await scenario(app, pilot)
            await pilot.pause()
            return result

    return asyncio.run(main())


def item_text(item) -> str:
    from textual.widgets import Static

    parts = [str(w.render()) for w in item.query(Static)]
    if not parts:
        parts = [str(item.render())]
    return " ".join(parts)


def shown(app) -> list[str]:
    from textual.widgets import ListItem

    return [item_text(i) for i in app.query_one("#todo-list").query(ListItem)]


def shown_titles(app, titles) -> list[str]:
    """For each shown row, which of `titles` it displays (in row order)."""
    out = []
    for text in shown(app):
        hits = [t for t in titles if t in text]
        out.append(max(hits, key=len) if hits else text)
    return out


async def add(pilot, *titles):
    for title in titles:
        pilot.app.query_one("#new-todo").focus()
        await pilot.pause()
        await pilot.press(*title, "enter")
        await pilot.pause()


async def focus_row(app, pilot, title):
    lv = app.query_one("#todo-list")
    lv.focus()
    await pilot.pause()
    rows = shown_titles(app, [title])
    lv.index = rows.index(title)
    await pilot.pause()


def test_widgets_exist(data):
    async def scenario(app, pilot):
        from textual.widgets import Input, ListView

        assert isinstance(app.query_one("#new-todo"), Input)
        assert isinstance(app.query_one("#todo-list"), ListView)
        assert shown(app) == []

    run(data, scenario)


def test_add_via_input_persists(data):
    async def scenario(app, pilot):
        await add(pilot, "buy milk", "call mum")
        assert app.query_one("#new-todo").value == ""
        assert sorted(shown_titles(app, ["buy milk", "call mum"])) == ["buy milk", "call mum"]

    run(data, scenario)
    assert saved_set(data) == {("buy milk", False), ("call mum", False)}
    assert all(set(t) == {"title", "done"} for t in saved(data))


def test_blank_input_adds_nothing(data):
    async def scenario(app, pilot):
        await add(pilot, "real one")
        await add(pilot, "", "   ")
        assert len(shown(app)) == 1

    run(data, scenario)
    assert len(saved(data)) == 1


def test_loads_existing_file(data):
    seed(data, [("water plants", False), ("pay rent", True), ("fix bike", False)])

    async def scenario(app, pilot):
        titles = ["water plants", "pay rent", "fix bike"]
        assert sorted(shown_titles(app, titles)) == sorted(titles)

    run(data, scenario)


def test_toggle_done_and_back(data):
    seed(data, [("water plants", False), ("pay rent", False)])

    async def scenario(app, pilot):
        await focus_row(app, pilot, "pay rent")
        await pilot.press("space")
        await pilot.pause()
        after_on = saved_set(data)
        await focus_row(app, pilot, "pay rent")
        await pilot.press("space")
        await pilot.pause()
        return after_on

    after_on = run(data, scenario)
    assert after_on == {("water plants", False), ("pay rent", True)}
    assert saved_set(data) == {("water plants", False), ("pay rent", False)}


def test_delete_with_d(data):
    seed(data, [("keep me", False), ("drop me", True), ("me too", False)])

    async def scenario(app, pilot):
        await focus_row(app, pilot, "drop me")
        await pilot.press("d")
        await pilot.pause()
        assert len(shown(app)) == 2

    run(data, scenario)
    assert saved_set(data) == {("keep me", False), ("me too", False)}


def test_filter_cycles_all_active_done(data):
    seed(data, [("laundry", False), ("taxes", True), ("dentist", False)])
    titles = ["laundry", "taxes", "dentist"]

    async def scenario(app, pilot):
        app.query_one("#todo-list").focus()
        await pilot.pause()
        seen = [sorted(shown_titles(app, titles))]
        for _ in range(3):
            await pilot.press("f")
            await pilot.pause()
            seen.append(sorted(shown_titles(app, titles)))
        return seen

    seen = run(data, scenario)
    assert seen == [sorted(titles), ["dentist", "laundry"], ["taxes"], sorted(titles)]
    assert saved_set(data) == {("laundry", False), ("taxes", True), ("dentist", False)}


def test_typing_keys_in_input_does_not_trigger_actions(data):
    seed(data, [("existing", False)])

    async def scenario(app, pilot):
        await add(pilot, "d f d")
        assert len(shown(app)) == 2

    run(data, scenario)
    assert saved_set(data) == {("existing", False), ("d f d", False)}


def test_survives_restart(data):
    async def first(app, pilot):
        await add(pilot, "alpha", "beta", "gamma")
        await focus_row(app, pilot, "beta")
        await pilot.press("space")
        await pilot.pause()
        await focus_row(app, pilot, "gamma")
        await pilot.press("d")

    run(data, first)

    async def second(app, pilot):
        return sorted(shown_titles(app, ["alpha", "beta", "gamma"]))

    assert run(data, second) == ["alpha", "beta"]
    assert saved_set(data) == {("alpha", False), ("beta", True)}


def test_intent_done_sorted_to_bottom(data):
    seed(data, [("apple", True), ("banana", False), ("cherry", False)])
    titles = ["apple", "banana", "cherry"]

    async def scenario(app, pilot):
        assert shown_titles(app, titles) == ["banana", "cherry", "apple"]
        await focus_row(app, pilot, "banana")
        await pilot.press("space")
        await pilot.pause()
        assert shown_titles(app, titles) == ["cherry", "apple", "banana"]
        await add(pilot, "plum")
        assert shown_titles(app, titles + ["plum"]) == ["cherry", "plum", "apple", "banana"]

    run(data, scenario)


def test_intent_input_keeps_focus_and_trims(data):
    async def scenario(app, pilot):
        app.query_one("#new-todo").focus()
        await pilot.pause()
        await pilot.press(*"  first  ", "enter")
        await pilot.pause()
        await pilot.press(*"second", "enter")  # no refocus in between
        await pilot.pause()

    run(data, scenario)
    assert saved_set(data) == {("first", False), ("second", False)}
