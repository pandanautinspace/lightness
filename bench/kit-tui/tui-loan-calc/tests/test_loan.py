import asyncio
import re

import pytest

from lightness.bench.testkit import import_from_workspace

MONEY = re.compile(r"\d[\d,]*(?:\.\d+)?")


def text_of(widget) -> str:
    """All visible text of a widget and its descendants (loose)."""
    parts = []
    for node in [widget, *widget.query("*")]:
        value = getattr(node, "value", None)
        if isinstance(value, str):
            parts.append(value)
        try:
            parts.append(str(node.render()))
        except Exception:
            pass
    return " ".join(parts)


def numbers(widget) -> list[float]:
    return [float(m.replace(",", "")) for m in MONEY.findall(text_of(widget)) if any(c.isdigit() for c in m)]


def has_digits(widget) -> bool:
    return any(c.isdigit() for c in text_of(widget))


def run(scenario):
    loan = import_from_workspace("loan")

    async def main():
        app = loan.LoanApp()
        async with app.run_test(size=(100, 40)) as pilot:
            await pilot.pause()
            result = await scenario(app, pilot)
            await pilot.pause()
            return result

    return asyncio.run(main())


async def type_into(pilot, widget_id: str, text: str):
    inp = pilot.app.query_one(f"#{widget_id}")
    inp.focus()
    await pilot.pause()
    inp.value = ""
    await pilot.pause()
    if text:
        await pilot.press(*text)
    await pilot.pause()


async def fill(pilot, principal, rate, years):
    await type_into(pilot, "principal", principal)
    await type_into(pilot, "rate", rate)
    await type_into(pilot, "years", years)


def payment(app):
    return numbers(app.query_one("#payment"))


def interest(app):
    return numbers(app.query_one("#total-interest"))


def close(values, expected, tol=0.011):
    return any(abs(v - expected) <= tol for v in values)


def test_widgets_exist_and_start_empty():
    async def scenario(app, pilot):
        from textual.widgets import Input

        for wid in ("principal", "rate", "years"):
            w = app.query_one(f"#{wid}")
            assert isinstance(w, Input)
            assert w.value == ""
        assert not has_digits(app.query_one("#payment"))
        assert not has_digits(app.query_one("#total-interest"))

    run(scenario)


def test_basic_mortgage():
    async def scenario(app, pilot):
        await fill(pilot, "200000", "6.5", "30")
        assert close(payment(app), 1264.14), text_of(app.query_one("#payment"))
        assert close(interest(app), 255089.7, tol=2.0), text_of(app.query_one("#total-interest"))

    run(scenario)


def test_small_loan():
    async def scenario(app, pilot):
        await fill(pilot, "1000", "12", "1")
        assert close(payment(app), 88.85)
        assert close(interest(app), 66.2, tol=0.02)

    run(scenario)


def test_fractional_rate():
    async def scenario(app, pilot):
        await fill(pilot, "5000", "3", "5")
        assert close(payment(app), 89.84)
        await type_into(pilot, "principal", "250000")
        await type_into(pilot, "rate", "4.25")
        await type_into(pilot, "years", "30")
        assert close(payment(app), 1229.85)

    run(scenario)


def test_live_recompute_without_enter():
    async def scenario(app, pilot):
        await fill(pilot, "200000", "6.5", "30")
        assert close(payment(app), 1264.14)
        years = app.query_one("#years")
        years.focus()
        await pilot.pause()
        await pilot.press("backspace", "backspace", "1", "5")
        await pilot.pause()
        assert years.value == "15"
        assert close(payment(app), 1742.21)

    run(scenario)


def test_payment_shown_with_two_decimals():
    async def scenario(app, pilot):
        await fill(pilot, "12000", "6", "2")
        text = text_of(app.query_one("#payment"))
        assert re.search(r"\d\.\d\d(?!\d)", text), text

    run(scenario)


def test_incomplete_input_shows_no_number():
    async def scenario(app, pilot):
        await type_into(pilot, "principal", "200000")
        await type_into(pilot, "rate", "6.5")
        assert not has_digits(app.query_one("#payment"))
        assert not has_digits(app.query_one("#total-interest"))

    run(scenario)


def test_garbage_principal_then_fixed():
    async def scenario(app, pilot):
        await fill(pilot, "abc", "6.5", "30")
        assert not has_digits(app.query_one("#payment"))
        assert app.query_one("#principal").has_class("-invalid")
        assert not app.query_one("#rate").has_class("-invalid")
        await type_into(pilot, "principal", "200000")
        assert not app.query_one("#principal").has_class("-invalid")
        assert close(payment(app), 1264.14)

    run(scenario)


@pytest.mark.parametrize("field,bad", [("principal", "-5000"), ("rate", "-1"), ("years", "2.5")])
def test_out_of_range_values_rejected(field, bad):
    good = {"principal": "5000", "rate": "3", "years": "5"}
    good[field] = bad

    async def scenario(app, pilot):
        await fill(pilot, good["principal"], good["rate"], good["years"])
        assert not has_digits(app.query_one("#payment")), text_of(app.query_one("#payment"))
        assert not has_digits(app.query_one("#total-interest"))
        assert app.query_one(f"#{field}").has_class("-invalid")

    run(scenario)


def test_intent_zero_rate_is_interest_free():
    async def scenario(app, pilot):
        await fill(pilot, "12000", "0", "2")
        assert close(payment(app), 500.0), text_of(app.query_one("#payment"))
        assert close(interest(app), 0.0), text_of(app.query_one("#total-interest"))
        assert not app.query_one("#rate").has_class("-invalid")

    run(scenario)


def test_intent_accepts_separators_and_dollar_sign():
    async def scenario(app, pilot):
        await fill(pilot, "$200,000", "6.5", "30")
        assert not app.query_one("#principal").has_class("-invalid")
        assert close(payment(app), 1264.14), text_of(app.query_one("#payment"))

    run(scenario)


def test_intent_thousands_separators_in_output():
    async def scenario(app, pilot):
        await fill(pilot, "200000", "6.5", "30")
        assert "1,264.14" in text_of(app.query_one("#payment"))
        assert re.search(r"255,0\d\d\.\d\d", text_of(app.query_one("#total-interest")))

    run(scenario)
