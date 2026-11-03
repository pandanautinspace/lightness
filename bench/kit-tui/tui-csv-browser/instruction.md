I have a bunch of CSV exports (my reading log, bank stuff, game stats) and I want to poke at
them in the terminal without firing up a spreadsheet. Make me a Textual app that opens a CSV as
a table, lets me sort by a column, and lets me type to narrow down the rows. There's a
`books.csv` in the folder to try it with.

## Contract

- `browse.py` defines `class BrowserApp(textual.app.App)` with `__init__(self, csv_path)`;
  `python browse.py FILE.csv` runs it. The CSV is UTF-8 with a header row; quoted fields (with
  commas inside) must work. The file is only read, never written.
- A `DataTable` with id `table` has one column per header field (in file order, the column label
  shows the header name) and one row per record, initially in file order. Each cell shows the
  field's text as it appears in the file. The table uses a cell (or column) cursor.
- An `Input` with id `filter`: as you type, the table shows only the rows where some field
  contains the text, case-insensitively. Empty filter = all rows.
- With the table focused, `s` sorts the shown rows by the column the cursor is in, ascending;
  pressing `s` again on the same column sorts descending. Sorting and filtering combine (changing
  the filter keeps the current sort).
- A widget with id `count` shows how many rows are shown and how many there are in total, as
  `<shown> of <total>` (e.g. `3 of 15 rows`).
