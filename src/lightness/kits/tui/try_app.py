"""Try the app: start it headless, run steps, print what the screen and data file show.

Copied into the workspace by the harness; the model runs it instead of writing test code.

    python .lightness/kit/try_app.py [--file NAME=PATH] [--file-text NAME=TEXT] [--kw NAME=VALUE] STEP ...

Steps: type:TEXT  press:KEY[,KEY...]  click:#id  focus:#id  wait:SECONDS  advance:SECONDS  restart
After the start and after each step it prints what changed (visible widgets, focus, screen,
notifications, any crash) and the contents of each data file the app keeps.

Each file parameter of the App gets a fresh path. A clock parameter gets a fake clock, which only
moves on advance:SECONDS.
"""

import argparse
import ast
import asyncio
import importlib
import json
import math
import shutil
import sys
import tempfile
import traceback
from pathlib import Path

ROWS = 15  # rows shown per list/table
FILE_ROLES = ("data", "input")
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


def snapshot(app) -> dict[str, list[str]]:
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


def files_now(data_files: dict[str, Path]) -> list[str]:
    return [file_text(path) for path in data_files.values()]


def show_files(data_files: dict[str, Path]) -> None:
    for param, path in data_files.items():
        print(f"  {param} file: {file_text(path)}")


class FakeClock:
    """The App's clock parameter: a zero-argument callable returning seconds. Moves only on advance."""

    def __init__(self, t: float = 1000.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


def timer_period(app) -> float:
    """The longest period of the running repeating timers (set_interval) on the app, its screens
    and widgets, capped at a second: long enough for each of them to tick once."""
    periods = [0.0]
    for screen in app.screen_stack:
        for node in [app, screen, *screen.walk_children()]:
            for timer in list(getattr(node, "_timers", ())):
                if timer._repeat != 0 and timer._active.is_set():
                    periods.append(timer._interval)
    return min(1.0, max(periods))


async def advance(app, pilot, clock: FakeClock, seconds: float) -> None:
    """Move the fake clock forward in up to 10 slices; after each slice, wait (real time) one period
    of the app's timers so their callbacks run and read the new time."""
    slices = max(1, min(10, math.ceil(seconds)))
    for _ in range(slices):
        clock.t += seconds / slices
        await pilot.pause(timer_period(app) + 0.05)


def show(state: dict[str, list[str]]) -> None:
    for lines in state.values():
        for line in lines:
            print("  " + line)


def show_changes(before: dict[str, list[str]], after: dict[str, list[str]], files_changed: bool = False) -> None:
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
    if not changed and not files_changed:
        print("  (nothing changed)")


def crash_text() -> str:
    lines = traceback.format_exc().strip().splitlines()
    ours = [i for i, line in enumerate(lines) if 'File "' in line and "site-packages" not in line and "try_app" not in line]
    keep = lines[ours[-1]:] if ours else lines[-3:]
    return "\n".join("  " + line for line in keep[-6:])


async def run(cls, kw, data_files: dict[str, Path], clock: FakeClock | None, steps) -> int:
    pending = list(steps)
    print("started:")
    while True:
        restart = False
        app = None
        try:
            app = cls(**kw)
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause()
                state, files = snapshot(app), files_now(data_files)
                show(state)
                show_files(data_files)
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
                    elif action == "advance" and clock is None:
                        print(f"  advance needs a clock parameter, and {cls.__name__} has none (wait:SECONDS waits in real time)")
                        continue
                    elif action == "advance":
                        await advance(app, pilot, clock, float(value))
                    else:
                        print(f"  unknown step {step!r} (use type:, press:, click:, focus:, wait:, advance:, restart)")
                        return 2
                    await pilot.pause()
                    if not app.is_running:
                        print("  the app exited")
                        show_files(data_files)
                        if pending and pending[0] == "restart":
                            pending.pop(0)
                            restart = True
                        elif pending:
                            print(f"  steps not run: {pending}")
                            return 0
                        break
                    new, new_files = snapshot(app), files_now(data_files)
                    show_changes(state, new, new_files != files)
                    show_files(data_files)
                    state, files = new, new_files
        except Exception:  # noqa: BLE001 - report any crash of the app under test
            print("CRASH:")
            print(crash_text())
            show_files(data_files)
            return 1
        if not restart:
            return 0
        print("after restart (same files):")


def pairs(items: list[str], flag: str, names: list[str]) -> dict[str, str] | None:
    out = {}
    for item in items:
        key, sep, value = item.partition("=")
        if not sep or key not in names:
            print(f"{flag} takes NAME=VALUE with NAME one of the App's file parameters: {', '.join(names) or 'none'}")
            return None
        out[key] = value
    return out


def main() -> int:
    config = json.loads((Path(__file__).parent / "try_app.json").read_text())
    params = config.get("params") or []
    files = [p for p in params if p["role"] in FILE_ROLES]
    names = [p["name"] for p in files]
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--file", action="append", default=[], metavar="NAME=PATH",
                   help="start file parameter NAME with a copy of PATH")
    p.add_argument("--file-text", action="append", default=[], metavar="NAME=TEXT",
                   help="start file parameter NAME with a file holding TEXT")
    p.add_argument("--data", help="TEXT for the App's only file parameter (same as --file-text NAME=TEXT)")
    p.add_argument("--data-from", help="PATH for the App's only file parameter (same as --file NAME=PATH)")
    p.add_argument("--kw", action="append", default=[], help="extra App argument NAME=VALUE (Python literal)")
    p.add_argument("steps", nargs="*")
    a = p.parse_args()
    texts, copies = pairs(a.file_text, "--file-text", names), pairs(a.file, "--file", names)
    if texts is None or copies is None:
        return 2
    if a.data is not None or a.data_from:
        if len(files) != 1:
            print(f"--data/--data-from need exactly one file parameter, and {config['app_class']} has "
                  f"{len(files)}{': ' + ', '.join(names) if names else ''}. Use --file NAME=PATH or --file-text NAME=TEXT.")
            return 2
        if a.data is not None:
            texts[names[0]] = a.data
        else:
            copies[names[0]] = a.data_from
    sys.path.insert(0, ".")
    cls = getattr(importlib.import_module(config["module"]), config["app_class"])
    tmp = Path(tempfile.mkdtemp(prefix="try-", dir=".lightness"))
    kw, data_files, said = {}, {}, []
    for f in files:
        default = f.get("file") or ("data.json" if f["role"] == "data" else "input.txt")
        path = tmp / f["name"] / default
        path.parent.mkdir()
        if f["name"] in texts:
            path.write_text(texts[f["name"]])
        elif f["name"] in copies:
            shutil.copy(copies[f["name"]], path)
        elif f["role"] == "input" and Path(default).is_file():
            shutil.copy(default, path)
            said.append(f"{f['name']}: a copy of the project's {default}")
        else:
            said.append(f"{f['name']}: no file yet")
        kw[f["name"]] = str(path)
        if f["role"] == "data":
            data_files[f["name"]] = path
    clock = None
    for c in params:
        if c["role"] == "clock":
            clock = kw[c["name"]] = FakeClock()
            said.append(f"{c['name']}: a fake clock (moves only on advance:SECONDS)")
    for item in a.kw:
        key, _, value = item.partition("=")
        try:
            kw[key] = ast.literal_eval(value)
        except (ValueError, SyntaxError):
            kw[key] = value
    if said:
        print("parameters: " + "; ".join(said))
    try:
        return asyncio.run(run(cls, kw, data_files, clock, a.steps))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
