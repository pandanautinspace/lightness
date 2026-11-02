I download transaction exports from my US checking account and my German Girokonto, and
they're a mess: dates in every format imaginable, amounts like "$1,234.50", "(12.00)" or
"-12,00 €", rows that show up twice, random spaces, blank lines. I want a script that turns
an export into a clean CSV I can load into a spreadsheet, and tells me briefly what it did
(how many rows, what it dropped, money in vs. money out). There's an example export in
`sample_export.csv`.

## Contract

- `python clean.py INPUT.csv OUTPUT.csv` writes the cleaned file to OUTPUT.csv and prints a
  short summary. The input file must not be modified.
- `python clean.py INPUT.csv OUTPUT.csv --json` does the same but prints the summary as a JSON
  object with at least: `rows_written`, `duplicates_removed`, `skipped` (rows that could not be
  understood; all three are integers), `total_in` and `total_out` (sums of money in and money
  out, as numbers).
- OUTPUT.csv is comma-separated with exactly the header `date,description,amount`; dates as
  `YYYY-MM-DD`; amounts as plain numbers (`.` decimal point, no currency symbols or thousands
  separators, negative = money out).
- Input files are UTF-8 (possibly with a BOM), comma- or semicolon-separated, and have date,
  description and amount columns whose header names vary in case, spacing and order; other
  columns may appear and are dropped.
- Use only the Python standard library.
