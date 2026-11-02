"""CSV export of notes, shared by the API route and the CLI."""

import csv
import io

from . import repository as repo

COLUMNS = ["id", "title", "body", "tags", "created_at", "updated_at"]


def notes_for_export(conn, tag=None):
    """All notes (oldest first), optionally only those with `tag`. Empty tag means all."""
    notes = repo.all_notes(conn)
    tag = (tag or "").strip().lower()
    if tag:
        notes = [n for n in notes if tag in n["tags"]]
    return notes


def write_csv(notes, f):
    w = csv.writer(f)
    w.writerow(COLUMNS)
    for n in notes:
        w.writerow([n["id"], n["title"], n["body"], ";".join(n["tags"]), n["created_at"], n["updated_at"]])


def to_csv(notes):
    buf = io.StringIO()
    write_csv(notes, buf)
    return buf.getvalue()
