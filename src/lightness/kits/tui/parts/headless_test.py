"""Part: testing a Textual app headlessly with pytest (no terminal needed).

- Run the real app with `async with app.run_test() as pilot:`; drive it with pilot.press(...)
  and call `await pilot.pause()` before checking anything.
- pytest-asyncio is not installed: write normal test functions that call asyncio.run(...).
- Type text with pilot.press(*"some text"); "enter", "space", "tab", "up", "down", "escape"
  are key names. Keys go to the focused widget: focus the right one first (pilot.click(selector)
  or widget.focus()).
- Test the cases a user hits: starting with no data file, starting with an existing file,
  and restarting after a change. Check the saved file's exact contents.
- Bad CSS or a crash in compose/on_mount fails the test when run_test exits, so even a
  "does it start" test catches them.
"""

import asyncio
import json

from textual.app import App, ComposeResult
from textual.widgets import Input, Label, ListItem, ListView


class NotesApp(App):  # in your tests, import your own app instead
    def __init__(self, path) -> None:
        super().__init__()
        self.path = path
        self.notes = json.loads(path.read_text()) if path.exists() else []

    def compose(self) -> ComposeResult:
        yield Input(id="new")
        yield ListView(*[ListItem(Label(n)) for n in self.notes], id="notes")

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.value.strip():
            self.notes.append(event.value.strip())
            self.path.write_text(json.dumps(self.notes))
            await self.query_one("#notes", ListView).append(ListItem(Label(event.value.strip())))
        event.input.value = ""


def shown(app) -> list[str]:
    return [str(item.query_one(Label).content) for item in app.query_one("#notes", ListView).children]


def test_starts_without_a_data_file(tmp_path):
    async def run():
        app = NotesApp(tmp_path / "notes.json")
        async with app.run_test() as pilot:
            await pilot.pause()
            assert shown(app) == []

    asyncio.run(run())


def test_add_saves_and_survives_restart(tmp_path):
    path = tmp_path / "notes.json"

    async def run():
        app = NotesApp(path)
        async with app.run_test() as pilot:
            await pilot.click("#new")
            await pilot.press(*"buy milk", "enter")
            await pilot.pause()
            assert shown(app) == ["buy milk"]
        assert json.loads(path.read_text()) == ["buy milk"]
        again = NotesApp(path)  # restart with the saved file
        async with again.run_test() as pilot:
            await pilot.pause()
            assert shown(again) == ["buy milk"]

    asyncio.run(run())


def test_starts_with_an_existing_file(tmp_path):
    path = tmp_path / "notes.json"
    path.write_text(json.dumps(["a", "b"]))

    async def run():
        app = NotesApp(path)
        async with app.run_test() as pilot:
            await pilot.pause()
            assert shown(app) == ["a", "b"]

    asyncio.run(run())
