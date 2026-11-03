"""Part: inputs with validation, live recompute, and a Select.

- Input(type="number"|"integer") restricts what can be typed; validators add rules and report
  through event.validation_result (None when the Input has no validators).
- Recompute on Input.Changed / Select.Changed; handle submit (enter) with Input.Submitted.
  Scope handlers to one widget with @on(Input.Changed, "#id").
- Select options are (label, value) pairs; the empty value is Select.NULL (not Select.BLANK).
- Show errors in the UI (a Static, or self.notify(..., severity="error")); never crash on bad input.
"""

from textual import on
from textual.app import App, ComposeResult
from textual.validation import Number
from textual.widgets import Input, Select, Static

RATES = {"km": 1.0, "mi": 1.609344}


class ConverterApp(App):
    def compose(self) -> ComposeResult:
        yield Input(placeholder="Distance", type="number", validators=[Number(minimum=0)], id="amount")
        yield Select([("kilometres", "km"), ("miles", "mi")], value="km", allow_blank=False, id="unit")
        yield Static("", id="result")
        yield Static("", id="error")

    @on(Input.Changed, "#amount")
    @on(Select.Changed, "#unit")
    def recompute(self) -> None:
        amount = self.query_one("#amount", Input)
        unit = self.query_one("#unit", Select).value
        result, error = self.query_one("#result", Static), self.query_one("#error", Static)
        if not amount.value:
            result.update("")
            error.update("")
            return
        validation = amount.validate(amount.value)
        if validation is not None and not validation.is_valid:
            result.update("")
            error.update("; ".join(validation.failure_descriptions))
            return
        metres = float(amount.value) * RATES[str(unit)] * 1000
        result.update(f"{metres:.0f} m")
        error.update("")


if __name__ == "__main__":
    ConverterApp().run()
