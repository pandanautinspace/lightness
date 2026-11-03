import asyncio
import sqlite3
from pathlib import Path

import pytest

from lightness.bench.testkit import import_from_workspace


@pytest.fixture
def db(tmp_path: Path) -> Path:
    return tmp_path / "bookmarks.db"


def seed(path: Path, rows):
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE bookmarks (id INTEGER PRIMARY KEY, title TEXT, url TEXT, tags TEXT)")
    con.executemany("INSERT INTO bookmarks (title, url, tags) VALUES (?, ?, ?)", rows)
    con.commit()
    con.close()


def norm_tags(tags) -> str:
    return ",".join(t.strip() for t in (tags or "").split(",") if t.strip())


def stored(path: Path) -> set[tuple]:
    return set(stored_with_ids(path).values())


def stored_with_ids(path: Path) -> dict:
    con = sqlite3.connect(path)
    try:
        return {r[0]: (r[1], r[2], norm_tags(r[3]))
                for r in con.execute("SELECT id, title, url, tags FROM bookmarks")}
    finally:
        con.close()


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
    mod = import_from_workspace("bookmarks")

    async def main():
        app = mod.BookmarksApp(path)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            result = await scenario(app, pilot)
            await pilot.pause()
            return result

    return asyncio.run(main())


def items(app):
    from textual.widgets import ListItem

    return list(app.query_one("#bookmark-list").query(ListItem))


def shown_titles(app, titles) -> list[str]:
    out = []
    for item in items(app):
        text = text_of(item)
        hits = [t for t in titles if t in text]
        out.append(max(hits, key=len) if hits else text)
    return out


def has_modal(app) -> bool:
    from textual.screen import ModalScreen

    return isinstance(app.screen, ModalScreen)


async def settle(pilot):
    await pilot.pause()
    await pilot.pause()


async def focus_list(pilot, title=None, titles=()):
    lv = pilot.app.query_one("#bookmark-list")
    lv.focus()
    await settle(pilot)
    if title is not None:
        lv.index = shown_titles(pilot.app, list(titles) or [title]).index(title)
        await settle(pilot)


async def fill(pilot, title=None, url=None, tags=None):
    for wid, text in (("bm-title", title), ("bm-url", url), ("bm-tags", tags)):
        if text is None:
            continue
        inp = pilot.app.screen.query_one(f"#{wid}")
        inp.focus()
        await pilot.pause()
        inp.value = ""
        await pilot.pause()
        if text:
            await pilot.press(*text)
        await pilot.pause()


async def open_add(pilot):
    await focus_list(pilot)
    await pilot.press("a")
    await settle(pilot)
    assert has_modal(pilot.app)


async def search(pilot, text):
    inp = pilot.app.query_one("#search")
    inp.focus()
    await pilot.pause()
    inp.value = ""
    await pilot.pause()
    if text:
        await pilot.press(*text)
    await settle(pilot)


SEED = [("Python docs", "https://docs.python.org/3/", "python,docs"),
        ("Hacker News", "https://news.ycombinator.com/", "news"),
        ("Textual", "https://textual.textualize.io/", "python,tui")]
SEED_TITLES = [r[0] for r in SEED]


def test_creates_table_in_new_db(db):
    async def scenario(app, pilot):
        from textual.widgets import Input, ListView

        assert isinstance(app.query_one("#bookmark-list"), ListView)
        assert isinstance(app.query_one("#search"), Input)
        assert items(app) == []

    run(db, scenario)
    assert stored(db) == set()


def test_lists_existing_bookmarks(db):
    seed(db, SEED)

    async def scenario(app, pilot):
        assert sorted(shown_titles(app, SEED_TITLES)) == sorted(SEED_TITLES)

    run(db, scenario)


def test_add_with_save_button(db):
    async def scenario(app, pilot):
        from textual.widgets import Button, Input

        await open_add(pilot)
        for wid in ("bm-title", "bm-url", "bm-tags"):
            assert isinstance(app.screen.query_one(f"#{wid}"), Input)
        for wid in ("bm-save", "bm-cancel"):
            assert isinstance(app.screen.query_one(f"#{wid}"), Button)
        await fill(pilot, "Rust book", "https://doc.rust-lang.org/book/", "rust,reading")
        await pilot.click("#bm-save")
        await settle(pilot)
        assert not has_modal(app)
        assert shown_titles(app, ["Rust book"]) == ["Rust book"]

    run(db, scenario)
    assert stored(db) == {("Rust book", "https://doc.rust-lang.org/book/", "rust,reading")}


def test_add_with_enter_in_input(db):
    seed(db, SEED)

    async def scenario(app, pilot):
        await open_add(pilot)
        await fill(pilot, "Lobsters", "https://lobste.rs/", "")
        app.screen.query_one("#bm-url").focus()
        await pilot.pause()
        await pilot.press("enter")
        await settle(pilot)
        assert not has_modal(app)
        assert len(items(app)) == 4

    run(db, scenario)
    assert ("Lobsters", "https://lobste.rs/", "") in stored(db)
    assert len(stored(db)) == 4


