"""New-feature tests: tag-based CSV export via the API route and the CLI."""

import csv
import io
from datetime import datetime

import pytest

from lightness.bench.testkit import run_cli

EXPORT = "/api/notes/export.csv"


def parse(text: str) -> list[list[str]]:
    return list(csv.reader(io.StringIO(text.lstrip("﻿"))))


def cells(rows) -> set[str]:
    return {c for row in rows for c in row}


def get_csv(client, query=""):
    resp = client.get(EXPORT + query)
    assert resp.status_code == 200, resp.data[:300]
    return resp, parse(resp.data.decode("utf-8"))


@pytest.fixture
def sample(make_note):
    return {
        "groceries": make_note("Groceries", "milk, eggs", ["home", "shopping"]),
        "standup": make_note("Standup", "talk about the release", ["work"]),
        "ideas": make_note("Side project", 'a "notes" app\nwith CSV, ünïcode – ok', ["ideas", "work"]),
        "plain": make_note("Untagged thought", "nothing"),
    }


def test_route_exports_only_notes_with_tag(client, sample):
    resp, rows = get_csv(client, "?tag=work")
    assert "csv" in resp.headers.get("Content-Type", "").lower()
    found = cells(rows)
    assert {"Standup", "Side project"} <= found
    assert not {"Groceries", "Untagged thought"} & found


def test_tag_filter_is_case_insensitive(client, sample):
    _, rows = get_csv(client, "?tag=WORK")
    assert {"Standup", "Side project"} <= cells(rows)
    assert "Groceries" not in cells(rows)


def test_route_without_tag_exports_every_note_not_just_a_page(client, make_note):
    titles = {f"bulk note {i}" for i in range(45)}
    for t in sorted(titles):
        make_note(t, tags=["bulk"] if t.endswith("7") else [])
    _, rows = get_csv(client)
    assert titles <= cells(rows)


def test_body_with_commas_quotes_newlines_and_unicode_survives(client, sample):
    _, rows = get_csv(client, "?tag=ideas")
    assert sample["ideas"]["body"] in cells(rows)


def test_unknown_tag_gives_no_notes(client, sample):
    _, rows = get_csv(client, "?tag=does-not-exist")
    assert not {"Groceries", "Standup", "Side project", "Untagged thought"} & cells(rows)


def test_cli_export_csv(client, sample, db_path, tmp_path):
    out = tmp_path / "work.csv"
    r = run_cli("-m", "notesapp.cli", "export-csv", "--db", str(db_path), "--tag", "work", str(out))
    assert r.returncode == 0, r.stderr
    found = cells(parse(out.read_text(encoding="utf-8")))
    assert {"Standup", "Side project"} <= found
    assert not {"Groceries", "Untagged thought"} & found

    out_all = tmp_path / "all.csv"
    r = run_cli("-m", "notesapp.cli", "export-csv", "--db", str(db_path), str(out_all))
    assert r.returncode == 0, r.stderr
    found = cells(parse(out_all.read_text(encoding="utf-8")))
    assert {"Groceries", "Standup", "Side project", "Untagged thought"} <= found
    assert sample["ideas"]["body"] in found


# --- intent-only details (column order, tag/date formats, empty tag) --------------------------

HEADER = ["id", "title", "body", "tags", "created_at", "updated_at"]


def test_intent_header_row_and_column_order(client, sample, db_path, tmp_path):
    _, rows = get_csv(client)
    assert [h.strip().lower() for h in rows[0]] == HEADER
    assert len(rows) == 1 + len(sample)

    out = tmp_path / "all.csv"
    r = run_cli("-m", "notesapp.cli", "export-csv", "--db", str(db_path), str(out))
    assert r.returncode == 0, r.stderr
    cli_rows = parse(out.read_text(encoding="utf-8"))
    assert [h.strip().lower() for h in cli_rows[0]] == HEADER
    assert len(cli_rows) == 1 + len(sample)


def test_intent_tags_joined_with_semicolon_and_iso_dates(client, sample):
    _, rows = get_csv(client)
    by_id = {row[0].strip(): row for row in rows[1:]}
    for note in sample.values():
        row = by_id[str(note["id"])]
        assert row[1] == note["title"]
        assert [t.strip() for t in row[3].split(";") if t.strip()] == sorted(note["tags"])
        for col, key in ((4, "created_at"), (5, "updated_at")):
            parsed = datetime.fromisoformat(row[col].strip().replace("Z", "+00:00"))
            assert parsed.replace(tzinfo=None) == datetime.fromisoformat(note[key]).replace(tzinfo=None)


def test_intent_empty_tag_means_all_notes_oldest_first(client, sample):
    _, rows = get_csv(client, "?tag=")
    ids = [int(row[0]) for row in rows[1:]]
    assert ids == sorted(n["id"] for n in sample.values())
