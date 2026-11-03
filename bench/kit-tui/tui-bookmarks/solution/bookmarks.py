"""Bookmark manager backed by SQLite, with a modal add/edit form."""

import re
import sqlite3
import sys
from pathlib import Path

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Footer, Header, Input, Label, ListItem, ListView

SCHEMA = "CREATE TABLE IF NOT EXISTS bookmarks (id INTEGER PRIMARY KEY, title TEXT, url TEXT, tags TEXT)"


def normalize_url(url: str) -> str:
    url = url.strip()
    if url and not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", url):
        url = "https://" + url
    return url


def normalize_tags(tags: str) -> str:
    out: list[str] = []
    for t in tags.split(","):
        t = t.strip().lower()
        if t and t not in out:
            out.append(t)
    return ",".join(out)


class BookmarkForm(ModalScreen[dict | None]):
    CSS = """
    BookmarkForm { align: center middle; }
    #form { width: 70; height: auto; padding: 1 2; border: thick $primary; background: $surface; }
    #buttons { height: auto; margin-top: 1; }
    #buttons Button { margin-right: 2; }
    """
    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, heading: str, values: dict | None = None):
        super().__init__()
        self.heading = heading
        self.values = values or {"title": "", "url": "", "tags": ""}

    def compose(self) -> ComposeResult:
        with Vertical(id="form"):
            yield Label(self.heading)
            yield Input(self.values["title"], placeholder="Title (optional)", id="bm-title")
            yield Input(self.values["url"], placeholder="URL", id="bm-url")
            yield Input(self.values["tags"], placeholder="tags, comma, separated", id="bm-tags")
            with Horizontal(id="buttons"):
                yield Button("Save", variant="primary", id="bm-save")
                yield Button("Cancel", id="bm-cancel")

    def on_mount(self) -> None:
        self.query_one("#bm-title", Input).focus()

    def submit(self) -> None:
        url = normalize_url(self.query_one("#bm-url", Input).value)
        if not url:
            self.query_one("#bm-url", Input).focus()
            self.notify("A URL is required", severity="warning")
            return
        title = self.query_one("#bm-title", Input).value.strip() or url
        tags = normalize_tags(self.query_one("#bm-tags", Input).value)
        self.dismiss({"title": title, "url": url, "tags": tags})

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        self.submit()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "bm-save":
            self.submit()
        else:
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)


class BookmarksApp(App):
    TITLE = "Bookmarks"
    CSS = """
    #search { margin: 0 1; }
    #bookmark-list { height: 1fr; border: round $primary; }
    """
    BINDINGS = [
        Binding("a", "add", "Add"),
        Binding("e", "edit", "Edit"),
        Binding("d", "delete", "Delete"),
    ]

    def __init__(self, db_path="bookmarks.db"):
        super().__init__()
        self.db = sqlite3.connect(Path(db_path))
        self.db.execute(SCHEMA)
        self.db.commit()
        self.shown: list[tuple] = []

    def compose(self) -> ComposeResult:
        yield Header()
        yield Input(placeholder="search title, url or tag", id="search")
        yield ListView(id="bookmark-list")
        yield Footer()

    async def on_mount(self) -> None:
        await self.refresh_list()
        self.query_one("#bookmark-list", ListView).focus()

    def on_unmount(self) -> None:
        self.db.close()

    def rows(self) -> list[tuple]:
        rows = self.db.execute("SELECT id, title, url, tags FROM bookmarks").fetchall()
        q = self.query_one("#search", Input).value.strip().lower()
        if q:
            rows = [r for r in rows if any(q in (v or "").lower() for v in r[1:])]
        return sorted(rows, key=lambda r: ((r[1] or "").lower(), r[0]))

    async def refresh_list(self, keep_id: int | None = None) -> None:
        lv = self.query_one("#bookmark-list", ListView)
        old = lv.index
        self.shown = self.rows()
        await lv.clear()
        items = []
        for _id, title, url, tags in self.shown:
            line = Text(title or "")
            line.append(f"  {url}", style="dim")
            if tags:
                line.append(f"  [{tags}]", style="italic dim")
            items.append(ListItem(Label(line)))
        await lv.extend(items)
        if self.shown:
            ids = [r[0] for r in self.shown]
            lv.index = ids.index(keep_id) if keep_id in ids else min(old or 0, len(ids) - 1)

    async def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "search":
            await self.refresh_list()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "search":
            self.query_one("#bookmark-list", ListView).focus()

    def current(self) -> tuple | None:
        lv = self.query_one("#bookmark-list", ListView)
        if self.focused is not lv or lv.index is None or not (0 <= lv.index < len(self.shown)):
            return None
        return self.shown[lv.index]

    def action_add(self) -> None:
        if not isinstance(self.focused, ListView):
            return

        async def done(values: dict | None) -> None:
            if values:
                cur = self.db.execute("INSERT INTO bookmarks (title, url, tags) VALUES (?, ?, ?)",
                                      (values["title"], values["url"], values["tags"]))
                self.db.commit()
                await self.refresh_list(keep_id=cur.lastrowid)
            self.query_one("#bookmark-list", ListView).focus()

        self.push_screen(BookmarkForm("Add bookmark"), done)

    def action_edit(self) -> None:
        row = self.current()
        if row is None:
            return
        bid, title, url, tags = row

        async def done(values: dict | None) -> None:
            if values:
                self.db.execute("UPDATE bookmarks SET title = ?, url = ?, tags = ? WHERE id = ?",
                                (values["title"], values["url"], values["tags"], bid))
                self.db.commit()
                await self.refresh_list(keep_id=bid)
            self.query_one("#bookmark-list", ListView).focus()

        self.push_screen(BookmarkForm("Edit bookmark", {"title": title or "", "url": url or "",
                                                        "tags": tags or ""}), done)

    async def action_delete(self) -> None:
        row = self.current()
        if row is None:
            return
        self.db.execute("DELETE FROM bookmarks WHERE id = ?", (row[0],))
        self.db.commit()
        await self.refresh_list()


if __name__ == "__main__":
    BookmarksApp(sys.argv[1] if len(sys.argv) > 1 else "bookmarks.db").run()
