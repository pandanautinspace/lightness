"""Part: filter-as-you-type over a list.

- Keep the full data; compute the visible subset from the query on every Input.Changed.
- Map actions on the highlighted row back to the full data through the visible subset.
- While the Input has focus, printable keys type into it: put list actions on keys the Input
  doesn't take (enter via ListView.Selected, or ctrl+/function keys), or move focus to the list.
- Don't name your attributes after Textual's own (visible, display, size, region, children,
  parent, name, id, classes, styles): `self.visible = [...]` breaks the app.
- For slow searches (big files), run the search in a worker (see the `worker` part).
"""

from textual.app import App, ComposeResult
from textual.widgets import Input, Label, ListItem, ListView, Static

WORDS = ["apple", "apricot", "banana", "blueberry", "cherry", "grape"]


class FilterApp(App):
    def __init__(self) -> None:
        super().__init__()
        self.words = list(WORDS)
        self.matches: list[str] = list(WORDS)

    def compose(self) -> ComposeResult:
        yield Input(placeholder="Filter", id="query")
        yield Static("", id="count")
        yield ListView(id="results")

    async def on_mount(self) -> None:
        await self.refresh_view()

    async def on_input_changed(self, event: Input.Changed) -> None:
        await self.refresh_view()

    async def refresh_view(self) -> None:
        query = self.query_one("#query", Input).value.strip().lower()
        self.matches = [w for w in self.words if query in w.lower()]
        lv = self.query_one("#results", ListView)
        await lv.clear()
        await lv.extend(ListItem(Label(w)) for w in self.matches)
        if self.matches:
            lv.index = 0
        self.query_one("#count", Static).update(f"{len(self.matches)} of {len(self.words)}")

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        self.notify(f"picked {self.matches[event.index]}", markup=False)


if __name__ == "__main__":
    FilterApp().run()
