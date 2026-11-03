"""Part: editing a text file with TextArea: load, save, unsaved-changes flag.

- TextArea(text, id=...); read and write .text. TextArea.Changed fires on every edit, and also
  after you set .text in code (later, not right away, so a "loading" flag doesn't help).
  Track unsaved changes by comparing the text with what was last saved.
- ctrl+s is free for save; TextArea takes printable keys, so app bindings must use ctrl+ keys.
- App.quit is bound to ctrl+q by default; override action_quit to ask before losing changes
  (see the `modal` part for the dialog).
"""

from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Footer, Static, TextArea


class EditorApp(App):
    BINDINGS = [Binding("ctrl+s", "save", "Save")]

    def __init__(self, path: str = "notes.txt") -> None:
        super().__init__()
        self.path = Path(path)
        self.saved = self.path.read_text() if self.path.exists() else ""

    @property
    def dirty(self) -> bool:
        return self.query_one("#editor", TextArea).text != self.saved

    def compose(self) -> ComposeResult:
        yield TextArea(self.saved, id="editor")
        yield Static("", id="status")
        yield Footer()

    def on_mount(self) -> None:
        self.refresh_status()

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        self.refresh_status()

    def refresh_status(self) -> None:
        self.query_one("#status", Static).update(f"{self.path.name}{' *' if self.dirty else ''}")

    def action_save(self) -> None:
        self.saved = self.query_one("#editor", TextArea).text
        self.path.write_text(self.saved)
        self.refresh_status()
        self.notify(f"Saved {self.path.name}", markup=False)


if __name__ == "__main__":
    EditorApp().run()
