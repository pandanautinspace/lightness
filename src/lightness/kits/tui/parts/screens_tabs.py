"""Part: several views: tabs inside one screen, or separate screens.

- Tabs: TabbedContent with TabPane(title, id=...); switch with tabbed.active = "pane-id".
- Screens: push_screen(SettingsScreen(...), callback); the screen closes with self.dismiss(result)
  and the callback gets the result: update the app's state there and refresh. Keep state on the
  App; pass what a screen needs into its __init__ (reading self.app.<attr> from a screen also
  works, but type checkers flag it).
- React to tab switches with on_tabbed_content_tab_activated.
- Footer shows the bindings of the active screen.
"""

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import Footer, Input, Static, TabbedContent, TabPane


class SettingsScreen(Screen[str | None]):
    """Returns the new name, or None when left with escape."""

    BINDINGS = [Binding("escape", "back", "Back")]

    def __init__(self, name: str) -> None:
        super().__init__()
        self.current = name

    def compose(self) -> ComposeResult:
        yield Static("Your name:")
        yield Input(value=self.current, id="name")
        yield Footer()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value.strip() or None)

    def action_back(self) -> None:
        self.dismiss(None)


class TabsApp(App):
    BINDINGS = [
        Binding("1", "show('home')", "Home"),
        Binding("2", "show('about')", "About"),
        Binding("s", "settings", "Settings"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.user_name = "friend"

    def compose(self) -> ComposeResult:
        with TabbedContent(initial="home", id="tabs"):
            with TabPane("Home", id="home"):
                yield Static("", id="greeting")
            with TabPane("About", id="about"):
                yield Static("A tabs and screens example.")
        yield Footer()

    def on_mount(self) -> None:
        self.refresh_view()

    def refresh_view(self) -> None:
        self.query_one("#greeting", Static).update(f"Hello, {self.user_name}!")

    def action_show(self, pane: str) -> None:
        self.query_one("#tabs", TabbedContent).active = pane

    def action_settings(self) -> None:
        def done(name: str | None) -> None:
            if name:
                self.user_name = name
            self.refresh_view()

        self.push_screen(SettingsScreen(self.user_name), done)


if __name__ == "__main__":
    TabsApp().run()
