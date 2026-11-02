I keep losing track of where my money goes each month. Build me a little expense tracker I can
run on my laptop and open in the browser: I want to jot down what I spent, fix or remove
mistakes, and see at a glance how much went to each kind of thing in a given month. Nothing
fancy, but it should be pleasant enough to actually use, and it mustn't forget my data or let
me save obvious garbage.

## Contract

- Flask + SQLite. `python app.py --db PATH --port N` serves on 127.0.0.1:N, storing everything
  in the SQLite file PATH (created if missing).
- An expense is JSON `{"id": int, "amount": number, "category": str, "date": "YYYY-MM-DD",
  "description": str}`.
- `GET /api/expenses` lists expenses; optional query filters `month=YYYY-MM` and `category=...`.
- `POST /api/expenses` (JSON body without `id`) creates one and returns it with status 201.
- `PUT /api/expenses/<id>` (JSON body with any subset of the fields) updates and returns it;
  `DELETE /api/expenses/<id>` removes it. Unknown ids give 404.
- Invalid input (missing/non-numeric amount, invalid date, missing category) gives a 4xx status
  and stores nothing.
- `GET /api/summary?month=YYYY-MM` returns `{"month": "YYYY-MM", "total": number,
  "by_category": {category: number}}`.
- `GET /` is the HTML page. It has a form that submits a normal form-encoded POST to `/expenses`
  with fields named `amount`, `category`, `date`, `description`, and an element with
  `data-testid="expense-list"` that shows the expenses.
