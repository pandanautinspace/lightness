# notesapp

A small personal notes API I use from a couple of scripts and a phone shortcut.
Flask + SQLite, no ORM, no auth (it only listens on localhost).

## Setup

```sh
python -m venv .venv && . .venv/bin/activate
pip install flask pytest
python -m notesapp.cli serve --db notes.db      # http://127.0.0.1:5000
```

## API

All endpoints live under `/api` and speak JSON.

| Method | Path | Notes |
|---|---|---|
| GET | `/api/notes` | newest first; `?page=`, `?per_page=` (max 100), `?tag=`, `?q=` |
| POST | `/api/notes` | `{"title": ..., "body": ..., "tags": [...]}` |
| GET | `/api/notes/<id>` | |
| PUT/PATCH | `/api/notes/<id>` | any of title / body / tags |
| DELETE | `/api/notes/<id>` | |
| GET | `/api/tags` | tags with note counts |
| GET | `/api/search?q=` | substring search over title and body, paginated |

List responses look like:

```json
{"items": [...], "page": 1, "per_page": 20, "total": 42, "pages": 3, "has_next": true}
```

Tags are case-insensitive and stored lowercase.

## CLI

```sh
python -m notesapp.cli export --db notes.db backup.json   # or - for stdout
python -m notesapp.cli import --db notes.db backup.json
```

## Tests

```sh
pytest
```
