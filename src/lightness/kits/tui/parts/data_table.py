"""Part: tabular records with a row cursor, sorting and selection.

- Add columns once (in on_mount), with keys. To refresh, clear() the rows (columns stay) and
  add them again; clear(columns=True) also removes the columns.
- Give rows a key (add_row(..., key=str(id))) and map the cursor back to your data with
  coordinate_to_cell_key(cursor_coordinate).row_key.value, not by row position after sorting.
- The cursor kind: cursor_type="row" highlights whole records and left/right do nothing (picking a
  record, e.g. enter to open it); "cell" (the default) moves over cells, so table.cursor_column says
  which column the user is on (sort by the cursor's column, act on one field). Use what the task asks.
  DataTable binds enter (-> RowSelected / CellSelected), arrows and page keys itself; App bindings on
  other printable keys still fire while it has focus.
- Sort your data and redraw (simplest), or use table.sort(column_key, reverse=...).
"""

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import DataTable, Static

ROWS = [
    {"id": 1, "name": "pear", "qty": 3},
    {"id": 2, "name": "apple", "qty": 10},
    {"id": 3, "name": "fig", "qty": 7},
]


class TableApp(App):
    BINDINGS = [Binding("s", "sort", "Sort by name"), Binding("q", "sort_qty", "Sort by qty")]

    def __init__(self) -> None:
        super().__init__()
        self.rows = list(ROWS)
        self.sort_key, self.reverse = "id", False

    def compose(self) -> ComposeResult:
        yield DataTable(id="table", cursor_type="row")
        yield Static("", id="detail")

    def on_mount(self) -> None:
        table = self.query_one("#table", DataTable)
        table.add_column("Name", key="name")
        table.add_column("Qty", key="qty")
        self.refresh_view()

    def refresh_view(self) -> None:
        table = self.query_one("#table", DataTable)
        table.clear()
        for row in sorted(self.rows, key=lambda r: r[self.sort_key], reverse=self.reverse):
            table.add_row(row["name"], row["qty"], key=str(row["id"]))

    def selected(self) -> dict | None:
        table = self.query_one("#table", DataTable)
        if table.row_count == 0:
            return None
        key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value
        return next(r for r in self.rows if str(r["id"]) == key)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        row = self.selected()
        self.query_one("#detail", Static).update(f"{row['name']}: {row['qty']}" if row else "")

    def action_sort(self) -> None:
        self.reverse = not self.reverse if self.sort_key == "name" else False
        self.sort_key = "name"
        self.refresh_view()

    def action_sort_qty(self) -> None:
        self.reverse = not self.reverse if self.sort_key == "qty" else False
        self.sort_key = "qty"
        self.refresh_view()


if __name__ == "__main__":
    TableApp().run()
