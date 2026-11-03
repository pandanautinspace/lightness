import asyncio
import csv
import json
import re
import shutil
from pathlib import Path

import pytest

from lightness.bench.testkit import import_from_workspace

FIXTURE = Path(__file__).parent / "fixtures" / "airports.csv"
with FIXTURE.open(encoding="utf-8") as _f:
    AIRPORTS = {row["code"]: row for row in csv.DictReader(_f)}


@pytest.fixture
def paths(tmp_path: Path):
    data = tmp_path / "airports.csv"
    shutil.copy(FIXTURE, data)
    return data, tmp_path / "favorites.json"


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


def run(paths, scenario):
    lookup = import_from_workspace("lookup")
    data, favs = paths

    async def main():
        app = lookup.LookupApp(data, favs)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            result = await scenario(app, pilot)
            await pilot.pause()
            return result

    return asyncio.run(main())


def items(app):
    from textual.widgets import ListItem

    return list(app.query_one("#results").query(ListItem))


def code_of(text: str) -> str | None:
    hits = [(m.start(), m.group()) for m in re.finditer(r"\b[A-Z]{3}\b", text) if m.group() in AIRPORTS]
    return min(hits)[1] if hits else None


def codes(app) -> list[str]:
    return [code_of(text_of(i)) for i in items(app)]


async def search(pilot, text):
    inp = pilot.app.query_one("#query")
    inp.focus()
    await pilot.pause()
    inp.value = ""
    await pilot.pause()
    if text:
        await pilot.press(*text)
    await pilot.pause()
    await pilot.pause()


async def highlight(pilot, code):
    lv = pilot.app.query_one("#results")
    lv.focus()
    await pilot.pause()
    lv.index = codes(pilot.app).index(code)
    await pilot.pause()
    await pilot.pause()


def starred(app) -> set[str]:
    return {code_of(text_of(i)) for i in items(app) if "★" in text_of(i)}


def test_widgets_exist(paths):
    async def scenario(app, pilot):
        from textual.widgets import Input, ListView

        assert isinstance(app.query_one("#query"), Input)
        assert isinstance(app.query_one("#results"), ListView)
        app.query_one("#detail")

    run(paths, scenario)


def test_search_by_city(paths):
    async def scenario(app, pilot):
        await search(pilot, "paris")
        assert sorted(codes(app)) == ["CDG", "ORY"]
        for item in items(app):
            text = text_of(item)
            assert AIRPORTS[code_of(text)]["name"] in text

    run(paths, scenario)


def test_search_case_insensitive_by_code(paths):
    async def scenario(app, pilot):
        await search(pilot, "jfk")
        assert codes(app) == ["JFK"]
        await search(pilot, "  JFK ")
        assert codes(app) == ["JFK"]

    run(paths, scenario)


def test_search_by_country_and_name(paths):
    async def scenario(app, pilot):
        await search(pilot, "Japan")
        assert sorted(codes(app)) == ["HND", "KIX", "NRT"]
        await search(pilot, "heathrow")
        assert codes(app) == ["LHR"]

    run(paths, scenario)


def test_no_matches(paths):
    async def scenario(app, pilot):
        await search(pilot, "qqqq")
        assert items(app) == []

    run(paths, scenario)


def test_at_most_50_results(tmp_path):
    data = tmp_path / "many.csv"
    rows = ["code,name,city,country"] + [f"{a}{b}X,Field {a}{b} Airport,Town{a}{b},Nowhere"
                                          for a in "ABCDEFGHIJ" for b in "ABCDEFGHIJ"]
    data.write_text("\n".join(rows) + "\n", encoding="utf-8")

    async def scenario(app, pilot):
        await search(pilot, "field")
        assert len(items(app)) == 50
        await search(pilot, "field ja")
        assert len(items(app)) == 1

    run((data, tmp_path / "f.json"), scenario)


def test_detail_follows_highlight(paths):
    async def scenario(app, pilot):
        await search(pilot, "milan")
        assert sorted(codes(app)) == ["LIN", "MXP"]
        for code in ("MXP", "LIN"):
            await highlight(pilot, code)
            detail = text_of(app.query_one("#detail"))
            a = AIRPORTS[code]
            for field in ("code", "name", "city", "country"):
                assert a[field] in detail, (field, detail)

    run(paths, scenario)


def test_toggle_favorite_persists(paths):
    data, favs = paths

    async def scenario(app, pilot):
        await search(pilot, "paris")
        assert starred(app) == set()
        await highlight(pilot, "CDG")
        await pilot.press("f")
        await pilot.pause()
        assert starred(app) == {"CDG"}
        assert json.loads(favs.read_text()) == ["CDG"]
        await highlight(pilot, "ORY")
        await pilot.press("f")
        await pilot.pause()
        assert sorted(json.loads(favs.read_text())) == ["CDG", "ORY"]
        await highlight(pilot, "CDG")
        await pilot.press("f")
        await pilot.pause()
        assert starred(app) == {"ORY"}

    run(paths, scenario)
    assert json.loads(favs.read_text()) == ["ORY"]


def test_favorites_loaded_on_start(paths):
    data, favs = paths
    favs.write_text(json.dumps(["ORY", "HND"]))

    async def scenario(app, pilot):
        await search(pilot, "paris")
        assert starred(app) == {"ORY"}
        await search(pilot, "tokyo")
        assert starred(app) == {"HND"}

    run(paths, scenario)


def test_typing_f_in_query_does_not_toggle(paths):
    data, favs = paths

    async def scenario(app, pilot):
        await search(pilot, "frankfurt")
        assert codes(app) == ["FRA"]
        assert starred(app) == set()

    run(paths, scenario)
    assert not favs.exists() or json.loads(favs.read_text()) == []


def test_data_file_untouched(paths):
    data, favs = paths

    async def scenario(app, pilot):
        await search(pilot, "oslo")
        await highlight(pilot, "OSL")
        await pilot.press("f")
        await pilot.pause()

    run(paths, scenario)
    assert data.read_bytes() == FIXTURE.read_bytes()


def test_intent_ranking(paths):
    async def scenario(app, pilot):
        await search(pilot, "lin")
        got = codes(app)
        # exact code, then name/city prefix, then other substring matches
        assert got[0] == "LIN", got
        assert got[1] == "LPI", got
        assert set(got[2:]) == {"BER", "DUB"}, got
        await search(pilot, "mad")
        assert codes(app) == ["MAD", "DOH"]  # exact code beats "Hamad"
        await search(pilot, "ca")
        got = codes(app)
        assert got[0] == "CPT", got  # "Cape Town" starts with "ca"
        assert set(got[1:]) == {"JNB", "ORD", "YUL", "YYZ"}, got

    run(paths, scenario)


def test_intent_accent_insensitive(paths):
    async def scenario(app, pilot):
        await search(pilot, "zurich")
        assert codes(app) == ["ZRH"]
        await search(pilot, "sao paulo")
        assert codes(app) == ["GRU"]
        await search(pilot, "reykjavik")
        assert codes(app) == ["KEF"]

    run(paths, scenario)


def test_intent_empty_query_shows_favorites(paths):
    data, favs = paths
    favs.write_text(json.dumps(["ZRH", "LHR"]))

    async def scenario(app, pilot):
        await search(pilot, "")
        assert sorted(codes(app)) == ["LHR", "ZRH"]
        await search(pilot, "x")
        await search(pilot, "")
        assert sorted(codes(app)) == ["LHR", "ZRH"]

    run(paths, scenario)
