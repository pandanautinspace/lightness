import json

from notesapp import cli, db, repository as repo


def test_export_import_roundtrip(tmp_path):
    src = tmp_path / "src.db"
    conn = db.connect(src)
    db.init_db(conn)
    repo.create_note(conn, "One", "first", ["a"])
    repo.create_note(conn, "Two", "zweite Notiz – ünïcode", ["a", "b"])
    conn.close()

    out = tmp_path / "backup.json"
    assert cli.main(["export", "--db", str(src), str(out)]) == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert [n["title"] for n in payload["notes"]] == ["One", "Two"]

    dst = tmp_path / "dst.db"
    assert cli.main(["import", "--db", str(dst), str(out)]) == 0
    conn = db.connect(dst)
    notes = repo.all_notes(conn)
    assert [(n["title"], n["body"], n["tags"]) for n in notes] == [
        ("One", "first", ["a"]),
        ("Two", "zweite Notiz – ünïcode", ["a", "b"]),
    ]
    assert notes[0]["created_at"] == payload["notes"][0]["created_at"]


def test_import_skips_notes_without_title(tmp_path, capsys):
    f = tmp_path / "in.json"
    f.write_text(json.dumps([{"title": "ok"}, {"body": "no title"}]))
    dbfile = tmp_path / "n.db"
    assert cli.main(["import", "--db", str(dbfile), str(f)]) == 0
    conn = db.connect(dbfile)
    assert [n["title"] for n in repo.all_notes(conn)] == ["ok"]
