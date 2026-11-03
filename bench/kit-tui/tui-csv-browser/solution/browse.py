"""Browse a CSV file as a sortable, filterable table."""

import csv
import sys
from pathlib import Path

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import DataTable, Footer, Header, Input, Static


def as_number(text: str):
    try:
        return float(text.replace(",", ""))
    except ValueError:
        return None


class BrowserApp(App):
    CSS = """
    #filter { margin: 0 1; }
    #table { height: 1fr; }
    #count { padding: 0 1; color: $text-muted; }
    """
    BINDINGS = [Binding("s", "sort", "Sort by column")]

    def __init__(self, csv_path):
        super().__init__()
        self.path = Path(csv_path)
        with self.path.open(newline="", encoding="utf-8") as f:
            rows = list(csv.reader(f))
        self.header = rows[0] if rows else []
        width = len(self.header)
        self.records = [(r + [""] * width)[:width] for r in rows[1:] if any(cell.strip() for cell in r)]
        self.sort_col: int | None = None
        self.sort_desc = False
        self.title = self.path.name

    def compose(self) -> ComposeResult:
        yield Header()
        yield Input(placeholder="filter (text, or column:text)", id="filter")
        yield DataTable(id="table", zebra_stripes=True)
        yield Static(id="count")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#table", DataTable)
        table.cursor_type = "cell"
        for name in self.header:
            table.add_column(name, key=name)
        self.refresh_rows()
        table.focus()

    def numeric(self, col: int) -> bool:
        values = [r[col].strip() for r in self.records if r[col].strip()]
        return bool(values) and all(as_number(v) is not None for v in values)

    def matches(self, record: list[str], query: str) -> bool:
        if not query:
            return True
        name, sep, text = query.partition(":")
        if sep:
            lower = [h.strip().lower() for h in self.header]
            if name.strip().lower() in lower:
                col = lower.index(name.strip().lower())
                return text.strip().lower() in record[col].lower()
        q = query.lower()
        return any(q in cell.lower() for cell in record)

    def visible(self) -> list[list[str]]:
        query = self.query_one("#filter", Input).value.strip()
        rows = [r for r in self.records if self.matches(r, query)]
        if self.sort_col is not None:
            col = self.sort_col
            numeric = self.numeric(col)
            filled = [r for r in rows if r[col].strip()]
            empty = [r for r in rows if not r[col].strip()]
            key = (lambda r: as_number(r[col])) if numeric else (lambda r: r[col].lower())
            rows = sorted(filled, key=key, reverse=self.sort_desc) + empty
        return rows

    def refresh_rows(self) -> None:
        table = self.query_one("#table", DataTable)
        coord = table.cursor_coordinate
        table.clear()
        shown = self.visible()
        for r in shown:
            table.add_row(*r)
        if shown:
            table.cursor_coordinate = coord
        for i, name in enumerate(self.header):
            arrow = ""
            if i == self.sort_col:
                arrow = " ▼" if self.sort_desc else " ▲"
            table.columns[name].label = Text(name + arrow)
        table.refresh()
        self.query_one("#count", Static).update(f"{len(shown)} of {len(self.records)} rows")

    def on_input_changed(self, event: Input.Changed) -> None:
        self.refresh_rows()

    def action_sort(self) -> None:
        table = self.query_one("#table", DataTable)
        if self.focused is not table or not self.header:
            return
        col = table.cursor_column
        if self.sort_col == col:
            self.sort_desc = not self.sort_desc
        else:
            self.sort_col, self.sort_desc = col, False
        self.refresh_rows()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: python browse.py FILE.csv")
    BrowserApp(sys.argv[1]).run()
