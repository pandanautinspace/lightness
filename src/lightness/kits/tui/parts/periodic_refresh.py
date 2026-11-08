"""Part: updating on a timer (clock, stopwatch, countdown, monitor), testable without waiting.

- Put the per-tick logic in a plain method (tick()) and call it from set_interval; tests call
  tick() directly instead of sleeping.
- Inject the clock (a `now` callable) so tests control time; never call time.time() deep inside.
- set_interval returns a Timer: timer.pause() / timer.resume() to stop and start.
- A reactive attribute plus watch_<name>() keeps the display in sync with the value.
- Every key that changes the state (start, pause, reset, ...) calls tick() itself before returning,
  so the screen is right at once, not only at the next timer tick (tests read it right after the key).
"""

import time

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.reactive import reactive
from textual.widgets import Digits, Footer


class StopwatchApp(App):
    BINDINGS = [Binding("space", "start_stop", "Start/stop"), Binding("r", "reset", "Reset")]
    elapsed = reactive(0.0)

    def __init__(self, now=time.monotonic) -> None:
        super().__init__()
        self.now = now
        self.started_at: float | None = None
        self.banked = 0.0  # time from earlier runs

    def compose(self) -> ComposeResult:
        yield Digits("00:00.0", id="display")
        yield Footer()

    def on_mount(self) -> None:
        self.timer = self.set_interval(0.1, self.tick, pause=True)

    def tick(self) -> None:
        running = self.now() - self.started_at if self.started_at is not None else 0.0
        self.elapsed = self.banked + running

    def watch_elapsed(self, value: float) -> None:
        minutes, seconds = divmod(value, 60)
        self.query_one("#display", Digits).update(f"{int(minutes):02d}:{seconds:04.1f}")

    def action_start_stop(self) -> None:
        if self.started_at is None:
            self.started_at = self.now()
            self.timer.resume()
        else:
            self.banked += self.now() - self.started_at
            self.started_at = None
            self.timer.pause()
        self.tick()

    def action_reset(self) -> None:
        self.banked = 0.0
        self.started_at = self.now() if self.started_at is not None else None
        self.tick()


if __name__ == "__main__":
    StopwatchApp().run()
