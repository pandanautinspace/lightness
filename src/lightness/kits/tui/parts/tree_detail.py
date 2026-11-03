"""Part: a tree on the left, details of the selected node on the right.

- Tree(label): build nodes with node.add(label, data=...) (branch) and node.add_leaf(label,
  data=...); keep the real object in `data` and read it back from event.node.data.
- Tree.NodeHighlighted fires on cursor moves, Tree.NodeSelected on enter/click. Expand with
  node.expand() (or tree.root.expand_all()).
- For folders, DirectoryTree(path) does this for you and posts DirectoryTree.FileSelected.
- Two panes: a Horizontal container with widths in fr units (no px, no flex).
"""

import json

from textual.app import App, ComposeResult
from textual.containers import Horizontal
from textual.widgets import Static, Tree

SAMPLE = {"name": "demo", "tags": ["a", "b"], "owner": {"id": 7, "email": "x@example.com"}}


class JsonTreeApp(App):
    CSS = """
    #tree { width: 1fr; }
    #detail { width: 2fr; padding: 0 1; }
    """

    def __init__(self, data=SAMPLE) -> None:
        super().__init__()
        self.data = data

    def compose(self) -> ComposeResult:
        with Horizontal():
            yield Tree("root", id="tree")
            yield Static("", id="detail")

    def on_mount(self) -> None:
        tree = self.query_one("#tree", Tree)
        tree.root.data = self.data
        self.add_nodes(tree.root, self.data)
        tree.root.expand_all()

    def add_nodes(self, node, value) -> None:
        items = value.items() if isinstance(value, dict) else enumerate(value)
        for key, child in items:
            if isinstance(child, (dict, list)):
                self.add_nodes(node.add(str(key), data=child), child)
            else:
                node.add_leaf(f"{key}: {child}", data=child)

    def on_tree_node_highlighted(self, event: Tree.NodeHighlighted) -> None:
        self.query_one("#detail", Static).update(json.dumps(event.node.data, indent=2))


if __name__ == "__main__":
    JsonTreeApp().run()
