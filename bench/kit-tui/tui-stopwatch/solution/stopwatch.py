"""Terminal stopwatch with laps and an injectable clock."""

import time

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Footer, Header, Label, ListItem, ListView, Static


def fmt(seconds: float) -> str:
    tenths = int(seconds * 10 + 1e-6)
    h, rem = divmod(tenths, 36000)
    m, rem = divmod(rem, 600)
    s, d = divmod(rem, 10)
    if h:
        return f"{h}:{m:02d}:{s:02d}.{d}"
    return f"{m:02d}:{s:02d}.{d}"


class StopwatchApp(App):
    TITLE = "Stopwatch"
    CSS = """
    #elapsed { text-style: bold; content-align: center middle; height: 5; border: round $primary; margin: 1 2; }
    #laps { height: 1fr; margin: 0 2; border: round $secondary; }
    """
    BINDINGS = [
        Binding("space", "toggle", "Start/Pause"),
        Binding("l", "lap", "Lap"),
        Binding("r", "reset", "Reset"),
    ]

    def __init__(self, clock=time.monotonic):
        super().__init__()
        self.clock = clock
        self.accumulated = 0.0  # time from finished running stretches
        self.started_at: float | None = None
        self.laps: list[float] = []  # total elapsed at each lap

    @property
    def running(self) -> bool:
        return self.started_at is not None

    def elapsed(self) -> float:
        if self.started_at is None:
            return self.accumulated
        return self.accumulated + (self.clock() - self.started_at)

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(fmt(0), id="elapsed")
        yield ListView(id="laps")
        yield Footer()

    def on_mount(self) -> None:
        self.set_interval(1 / 20, self.tick)

    def tick(self) -> None:
        self.query_one("#elapsed", Static).update(fmt(self.elapsed()))

    def action_toggle(self) -> None:
        if self.running:
            self.accumulated = self.elapsed()
            self.started_at = None
        else:
            self.started_at = self.clock()
        self.tick()

    async def action_lap(self) -> None:
        if not self.running:
            return
        total = self.elapsed()
        prev = self.laps[-1] if self.laps else 0.0
        self.laps.append(total)
        label = f"Lap {len(self.laps)}   {fmt(total - prev)}   (total {fmt(total)})"
        await self.query_one("#laps", ListView).insert(0, [ListItem(Label(label))])

    async def action_reset(self) -> None:
        if self.running:
            return
        self.accumulated = 0.0
        self.laps = []
        await self.query_one("#laps", ListView).clear()
        self.tick()


if __name__ == "__main__":
    StopwatchApp().run()
