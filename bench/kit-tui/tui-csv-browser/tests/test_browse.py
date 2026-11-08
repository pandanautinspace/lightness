import asyncio
import re
from pathlib import Path

import pytest

from lightness.bench.testkit import import_from_workspace

CSV = """name,team,score,joined
Carol,red,100,2022-01-09
Alice,red,9,2021-03-01
Eve,blue,3,2019-07-30
Bob,Blue,10,2020-11-15
Dave,green,25,
"""
FILE_ORDER = ["Carol", "Alice", "Eve", "Bob", "Dave"]

QUOTED = '''title,author,year
"Roadside Picnic","Strugatsky, Arkady",1972
"Hello, World",Someone,2001
Plain,Writer,1999
'''


@pytest.fixture
def csv_file(tmp_path: Path) -> Path:
    p = tmp_path / "people.csv"
    p.write_text(CSV, encoding="utf-8")
    return p


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
    browse = import_from_workspace("browse")

    async def main():
        app = browse.BrowserApp(path)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            result = await scenario(app, pilot)
            await pilot.pause()
            return result

    return asyncio.run(main())


def rows(app) -> list[list[str]]:
    table = app.query_one("#table")
    return [[str(c).strip() for c in table.get_row_at(i)] for i in range(table.row_count)]


def column(app, idx) -> list[str]:
    return [r[idx] for r in rows(app)]


def count_numbers(app) -> list[int]:
    return [int(n) for n in re.findall(r"\d+", text_of(app.query_one("#count")))]


async def set_filter(pilot, text):
    inp = pilot.app.query_one("#filter")
    inp.focus()
    await pilot.pause()
    inp.value = ""
    await pilot.pause()
    if text:
        await pilot.press(*text)
    await pilot.pause()


async def sort_by(pilot, col, times=1):
    table = pilot.app.query_one("#table")
    table.focus()
    await pilot.pause()
    for _ in range(20):  # bounded: a cursor that left/right don't move fails here, not by timeout
        if table.cursor_column == col:
            break
        await pilot.press("left" if table.cursor_column > col else "right")
    await pilot.pause()
    assert table.cursor_column == col, f"left/right did not move the table cursor to column {col}"
    for _ in range(times):
        await pilot.press("s")
        await pilot.pause()


def test_table_matches_file(csv_file):
    async def scenario(app, pilot):
        from textual.widgets import DataTable, Input

        table = app.query_one("#table")
        assert isinstance(table, DataTable)
        assert isinstance(app.query_one("#filter"), Input)
        labels = [str(c.label) for c in table.columns.values()]
        assert len(labels) == 4
        for want, got in zip(["name", "team", "score", "joined"], labels):
            assert want in got
        assert column(app, 0) == FILE_ORDER
        assert rows(app)[3] == ["Bob", "Blue", "10", "2020-11-15"]

    run(csv_file, scenario)


def test_quoted_fields(tmp_path):
    p = tmp_path / "books.csv"
    p.write_text(QUOTED, encoding="utf-8")

    async def scenario(app, pilot):
        assert rows(app) == [["Roadside Picnic", "Strugatsky, Arkady", "1972"],
                             ["Hello, World", "Someone", "2001"],
                             ["Plain", "Writer", "1999"]]
        assert count_numbers(app)[:2] == [3, 3]

    run(p, scenario)


def test_count_shows_shown_and_total(csv_file):
    async def scenario(app, pilot):
        assert count_numbers(app)[:2] == [5, 5]

    run(csv_file, scenario)


def test_filter_case_insensitive_and_count(csv_file):
    async def scenario(app, pilot):
        await set_filter(pilot, "BLUE")
        assert column(app, 0) == ["Eve", "Bob"]
        assert count_numbers(app)[:2] == [2, 5]
        await set_filter(pilot, "2021")
        assert column(app, 0) == ["Alice"]

    run(csv_file, scenario)


def test_clearing_filter_restores_file_order(csv_file):
    async def scenario(app, pilot):
        await set_filter(pilot, "red")
        assert column(app, 0) == ["Carol", "Alice"]
        app.query_one("#filter").focus()
        await pilot.pause()
        await pilot.press(*["backspace"] * 3)
        await pilot.pause()
        assert column(app, 0) == FILE_ORDER
        assert count_numbers(app)[:2] == [5, 5]

    run(csv_file, scenario)


def test_no_matches(csv_file):
    async def scenario(app, pilot):
        await set_filter(pilot, "zzz")
        assert rows(app) == []
        assert count_numbers(app)[:2] == [0, 5]

    run(csv_file, scenario)


def test_sort_text_column_then_reverse(csv_file):
    async def scenario(app, pilot):
        await sort_by(pilot, 0)
        assert column(app, 0) == ["Alice", "Bob", "Carol", "Dave", "Eve"]
        await sort_by(pilot, 0)
        assert column(app, 0) == ["Eve", "Dave", "Carol", "Bob", "Alice"]

    run(csv_file, scenario)


def test_sort_by_other_column(csv_file):
    async def scenario(app, pilot):
        await sort_by(pilot, 3)
        # where empty cells go isn't in the contract (test_intent_empty_cells_last asks for last): ignore them
        assert [c for c in column(app, 3) if c] == ["2019-07-30", "2020-11-15", "2021-03-01", "2022-01-09"]

    run(csv_file, scenario)


def test_sort_and_filter_combine(csv_file):
    async def scenario(app, pilot):
        await sort_by(pilot, 0, times=2)  # descending by name
        await set_filter(pilot, "r")      # red, red, green
        assert column(app, 0) == ["Dave", "Carol", "Alice"]

    run(csv_file, scenario)


def test_typing_s_in_filter_does_not_sort(csv_file):
    async def scenario(app, pilot):
        await set_filter(pilot, "s")
        assert app.query_one("#filter").value == "s"
        await pilot.press("backspace")
        await pilot.pause()
        assert column(app, 0) == FILE_ORDER

    run(csv_file, scenario)


def test_file_not_modified(csv_file):
    async def scenario(app, pilot):
        await sort_by(pilot, 2)
        await set_filter(pilot, "red")

    run(csv_file, scenario)
    assert csv_file.read_text(encoding="utf-8") == CSV


def test_intent_numeric_sort(csv_file):
    async def scenario(app, pilot):
        await sort_by(pilot, 2)
        assert column(app, 2) == ["3", "9", "10", "25", "100"]
        await sort_by(pilot, 2)
        assert column(app, 2) == ["100", "25", "10", "9", "3"]

    run(csv_file, scenario)


def test_intent_empty_cells_last(csv_file):
    async def scenario(app, pilot):
        await sort_by(pilot, 3)
        assert column(app, 3)[-1] == ""
        await sort_by(pilot, 3)
        assert column(app, 3)[-1] == ""
        assert column(app, 3)[0] == "2022-01-09"

    run(csv_file, scenario)


def test_intent_column_filter(csv_file):
    async def scenario(app, pilot):
        await set_filter(pilot, "name:e")
        assert column(app, 0) == ["Alice", "Eve", "Dave"]
        await set_filter(pilot, "TEAM:r")
        assert column(app, 0) == ["Carol", "Alice", "Dave"]
        await set_filter(pilot, "joined:2020")
        assert column(app, 0) == ["Bob"]

    run(csv_file, scenario)
