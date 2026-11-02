"""Data access for notes and tags.

Everything here takes an open sqlite3 connection so it can be shared between
the web routes and the CLI.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone


def now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def normalize_tags(tags):
    """Lowercase, strip, de-duplicate. Accepts a list or a comma separated string."""
    if tags is None:
        return []
    if isinstance(tags, str):
        tags = tags.split(",")
    seen = []
    for t in tags:
        t = str(t).strip().lower()
        if t and t not in seen:
            seen.append(t)
    return seen


@dataclass
class Page:
    items: list
    page: int
    per_page: int
    total: int
    pages: int = field(init=False)

    def __post_init__(self):
        # number of pages, at least 1 so an empty list still has "page 1"
        self.pages = max(1, self.total // self.per_page)

    @property
    def has_next(self):
        return self.page < self.pages

    def to_dict(self):
        return {
            "items": self.items,
            "page": self.page,
            "per_page": self.per_page,
            "total": self.total,
            "pages": self.pages,
            "has_next": self.has_next,
        }


def _tags_for(conn, note_ids):
    if not note_ids:
        return {}
    marks = ",".join("?" * len(note_ids))
    rows = conn.execute(
        f"""SELECT nt.note_id, t.name FROM note_tags nt
            JOIN tags t ON t.id = nt.tag_id
            WHERE nt.note_id IN ({marks})
            ORDER BY t.name""",
        list(note_ids),
    ).fetchall()
    out = {nid: [] for nid in note_ids}
    for r in rows:
        out[r["note_id"]].append(r["name"])
    return out


def _row_to_note(row, tags):
    return {
        "id": row["id"],
        "title": row["title"],
        "body": row["body"],
        "tags": tags,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _set_tags(conn, note_id, tags):
    conn.execute("DELETE FROM note_tags WHERE note_id = ?", (note_id,))
    for name in tags:
        conn.execute("INSERT OR IGNORE INTO tags (name) VALUES (?)", (name,))
        tag_id = conn.execute("SELECT id FROM tags WHERE name = ?", (name,)).fetchone()["id"]
        conn.execute("INSERT INTO note_tags (note_id, tag_id) VALUES (?, ?)", (note_id, tag_id))


def create_note(conn, title, body="", tags=None, created_at=None):
    ts = created_at or now_iso()
    cur = conn.execute(
        "INSERT INTO notes (title, body, created_at, updated_at) VALUES (?, ?, ?, ?)",
        (title, body, ts, ts),
    )
    _set_tags(conn, cur.lastrowid, normalize_tags(tags))
    conn.commit()
    return get_note(conn, cur.lastrowid)


def get_note(conn, note_id):
    row = conn.execute("SELECT * FROM notes WHERE id = ?", (note_id,)).fetchone()
    if row is None:
        return None
    return _row_to_note(row, _tags_for(conn, [note_id])[note_id])


def update_note(conn, note_id, title=None, body=None, tags=None):
    existing = get_note(conn, note_id)
    if existing is None:
        return None
    conn.execute(
        "UPDATE notes SET title = ?, body = ?, updated_at = ? WHERE id = ?",
        (
            title if title is not None else existing["title"],
            body if body is not None else existing["body"],
            now_iso(),
            note_id,
        ),
    )
    if tags is not None:
        _set_tags(conn, note_id, normalize_tags(tags))
    conn.commit()
    return get_note(conn, note_id)


def delete_note(conn, note_id):
    cur = conn.execute("DELETE FROM notes WHERE id = ?", (note_id,))
    conn.commit()
    return cur.rowcount > 0


def _filters(tag=None, q=None):
    where, params = [], []
    if tag:
        where.append(
            "n.id IN (SELECT nt.note_id FROM note_tags nt JOIN tags t ON t.id = nt.tag_id WHERE t.name = ?)"
        )
        params.append(tag.strip().lower())
    if q:
        where.append("(n.title LIKE ? OR n.body LIKE ?)")
        like = f"%{q}%"
        params += [like, like]
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    return clause, params


def list_notes(conn, page=1, per_page=20, tag=None, q=None):
    """Newest first, paginated. `page` is 1-based."""
    clause, params = _filters(tag, q)
    total = conn.execute(f"SELECT COUNT(*) FROM notes n {clause}", params).fetchone()[0]

    pg = Page([], page, per_page, total)
    if pg.page > pg.pages:
        # asking past the end gives you the last page rather than an empty list
        pg.page = pg.pages
    offset = (pg.page - 1) * per_page

    rows = conn.execute(
        f"""SELECT n.* FROM notes n {clause}
            ORDER BY n.created_at DESC, n.id DESC
            LIMIT ? OFFSET ?""",
        params + [per_page, offset],
    ).fetchall()
    tags = _tags_for(conn, [r["id"] for r in rows])
    pg.items = [_row_to_note(r, tags[r["id"]]) for r in rows]
    return pg


def all_notes(conn):
    """Every note, oldest first. Used for export."""
    rows = conn.execute("SELECT * FROM notes ORDER BY id").fetchall()
    tags = _tags_for(conn, [r["id"] for r in rows])
    return [_row_to_note(r, tags[r["id"]]) for r in rows]


def tag_counts(conn):
    rows = conn.execute(
        """SELECT t.name, COUNT(nt.note_id) AS count FROM tags t
           JOIN note_tags nt ON nt.tag_id = t.id
           GROUP BY t.id ORDER BY count DESC, t.name"""
    ).fetchall()
    return [{"name": r["name"], "count": r["count"]} for r in rows]
