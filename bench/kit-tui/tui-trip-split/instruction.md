Every group trip ends with a spreadsheet nobody understands. I want a small Textual app instead:
one tab where I list who's on the trip, one where I log expenses (what, how much, who paid), and
one that shows where everybody stands at the end. Everything gets split evenly. Save it to a
file so I can keep adding stuff during the trip.

## Contract

- `split.py` defines `class SplitApp(textual.app.App)` with `__init__(self, data_path)`;
  `python split.py [PATH]` runs it (default `trip.json`).
- The JSON file at `data_path` holds
  `{"people": [name, ...], "expenses": [{"description": str, "amount": number, "payer": name}, ...]}`,
  saved after every change. A missing file means an empty trip.
- A `TabbedContent` with id `tabs` and three `TabPane`s with ids `people`, `expenses` and
  `balances`.
- People tab: an `Input` with id `person-name` — enter adds the (trimmed) name to the trip and
  clears the input; a blank (or all-spaces) name adds nothing, and enter clears the input then too. A `ListView` with id `people-list` has one item per
  person, showing the name.
- Expenses tab: `Input`s with ids `expense-desc` and `expense-amount`, a `Select` with id
  `expense-payer` whose option values are the names of the people currently on the trip (it must
  reflect people added on the People tab), and a `Button` with id `add-expense`. Pressing the
  button adds the expense if the description is non-empty, the amount is a positive number and a
  payer is chosen, and then clears the description and amount; otherwise it adds nothing. A
  `ListView` with id `expense-list` has one item per expense, showing its description and amount.
- Every expense is split equally between all people on the trip. Balances tab: a `DataTable`
  with id `balance-table`, one row per person; the first cell is the name and the last cell is
  that person's balance (what they paid minus their share) with 2 decimals — positive means
  they are owed money, negative means they owe.
