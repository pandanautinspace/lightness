"""Try the app: start it headless, run steps, print what the screen and data file show.

Copied into the workspace by the harness; the model runs it instead of writing test code.

    python .lightness/kit/try_app.py [--data TEXT | --data-from PATH] [--kw NAME=VALUE ...] STEP ...

Steps: type:TEXT  press:KEY[,KEY...]  click:#id  focus:#id  wait:SECONDS  restart
After the start and after each step it prints what changed: visible widgets, focus, screen,
notifications, the data file, and any crash.
"""

import argparse
import ast
import asyncio
import importlib
import json
import shutil
import sys
import tempfile
import traceback
from pathlib import Path

ROWS = 15  # rows shown per list/table
TEXT = 300  # characters shown per text value

CONTAINERS = ("ListView", "DataTable", "Tree", "TextArea", "Input", "Select", "Checkbox", "Switch",
              "RadioSet", "TabbedContent", "Digits", "ProgressBar", "OptionList", "SelectionList", "Log",
              "RichLog", "Tabs", "Footer", "Header")


def plain(renderable) -> str:
    text = getattr(renderable, "plain", None)
    if text is None:
        text = str(renderable) if isinstance(renderable, str) else ""
    return " ".join(text.split())


def cut(text: str) -> str:
    return text if len(text) <= TEXT else text[:TEXT] + f"… ({len(text)} chars)"


def item_text(widget) -> str:
    parts = [plain(w.render()) for w in widget.query("Static, Label")]
    return " | ".join(p for p in parts if p) or plain(widget.render())


def shown(widget) -> bool:
    return all(w.display and w.visible for w in widget.ancestors_with_self if hasattr(w, "display"))


def name(widget) -> str:
    return f"#{widget.id}" if widget.id else type(widget).__name__


def rows(lines: list[str]) -> list[str]:
    extra = len(lines) - ROWS
    return lines[:ROWS] + ([f"… {extra} more"] if extra > 0 else [])


def describe(widget) -> list[str]:
    kind = type(widget).__name__
    bases = {c.__name__ for c in type(widget).__mro__}
    if "ListView" in bases:
        items = [item_text(c) for c in widget.children]
        return [f"{name(widget)} list, highlighted={widget.index}:"] + ([f"  [{i}] {t}" for i, t in enumerate(rows(items))] or ["  (empty)"])
    if "DataTable" in bases:
        cols = [plain(c.label) for c in widget.columns.values()]
        body = [" | ".join(str(v) for v in widget.get_row_at(i)) for i in range(widget.row_count)]
        head = f"{name(widget)} table {widget.row_count} rows, cursor={tuple(widget.cursor_coordinate)}, columns={cols}:"
        return [head] + [f"  [{i}] {t}" for i, t in enumerate(rows(body))]
    if "Tree" in bases:
        lines = []

        def walk(node, depth):
            mark = "▼ " if node.allow_expand and node.is_expanded else "▶ " if node.allow_expand else "  "
            lines.append("  " + "  " * depth + mark + plain(node.label) + (" ◀ cursor" if node is widget.cursor_node else ""))
            if node.is_expanded:
                for child in node.children:
                    walk(child, depth + 1)

        walk(widget.root, 0)
        return [f"{name(widget)} tree:"] + rows(lines)
    if "TextArea" in bases:
        return [f"{name(widget)} text (cursor {widget.cursor_location}): {cut(widget.text)!r}"]
    if "Input" in bases:
        return [f"{name(widget)} input: {widget.value!r}"]
    if "Select" in bases or "Checkbox" in bases or "Switch" in bases:
        return [f"{name(widget)} {kind.lower()}: {widget.value!r}"]
    if "RadioSet" in bases:
        pressed = widget.pressed_button
        return [f"{name(widget)} radio: {plain(pressed.label) if pressed else None!r}"]
    if "TabbedContent" in bases:
        return [f"{name(widget)} tabs, active={widget.active!r}"]
    if "Digits" in bases:
        return [f"{name(widget)} digits: {widget.value!r}"]
    if "ProgressBar" in bases:
        return [f"{name(widget)} progress: {widget.progress}/{widget.total}"]
    if "OptionList" in bases or "SelectionList" in bases:
        opts = [plain(widget.get_option_at_index(i).prompt) for i in range(widget.option_count)]
        return [f"{name(widget)} options, highlighted={widget.highlighted}:"] + [f"  [{i}] {t}" for i, t in enumerate(rows(opts))]
    if "Log" in bases or "RichLog" in bases:
        lines = [str(x) for x in getattr(widget, "lines", [])]
        return [f"{name(widget)} log, last lines:"] + ["  " + cut(plain(x) or str(x)) for x in lines[-ROWS:]]
    text = plain(widget.render())
    return [f"{name(widget)}: {cut(text)!r}"] if text else []


