"""Airport code lookup with favourites."""

import csv
import json
import sys
import unicodedata
from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Footer, Header, Input, Label, ListItem, ListView, Static

MAX_RESULTS = 50


def fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).casefold()


class LookupApp(App):
    TITLE = "Airport lookup"
    CSS = """
    #query { margin: 0 1; }
    #results { height: 1fr; border: round $primary; }
    #detail { height: auto; padding: 0 1; border: round $secondary; }
    """
    BINDINGS = [Binding("f", "favorite", "Toggle favourite")]

    def __init__(self, data_path="airports.csv", favorites_path="favorites.json"):
        super().__init__()
        with Path(data_path).open(newline="", encoding="utf-8") as f:
            self.airports = [
                {k: (row.get(k) or "").strip() for k in ("code", "name", "city", "country")}
                for row in csv.DictReader(f)
            ]
        for a in self.airports:
            a["_folded"] = {k: fold(a[k]) for k in ("code", "name", "city", "country")}
        self.favorites_path = Path(favorites_path)
        try:
            self.favorites = [str(c) for c in json.loads(self.favorites_path.read_text())]
        except (FileNotFoundError, json.JSONDecodeError):
            self.favorites = []
        self.shown: list[dict] = []

    def compose(self) -> ComposeResult:
        yield Header()
        yield Input(placeholder="code, airport, city or country", id="query")
        yield ListView(id="results")
        yield Static(id="detail")
        yield Footer()

    async def on_mount(self) -> None:
        await self.refresh_results()
        self.query_one("#query", Input).focus()

    def search(self, query: str) -> list[dict]:
        q = fold(query.strip())
        if not q:
            return [a for a in self.airports if a["code"] in self.favorites]
        ranked = []
        for a in self.airports:
            f = a["_folded"]
            if not any(q in v for v in f.values()):
                continue
            if f["code"] == q:
                tier = 0
            elif f["name"].startswith(q) or f["city"].startswith(q):
                tier = 1
            else:
                tier = 2
            ranked.append((tier, a["code"], a))
        ranked.sort(key=lambda t: (t[0], t[1]))
        return [a for _, _, a in ranked[:MAX_RESULTS]]

    def item_text(self, a: dict) -> str:
        star = "★" if a["code"] in self.favorites else " "
        return f"{star} {a['code']}  {a['name']} — {a['city']}, {a['country']}"

    async def refresh_results(self, keep_index: bool = False) -> None:
        lv = self.query_one("#results", ListView)
        old = lv.index
        self.shown = self.search(self.query_one("#query", Input).value)
        await lv.clear()
        await lv.extend([ListItem(Label(self.item_text(a), markup=False)) for a in self.shown])
        if self.shown:
            lv.index = min(old or 0, len(self.shown) - 1) if keep_index else 0
        self.show_detail()

    def show_detail(self) -> None:
        lv = self.query_one("#results", ListView)
        detail = self.query_one("#detail", Static)
        if lv.index is None or not (0 <= lv.index < len(self.shown)):
            detail.update("")
            return
        a = self.shown[lv.index]
        detail.update(f"{a['code']}  {a['name']}\n{a['city']}, {a['country']}")

    async def on_input_changed(self, event: Input.Changed) -> None:
        await self.refresh_results()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if self.shown:
            self.query_one("#results", ListView).focus()

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        self.show_detail()

    async def action_favorite(self) -> None:
        lv = self.query_one("#results", ListView)
        if self.focused is not lv or lv.index is None or not (0 <= lv.index < len(self.shown)):
            return
        code = self.shown[lv.index]["code"]
        if code in self.favorites:
            self.favorites.remove(code)
        else:
            self.favorites.append(code)
        self.favorites_path.write_text(json.dumps(self.favorites, indent=2))
        await self.refresh_results(keep_index=True)
        lv.focus()


if __name__ == "__main__":
    args = sys.argv[1:]
    LookupApp(*(args[:2] if args else [])).run()
