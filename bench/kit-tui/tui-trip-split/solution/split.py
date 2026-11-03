"""Split group-trip expenses evenly across tabs: people, expenses, balances."""

import json
import sys
from pathlib import Path

from textual.app import App, ComposeResult
from textual.containers import Horizontal
from textual.widgets import (Button, DataTable, Footer, Header, Input, Label, ListItem, ListView,
                             Select, Static, TabbedContent, TabPane)


def parse_amount(text: str) -> float | None:
    try:
        value = float(text.strip().replace(",", ""))
    except ValueError:
        return None
    return value if value > 0 else None


def balances(people: list[str], expenses: list[dict]) -> dict[str, float]:
    if not people:
        return {}
    total = sum(e["amount"] for e in expenses)
    share = total / len(people)
    paid = {p: 0.0 for p in people}
    for e in expenses:
        if e["payer"] in paid:
            paid[e["payer"]] += e["amount"]
    return {p: round(paid[p] - share, 2) for p in people}


def settle(bal: dict[str, float]) -> list[tuple[str, str, float]]:
    """Greedy: largest debtor pays largest creditor."""
    debtors = sorted(((-v, p) for p, v in bal.items() if v < -0.005), reverse=True)
    creditors = sorted(((v, p) for p, v in bal.items() if v > 0.005), reverse=True)
    out = []
    d = [list(x) for x in debtors]
    c = [list(x) for x in creditors]
    i = j = 0
    while i < len(d) and j < len(c):
        amount = round(min(d[i][0], c[j][0]), 2)
        if amount > 0:
            out.append((d[i][1], c[j][1], amount))
        d[i][0] -= amount
        c[j][0] -= amount
        if d[i][0] < 0.005:
            i += 1
        if c[j][0] < 0.005:
            j += 1
    return out


class SplitApp(App):
    TITLE = "Trip split"
    CSS = """
    Input { margin: 0 1; }
    #people-list, #expense-list { height: 1fr; border: round $primary; }
    #expense-form { height: auto; }
    #expense-form Input { width: 1fr; }
    #expense-payer { width: 24; }
    #balance-table { height: auto; max-height: 60%; }
    #settle { padding: 1 1; }
    """

    def __init__(self, data_path="trip.json"):
        super().__init__()
        self.path = Path(data_path)
        try:
            data = json.loads(self.path.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            data = {}
        self.people: list[str] = [str(p) for p in data.get("people", [])]
        self.expenses: list[dict] = [
            {"description": str(e["description"]), "amount": float(e["amount"]), "payer": str(e["payer"])}
            for e in data.get("expenses", [])
        ]

    def save(self) -> None:
        self.path.write_text(json.dumps({"people": self.people, "expenses": self.expenses}, indent=2))

    def compose(self) -> ComposeResult:
        yield Header()
        with TabbedContent(id="tabs"):
            with TabPane("People", id="people"):
                yield Input(placeholder="Name, then enter", id="person-name")
                yield ListView(id="people-list")
            with TabPane("Expenses", id="expenses"):
                with Horizontal(id="expense-form"):
                    yield Input(placeholder="What", id="expense-desc")
                    yield Input(placeholder="Amount", id="expense-amount")
                    yield Select([], prompt="Paid by", id="expense-payer")
                    yield Button("Add", variant="primary", id="add-expense")
                yield ListView(id="expense-list")
            with TabPane("Balances", id="balances"):
                yield DataTable(id="balance-table", cursor_type="row")
                yield Label("Settle up:")
                yield Static(id="settle")
        yield Footer()

    async def on_mount(self) -> None:
        table = self.query_one("#balance-table", DataTable)
        table.add_columns("Person", "Paid", "Share", "Balance")
        await self.refresh_people()
        await self.refresh_expenses()
        self.refresh_balances()
        self.query_one("#person-name", Input).focus()

    async def refresh_people(self) -> None:
        lv = self.query_one("#people-list", ListView)
        await lv.clear()
        await lv.extend([ListItem(Label(p, markup=False)) for p in self.people])
        payer = self.query_one("#expense-payer", Select)
        current = payer.value
        payer.set_options([(p, p) for p in self.people])
        if current in self.people:
            payer.value = current

    async def refresh_expenses(self) -> None:
        lv = self.query_one("#expense-list", ListView)
        await lv.clear()
        await lv.extend([
            ListItem(Label(f"{e['description']}  {e['amount']:.2f}  (paid by {e['payer']})", markup=False))
            for e in self.expenses
        ])

    def refresh_balances(self) -> None:
        table = self.query_one("#balance-table", DataTable)
        table.clear()
        bal = balances(self.people, self.expenses)
        share = sum(e["amount"] for e in self.expenses) / len(self.people) if self.people else 0
        for p in self.people:
            paid = sum(e["amount"] for e in self.expenses if e["payer"] == p)
            table.add_row(p, f"{paid:.2f}", f"{share:.2f}", f"{bal[p]:+.2f}")
        lines = [f"{d} → {c}: {amt:.2f}" for d, c, amt in settle(bal)]
        self.query_one("#settle", Static).update("\n".join(lines) or "All square.")

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "person-name":
            name = event.value.strip()
            event.input.value = ""
            if not name or name.casefold() in {p.casefold() for p in self.people}:
                return
            self.people.append(name)
            self.save()
            await self.refresh_people()
            self.refresh_balances()
        elif event.input.id in ("expense-desc", "expense-amount"):
            await self.add_expense()

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "add-expense":
            await self.add_expense()

    async def add_expense(self) -> None:
        desc_w = self.query_one("#expense-desc", Input)
        amount_w = self.query_one("#expense-amount", Input)
        payer = self.query_one("#expense-payer", Select).value
        desc = desc_w.value.strip()
        amount = parse_amount(amount_w.value)
        if not desc or amount is None or payer not in self.people:
            self.notify("Need a description, a positive amount and who paid.", severity="warning")
            return
        self.expenses.append({"description": desc, "amount": amount, "payer": payer})
        self.save()
        desc_w.value = ""
        amount_w.value = ""
        await self.refresh_expenses()
        self.refresh_balances()


if __name__ == "__main__":
    SplitApp(sys.argv[1] if len(sys.argv) > 1 else "trip.json").run()