def grid(widget) -> list[str] | None:
    """A grid layout of leaf cells, drawn as rows: each cell's text, or its own CSS classes."""
    if widget.styles.layout is None or widget.styles.layout.name != "grid":
        return None
    cells = [c for c in widget.children if shown(c)]
    if not cells or any(c.children for c in cells):
        return None
    common = set.intersection(*(set(c.classes) for c in cells))
    labels = [plain(c.render()) or "+".join(sorted(set(c.classes) - common)) or "." for c in cells]
    cols = widget.styles.grid_size_columns or 1
    width = max(len(t) for t in labels)
    lines = ["  " + " ".join(t.ljust(width) for t in labels[i:i + cols]).rstrip() for i in range(0, len(labels), cols)]
    return [f"{name(widget)} grid {cols} wide:"] + rows(lines)


def snapshot(app, data_path: Path | None) -> dict[str, list[str]]:
    """What the user would see, as blocks keyed by what they describe."""
    out: dict[str, list[str]] = {}

    def add(key: str, lines: list[str]) -> None:
        n = 2
        while key in out:
            key, n = f"{key.split(' (')[0]} ({n})", n + 1
        out[key] = lines

    screen = app.screen
    if type(screen).__name__ != "Screen":
        add("screen", [f"screen: {type(screen).__name__}"])
    add("focus", [f"focus: {name(app.focused) if app.focused else None}"])

    def visit(widget):
        for child in widget.children:
            if not shown(child) or (child.id or "").startswith("-"):
                continue
            bases = {c.__name__ for c in type(child).__mro__}
            if bases & {"Footer", "Header", "Tabs"}:
                continue
            if bases & set(CONTAINERS) or not child.children:
                lines = describe(child)
                if lines:
                    add(name(child), lines)
                if "TabbedContent" in bases:
                    visit(child)
            elif (cells := grid(child)) is not None:
                add(name(child), cells)
            else:
                visit(child)

    visit(screen)
    notes = [plain(n.message) or str(n.message) for n in app._notifications]
    if notes:
        add("notifications", [f"notifications: {notes}"])
    if data_path is not None:
        add("data file", [f"data file: {file_text(data_path)}"])
    return out


def file_text(path: Path) -> str:
    if not path.exists():
        return "(not created)"
    raw = path.read_bytes()
    try:
        text = raw.decode()
    except UnicodeDecodeError:
        return f"({len(raw)} bytes, binary)"
    try:
        return cut(json.dumps(json.loads(text), ensure_ascii=False))
    except ValueError:
        return cut(repr(text)) if text.strip() else "(empty)"


def show(state: dict[str, list[str]]) -> None:
    for lines in state.values():
        for line in lines:
            print("  " + line)


