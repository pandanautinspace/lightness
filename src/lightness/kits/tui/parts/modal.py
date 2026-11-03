"""Part: dialogs over the app that return a result.

- Subclass ModalScreen[ResultType]; close it with self.dismiss(result).
- Open it with self.push_screen(Screen(), callback); the callback gets the result.
  (push_screen_wait only works inside an @work worker; the callback form works anywhere.)
- Escape-to-cancel: a binding ("escape", "cancel") whose action dismisses with None/False.
- While a modal is open, keys go to the modal, not to the app's bindings.
"""

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Static


class ConfirmScreen(ModalScreen[bool]):
    BINDINGS = [Binding("escape", "cancel", "Cancel")]
    DEFAULT_CSS = """
    ConfirmScreen { align: center middle; }
    ConfirmScreen > Vertical { width: 50; height: auto; border: thick $primary; padding: 1 2; }
    """

    def __init__(self, question: str) -> None:
        super().__init__()
        self.question = question

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label(self.question)
            with Horizontal():
                yield Button("Yes", id="yes", variant="error")
                yield Button("No", id="no")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "yes")

    def action_cancel(self) -> None:
        self.dismiss(False)


class EditScreen(ModalScreen[str | None]):
    """A one-field form; returns the new text, or None when cancelled."""

    BINDINGS = [Binding("escape", "cancel", "Cancel")]
    DEFAULT_CSS = """
    EditScreen { align: center middle; }
    EditScreen > Vertical { width: 60; height: auto; border: thick $primary; padding: 1 2; }
    """

    def __init__(self, value: str = "") -> None:
        super().__init__()
        self.value = value

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("Title")
            yield Input(value=self.value, id="edit-value")

    def on_mount(self) -> None:
        self.query_one("#edit-value", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value.strip() or None)

    def action_cancel(self) -> None:
        self.dismiss(None)


class ModalApp(App):
    BINDINGS = [Binding("e", "edit", "Edit"), Binding("x", "clear", "Clear")]

    def __init__(self) -> None:
        super().__init__()
        self.title_text = "untitled"

    def compose(self) -> ComposeResult:
        yield Static(self.title_text, id="title")

    def action_edit(self) -> None:
        def done(value: str | None) -> None:
            if value is not None:
                self.title_text = value
                self.query_one("#title", Static).update(value)

        self.push_screen(EditScreen(self.title_text), done)

    def action_clear(self) -> None:
        def done(yes: bool | None) -> None:
            if yes:
                self.title_text = ""
                self.query_one("#title", Static).update("")

        self.push_screen(ConfirmScreen("Clear the title?"), done)


if __name__ == "__main__":
    ModalApp().run()
