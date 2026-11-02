What the user wants but did not write down (answer questions only from this):

- One row per note, with a header row. Columns, in this order:
  `id, title, body, tags, created_at, updated_at`.
- Tags in a single column, joined with ";" (no spaces), alphabetical like the API returns them.
- Dates in ISO 8601, exactly as the app already stores them (e.g. `2024-05-01T12:00:00+00:00`).
- UTF-8, standard comma-separated CSV with normal quoting, so bodies with commas, quotes and
  newlines survive. No BOM needed.
- Tag matching is case-insensitive, like the existing `?tag=` filter.
- No tag, or an empty tag (`?tag=`), means export all notes.
- Rows ordered oldest first (by id), like the existing JSON export.
- The export contains every matching note, not just one page.
- Unknown tag: return the header row only (still 200), not an error.
- The API response should be `text/csv`; a download filename is nice but not required.
- CLI: OUT may be `-` for stdout, like the existing `export` command (nice to have).
- Updating the README with the new endpoint/command would be nice.
