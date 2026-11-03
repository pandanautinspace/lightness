What the user wants but did not write down (answer questions only from this):

- Slash dates are American: `04/03/2024` is April 3rd (MM/DD/YYYY). Dotted dates are German:
  `04.03.2024` is March 4th (DD.MM.YYYY). ISO dates (`2024-03-04`, `2024/03/04`) and dates with
  month names (`Mar 4, 2024`, `4 Mar 2024`, `04-Mar-2024`) also occur.
- Output rows are sorted by date, oldest first (keep input order for the same date).
- Amounts are always written with exactly two decimals (`2000.00`, `-4.50`).
- Amounts in parentheses are negative. In "€" amounts the comma is the decimal separator and
  "." groups thousands (`-1.250,00 €`); in "$" or bare amounts it's the other way round.
- Descriptions: trim leading/trailing spaces and collapse every internal run of spaces to a
  single space (`"  Payroll   ACME Corp "` becomes `"Payroll ACME Corp"`); keep the original
  case and accents.
- A duplicate is a row with the same date, description and amount after cleaning (so after the
  space collapsing above: `Corner  Store` and `Corner Store` on the same day with the same
  amount are duplicates); keep the first one.
- Rows whose date or amount can't be understood are skipped and counted, not a crash.
- Money in / money out in the summary: total of positive amounts and total of negative amounts.
