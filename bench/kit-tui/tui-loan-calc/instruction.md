Before I talk to the bank I want to play with loan numbers in my terminal. Make me a little
Textual calculator: I type how much I'd borrow, the interest rate and how many years, and it
tells me the monthly payment and how much interest I'd pay overall. It should update as I type
— no "calculate" button — and not fall over or show nonsense when I've typed something silly.

## Contract

- `loan.py` defines `class LoanApp(textual.app.App)` with `__init__(self)` (no arguments);
  `python loan.py` runs it.
- Three `Input`s: id `principal` (amount borrowed), id `rate` (annual interest rate in percent,
  e.g. `5` or `4.25`), id `years` (loan term, a positive whole number of years). They start empty.
- A widget with id `payment` shows the monthly payment of a fixed-rate loan with monthly
  compounding: `P * r / (1 - (1 + r) ** -n)` where `r = rate / 1200` and `n = years * 12`,
  rounded to cents (2 decimals). A widget with id `total-interest` shows the total interest over
  the loan, `payment * n - P`, also with 2 decimals.
- Both are recomputed live whenever any input changes (no button or enter needed).
- When any input is empty or invalid (not a number, principal ≤ 0, rate < 0, years not a
  positive whole number), `payment` and `total-interest` show no digits at all (e.g. a dash or a
  short hint), and each invalid non-empty `Input` has the CSS class `-invalid`.