def show_changes(before: dict[str, list[str]], after: dict[str, list[str]]) -> None:
    if before.get("screen") != after.get("screen"):
        print(f"  (now on {after['screen'][0][8:] if 'screen' in after else 'the main screen'})")
        show(after)
        return
    changed = False
    for key, lines in after.items():
        if before.get(key) != lines:
            changed = True
            for line in lines:
                print("  " + line)
    for key in before:
        if key not in after:
            changed = True
            print(f"  {key}: (no longer shown)")
    if not changed:
        print("  (nothing changed)")


def crash_text() -> str:
    lines = traceback.format_exc().strip().splitlines()
    ours = [i for i, line in enumerate(lines) if 'File "' in line and "site-packages" not in line and "try_app" not in line]
    keep = lines[ours[-1]:] if ours else lines[-3:]
    return "\n".join("  " + line for line in keep[-6:])


async def run(cls, args_for_app, kw, data_path, steps) -> int:
    pending = list(steps)
    print("started:")
    while True:
        restart = False
        app = None
        try:
            app = cls(*args_for_app, **kw)
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause()
                state = snapshot(app, data_path)
                show(state)
                while pending and not restart:
                    step = pending.pop(0)
                    if step == "restart":
                        restart = True
                        break
                    print(f"after {step}:")
                    action, _, value = step.partition(":")
                    if action == "type":
                        await pilot.press(*value)
                    elif action == "press":
                        await pilot.press(*[k.strip() for k in value.split(",") if k.strip()])
                    elif action in ("click", "focus") and not app.screen.query(value):
                        ids = sorted(f"#{w.id}" for w in app.screen.query("*") if w.id and not w.id.startswith("-"))
                        print(f"  no widget matches {value!r} on this screen; ids here: {', '.join(ids) or 'none'}")
                        continue
                    elif action == "click":
                        await pilot.click(value)
                    elif action == "focus":
                        app.query_one(value).focus()
                    elif action == "wait":
                        await asyncio.sleep(float(value))
                    else:
                        print(f"  unknown step {step!r} (use type:, press:, click:, focus:, wait:, restart)")
                        return 2
                    await pilot.pause()
                    if not app.is_running:
                        print("  the app exited")
                        if data_path is not None:
                            print(f"  data file: {file_text(data_path)}")
                        if pending and pending[0] == "restart":
                            pending.pop(0)
                            restart = True
                        elif pending:
                            print(f"  steps not run: {pending}")
                            return 0
                        break
                    new = snapshot(app, data_path)
                    show_changes(state, new)
                    state = new
        except Exception:  # noqa: BLE001 - report any crash of the app under test
            print("CRASH:")
            print(crash_text())
            if data_path is not None:
                print(f"  data file: {file_text(data_path)}")
            return 1
        if not restart:
            return 0
        print("after restart (same data file):")


def main() -> int:
    config = json.loads((Path(__file__).parent / "try_app.json").read_text())
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--data", help="contents of the data file to start with")
    p.add_argument("--data-from", help="copy this file as the data file to start with")
    p.add_argument("--kw", action="append", default=[], help="extra App argument NAME=VALUE (Python literal)")
    p.add_argument("steps", nargs="*")
    a = p.parse_args()
    sys.path.insert(0, ".")
    cls = getattr(importlib.import_module(config["module"]), config["app_class"])
    data_path = None
    args_for_app = []
    if config.get("storage", "none") != "none" and config.get("data_arg"):
        data_path = Path(tempfile.mkdtemp(prefix="try-", dir=".lightness")) / (config.get("data_default") or "data")
        if a.data is not None:
            data_path.write_text(a.data)
        elif a.data_from:
            shutil.copy(a.data_from, data_path)
        args_for_app = [str(data_path)]
    kw = {}
    for item in a.kw:
        key, _, value = item.partition("=")
        try:
            kw[key] = ast.literal_eval(value)
        except (ValueError, SyntaxError):
            kw[key] = value
    try:
        return asyncio.run(run(cls, args_for_app, kw, data_path, a.steps))
    finally:
        if data_path is not None:
            shutil.rmtree(data_path.parent, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
