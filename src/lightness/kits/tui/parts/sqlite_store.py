"""Part: keeping records in a sqlite file (no Textual code; use it from the app).

- One small class owns the database: schema on open, one method per operation, commit after
  each write. The app holds the store and reloads its rows after each change.
- Parameterized SQL only (`?` placeholders), never f-strings with values.
- row_factory = sqlite3.Row gives dict-like rows; convert to dicts before keeping them in app state.
- For a worker thread (see the `worker` part) open the connection with check_same_thread=False,
  or open a new connection in the thread.
"""

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS contacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    favourite INTEGER NOT NULL DEFAULT 0
)
"""


class Store:
    def __init__(self, path: str | Path) -> None:
        self.db = sqlite3.connect(str(path))
        self.db.row_factory = sqlite3.Row
        self.db.execute(SCHEMA)
        self.db.commit()

    def all(self) -> list[dict]:
        return [dict(r) for r in self.db.execute("SELECT id, name, favourite FROM contacts ORDER BY id")]

    def add(self, name: str) -> int:
        cur = self.db.execute("INSERT INTO contacts (name) VALUES (?)", (name,))
        self.db.commit()
        return cur.lastrowid

    def set_favourite(self, contact_id: int, favourite: bool) -> None:
        self.db.execute("UPDATE contacts SET favourite = ? WHERE id = ?", (int(favourite), contact_id))
        self.db.commit()

    def delete(self, contact_id: int) -> None:
        self.db.execute("DELETE FROM contacts WHERE id = ?", (contact_id,))
        self.db.commit()

    def close(self) -> None:
        self.db.close()


if __name__ == "__main__":
    store = Store(":memory:")
    store.set_favourite(store.add("Ada"), True)
    print(store.all())
