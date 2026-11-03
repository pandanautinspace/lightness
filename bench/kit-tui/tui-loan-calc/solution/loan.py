"""Live loan payment calculator."""

from textual.app import App, ComposeResult
from textual.containers import Vertical
from textual.widgets import Footer, Header, Input, Label, Static


def parse_money(text: str) -> float | None:
    cleaned = text.strip().replace(",", "").replace("$", "").replace(" ", "").replace("_", "")
    try:
        return float(cleaned)
    except ValueError:
        return None


def monthly_payment(principal: float, rate_pct: float, years: int) -> float:
    n = years * 12
    r = rate_pct / 1200
    if r == 0:
        return principal / n
    return principal * r / (1 - (1 + r) ** -n)


class LoanApp(App):
    TITLE = "Loan calculator"
    CSS = """
    Vertical { padding: 1 2; height: auto; }
    Input { margin-bottom: 1; }
    Input.-invalid { border: tall $error; }
    .result { text-style: bold; margin-top: 1; }
    """

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical():
            yield Label("Amount borrowed")
            yield Input(placeholder="e.g. 250,000", id="principal")
            yield Label("Annual interest rate (%)")
            yield Input(placeholder="e.g. 4.5", id="rate")
            yield Label("Term (years)")
            yield Input(placeholder="e.g. 30", id="years")
            yield Static("Monthly payment:", classes="label")
            yield Static("—", id="payment", classes="result")
            yield Static("Total interest:", classes="label")
            yield Static("—", id="total-interest", classes="result")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#principal", Input).focus()

    def read_inputs(self):
        values = {}
        ok = True
        for name in ("principal", "rate", "years"):
            inp = self.query_one(f"#{name}", Input)
            text = inp.value.strip()
            value = parse_money(text) if text else None
            valid = value is not None
            if valid and name == "principal":
                valid = value > 0
            elif valid and name == "rate":
                valid = value >= 0
            elif valid and name == "years":
                valid = value > 0 and float(value).is_integer()
            inp.set_class(bool(text) and not valid, "-invalid")
            ok = ok and valid
            values[name] = value
        return values if ok else None

    def on_input_changed(self, event: Input.Changed) -> None:
        self.recompute()

    def recompute(self) -> None:
        values = self.read_inputs()
        payment_w = self.query_one("#payment", Static)
        interest_w = self.query_one("#total-interest", Static)
        if values is None:
            payment_w.update("—")
            interest_w.update("—")
            return
        n = int(values["years"]) * 12
        pay = round(monthly_payment(values["principal"], values["rate"], int(values["years"])), 2)
        interest = max(pay * n - values["principal"], 0.0)
        payment_w.update(f"{pay:,.2f}")
        interest_w.update(f"{interest:,.2f}")


if __name__ == "__main__":
    LoanApp().run()
