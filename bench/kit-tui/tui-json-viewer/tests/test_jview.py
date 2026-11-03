import asyncio
import json
import re
from pathlib import Path

import pytest

from lightness.bench.testkit import import_from_workspace

DOC = {
    "title": "Team roster",
    "version": 3,
    "active": True,
    "owner": None,
    "users": [
        {"name": "Ada", "age": 36, "langs": ["python", "ocaml"]},
        {"name": "Bob", "age": 41, "city": "Zürich"},
        {"name": "Cy", "age": 29, "langs": []},
    ],
    "settings": {"theme": "dark", "ratio": 3.5},
}


@pytest.fixture
def doc_file(tmp_path: Path) -> Path:
    p = tmp_path / "doc.json"
    p.write_text(json.dumps(DOC, ensure_ascii=False), encoding="utf-8")
    return p


def text_of(widget) -> str:
    text = getattr(widget, "text", None)
    if isinstance(text, str):
        return text
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
    jview = import_from_workspace("jview")

    async def main():
        app = jview.JsonViewerApp(path)
        async with app.run_test(size=(140, 50)) as pilot:
            await pilot.pause()
            result = await scenario(app, pilot)
            await pilot.pause()
            return result

    return asyncio.run(main())


def label(node) -> str:
    return str(node.label).strip()


def starts_with_key(text: str, key: str) -> bool:
    return re.match(re.escape(key) + r"(?![\w\]])", text) is not None


async def child(pilot, node, key):
    if not node.is_expanded:
        node.expand()
        await pilot.pause()
    await pilot.pause()
    hits = [c for c in node.children if starts_with_key(label(c), key)]
    assert hits, f"no child {key!r} under {label(node)!r}: {[label(c) for c in node.children]}"
    return hits[0]


async def find(pilot, *keys):
    node = pilot.app.query_one("#tree").root
    for key in keys:
        node = await child(pilot, node, key)
    return node


async def goto(pilot, *keys):
    node = await find(pilot, *keys)
    tree = pilot.app.query_one("#tree")
    tree.focus()
    tree.move_cursor(node)
    await pilot.pause()
    await pilot.pause()
    return node


def shown_path(app) -> str:
    return text_of(app.query_one("#path")).strip()


def shown_value(app):
    return json.loads(text_of(app.query_one("#detail")).strip())


def test_root_shows_top_level_keys_in_order(doc_file):
    async def scenario(app, pilot):
        from textual.widgets import Tree

        tree = app.query_one("#tree")
        assert isinstance(tree, Tree)
        assert tree.root.is_expanded
        labels = [label(c) for c in tree.root.children]
        assert len(labels) == 6
        for key, text in zip(DOC, labels):
            assert starts_with_key(text, key), (key, text)

    run(doc_file, scenario)


def test_cursor_starts_on_root_with_whole_document(doc_file):
    async def scenario(app, pilot):
        assert shown_path(app) == "$"
        assert shown_value(app) == DOC

    run(doc_file, scenario)


def test_array_children_are_indexed(doc_file):
    async def scenario(app, pilot):
        users = await find(pilot, "users")
        users.expand()
        await pilot.pause()
        labels = [label(c) for c in users.children]
        assert len(labels) == 3
        for i, text in enumerate(labels):
            assert starts_with_key(text, f"[{i}]"), text

    run(doc_file, scenario)


def test_nested_leaf_path_and_value(doc_file):
    async def scenario(app, pilot):
        await goto(pilot, "users", "[1]", "name")
        assert shown_path(app) == "$.users[1].name"
        assert shown_value(app) == "Bob"
        await goto(pilot, "users", "[0]", "langs", "[1]")
        assert shown_path(app) == "$.users[0].langs[1]"
        assert shown_value(app) == "ocaml"

    run(doc_file, scenario)