def test_cancel_and_escape_store_nothing(db):
    seed(db, SEED)

    async def scenario(app, pilot):
        await open_add(pilot)
        await fill(pilot, "Nope", "https://nope.example/", "x")
        await pilot.click("#bm-cancel")
        await settle(pilot)
        assert not has_modal(app)
        await open_add(pilot)
        await fill(pilot, "Nope2", "https://nope2.example/", "")
        await pilot.press("escape")
        await settle(pilot)
        assert not has_modal(app)
        assert len(items(app)) == 3

    run(db, scenario)
    assert stored(db) == set(SEED)


def test_empty_url_keeps_dialog_open(db):
    async def scenario(app, pilot):
        await open_add(pilot)
        await fill(pilot, "No url here", "", "")
        await pilot.click("#bm-save")
        await settle(pilot)
        assert has_modal(app)
        await fill(pilot, url="https://finally.example/")
        await pilot.click("#bm-save")
        await settle(pilot)
        assert not has_modal(app)

    run(db, scenario)
    assert stored(db) == {("No url here", "https://finally.example/", "")}


def test_edit_prefills_and_updates_in_place(db):
    seed(db, SEED)
    before = stored_with_ids(db)

    async def scenario(app, pilot):
        await focus_list(pilot, "Hacker News", SEED_TITLES)
        await pilot.press("e")
        await settle(pilot)
        assert has_modal(app)
        assert app.screen.query_one("#bm-title").value == "Hacker News"
        assert app.screen.query_one("#bm-url").value == "https://news.ycombinator.com/"
        tags = app.screen.query_one("#bm-tags").value
        assert [t.strip() for t in tags.split(",")] == ["news"]
        await fill(pilot, title="HN", tags="news,daily")
        await pilot.click("#bm-save")
        await settle(pilot)
        assert not has_modal(app)

    run(db, scenario)
    after = stored_with_ids(db)
    assert set(after) == set(before)
    hn_id = next(i for i, r in before.items() if r[0] == "Hacker News")
    assert after[hn_id] == ("HN", "https://news.ycombinator.com/", "news,daily")


def test_delete_highlighted(db):
    seed(db, SEED)

    async def scenario(app, pilot):
        await focus_list(pilot, "Python docs", SEED_TITLES)
        await pilot.press("d")
        await settle(pilot)
        assert sorted(shown_titles(app, SEED_TITLES)) == ["Hacker News", "Textual"]

    run(db, scenario)
    assert stored(db) == set(SEED[1:])


def test_search_by_title_url_and_tag(db):
    seed(db, SEED)

    async def scenario(app, pilot):
        await search(pilot, "PYTHON")
        assert sorted(shown_titles(app, SEED_TITLES)) == ["Python docs", "Textual"]
        await search(pilot, "ycombinator")
        assert shown_titles(app, SEED_TITLES) == ["Hacker News"]
        await search(pilot, "tui")
        assert shown_titles(app, SEED_TITLES) == ["Textual"]
        await search(pilot, "")
        assert len(items(app)) == 3

    run(db, scenario)


def test_typing_in_search_does_not_trigger_keys(db):
    seed(db, SEED)

    async def scenario(app, pilot):
        await search(pilot, "a d e")
        assert not has_modal(app)

    run(db, scenario)
    assert stored(db) == set(SEED)


def test_survives_restart(db):
    async def first(app, pilot):
        for title, url in (("One", "https://one.example/"), ("Two", "https://two.example/")):
            await open_add(pilot)
            await fill(pilot, title, url, "t")
            await pilot.click("#bm-save")
            await settle(pilot)

    run(db, first)

    async def second(app, pilot):
        return sorted(shown_titles(app, ["One", "Two"]))

    assert run(db, second) == ["One", "Two"]


def test_intent_sorted_by_title(db):
    seed(db, [("zebra facts", "https://z.example/", ""), ("Apple", "https://a.example/", ""),
              ("mango", "https://m.example/", "")])

    async def scenario(app, pilot):
        titles = ["zebra facts", "Apple", "mango", "Banana"]
        assert shown_titles(app, titles) == ["Apple", "mango", "zebra facts"]
        await open_add(pilot)
        await fill(pilot, "Banana", "https://b.example/", "")
        await pilot.click("#bm-save")
        await settle(pilot)
        assert shown_titles(app, titles) == ["Apple", "Banana", "mango", "zebra facts"]

    run(db, scenario)


def test_intent_scheme_added(db):
    async def scenario(app, pilot):
        await open_add(pilot)
        await fill(pilot, "Example", "example.com/page", "")
        await pilot.click("#bm-save")
        await settle(pilot)
        await open_add(pilot)
        await fill(pilot, "Plain http", "http://old.example/", "")
        await pilot.click("#bm-save")
        await settle(pilot)

    run(db, scenario)
    assert stored(db) == {("Example", "https://example.com/page", ""),
                          ("Plain http", "http://old.example/", "")}


def test_intent_blank_title_uses_url(db):
    async def scenario(app, pilot):
        await open_add(pilot)
        await fill(pilot, "", "https://untitled.example/x", "")
        await pilot.click("#bm-save")
        await settle(pilot)
        assert "https://untitled.example/x" in text_of(items(app)[0])

    run(db, scenario)
    assert stored(db) == {("https://untitled.example/x", "https://untitled.example/x", "")}
