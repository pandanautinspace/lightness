"""Browse a JSON document as a tree with a detail pane."""

import json
import sys
from pathlib import Path

from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import Footer, Header, Static, Tree


def path_step(parent_path: str, key) -> str:
    return f"{parent_path}[{key}]" if isinstance(key, int) else f"{parent_path}.{key}"


def label_for(key, value) -> Text:
    name = f"[{key}]" if isinstance(key, int) else str(key)
    if isinstance(value, dict):
        return Text.assemble((name, "bold"), (f" {{{len(value)}}}", "dim"))
    if isinstance(value, list):
        return Text.assemble((name, "bold"), (f" [{len(value)}]", "dim"))
    return Text.assemble((name, "bold"), ": ", (json.dumps(value, ensure_ascii=False), "green"))


class JsonViewerApp(App):
    CSS = """
    #tree { width: 1fr; border: round $primary; }
    #side { width: 1fr; border: round $secondary; }
    #path { text-style: bold; padding: 0 1; }
    #detail { padding: 0 1; }
    """

    def __init__(self, json_path):
        super().__init__()
        self.path = Path(json_path)
        self.title = self.path.name
        self.error: str | None = None
        try:
            self.doc = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
            self.doc = None
            self.error = f"Invalid JSON in {self.path.name}: {e}"

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal():
            yield Tree("$", id="tree")
            with VerticalScroll(id="side"):
                yield Static(id="path")
                yield Static(id="detail", markup=False)
        yield Footer()

    def on_mount(self) -> None:
        tree = self.query_one("#tree", Tree)
        if self.error:
            tree.root.label = Text("(invalid JSON)")
            tree.root.data = None
            self.query_one("#path", Static).update("")
            self.query_one("#detail", Static).update(self.error)
            return
        tree.root.label = label_for("$", self.doc) if isinstance(self.doc, (dict, list)) else Text("$")
        tree.root.data = ("$", self.doc)
        self.populate(tree.root)
        tree.root.expand()
        tree.focus()
        tree.move_cursor(tree.root)
        self.show(tree.root)

    def populate(self, node) -> None:
        if node.children or node.data is None:
            return
        path, value = node.data
        items = value.items() if isinstance(value, dict) else enumerate(value) if isinstance(value, list) else []
        for key, child in items:
            data = (path_step(path, key), child)
            if isinstance(child, (dict, list)) and child:
                node.add(label_for(key, child), data=data)
            else:
                node.add_leaf(label_for(key, child), data=data)

    def on_tree_node_expanded(self, event: Tree.NodeExpanded) -> None:
        self.populate(event.node)

    def on_tree_node_highlighted(self, event: Tree.NodeHighlighted) -> None:
        self.show(event.node)

    def show(self, node) -> None:
        if node.data is None:
            return
        path, value = node.data
        self.query_one("#path", Static).update(path)
        self.query_one("#detail", Static).update(json.dumps(value, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: python jview.py FILE.json")
    JsonViewerApp(sys.argv[1]).run()
