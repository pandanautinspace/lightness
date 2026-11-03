import asyncio
import json
import re
from pathlib import Path

import pytest

from lightness.bench.testkit import import_from_workspace


@pytest.fixture
def data(tmp_path: Path) -> Path:
    return tmp_path / "trip.json"


def saved(path: Path) -> dict:
    return json.loads(path.read_text())


def text_of(widget) -> str:
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


def run(path: Path, scenario):
    mod = import_from_workspace("split")

    async def main():
        app = mod.SplitApp(path)
        async with app.run_test(size=(140, 45)) as pilot:
            await pilot.pause()
            result = await scenario(app, pilot)
            await pilot.pause()
            return result

    return asyncio.run(main())


async def settle(pilot):
    await pilot.pause()
    await pilot.pause()


async def tab(pilot, pane):
    # Drop focus first: if the focused widget sits in the old pane, Textual's TabbedContent
    # follows the focus back to that pane.
    pilot.app.screen.set_focus(None)
    await pilot.pause()
    pilot.app.query_one("#tabs").active = pane
    await settle(pilot)
    assert pilot.app.query_one("#tabs").active == pane


async def type_into(pilot, wid, text):
    inp = pilot.app.query_one(f"#{wid}")
    inp.focus()
    await pilot.pause()
    inp.value = ""
    await pilot.pause()
    if text:
        await pilot.press(*text)
    await pilot.pause()


async def add_people(pilot, *names):
    await tab(pilot, "people")
    for name in names:
        await type_into(pilot, "person-name", name)
        await pilot.press("enter")
        await settle(pilot)


async def add_expense(pilot, desc, amount, payer):
    await tab(pilot, "expenses")
    await type_into(pilot, "expense-desc", desc)
    await type_into(pilot, "expense-amount", amount)
    if payer is not None:
        pilot.app.query_one("#expense-payer").value = payer
        await settle(pilot)
    await pilot.click("#add-expense")
    await settle(pilot)


def list_texts(app, wid) -> list[str]:
    from textual.widgets import ListItem

    return [text_of(i) for i in app.query_one(f"#{wid}").query(ListItem)]


MONEY = re.compile(r"\d[\d,]*\.\d\d")


def balance_rows(app) -> dict[str, float]:
    table = app.query_one("#balance-table")
    out = {}
    for i in range(table.row_count):
        row = [str(c) for c in table.get_row_at(i)]
        found = MONEY.findall(row[-1])
        assert found, row
        value = float(found[0].replace(",", ""))
        out[row[0].strip()] = -value if ("-" in row[-1] or "−" in row[-1]) else value
    return out


async def balances(pilot) -> dict[str, float]:
    await tab(pilot, "balances")
    return balance_rows(pilot.app)


def test_tabs_and_widgets(data):
    async def scenario(app, pilot):
        from textual.widgets import Button, DataTable, Input, ListView, Select, TabbedContent

        assert isinstance(app.query_one("#tabs"), TabbedContent)
        expected = {"people": [("person-name", Input), ("people-list", ListView)],
                    "expenses": [("expense-desc", Input), ("expense-amount", Input),
                                 ("expense-payer", Select), ("add-expense", Button),
                                 ("expense-list", ListView)],
                    "balances": [("balance-table", DataTable)]}
        for pane, widgets in expected.items():
            await tab(pilot, pane)
            assert app.query_one("#tabs").active == pane
            for wid, kind in widgets:
                assert isinstance(app.query_one(f"#{wid}"), kind), wid

    run(data, scenario)


def test_add_people(data):
    async def scenario(app, pilot):
        await add_people(pilot, "Alice", "  Bob  ", "", "   ")
        texts = list_texts(app, "people-list")
        assert len(texts) == 2
        assert "Alice" in texts[0] and "Bob" in texts[1]
        assert app.query_one("#person-name").value == ""

    run(data, scenario)
    assert saved(data)["people"] == ["Alice", "Bob"]


def test_payer_select_follows_people(data):
    async def scenario(app, pilot):
        await add_people(pilot, "Alice")
        await tab(pilot, "expenses")
        app.query_one("#expense-payer").value = "Alice"
        await add_people(pilot, "Carol")
        await tab(pilot, "expenses")
        app.query_one("#expense-payer").value = "Carol"  # raises if Carol isn't an option
        await settle(pilot)
        assert app.query_one("#expense-payer").value == "Carol"

    run(data, scenario)


def test_add_expense(data):
    async def scenario(app, pilot):
        await add_people(pilot, "Alice", "Bob")
        await add_expense(pilot, "Groceries", "42.50", "Bob")
        texts = list_texts(app, "expense-list")
        assert len(texts) == 1
        assert "Groceries" in texts[0] and "42.5" in texts[0]
        assert app.query_one("#expense-desc").value == ""
        assert app.query_one("#expense-amount").value == ""

    run(data, scenario)
    exp = saved(data)["expenses"]
    assert len(exp) == 1
    assert exp[0]["description"] == "Groceries"
    assert exp[0]["payer"] == "Bob"
    assert float(exp[0]["amount"]) == pytest.approx(42.5)


