"""Part: slow or blocking work without freezing the UI.

- Blocking (non-async) code: @work(thread=True) and update widgets with
  self.call_from_thread(fn, *args). Never touch widgets directly from the thread.
- exclusive=True cancels the previous run (search-as-you-type).
- Tests: after triggering the work, `await app.workers.wait_for_complete()` then
  `await pilot.pause()` before checking.
"""

from pathlib import Path

from textual import work
from textual.app import App, ComposeResult
from textual.widgets import Input, Static


class GrepApp(App):
    def __init__(self, folder: str = ".") -> None:
        super().__init__()
        self.folder = Path(folder)
        self.hits: list[str] = []

    def compose(self) -> ComposeResult:
        yield Input(placeholder="Search text", id="query")
        yield Static("", id="status")
        yield Static("", id="hits")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.query_one("#status", Static).update("searching…")
        self.search(event.value)

    @work(thread=True, exclusive=True)
    def search(self, text: str) -> None:
        hits = []
        for path in sorted(self.folder.rglob("*.txt")):
            for n, line in enumerate(path.read_text(errors="replace").splitlines(), 1):
                if text and text.lower() in line.lower():
                    hits.append(f"{path.name}:{n}: {line.strip()}")
        self.call_from_thread(self.show, hits)

    def show(self, hits: list[str]) -> None:
        self.hits = hits
        self.query_one("#status", Static).update(f"{len(hits)} matches")
        self.query_one("#hits", Static).update("\n".join(hits))


if __name__ == "__main__":
    GrepApp().run()
