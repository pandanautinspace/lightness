"""Personal expense tracker: Flask + SQLite, JSON API and a server-rendered page."""

import argparse
import sqlite3
from datetime import date

from flask import Flask, abort, g, jsonify, redirect, render_template_string, request, url_for

CATEGORIES = ["Food", "Rent", "Transport", "Utilities", "Entertainment", "Health", "Other"]
FIELDS = ("amount", "category", "date", "description")

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Expenses</title>
<style>
  body { font-family: system-ui, sans-serif; max-width: 52rem; margin: 2rem auto; padding: 0 1rem; }
  form.add { display: flex; gap: .5rem; flex-wrap: wrap; align-items: end; margin-bottom: 1.5rem; }
  label { display: flex; flex-direction: column; font-size: .85rem; }
  table { border-collapse: collapse; width: 100%; }
  td, th { padding: .3rem .5rem; border-bottom: 1px solid #ddd; text-align: left; }
  td.num, th.num { text-align: right; }
  .error { color: #b00020; }
</style>
</head>
<body>
<h1>Expenses</h1>
{% if error %}<p class="error">{{ error }}</p>{% endif %}
<form class="add" method="post" action="/expenses">
  <label for="amount">Amount (€)<input id="amount" name="amount" type="number" step="0.01" min="0.01" required></label>
  <label for="category">Category
    <select id="category" name="category">{% for c in categories %}<option>{{ c }}</option>{% endfor %}</select>
  </label>
  <label for="date">Date<input id="date" name="date" type="date" value="{{ today }}" required></label>
  <label for="description">Description<input id="description" name="description" type="text"></label>
  <button type="submit">Add</button>
</form>

<form method="get" action="/">
  <label>Month<input name="month" type="month" value="{{ month }}"></label>
  <label>Category
    <select name="category"><option value="">All</option>
    {% for c in categories %}<option {% if c == category %}selected{% endif %}>{{ c }}</option>{% endfor %}
    </select>
  </label>
  <button type="submit">Filter</button>
</form>

<h2>{{ month }}</h2>
<table data-testid="expense-list">
  <tr><th>Date</th><th>Category</th><th>Description</th><th class="num">Amount</th><th></th></tr>
  {% for e in expenses %}
  <tr>
    <td>{{ e.date }}</td><td>{{ e.category }}</td><td>{{ e.description }}</td>
    <td class="num">€{{ "%.2f"|format(e.amount) }}</td>
    <td>
      <a href="/expenses/{{ e.id }}/edit">edit</a>
      <form method="post" action="/expenses/{{ e.id }}/delete" style="display:inline"><button>delete</button></form>
    </td>
  </tr>
  {% else %}
  <tr><td colspan="5">No expenses.</td></tr>
  {% endfor %}
</table>

<h2>Totals</h2>
<table data-testid="summary">
  {% for c, t in summary.by_category.items() %}<tr><td>{{ c }}</td><td class="num">€{{ "%.2f"|format(t) }}</td></tr>{% endfor %}
  <tr><th>Total</th><th class="num">€{{ "%.2f"|format(summary.total) }}</th></tr>
</table>
</body>
</html>"""

EDIT_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Edit expense</title></head>
<body style="font-family: system-ui, sans-serif; max-width: 40rem; margin: 2rem auto;">
<h1>Edit expense</h1>
<form method="post" action="/expenses/{{ e.id }}">
  <label>Amount (€) <input name="amount" type="number" step="0.01" value="{{ '%.2f'|format(e.amount) }}"></label><br>
  <label>Category <select name="category">{% for c in categories %}
    <option {% if c == e.category %}selected{% endif %}>{{ c }}</option>{% endfor %}</select></label><br>
  <label>Date <input name="date" type="date" value="{{ e.date }}"></label><br>
  <label>Description <input name="description" value="{{ e.description }}"></label><br>
  <button type="submit">Save</button> <a href="/">cancel</a>
</form>
</body></html>"""


class Invalid(ValueError):
    pass


def validate(data: dict, partial: bool = False) -> dict:
    """Return a clean dict of fields, raising Invalid on bad input."""
    out = {}
    for key in FIELDS:
        if key not in data or data[key] is None:
            if partial or key == "description":
                continue
            raise Invalid(f"{key} is required")
        value = data[key]
        if key == "amount":
            if isinstance(value, bool):
                raise Invalid("amount must be a number")
            try:
                cents = round(float(str(value).replace(",", ".").strip()) * 100)
            except ValueError:
                raise Invalid("amount must be a number") from None
            if cents <= 0:
                raise Invalid("amount must be greater than zero")
            out["amount_cents"] = cents
        elif key == "category":
            if value not in CATEGORIES:
                raise Invalid(f"category must be one of {', '.join(CATEGORIES)}")
            out["category"] = value
        elif key == "date":
            try:
                out["date"] = date.fromisoformat(str(value)).isoformat()
            except ValueError:
                raise Invalid("date must be YYYY-MM-DD") from None
            if len(str(value)) != 10:
                raise Invalid("date must be YYYY-MM-DD")
        else:
            out["description"] = str(value).strip()
    return out


def valid_month(month: str | None) -> str | None:
    if not month:
        return None
    try:
        date.fromisoformat(month + "-01")
    except ValueError:
        abort(400, "month must be YYYY-MM")
    return month


def create_app(db_path: str) -> Flask:
    app = Flask(__name__)

    def db() -> sqlite3.Connection:
        if "db" not in g:
            g.db = sqlite3.connect(db_path)
            g.db.row_factory = sqlite3.Row
        return g.db

    @app.teardown_appcontext
    def close(_exc):
        conn = g.pop("db", None)
        if conn is not None:
            conn.close()

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS expenses (id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " amount_cents INTEGER NOT NULL, category TEXT NOT NULL, date TEXT NOT NULL,"
            " description TEXT NOT NULL DEFAULT '')"
        )

    def to_json(row) -> dict:
        return {"id": row["id"], "amount": row["amount_cents"] / 100, "category": row["category"],
                "date": row["date"], "description": row["description"]}

    def query(month=None, category=None) -> list[dict]:
        sql, args = "SELECT * FROM expenses WHERE 1=1", []
        if month:
            sql += " AND substr(date, 1, 7) = ?"
            args.append(month)
        if category:
            sql += " AND category = ?"
            args.append(category)
        sql += " ORDER BY date DESC, id DESC"
        return [to_json(r) for r in db().execute(sql, args)]

    def get_one(eid: int) -> dict:
        row = db().execute("SELECT * FROM expenses WHERE id = ?", (eid,)).fetchone()
        if row is None:
            abort(404)
        return to_json(row)

    def insert(clean: dict) -> dict:
        cur = db().execute(
            "INSERT INTO expenses (amount_cents, category, date, description) VALUES (?, ?, ?, ?)",
            (clean["amount_cents"], clean["category"], clean["date"], clean.get("description", "")),
        )
        db().commit()
        return get_one(cur.lastrowid)

    def update(eid: int, clean: dict) -> dict:
        get_one(eid)
        if clean:
            cols = ", ".join(f"{k} = ?" for k in clean)
            db().execute(f"UPDATE expenses SET {cols} WHERE id = ?", (*clean.values(), eid))
            db().commit()
        return get_one(eid)

    def summary(month: str) -> dict:
        rows = db().execute(
            "SELECT category, SUM(amount_cents) AS c FROM expenses WHERE substr(date, 1, 7) = ?"
            " GROUP BY category ORDER BY c DESC",
            (month,),
        ).fetchall()
        by_cat = {r["category"]: r["c"] / 100 for r in rows}
        return {"month": month, "total": sum(r["c"] for r in rows) / 100, "by_category": by_cat}

    @app.errorhandler(Invalid)
    def bad_input(e):
        if request.path.startswith("/api/"):
            return jsonify(error=str(e)), 400
        return page(error=str(e)), 400

    # ---- JSON API ----
    @app.get("/api/expenses")
    def api_list():
        return jsonify(query(valid_month(request.args.get("month")), request.args.get("category") or None))

    @app.post("/api/expenses")
    def api_create():
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            raise Invalid("expected a JSON object")
        return jsonify(insert(validate(data))), 201

    @app.get("/api/expenses/<int:eid>")
    def api_get(eid):
        return jsonify(get_one(eid))

    @app.put("/api/expenses/<int:eid>")
    def api_update(eid):
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            raise Invalid("expected a JSON object")
        get_one(eid)
        return jsonify(update(eid, validate(data, partial=True)))

    @app.delete("/api/expenses/<int:eid>")
    def api_delete(eid):
        get_one(eid)
        db().execute("DELETE FROM expenses WHERE id = ?", (eid,))
        db().commit()
        return "", 204

    @app.get("/api/categories")
    def api_categories():
        return jsonify(CATEGORIES)

    @app.get("/api/summary")
    def api_summary():
        return jsonify(summary(valid_month(request.args.get("month")) or date.today().strftime("%Y-%m")))

    # ---- HTML ----
    def page(error=None):
        month = valid_month(request.args.get("month")) or date.today().strftime("%Y-%m")
        category = request.args.get("category") or ""
        return render_template_string(
            PAGE, expenses=query(month, category or None), summary=summary(month), month=month,
            category=category, categories=CATEGORIES, today=date.today().isoformat(), error=error,
        )

    @app.get("/")
    def index():
        return page()

    @app.post("/expenses")
    def form_create():
        e = insert(validate(request.form.to_dict()))
        return redirect(url_for("index", month=e["date"][:7]))

    @app.get("/expenses/<int:eid>/edit")
    def form_edit(eid):
        return render_template_string(EDIT_PAGE, e=get_one(eid), categories=CATEGORIES)

    @app.post("/expenses/<int:eid>")
    def form_update(eid):
        e = update(eid, validate(request.form.to_dict()))
        return redirect(url_for("index", month=e["date"][:7]))

    @app.post("/expenses/<int:eid>/delete")
    def form_delete(eid):
        e = get_one(eid)
        db().execute("DELETE FROM expenses WHERE id = ?", (eid,))
        db().commit()
        return redirect(url_for("index", month=e["date"][:7]))

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default="expenses.db")
    parser.add_argument("--port", type=int, default=5000)
    args = parser.parse_args()
    create_app(args.db).run(host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
