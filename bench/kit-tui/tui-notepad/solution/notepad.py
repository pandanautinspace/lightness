"""A tiny plain-text notepad with save, dirty flag and quit confirmation."""

import shutil
import sys
from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Grid
from textual.screen import ModalScreen
from textual.widgets import Button, Footer, Header, Label, Static, TextArea


class ConfirmQuit(ModalScreen[str]):
    CSS = """
    ConfirmQuit { align: center middle; }
    #dialog { grid-size: 3; grid-gutter: 1 2; grid-rows: auto 3; padding: 1 2; width: 60; height: auto;
              border: thick $warning; background: $surface; }
    #question { column-span: 3; width: 1fr; content-align: center middle; }
    """
    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def compose(self) -> ComposeResult:
        with Grid(id="dialog"):
            yield Label("You have unsaved changes. Save before quitting?", id="question")
            yield Button("Save", variant="primary", id="save")
            yield Button("Discard", variant="error", id="discard")
            yield Button("Cancel", id="cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id)

    def action_cancel(self) -> None:
        self.dismiss("cancel")


class NotepadApp(App):
    CSS = """
    #editor { height: 1fr; }
    #status { height: 1; padding: 0 1; background: $panel; }
    """
    BINDINGS = [
        Binding("ctrl+s", "save", "Save", priority=True),
        Binding("ctrl+q", "quit", "Quit", priority=True),
    ]

    def __init__(self, path):
        super().__init__()
        self.path = Path(path)
        self.saved_text = self.path.read_text(encoding="utf-8") if self.path.exists() else ""
        self.title = self.path.name

    def compose(self) -> ComposeResult:
        yield Header()
        yield TextArea(self.saved_text, id="editor")
        yield Static(id="status")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#editor", TextArea).focus()
        self.update_status()

    @property
    def dirty(self) -> bool:
        return self.query_one("#editor", TextArea).text != self.saved_text

    def update_status(self) -> None:
        state = "modified" if self.dirty else "saved"
        self.query_one("#status", Static).update(f"{self.path.name} — {state}")

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        self.update_status()

    def save(self) -> None:
        text = self.query_one("#editor", TextArea).text
        out = text if text.endswith("\n") else text + "\n"
        if self.path.exists():
            shutil.copyfile(self.path, self.path.with_name(self.path.name + ".bak"))
        self.path.write_text(out, encoding="utf-8")
        self.saved_text = text
        self.update_status()

    def action_save(self) -> None:
        self.save()
        self.notify(f"Saved {self.path.name}")

    async def action_quit(self) -> None:
        if not self.dirty:
            self.exit()
            return

        def decided(choice: str | None) -> None:
            if choice == "save":
                self.save()
                self.exit()
            elif choice == "discard":
                self.exit()

        self.push_screen(ConfirmQuit(), decided)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: python notepad.py FILE")
    NotepadApp(sys.argv[1]).run()
