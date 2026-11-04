"""Part: pytest tests that drive a Textual app headlessly (no terminal needed).

Setup
- pytest-asyncio is not installed: write plain test functions that call asyncio.run(...).
- Run tests with `python -m pytest` from the project root; that puts the root on sys.path,
  so `from mymodule import MyApp` works from any test file.
- Drive the real app: `async with app.run_test() as pilot:`, then `await pilot.pause()` after
  every action before checking anything.

Keys and inputs
- Keys go to the focused widget. Focus it first (widget.focus() or pilot.click("#id")).
- Printable keys typed into an Input go into the Input: they don't fire App bindings. To use
  a letter binding, focus the list or table first.
- To replace an Input's text: focus it, press "end", "ctrl+u" (clears to the left), then type.
- Type text with pilot.press(*"some text"); "enter", "space", "tab", "up", "down", "escape" are
  key names.

What to check
- Read results from the app's state and from the saved file's exact contents, not from how
  widgets look. Notifications are in app._notifications (each has .message).
- A ListView that is cleared and refilled loses its highlight: read list.index after the
  rebuild instead of assuming it stayed.
- Time: pass a fake clock (a callable you move forward) as the app's clock parameter. Move it,
  then `await pilot.pause(0.3)` so a set_interval timer ticks and reads it. Never sleep for the
  real duration.

Expected values
- Take them from the task text. When unsure what the app actually does, run the try command
  and compare with the task before writing the assertion.
- When a test fails, check the case with the try command, then fix whichever side disagrees
  with the task: the test or the app.

Size: one tests file with about one test per contract item (each key, the file format, starting
with and without a data file, restarting after a change).
"""

import asyncio
import json

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Input, Label, ListItem, ListView, Static


class TallyApp(App):  # in your tests, import your own app instead: from mymodule import MyApp
    """Named counters: type a name and press enter to add it; `+` on the list counts the highlighted one."""

    BINDINGS = [Binding("plus", "bump", "Count")]

    def __init__(self, path, now) -> None:
        super().__init__()
        self.path, self.now = path, now
        self.counts = json.loads(path.read_text()) if path.exists() else {}
        self.changed_at = now()

    def compose(self) -> ComposeResult:
        yield Input(id="name")
        yield ListView(id="counters")
        yield Static("", id="since")

    def on_mount(self) -> None:
        self.refresh_list()
        self.set_interval(0.1, self.tick)

    def tick(self) -> None:
        self.query_one("#since", Static).update(f"changed {int(self.now() - self.changed_at)}s ago")

    def refresh_list(self) -> None:
        view = self.query_one("#counters", ListView)
        view.clear()
        view.extend(ListItem(Label(f"{name}: {n}")) for name, n in self.counts.items())

    def change(self) -> None:
        self.path.write_text(json.dumps(self.counts))
        self.changed_at = self.now()
        self.refresh_list()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        name = event.value.strip()
        if name in self.counts:
            self.notify(f"{name} already exists")
        elif name:
            self.counts[name] = 0
            self.change()
        event.input.value = ""

    def action_bump(self) -> None:
        index = self.query_one("#counters", ListView).index
        if index is not None:
            name = list(self.counts)[index]
            self.counts[name] += 1
            self.change()


class FakeClock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


def run(app, steps):
    """Start the app headless, run steps(app, pilot), and return what it returns."""
    async def main():
        async with app.run_test() as pilot:
            await pilot.pause()
            return await steps(app, pilot)

    return asyncio.run(main())


def shown(app) -> list[str]:
    return [str(item.query_one(Label).content) for item in app.query_one("#counters", ListView).children]


def test_starts_without_a_data_file(tmp_path):
    async def steps(app, pilot):
        assert shown(app) == [] and app.counts == {}

    run(TallyApp(tmp_path / "counts.json", FakeClock()), steps)


def test_starts_with_an_existing_file(tmp_path):
    path = tmp_path / "counts.json"
    path.write_text('{"a": 2, "b": 0}')

    async def steps(app, pilot):
        assert shown(app) == ["a: 2", "b: 0"]

    run(TallyApp(path, FakeClock()), steps)


def test_add_saves_exact_format_and_survives_restart(tmp_path):
    path = tmp_path / "counts.json"

    async def add(app, pilot):
        app.query_one("#name").focus()
        await pilot.press(*"laps", "enter")
        await pilot.pause()
        assert shown(app) == ["laps: 0"]

    run(TallyApp(path, FakeClock()), add)
    assert json.loads(path.read_text()) == {"laps": 0}

    async def after_restart(app, pilot):
        assert shown(app) == ["laps: 0"]

    run(TallyApp(path, FakeClock()), after_restart)


def test_key_binding_acts_on_the_highlighted_item(tmp_path):
    path = tmp_path / "counts.json"
    path.write_text('{"a": 0, "b": 0}')

    async def steps(app, pilot):
        view = app.query_one("#counters", ListView)
        view.focus()  # "+" typed into the Input would not count
        view.index = 1  # highlight "b" (after a rebuild nothing is highlighted, so "down" would pick "a")
        await pilot.press("plus")
        await pilot.pause()
        assert app.counts == {"a": 0, "b": 1}
        assert view.index is None  # the rebuild dropped the highlight

    run(TallyApp(path, FakeClock()), steps)
    assert json.loads(path.read_text()) == {"a": 0, "b": 1}


def test_replacing_input_text_and_duplicate_notification(tmp_path):
    path = tmp_path / "counts.json"
    path.write_text('{"a": 0}')

    async def steps(app, pilot):
        app.query_one("#name").focus()
        await pilot.press(*"xyz")
        await pilot.press("end", "ctrl+u", *"a", "enter")  # replace "xyz" with "a"
        await pilot.pause()
        assert [n.message for n in app._notifications] == ["a already exists"]
        assert app.counts == {"a": 0}

    run(TallyApp(path, FakeClock()), steps)


def test_time_moves_with_the_fake_clock(tmp_path):
    clock = FakeClock()

    async def steps(app, pilot):
        clock.t += 30
        await pilot.pause(0.3)  # one timer period: tick() reads the moved clock
        assert "changed 30s ago" in str(app.query_one("#since", Static).content)

    run(TallyApp(tmp_path / "counts.json", clock), steps)