def test_container_detail_is_subtree(doc_file):
    async def scenario(app, pilot):
        await goto(pilot, "users", "[0]")
        assert shown_path(app) == "$.users[0]"
        assert shown_value(app) == DOC["users"][0]
        await goto(pilot, "settings")
        assert shown_path(app) == "$.settings"
        assert shown_value(app) == {"theme": "dark", "ratio": 3.5}

    run(doc_file, scenario)


def test_scalar_types_render_as_json(doc_file):
    async def scenario(app, pilot):
        await goto(pilot, "owner")
        assert text_of(app.query_one("#detail")).strip() == "null"
        await goto(pilot, "active")
        assert text_of(app.query_one("#detail")).strip() == "true"
        await goto(pilot, "settings", "ratio")
        assert shown_value(app) == 3.5
        await goto(pilot, "users", "[1]", "city")
        assert shown_value(app) == "Zürich"

    run(doc_file, scenario)


def test_keyboard_navigation_updates_detail(doc_file):
    async def scenario(app, pilot):
        app.query_one("#tree").focus()
        await pilot.pause()
        await pilot.press("down")
        await pilot.pause()
        assert shown_path(app) == "$.title"
        assert shown_value(app) == "Team roster"
        await pilot.press("down")
        await pilot.pause()
        assert shown_path(app) == "$.version"
        assert shown_value(app) == 3

    run(doc_file, scenario)


def test_empty_containers(doc_file):
    async def scenario(app, pilot):
        await goto(pilot, "users", "[2]", "langs")
        assert shown_path(app) == "$.users[2].langs"
        assert shown_value(app) == []

    run(doc_file, scenario)


def test_top_level_array(tmp_path):
    p = tmp_path / "list.json"
    p.write_text(json.dumps([10, {"k": "v"}, [1, 2]]))

    async def scenario(app, pilot):
        await goto(pilot, "[1]", "k")
        assert shown_path(app) == "$[1].k"
        assert shown_value(app) == "v"
        await goto(pilot, "[2]")
        assert shown_path(app) == "$[2]"
        assert shown_value(app) == [1, 2]

    run(p, scenario)


def test_file_untouched(doc_file):
    before = doc_file.read_bytes()

    async def scenario(app, pilot):
        await goto(pilot, "users", "[0]", "name")

    run(doc_file, scenario)
    assert doc_file.read_bytes() == before


def test_intent_leaf_labels_show_values(doc_file):
    async def scenario(app, pilot):
        name = await find(pilot, "users", "[0]", "name")
        assert '"Ada"' in label(name), label(name)
        age = await find(pilot, "users", "[0]", "age")
        assert "36" in label(age)
        owner = await find(pilot, "owner")
        assert "null" in label(owner)
        lang = await find(pilot, "users", "[0]", "langs", "[0]")
        assert '"python"' in label(lang)

    run(doc_file, scenario)


def test_intent_container_labels_show_counts(doc_file):
    async def scenario(app, pilot):
        users = await find(pilot, "users")
        assert "3" in label(users)[len("users"):], label(users)
        settings = await find(pilot, "settings")
        assert "2" in label(settings)[len("settings"):], label(settings)
        langs = await find(pilot, "users", "[0]", "langs")
        assert "2" in label(langs)[len("langs"):], label(langs)

    run(doc_file, scenario)


def test_intent_invalid_json_shows_error(tmp_path):
    p = tmp_path / "broken.json"
    p.write_text('{"a": 1, "b": [1, 2,,]}')

    async def scenario(app, pilot):
        await pilot.pause()
        texts = []
        for w in app.screen.query("*"):
            texts.append(text_of(w) if w.id in ("detail", "path") else "")
            try:
                texts.append(str(w.render()))
            except Exception:
                pass
        texts += [str(getattr(n, "message", "")) for n in getattr(app, "_notifications", [])]
        tree = app.query_one("#tree")
        texts += [label(tree.root)] + [label(c) for c in tree.root.children]
        blob = " ".join(texts).lower()
        assert "invalid" in blob or "error" in blob or "expecting" in blob, blob[:500]
        assert not any(starts_with_key(label(c), "a") for c in tree.root.children)

    run(p, scenario)
