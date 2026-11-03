"""Part: reading an input file given on the command line, with clear errors.

- Load in on_mount (or __init__ for pure data), never at import time.
- A missing or malformed file is a normal case: show a message in the UI and start empty;
  don't crash. self.notify(..., severity="error", markup=False) for messages with user data
  (markup=True chokes on stray "[").
- CSV: open with encoding="utf-8-sig" (drops a BOM) and newline=""; csv.DictReader gives dicts.
"""

import csv
import json
from pathlib import Path

from textual.app import App, ComposeResult
from textual.widgets import DataTable, Static


def read_records(path: Path) -> list[dict]:
    """Rows from a .csv or .json file (a JSON list of objects). Raises ValueError with a readable message."""
    try:
        if path.suffix.lower() == ".csv":
            with path.open(encoding="utf-8-sig", newline="") as f:
                return list(csv.DictReader(f))
        data = json.loads(path.read_text())
    except FileNotFoundError:
        raise ValueError(f"{path} not found") from None
    except (json.JSONDecodeError, UnicodeDecodeError, csv.Error) as e:
        raise ValueError(f"could not read {path}: {e}") from None
    if not isinstance(data, list) or not all(isinstance(r, dict) for r in data):
        raise ValueError(f"{path} is not a list of records")
    return data


class LoaderApp(App):
    def __init__(self, path: str) -> None:
        super().__init__()
        self.path = Path(path)
        self.records: list[dict] = []

    def compose(self) -> ComposeResult:
        yield Static("", id="status")
        yield DataTable(id="records")

    def on_mount(self) -> None:
        try:
            self.records = read_records(self.path)
            status = f"{len(self.records)} records from {self.path.name}"
        except ValueError as e:
            self.records, status = [], str(e)
            self.notify(str(e), severity="error", markup=False)
        self.query_one("#status", Static).update(status)
        table = self.query_one("#records", DataTable)
        columns = list(self.records[0]) if self.records else []
        for name in columns:
            table.add_column(name, key=name)
        for i, record in enumerate(self.records):
            table.add_row(*(str(record.get(c, "")) for c in columns), key=str(i))


if __name__ == "__main__":
    import sys

    LoaderApp(sys.argv[1] if len(sys.argv) > 1 else "data.csv").run()
