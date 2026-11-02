This repo is my little notes app. I'd like to get my notes out into a spreadsheet: a CSV export,
ideally just the notes with a given tag (e.g. everything tagged "work") so I can share them or
open them in Excel/Numbers. I want it both from the API (so I can hit it from the browser) and
from the command line next to the existing import/export commands. Please keep everything else
working as it does now.

## Contract

- API: `GET /api/notes/export.csv?tag=TAG` returns the notes as CSV; `tag` is optional.
- CLI: `python -m notesapp.cli export-csv --db PATH [--tag TAG] OUT` writes the CSV to the file OUT.
- Keep the existing API, CLI and `create_app(db_path)` factory working.
- Use only the Python standard library and Flask.
