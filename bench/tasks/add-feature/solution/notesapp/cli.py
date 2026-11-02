"""Command line helpers: import/export notes as JSON.

    python -m notesapp.cli export --db notes.db backup.json
    python -m notesapp.cli import --db notes.db backup.json
    python -m notesapp.cli export-csv --db notes.db [--tag work] notes.csv
    python -m notesapp.cli serve --db notes.db --port 5000
"""

import argparse
import json
import sys

from . import csv_export, db, repository as repo


def cmd_export(args):
    conn = db.connect(args.db)
    db.init_db(conn)
    notes = repo.all_notes(conn)
    payload = {"version": 1, "notes": notes}
    if args.out == "-":
        json.dump(payload, sys.stdout, indent=2, ensure_ascii=False)
        sys.stdout.write("\n")
    else:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        print(f"exported {len(notes)} notes to {args.out}", file=sys.stderr)
    return 0


def cmd_export_csv(args):
    conn = db.connect(args.db)
    db.init_db(conn)
    notes = csv_export.notes_for_export(conn, args.tag)
    if args.out == "-":
        csv_export.write_csv(notes, sys.stdout)
    else:
        with open(args.out, "w", encoding="utf-8", newline="") as f:
            csv_export.write_csv(notes, f)
        print(f"exported {len(notes)} notes to {args.out}", file=sys.stderr)
    return 0


def cmd_import(args):
    with open(args.file, encoding="utf-8") as f:
        payload = json.load(f)
    notes = payload["notes"] if isinstance(payload, dict) else payload
    conn = db.connect(args.db)
    db.init_db(conn)
    count = 0
    for n in notes:
        if not n.get("title"):
            print(f"skipping note without title: {n!r}", file=sys.stderr)
            continue
        repo.create_note(conn, n["title"], n.get("body", ""), n.get("tags"), created_at=n.get("created_at"))
        count += 1
    print(f"imported {count} notes", file=sys.stderr)
    return 0


def cmd_serve(args):
    from . import create_app

    create_app(args.db).run(port=args.port, debug=args.debug)
    return 0


def build_parser():
    parser = argparse.ArgumentParser(prog="notesapp", description="notesapp utilities")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("export", help="export all notes to JSON")
    p.add_argument("--db", default="notes.db")
    p.add_argument("out", help="output file, or - for stdout")
    p.set_defaults(func=cmd_export)

    p = sub.add_parser("export-csv", help="export notes to CSV, optionally only one tag")
    p.add_argument("--db", default="notes.db")
    p.add_argument("--tag", default=None, help="only notes with this tag")
    p.add_argument("out", help="output file, or - for stdout")
    p.set_defaults(func=cmd_export_csv)

    p = sub.add_parser("import", help="import notes from a JSON export")
    p.add_argument("--db", default="notes.db")
    p.add_argument("file")
    p.set_defaults(func=cmd_import)

    p = sub.add_parser("serve", help="run the development server")
    p.add_argument("--db", default="notes.db")
    p.add_argument("--port", type=int, default=5000)
    p.add_argument("--debug", action="store_true")
    p.set_defaults(func=cmd_serve)

    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
