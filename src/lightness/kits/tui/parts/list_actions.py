"""Part: a list of items with key actions on the highlighted item.

- Items are plain dicts in self.items; the ListView only displays them. Never read state back
  from widgets, and never save UI-only fields (index, selection) into the data.
- App BINDINGS on printable keys (space, d, e) fire while the ListView has focus: it only binds
  enter/up/down itself. They do NOT fire while an Input has focus: it takes printable keys.
  For enter on the list, handle ListView.Selected instead of a binding.
- Rebuilding the list (clear + extend) resets ListView.index to None. Restore it, or the
  actions find no highlighted item.
- ListView items must be ListItem(Label(...)), not strings. Await clear()/extend().
"""

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Footer, Input, Label, ListItem, ListView


class ListActionsApp(App):
    BINDINGS = [
        Binding("space", "toggle", "Toggle"),
        Binding("d", "delete", "Delete"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.items: list[dict] = [{"title": "first", "done": False}, {"title": "second", "done": False}]

    def compose(self) -> ComposeResult:
        yield Input(placeholder="New item", id="new-item")
        yield ListView(id="items")
        yield Footer()

    async def on_mount(self) -> None:
        await self.refresh_view()

    async def refresh_view(self, index: int | None = None) -> None:
        lv = self.query_one("#items", ListView)
        keep = lv.index if index is None else index
        await lv.clear()
        await lv.extend(ListItem(Label(("✓ " if it["done"] else "  ") + it["title"])) for it in self.items)
        if self.items:
            lv.index = min(keep or 0, len(self.items) - 1)

    def current(self) -> int | None:
        index = self.query_one("#items", ListView).index
        return index if index is not None and index < len(self.items) else None

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        title = event.value.strip()
        event.input.value = ""  # focus stays in the input, ready for the next one
        if title:
            self.items.append({"title": title, "done": False})
            await self.refresh_view(index=len(self.items) - 1)  # then save, if the app keeps data

    async def on_list_view_selected(self, event: ListView.Selected) -> None:
        await self.action_toggle()  # enter on the list

    async def action_toggle(self) -> None:
        i = self.current()
        if i is not None:
            self.items[i]["done"] = not self.items[i]["done"]
            await self.refresh_view()

    async def action_delete(self) -> None:
        i = self.current()
        if i is not None:
            del self.items[i]
            await self.refresh_view()


if __name__ == "__main__":
    ListActionsApp().run()
