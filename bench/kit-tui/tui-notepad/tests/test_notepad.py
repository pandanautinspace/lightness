import asyncio
from pathlib import Path

import pytest

from lightness.bench.testkit import import_from_workspace


@pytest.fixture
def note(tmp_path: Path) -> Path:
    return tmp_path / "notes.txt"


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
    notepad = import_from_workspace("notepad")

    async def main():
        app = notepad.NotepadApp(path)
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            result = await scenario(app, pilot)
            await pilot.pause()
            return result

    return asyncio.run(main())


def editor(app):
    return app.query_one("#editor")


def is_modified(app) -> bool:
    return "modified" in text_of(app.query_one("#status")).lower()


async def type_text(pilot, text):
    editor(pilot.app).focus()
    await pilot.pause()
    await pilot.press(*text)
    await pilot.pause()


async def key(pilot, *keys):
    await pilot.press(*keys)
    await pilot.pause()
    await pilot.pause()


def has_modal(app) -> bool:
    from textual.screen import ModalScreen

    return isinstance(app.screen, ModalScreen)


def test_loads_existing_file(note):
    note.write_text("first line\nsecond line\n")

    async def scenario(app, pilot):
        from textual.widgets import TextArea

        assert isinstance(editor(app), TextArea)
        assert editor(app).text.rstrip("\n") == "first line\nsecond line"
        assert not is_modified(app)

    run(note, scenario)
    assert note.read_text() == "first line\nsecond line\n"


def test_missing_file_starts_empty_and_is_not_created(note):
    async def scenario(app, pilot):
        assert editor(app).text == ""
        assert not is_modified(app)

    run(note, scenario)
    assert not note.exists()


def test_typing_marks_modified(note):
    note.write_text("hello\n")

    async def scenario(app, pilot):
        await type_text(pilot, "oh ")
        assert editor(app).text.startswith("oh hello")
        assert is_modified(app)

    run(note, scenario)
    assert note.read_text() == "hello\n"


def test_ctrl_s_saves_and_clears_modified(note):
    note.write_text("hello\n")

    async def scenario(app, pilot):
        await type_text(pilot, "oh ")
        await key(pilot, "ctrl+s")
        assert not is_modified(app)
        await type_text(pilot, "x")
        assert is_modified(app)

    run(note, scenario)
    assert note.read_text().rstrip("\n") == "oh hello"


def test_save_creates_new_file(note):
    async def scenario(app, pilot):
        await type_text(pilot, "brand new")
        await key(pilot, "ctrl+s")

    run(note, scenario)
    assert note.read_text().rstrip("\n") == "brand new"


def test_unicode_round_trip(note):
    note.write_text("café ☕ — naïve\n", encoding="utf-8")

    async def scenario(app, pilot):
        assert "café ☕ — naïve" in editor(app).text
        await type_text(pilot, "ok ")
        await key(pilot, "ctrl+s")

    run(note, scenario)
    assert note.read_text(encoding="utf-8").rstrip("\n") == "ok café ☕ — naïve"


def test_quit_without_changes_exits_immediately(note):
    note.write_text("hello\n")

    async def scenario(app, pilot):
        await key(pilot, "ctrl+q")
        assert not has_modal(app)
        assert not app.is_running

    run(note, scenario)


def test_quit_with_changes_asks_then_cancel_keeps_editing(note):
    note.write_text("hello\n")

    async def scenario(app, pilot):
        from textual.widgets import Button

        await type_text(pilot, "draft ")
        await key(pilot, "ctrl+q")
        assert app.is_running
        assert has_modal(app)
        for bid in ("save", "discard", "cancel"):
            assert isinstance(app.screen.query_one(f"#{bid}"), Button)
        await pilot.click("#cancel")
        await pilot.pause()
        await pilot.pause()
        assert app.is_running and not has_modal(app)
        assert editor(app).text.startswith("draft hello")
        assert is_modified(app)

    run(note, scenario)
    assert note.read_text() == "hello\n"


def test_escape_cancels_quit_dialog(note):
    async def scenario(app, pilot):
        await type_text(pilot, "unsaved")
        await key(pilot, "ctrl+q")
        assert has_modal(app)
        await key(pilot, "escape")
        assert app.is_running and not has_modal(app)
        assert editor(app).text == "unsaved"

    run(note, scenario)
    assert not note.exists()


def test_quit_discard_exits_without_saving(note):
    note.write_text("hello\n")

    async def scenario(app, pilot):
        await type_text(pilot, "junk ")
        await key(pilot, "ctrl+q")
        await pilot.click("#discard")
        await pilot.pause()
        await pilot.pause()
        assert not app.is_running

    run(note, scenario)
    assert note.read_text() == "hello\n"


def test_quit_save_saves_then_exits(note):
    note.write_text("hello\n")

    async def scenario(app, pilot):
        await type_text(pilot, "keep ")
        await key(pilot, "ctrl+q")
        await pilot.click("#save")
        await pilot.pause()
        await pilot.pause()
        assert not app.is_running

    run(note, scenario)
    assert note.read_text().rstrip("\n") == "keep hello"


def test_intent_backup_of_previous_version(note):
    note.write_text("version one\n")
    bak = note.with_name("notes.txt.bak")

    async def scenario(app, pilot):
        await type_text(pilot, "2 ")
        await key(pilot, "ctrl+s")
        assert bak.read_text() == "version one\n"
        await type_text(pilot, "3 ")
        await key(pilot, "ctrl+s")

    run(note, scenario)
    assert bak.read_text().rstrip("\n") == "2 version one"
    assert note.read_text().rstrip("\n") == "2 3 version one"


def test_intent_saved_file_ends_with_newline(note):
    async def scenario(app, pilot):
        await type_text(pilot, "no newline here")
        await key(pilot, "ctrl+s")
        assert not is_modified(app)

    run(note, scenario)
    assert note.read_text() == "no newline here\n"
