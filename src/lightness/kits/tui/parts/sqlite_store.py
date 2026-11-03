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
CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    done INTEGER NOT NULL DEFAULT 0
)
"""


class Store:
    def __init__(self, path: str | Path) -> None:
        self.db = sqlite3.connect(str(path))
        self.db.row_factory = sqlite3.Row
        self.db.execute(SCHEMA)
        self.db.commit()

    def all(self) -> list[dict]:
        return [dict(r) for r in self.db.execute("SELECT id, title, done FROM items ORDER BY id")]

    def add(self, title: str) -> int:
        cur = self.db.execute("INSERT INTO items (title) VALUES (?)", (title,))
        self.db.commit()
        return cur.lastrowid

    def set_done(self, item_id: int, done: bool) -> None:
        self.db.execute("UPDATE items SET done = ? WHERE id = ?", (int(done), item_id))
        self.db.commit()

    def delete(self, item_id: int) -> None:
        self.db.execute("DELETE FROM items WHERE id = ?", (item_id,))
        self.db.commit()

    def close(self) -> None:
        self.db.close()


if __name__ == "__main__":
    store = Store(":memory:")
    store.set_done(store.add("example"), True)
    print(store.all())
