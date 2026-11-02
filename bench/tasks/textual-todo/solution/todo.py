"""A small Textual todo list persisted to a JSON file."""

import json
import sys
from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Footer, Header, Input, Label, ListItem, ListView

FILTERS = ("all", "active", "done")


class TodoApp(App):
    TITLE = "Todos"
    CSS = """
    #new-todo { margin: 0 1; }
    #todo-list { height: 1fr; margin: 0 1; border: round $primary; }
    #status { margin: 0 2; color: $text-muted; }
    ListItem.done Label { color: $text-muted; text-style: strike; }
    """
    BINDINGS = [
        Binding("space", "toggle", "Toggle done"),
        Binding("d", "delete", "Delete"),
        Binding("f", "cycle_filter", "Filter"),
    ]

    def __init__(self, data_path="todos.json"):
        super().__init__()
        self.data_path = Path(data_path)
        self.todos: list[dict] = self.load()
        self.filter = "all"
        self.shown: list[dict] = []

    # ---- persistence ----
    def load(self) -> list[dict]:
        try:
            data = json.loads(self.data_path.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            return []
        return [{"title": str(t["title"]), "done": bool(t.get("done"))} for t in data if "title" in t]

    def save(self) -> None:
        self.data_path.write_text(json.dumps(self.todos, indent=2))

    # ---- ui ----
    def compose(self) -> ComposeResult:
        yield Header()
        yield Input(placeholder="What needs doing? (enter to add)", id="new-todo")
        yield ListView(id="todo-list")
        yield Label(id="status")
        yield Footer()

    async def on_mount(self) -> None:
        await self.refresh_list()
        self.query_one("#new-todo", Input).focus()

    def visible(self) -> list[dict]:
        ordered = sorted(self.todos, key=lambda t: t["done"])  # stable: open first, then done
        if self.filter == "active":
            return [t for t in ordered if not t["done"]]
        if self.filter == "done":
            return [t for t in ordered if t["done"]]
        return ordered

    async def refresh_list(self, keep: dict | None = None) -> None:
        lv = self.query_one("#todo-list", ListView)
        old_index = lv.index
        self.shown = self.visible()
        await lv.clear()
        items = []
        for t in self.shown:
            mark = "[x]" if t["done"] else "[ ]"
            items.append(ListItem(Label(f"{mark} {t['title']}", markup=False), classes="done" if t["done"] else ""))
        await lv.extend(items)
        if self.shown:
            if keep is not None and any(t is keep for t in self.shown):
                index = next(i for i, t in enumerate(self.shown) if t is keep)
            else:
                index = min(old_index or 0, len(self.shown) - 1)
            lv.index = index
        left = sum(not t["done"] for t in self.todos)
        self.query_one("#status", Label).update(f"filter: {self.filter}  ·  {left} left")

    def highlighted(self) -> dict | None:
        lv = self.query_one("#todo-list", ListView)
        if lv.index is None or not (0 <= lv.index < len(self.shown)):
            return None
        return self.shown[lv.index]

    # ---- actions ----
    async def on_input_submitted(self, event: Input.Submitted) -> None:
        title = event.value.strip()
        event.input.value = ""
        if not title:
            return
        self.todos.append({"title": title, "done": False})
        self.save()
        await self.refresh_list()
        event.input.focus()

    def _list_focused(self) -> bool:
        return isinstance(self.focused, ListView)

    async def action_toggle(self) -> None:
        todo = self.highlighted() if self._list_focused() else None
        if todo is None:
            return
        todo["done"] = not todo["done"]
        self.save()
        await self.refresh_list(keep=todo)

    async def action_delete(self) -> None:
        todo = self.highlighted() if self._list_focused() else None
        if todo is None:
            return
        self.todos = [t for t in self.todos if t is not todo]
        self.save()
        await self.refresh_list()

    async def action_cycle_filter(self) -> None:
        if not self._list_focused():
            return
        self.filter = FILTERS[(FILTERS.index(self.filter) + 1) % len(FILTERS)]
        await self.refresh_list()


if __name__ == "__main__":
    TodoApp(sys.argv[1] if len(sys.argv) > 1 else "todos.json").run()