@pytest.mark.parametrize("desc,amount", [("Taxi", "abc"), ("Taxi", "-5"), ("", "12")])
def test_invalid_expense_rejected(data, desc, amount):
    async def scenario(app, pilot):
        await add_people(pilot, "Alice", "Bob")
        await add_expense(pilot, desc, amount, "Alice")
        assert list_texts(app, "expense-list") == []

    run(data, scenario)
    assert not data.exists() or saved(data)["expenses"] == []


def test_balances_two_way(data):
    async def scenario(app, pilot):
        await add_people(pilot, "Alice", "Bob", "Carol")
        await add_expense(pilot, "Cabin", "300", "Alice")
        await add_expense(pilot, "Fuel", "60", "Bob")
        return await balances(pilot)

    bal = run(data, scenario)
    assert bal == {"Alice": pytest.approx(180.0), "Bob": pytest.approx(-60.0), "Carol": pytest.approx(-120.0)}


def test_balances_update_after_more_expenses(data):
    async def scenario(app, pilot):
        await add_people(pilot, "Alice", "Bob")
        await add_expense(pilot, "Lunch", "20", "Alice")
        first = await balances(pilot)
        await add_expense(pilot, "Dinner", "50", "Bob")
        second = await balances(pilot)
        return first, second

    first, second = run(data, scenario)
    assert first == {"Alice": pytest.approx(10.0), "Bob": pytest.approx(-10.0)}
    assert second == {"Alice": pytest.approx(-15.0), "Bob": pytest.approx(15.0)}


def test_loads_existing_trip(data):
    data.write_text(json.dumps({
        "people": ["Ann", "Ben"],
        "expenses": [{"description": "Tickets", "amount": 80, "payer": "Ann"},
                     {"description": "Snacks", "amount": 10.5, "payer": "Ben"}],
    }))

    async def scenario(app, pilot):
        await tab(pilot, "people")
        assert len(list_texts(app, "people-list")) == 2
        await tab(pilot, "expenses")
        texts = list_texts(app, "expense-list")
        assert len(texts) == 2 and "Tickets" in texts[0] and "Snacks" in texts[1]
        return await balances(pilot)

    assert run(data, scenario) == {"Ann": pytest.approx(34.75), "Ben": pytest.approx(-34.75)}


def test_survives_restart(data):
    async def first(app, pilot):
        await add_people(pilot, "Alice", "Bob")
        await add_expense(pilot, "Boat", "90", "Bob")

    run(data, first)

    async def second(app, pilot):
        await tab(pilot, "expenses")
        assert len(list_texts(app, "expense-list")) == 1
        return await balances(pilot)

    assert run(data, second) == {"Alice": pytest.approx(-45.0), "Bob": pytest.approx(45.0)}


def test_intent_later_people_share_earlier_expenses(data):
    async def scenario(app, pilot):
        await add_people(pilot, "Alice", "Bob")
        await add_expense(pilot, "Cabin", "30", "Alice")
        await add_people(pilot, "Carol")
        return await balances(pilot)

    assert run(data, scenario) == {"Alice": pytest.approx(20.0), "Bob": pytest.approx(-10.0),
                                   "Carol": pytest.approx(-10.0)}


def test_intent_duplicate_names_ignored(data):
    async def scenario(app, pilot):
        await add_people(pilot, "Alice", "Bob", "alice", "ALICE ")
        assert len(list_texts(app, "people-list")) == 2

    run(data, scenario)
    assert saved(data)["people"] == ["Alice", "Bob"]


def test_intent_settle_up_suggestions(data):
    async def scenario(app, pilot):
        await add_people(pilot, "Alice", "Bob", "Carol")
        await add_expense(pilot, "Cabin", "300", "Alice")
        await add_expense(pilot, "Fuel", "60", "Bob")
        from textual.widgets import DataTable

        await tab(pilot, "balances")
        lines = []
        for w in app.query_one("#balances").query("*"):
            if isinstance(w, DataTable) and w.id != "balance-table":
                lines += [" ".join(str(c) for c in w.get_row_at(i)) for i in range(w.row_count)]
            if isinstance(w, DataTable) or any(isinstance(a, DataTable) for a in w.ancestors):
                continue
            try:
                lines += str(w.render()).splitlines()
            except Exception:
                pass
        return lines

    lines = run(data, scenario)

    def payment(debtor, creditor, amount):
        for line in lines:
            if debtor in line and creditor in line and amount in line and line.index(debtor) < line.index(creditor):
                return True
        return False

    assert payment("Carol", "Alice", "120.00"), lines
    assert payment("Bob", "Alice", "60.00"), lines
