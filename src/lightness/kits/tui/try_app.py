"""Try the app: start it headless, run steps, print what the screen and data file show.

Copied into the workspace by the harness; the model runs it instead of writing test code.

    python .lightness/kit/try_app.py [--file NAME=PATH] [--file-text NAME=TEXT] [--kw NAME=VALUE] STEP ...

Steps: type:TEXT  press:KEY[,KEY...] (KEY*N repeats it, e.g. down*5)  click:#id  focus:#id  wait:SECONDS  advance:SECONDS  restart
       expect:TEXT  expect-not:TEXT  expect-file:PARAM=TEXT
After the start and after each step it prints what changed (visible widgets, focus, screen,
notifications, any crash) and the contents of each data file the app keeps.

    python .lightness/kit/try_app.py --checks checks.txt [--builtin]

runs each line of checks.txt (NAME: [options] STEP ...) in a fresh app and prints PASS or FAIL
per line; --builtin adds the harness's own checks (every key works, restarts keep saved files).

Each file parameter of the App gets a fresh path. A clock parameter gets a fake clock, which only
moves on advance:SECONDS.
"""

import argparse
from collections import Counter
import ast
import asyncio
import contextlib
import io
import importlib
import json
import math
import os
import re
import shlex
import signal
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


OUT = [sys.stdout]  # where output goes; checks mode swaps in a buffer (Textual resets sys.stdout after a run)


def say(*args) -> None:
    print(*args, file=OUT[0])


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
        # say what the cursor moves: csv-browser's table used a row cursor (left/right do nothing) in every run,
        # though its task asked for a cell cursor, and sorting "by the cursor's column" could never change column
        kind = {"row": "row cursor: left/right do nothing", "column": "column cursor: up/down do nothing",
                "cell": "cell cursor", "none": "no cursor"}.get(widget.cursor_type, f"{widget.cursor_type} cursor")
        head = (f"{name(widget)} table {widget.row_count} rows, cursor={tuple(widget.cursor_coordinate)} ({kind}), "
                f"columns={cols}:")
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
        # number the rows (row = cursor_line, so a check can count presses) and keep the cursor in view
        lines = [f"  [{i}]{line[1:]}" for i, line in enumerate(lines)]
        at = next((i for i, line in enumerate(lines) if line.endswith("◀ cursor")), 0)
        start = max(0, min(at - ROWS // 2, len(lines) - ROWS))
        shown = ([f"  … {start} rows above"] if start else []) + lines[start:start + ROWS]
        below = len(lines) - start - ROWS
        return [f"{name(widget)} tree, {len(lines)} rows (up/down move one row, space opens/closes its node, left/right do nothing; press:down*K moves K rows):"] + shown + (
            [f"  … {below} more"] if below > 0 else [])
    if "TextArea" in bases:
        return [f"{name(widget)} text (cursor {widget.cursor_location}): {cut(widget.text)!r}"]
    if "Input" in bases:  # its classes too: validity is often a class (e.g. -invalid)
        classes = f" classes: {' '.join(sorted(widget.classes))}" if widget.classes else ""
        return [f"{name(widget)} input: {widget.value!r}{classes}"]
    if "Select" in bases:  # its options too: a check may need to know what can be picked
        labels = [plain(label) if not isinstance(label, str) else label
                  for label, value in getattr(widget, "_options", []) if not type(value).__name__ == "NoSelection"]
        return [f"{name(widget)} select: {widget.value!r}, options: {', '.join(labels) or '(none)'}"]
    if "Checkbox" in bases or "Switch" in bases:
        return [f"{name(widget)} {kind.lower()}: {widget.value!r}"]
    if "RadioSet" in bases:
        pressed = widget.pressed_button
        return [f"{name(widget)} radio: {plain(pressed.label) if pressed else None!r}"]
    if "TabbedContent" in bases:
        panes = [pane.id for pane in widget.query("TabPane") if pane.id and pane.id != widget.active]
        switch = ("; switch: " + ", ".join(f"click:#--content-tab-{p}" for p in panes)) if panes else ""
        return [f"{name(widget)} tabs, active={widget.active!r}{switch}"]
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
    source = getattr(widget, "content", None)
    if isinstance(source, str) and "[" in source and plain(widget.render()).strip() != source.strip() \
            and any(not_a_style(tag) for tag in re.findall(r"\[([^\]/][^\]]*)\]", source)):
        # "[modified]" set on a Static is read as a markup tag and shows nothing (the 35B, notepad)
        # (the 35B read "Static(..., markup=False)" as an update() argument: say where it goes)
        lost = f" (its text {cut(source)!r} was read as markup: [..] is a style tag; to show brackets, create " \
               f"the widget with Static('', markup=False), or update(rich.markup.escape(text)); update() itself " \
               f"has no markup argument)"
    else:
        lost = ""
    if not text:  # an empty widget the task names (has an id) is shown, so "empty" differs from "missing"
        return [f"{name(widget)}: (empty){lost}"] if widget.id else []
    return [f"{name(widget)}: {cut(text)!r}{lost}"]


def not_a_style(tag: str) -> bool:
    """A [tag] in widget text that isn't a style, a link or a theme variable: meant as text, not markup."""
    from rich.style import Style

    tag = tag.strip()
    if tag.startswith(("$", "@", "link=")) or not tag:
        return False
    try:
        Style.parse(tag)
        return False
    except Exception:  # noqa: BLE001 - rich's StyleSyntaxError and friends
        return True


GRID_CLASS_CELLS = 15  # cells listed per class


def grid(widget) -> list[str] | None:
    """A grid layout of leaf cells, drawn as rows: each cell's text, or its own CSS classes."""
    if widget.styles.layout is None or widget.styles.layout.name != "grid":
        return None
    cells = [c for c in widget.children if shown(c)]
    if not cells or any(c.children for c in cells):
        return None
    common = set.intersection(*(set(c.classes) for c in cells))
    texts = [plain(c.render()) for c in cells]
    by_class = ["+".join(sorted(set(c.classes) - common)) or "." for c in cells]
    # every cell showing the same text while their classes differ (a board styled by class): the text
    # tells nothing, so draw the classes (the 35B read an all-'.' drawing of a lit board as "no board")
    same_text = all(texts) and len(set(texts)) == 1 and len(set(by_class)) > 1
    labels = by_class if same_text else [t or k for t, k in zip(texts, by_class)]
    cols = widget.styles.grid_size_columns or 1
    width = max(len(t) for t in labels)
    lines = ["  " + " ".join(t.ljust(width) for t in labels[i:i + cols]).rstrip() for i in range(0, len(labels), cols)]
    if same_text:
        lines.insert(0, f"  (every cell shows {texts[0]!r}; drawn by CSS class instead)")
    if cells[0].id and cells[-1].id:  # the 35B checked expect:"#cell-4-4", which no line named (lights-out)
        lines.append(f"  cells {name(cells[0])} … {name(cells[-1])} ({len(cells)}, row by row)")
    if common - {"-highlight"}:  # a state every cell has (an all-lit board) is still state: name it
        # one line, not 25: the 35B then probed for "class cell: #cell-0-4" for 3 steps; say how to check it
        lines.append(f"  every cell has class: {', '.join(sorted(common))} (listed once here, not per cell; check it "
                     f"with expect:\"every cell has class\")")
    # which cell has which class (a cursor, lit cells, a selection), one line per cell so a check can
    # expect "class on: #cell-0-1"; listing only classes 1-2 cells had left 3+ lit cells uncheckable
    counts = Counter(c for cell in cells for c in set(cell.classes) - common)
    for cls_name in sorted(counts, key=lambda k: (counts[k], k)):  # rarest first: a cursor before 20 dark cells
        where = [f"{name(c)} (row {i // cols}, col {i % cols})" for i, c in enumerate(cells) if cls_name in c.classes]
        lines += [f"  class {cls_name}: {w}" for w in where[:GRID_CLASS_CELLS]]
        if len(where) > GRID_CLASS_CELLS:
            lines.append(f"  class {cls_name}: … {len(where) - GRID_CLASS_CELLS} more cells")
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
    if app.screen.query("Header"):  # the Header shows the app's title (and sub-title)
        title = app.title + (f" - {app.sub_title}" if app.sub_title else "")
        add("title", [f"title: {title}"])
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


SQLITE = (".db", ".sqlite", ".sqlite3")


def sqlite_text(path: Path) -> str:
    """A SQLite file's tables and rows, short."""
    import sqlite3

    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' "
                                                "AND name NOT LIKE 'sqlite_%' ORDER BY name")]
            parts = []
            for t in tables:
                rows = con.execute(f'SELECT * FROM "{t}" LIMIT 6').fetchall()
                parts.append(f"table {t}: " + (", ".join(map(repr, rows)) if rows else "(no rows)"))
            return cut("SQLite: " + ("; ".join(parts) if parts else "no tables"))
        finally:
            con.close()
    except sqlite3.Error as e:
        return f"(SQLite file, unreadable: {e})"


def file_text(path: Path) -> str:
    if not path.exists():
        return "(not created)"
    raw = path.read_bytes()
    if raw.startswith(b"SQLite format 3"):
        return sqlite_text(path)
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
        say(f"  {param} file: {file_text(path)}")


class FakeClock:
    """The App's clock parameter: a zero-argument callable returning seconds. Moves only on advance."""

    def __init__(self, t: float = 1000.0) -> None:
        self.t, self.reads = t, 0

    def __call__(self) -> float:
        self.reads += 1
        return self.t


def timer_period(app) -> float:
    """The longest period of the app's own running repeating timers (set_interval) on the app, its
    screens and widgets, capped at a second: long enough for each of them to tick once. Textual's
    own timers (cursor blink, ...) don't count."""
    periods = [0.0]
    for screen in app.screen_stack:
        for node in [app, screen, *screen.walk_children()]:
            for timer in list(getattr(node, "_timers", ())):
                own = not (getattr(timer._callback, "__module__", "") or "").startswith("textual")
                if own and timer._repeat != 0 and timer._active.is_set():
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
            say("  " + line)


CURSOR_LINE = re.compile(r" (tree|list|table)\b")  # the first line of a tree/list/table block


def show_changes(before: dict[str, list[str]], after: dict[str, list[str]], files_changed: bool = False) -> None:
    if before.get("screen") != after.get("screen"):
        say(f"  (now on {after['screen'][0][8:] if 'screen' in after else 'the main screen'})")
        show(after)
        return
    changed = []
    for key, lines in after.items():
        if before.get(key) != lines:
            changed.append(key)
            for line in lines:
                say("  " + line)
    for key in before:
        if key not in after:
            changed.append(key)
            say(f"  {key}: (no longer shown)")
    if not changed and not files_changed:
        say("  (nothing changed)")
    elif len(changed) == 1 and not files_changed and CURSOR_LINE.search(" ".join(after.get(changed[0], [""])[:1])):
        # only a list/table/tree cursor moved: say so plainly, the app may be meant to react to it
        say(f"  (only the cursor in {changed[0]} moved; no other widget changed)")


# the harness's own notes inside widget lines are not what the app shows: an expect must not match them
# (notepad pass 6: status.update("[modified]") showed nothing, and expect:"modified" passed on the markup
# note that quoted the lost text)
HARNESS_NOTES = re.compile(r" \(its text .*? was read as markup: .*?update\(\) itself has no markup argument\)"
                           r"| \(up/down move one row, [^)]*\)| \((?:row|column|cell|no) cursor[^)]*\)")


def screen_text(state: dict[str, list[str]]) -> str:
    return " ".join(" ".join(HARNESS_NOTES.sub("", line).split()) for lines in state.values() for line in lines)


def expectation(action: str, value: str, state: dict[str, list[str]], data_files: dict[str, Path]) -> str | None:
    """None if the expect step holds, else what is wrong."""
    if action == "expect-file":
        param, sep, want = value.partition("=")
        if not sep or param not in data_files:
            return f"expect-file takes PARAM=TEXT with PARAM one of the data files: {', '.join(data_files) or 'none'}"
        path = data_files[param]
        if not path.exists():
            return "the file was not created"
        if path.suffix in SQLITE:
            return (f"{param} is a SQLite database, not text: check what the app shows instead (e.g. restart, then "
                    f"expect:), it holds {file_text(path)}")
        got = path.read_text(errors="replace")
        try:
            same = json.loads(got) == json.loads(want)
        except ValueError:
            same = got.strip() == want.strip()
        return None if same else f"the file holds {file_text(path)}"
    want, screen = " ".join(value.split()), screen_text(state)
    if not want:
        return f"{action}: needs the text to look for (an empty {action}: checks nothing)"
    found = want in screen
    if not found and (m := re.fullmatch(r"(#[\w-]+)\s+('.*'|\".*\")", want)):
        # "#path '$'" can only mean "#path: '$'": the 35B drops the colon in nearly every run and kept doing so
        # after the hint named the right form (json-viewer, passes 4-6), so take it as meant
        found = f"{m[1]}: {m[2]}" in screen
    if action == "expect":
        if found:
            return None
        if want.lower() in screen.lower():
            i = screen.lower().index(want.lower())
            return f"not on the screen (only with different case: {screen[i:i + len(want)]!r})"
        if m := re.fullmatch(r"(#[\w-]+):?\s+(\S.*)", want):
            # the 35B wrote expect:"#path '$'" (no colon) and expect:"#path: $" (no quotes) for steps while
            # the screen said #path: '$' (json-viewer)
            text = m[2][1:-1] if len(m[2]) > 1 and m[2][0] == m[2][-1] and m[2][0] in "'\"" else m[2]
            for near in (f"{m[1]}: {text!r}", f"{m[1]}: {m[2]}", f"{m[1]}: {m[2]!r}"):  # last: '"inventory"'
                if near != want and near in screen:
                    return (f"not on the screen as written (the screen has {near}: write it exactly so, with the "
                            "colon after the id and the quotes)")
        if CLASS_LIKE.match(want):
            return ("not on the screen (if you meant a CSS class or selector: expect matches the text the screen "
                    "shows, as the dump below prints it, not selectors)")
        return "not on the screen"
    return "it is on the screen" if found else None


def css_error_text(exc) -> str:
    """A Textual StylesheetParseError as plain lines: each bad CSS line and what is wrong with it."""
    import io
    from rich.console import Console
    buf = io.StringIO()
    Console(file=buf, width=100, no_color=True, color_system=None).print(exc.errors)
    out = []
    for line in buf.getvalue().splitlines():
        t = line.strip()
        if not t or t[0] in "\u256d\u2570":  # panel top/bottom borders
            continue
        if t.startswith("\u2502"):  # a code line inside the panel: keep only the marked one
            if "\u2771" in t:
                out.append("  at CSS line: " + " ".join(t.replace("\u2502", " ").replace("\u2771", " ").split()))
            continue
        out.append("  " + t)
    return "CSS error in the app's CSS:\n" + "\n".join(out[:24])


def not_clickable(app, selector: str) -> str | None:
    """Why a click on the widget would miss (it is clipped or covered), or None if it would land."""
    widget = app.screen.query_one(selector)
    region = widget.region
    if not region.area:
        return "it takes no space on the screen"
    x, y = region.x + region.width // 2, region.y + region.height // 2
    try:
        hit, _ = app.screen.get_widget_at(x, y)
    except Exception:  # noqa: BLE001 - off the screen
        hit = None
    node = hit
    while node is not None and node is not widget:
        node = node.parent
    if node is None:
        return (f"its middle ({x}, {y}) shows {name(hit) if hit else 'nothing'} instead: it is cut off by its "
                f"container or the {app.size.width}x{app.size.height} screen")
    return None


def attr_hint(exc) -> str:
    """For an AttributeError on an object: the real names closest to the missing one."""
    import difflib
    obj, missing = getattr(exc, "obj", None), getattr(exc, "name", None)
    if obj is None or not missing:
        return ""
    names = [n for n in dir(obj) if not n.startswith("_")]
    close = difflib.get_close_matches(missing, names, n=6, cutoff=0.5)
    close += [n for n in names if (missing.split("_")[0] in n or n in missing) and n not in close][:6 - len(close)]
    kind = type(obj).__name__
    return (f"{kind} has no {missing!r}. Closest names on {kind}: {', '.join(close)}" if close
            else f"{kind} has no {missing!r}. Its public names: {', '.join(names[:40])}")


def crash_text() -> str:
    exc = sys.exc_info()[1]
    if type(exc).__name__ == "CheckTimeout" or "CheckTimeout" in traceback.format_exc()[-200:]:
        return (f"  this check did not finish within {CHECK_SECONDS}s: the app hangs (an endless loop or a "
                "wait) in the step above")
    if type(exc).__name__ == "StylesheetParseError":
        return "\n".join("  " + line for line in css_error_text(exc).splitlines())
    lines = traceback.format_exc().strip().splitlines()
    ours = [i for i, line in enumerate(lines) if 'File "' in line and "site-packages" not in line and "try_app" not in line]
    keep = lines[ours[-1]:] if ours else lines[-3:]
    hint = attr_hint(exc) if isinstance(exc, AttributeError) else ""
    return "\n".join("  " + line for line in keep[-6:] + ([f"hint: {hint}"] if hint else []))


async def run(cls, kw, data_files: dict[str, Path], clock: FakeClock | None, steps, stop_on_fail=False) -> int:
    """Returns 0, 1 on a crash, 2 on a bad step, 3 when an expect step failed."""
    pending, failed = list(steps), False
    say("started:")
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
                    action, _, value = step.partition(":")
                    if action in ("expect", "expect-not", "expect-file"):
                        problem = expectation(action, value, snapshot(app), data_files)
                        if problem is None:
                            say(f"ok: {step}")
                            continue
                        failed = True
                        say(f"FAILED {step}: {problem}. Screen now:")
                        show(snapshot(app))
                        show_files(data_files)
                        if stop_on_fail:
                            return 3
                        continue
                    say(f"after {step}:")
                    if action == "type":
                        target = app.focused
                        before = getattr(target, "value", None) if type(target).__name__ == "Input" else None
                        await pilot.press(*value)
                        after = getattr(target, "value", None)
                        if before is not None and isinstance(after, str) and value not in after and (
                                target.type != "text" or target.restrict):
                            # Input(type="number"/"integer") or restrict= drops keys silently: the 35B typed "abc"
                            # into a number field to test validation and got "(nothing changed)" (loan-calc)
                            kind = f"type={target.type!r}" if target.type != "text" else f"restrict={target.restrict!r}"
                            say(f"  ({name(target)} is an Input with {kind}: it dropped the keys that don't fit, so it "
                                f"holds {after!r}, not {before + value!r}; input it can't hold can't be typed into it)")
                    elif action == "press":
                        focused = app.focused
                        typed_before = getattr(focused, "value", None) if type(focused).__name__ == "Input" else None
                        table_before = (focused.cursor_type, tuple(focused.cursor_coordinate)) \
                            if type(focused).__name__ == "DataTable" else None
                        is_tree = focused is not None and "Tree" in [c.__name__ for c in type(focused).__mro__]
                        dead_tree_key = False
                        if is_tree:  # one key at a time: in press:right,down the down hid the dead right
                            for k in keys_of(value):
                                tree_before = (focused.cursor_line, focused.last_line)
                                await pilot.press(k)
                                dead_tree_key |= k in ("left", "right") and (focused.cursor_line, focused.last_line) == tree_before
                        else:
                            await pilot.press(*keys_of(value))
                        if dead_tree_key:
                            # json-viewer (passes 4 and 5): checks pressed right to open a node, 12 of 30 stuck
                            say(f"  (left/right did nothing: {name(focused)} is a Tree; up/down move one row, space "
                                "opens/closes the node under the cursor)")
                        dead = {"row": {"left", "right"}, "column": {"up", "down"}}
                        if table_before and set(keys_of(value)) & dead.get(table_before[0], set()) \
                                and tuple(focused.cursor_coordinate) == table_before[1]:
                            # csv-browser (every run): a row-cursor table, checks pressing right to reach a column
                            moved = "left/right" if table_before[0] == "row" else "up/down"
                            say(f"  ({moved} did nothing: {name(focused)} has a {table_before[0]} cursor. For a cursor "
                                f"that moves by cell, create it with DataTable(cursor_type=\"cell\"))")
                        letters = [k for k in keys_of(value) if len(k) == 1 and k.isprintable()]
                        if typed_before is not None and letters and getattr(focused, "value", None) != typed_before:
                            # the 35B's checks did focus:#search press:a and then reworked the app's focus for
                            # 3 steps: the "a" never reached the binding
                            say(f"  ({''.join(letters)!r} went into {name(focused)} as text: an Input has focus, so "
                                f"the app's key bindings for those keys don't fire; focus another widget first)")
                    elif action in ("click", "focus") and not app.screen.query(value):
                        ids = sorted(f"#{w.id}" for w in app.screen.query("*") if w.id and not w.id.startswith("-"))
                        say(f"  no widget matches {value!r} on this screen; ids here: {', '.join(ids) or 'none'}")
                        continue
                    elif action == "click":
                        if (hidden := not_clickable(app, value)) is not None:
                            say(f"  {value} can't be clicked: {hidden}. A user couldn't click it either: fix the "
                                "layout (sizes of it and its container; a dialog's box needs room for every line in it)")
                            continue
                        await pilot.click(value)
                    elif action == "focus":
                        app.screen.query_one(value).focus()  # the active screen: a dialog's widgets too
                    elif action == "wait":
                        await asyncio.sleep(float(value))
                    elif action == "advance" and clock is None:
                        say(f"  advance needs a clock parameter, and {cls.__name__} has none (wait:SECONDS waits in real time)")
                        continue
                    elif action == "advance":
                        reads, start = clock.reads, clock.t
                        await advance(app, pilot, clock, float(value))
                        # say what happened to time: "(nothing changed)" alone read as "advance didn't run
                        # the timers" to the 35B, whose app showed a stale number (stopwatch)
                        n = clock.reads - reads
                        clock_note = (f"  (the clock moved {clock.t - start:g} s and the app's timers ran; the app read "
                                      f"the clock {n} time{'s' if n != 1 else ''}" + (")" if n else
                                      ": its timer isn't running, or the code it runs doesn't read the clock)"))
                    else:
                        say(f"  unknown step {step!r} (use type:, press:, click:, focus:, wait:, advance:, restart, "
                              "expect:, expect-not:, expect-file:)")
                        return 2
                    await pilot.pause()
                    if not app.is_running:
                        say("  the app exited")
                        show_files(data_files)
                        if pending and pending[0] == "restart":
                            pending.pop(0)
                            restart = True
                        elif pending:
                            say(f"  steps not run: {pending}")
                            return 3 if failed else 0
                        break
                    new, new_files = snapshot(app), files_now(data_files)
                    show_changes(state, new, new_files != files)
                    if action == "advance" and clock is not None:
                        say(clock_note)
                    show_files(data_files)
                    state, files = new, new_files
        except Exception:  # noqa: BLE001 - report any crash of the app under test
            say("CRASH:")
            say(crash_text())
            show_files(data_files)
            return 1
        if not restart:
            return 3 if failed else 0
        say("after restart (same files):")


def pairs(items: list[str], flag: str, names: list[str]) -> dict[str, str] | None:
    out = {}
    for item in items:
        key, sep, value = item.partition("=")
        if not sep or key not in names:
            say(f"{flag} takes NAME=VALUE with NAME one of the App's file parameters: {', '.join(names) or 'none'}"
                f" (got {item[:40]!r}; write {names[0] if names else 'NAME'}=..., with '=')")
            return None
        out[key] = value
    return out


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--file", action="append", default=[], metavar="NAME=PATH",
                   help="start file parameter NAME with a copy of PATH")
    p.add_argument("--file-text", action="append", default=[], metavar="NAME=TEXT",
                   help="start file parameter NAME with a file holding TEXT")
    p.add_argument("--data", help="TEXT for the App's only file parameter (same as --file-text NAME=TEXT)")
    p.add_argument("--data-from", help="PATH for the App's only file parameter (same as --file NAME=PATH)")
    p.add_argument("--kw", action="append", default=[], help="extra App argument NAME=VALUE (Python literal)")
    p.add_argument("--checks", metavar="FILE", help="run each line of FILE (NAME: [options] STEP ...) as a check")
    p.add_argument("--builtin", action="store_true", help="also run the harness's own checks")
    p.add_argument("--empty", action="store_true", help="start data files missing even when the project has one")
    p.add_argument("steps", nargs="*")
    return p


def load_app(config: dict):
    sys.path.insert(0, ".")
    return getattr(importlib.import_module(config["module"]), config["app_class"])


def prepare(config: dict, a, tmp: Path):
    """The App's arguments for these options: (kw, data files, fake clock, what was passed), or an exit code."""
    params = config.get("params") or []
    files = [p for p in params if p["role"] in FILE_ROLES]
    names = [p["name"] for p in files]
    texts, copies = pairs(a.file_text, "--file-text", names), pairs(a.file, "--file", names)
    if texts is None or copies is None:
        return 2
    if a.data is not None or a.data_from:
        if len(files) != 1:
            say(f"--data/--data-from need exactly one file parameter, and {config['app_class']} has "
                  f"{len(files)}{': ' + ', '.join(names) if names else ''}. Use --file NAME=PATH or --file-text NAME=TEXT.")
            return 2
        if a.data is not None:
            texts[names[0]] = a.data
        else:
            copies[names[0]] = a.data_from
    kw, data_files, said = {}, {}, []
    for f in files:
        default = f.get("file") or ("data.json" if f["role"] == "data" else "input.txt")
        path = tmp / f["name"] / default
        path.parent.mkdir(parents=True)
        if f["name"] in texts and path.suffix in SQLITE:
            say(f"{f['name']} is a SQLite database: --file-text can't fill it. Start without it and add records "
                "with steps (then restart to check they were kept), or use --file NAME=PATH with a database file.")
            return 2
        if f["name"] in texts:
            text = texts[f["name"]]
            if path.suffix != ".json" and "\n" not in text:  # one-line text for a CSV/text file:
                text = text.replace("\\n", "\n").replace("\\t", "\t")  # \n and \t mean line break, tab
            path.write_text(text)
        elif f["name"] in copies:
            if not Path(copies[f["name"]]).is_file():
                say(f"--file {f['name']}=PATH copies a file, and there is no file {copies[f['name']][:60]!r}. "
                    f"To give the contents, use --file-text {f['name']}='...'")
                return 2
            shutil.copy(copies[f["name"]], path)
        elif Path(default).is_file() and (f["role"] == "input" or not a.empty):
            # a data file the project already has (e.g. shipped records) starts as a copy, as
            # `python app.py` would read it; the harness's own no-file check passes --empty
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
        # the value and its type as the App gets it (the 35B passed a list-of-rows board as one string,
        # bent the app to split it, and chased an IndexError from a 4-character row)
        said.append(f"{key}={cut(repr(kw[key]))} ({type(kw[key]).__name__})")
    return kw, data_files, clock, said


def try_once(config: dict, cls, a, stop_on_fail=False) -> int:
    tmp = Path(tempfile.mkdtemp(prefix="try-", dir=".lightness"))
    try:
        prepared = prepare(config, a, tmp)
        if isinstance(prepared, int):
            return prepared
        kw, data_files, clock, said = prepared
        if said:
            say("parameters: " + "; ".join(said))
        return asyncio.run(run(cls, kw, data_files, clock, a.steps, stop_on_fail))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


DETAIL = 30  # lines of a failing check's output shown
STEP_NOTE = re.compile(r"can't be clicked|no widget matches|did nothing: |as text: an Input has focus|"
                       r"dropped the keys that don't fit|needs a clock parameter")


# a name that is really a step or an option: the steps were written where the name goes
BAD_NAME = re.compile(r"^(--|(type|press|click|focus|wait|advance|restart|expect|expect-not|expect-file)(:|$))")


NAMES: set[str] = set()
# a compound selector (#cell-1.cursor, #a:focus, #a > b): never screen text. A bare #id is fine (the dump
# prints "#id ..."), and so is ".word" (data often has it: "$.service", ".5"); if it is meant as a class,
# the runtime failure says so (CLASS_LIKE).
# (not "#path: '$'": a line copied from the dump, colon then space, is real screen text)
SELECTOR = re.compile(r"^#[\w-]+(\.[\w-]|:[a-z]|\[| *> )")
CLASS_LIKE = re.compile(r"^(\.[\w-]+$|#[\w-]+(\.[\w-]|:[a-z]|\[| *> ))")  # one bare .class, or a compound selector
# type:enter typed the word "enter" into an input (the 35B, bookmarks); a whole value that is a key name
TYPED_KEYS = {"enter", "tab", "escape", "esc", "space", "backspace", "delete", "up", "down", "left", "right"}
STEP_NAMES = ("type", "press", "click", "focus", "wait", "advance", "expect", "expect-not", "expect-file")
OPTIONS = ("--file", "--file-text", "--kw", "--data", "--data-from")
# a step glued to the one before by a comma (press:down,down,press:enter): the 35B read "one step per word"
# as "no commas" and swapped every comma for a space, then back
NEW_STEP = ("a new step starts a new word: keys inside one press: are separated by commas (press:down,down,enter), "
            "and the next step comes after a space (press:down*2 expect:x); quote text with spaces, e.g. "
            "type:\"My Site\"")


def key_names() -> set[str]:
    from textual import keys
    return ({k.value for k in keys.Keys} | set(keys.KEY_ALIASES) | {"space", "enter", "tab", "escape"}
            | {keys._character_to_key(chr(c)) for c in range(33, 127)})


REPEAT = re.compile(r"^(.+)\*(\d+)$")


def keys_of(value: str) -> list[str]:
    """The keys of a press: step, with KEY*N repeated N times (counting 15 downs by hand goes wrong)."""
    keys = []
    for k in (k.strip() for k in value.split(",")):
        m = REPEAT.match(k) if k != "*" else None
        keys += [m.group(1)] * int(m.group(2)) if m else [k] if k else []
    return keys


def valid_key(key: str, names: set[str]) -> bool:
    while "+" in key[:-1] and key.split("+", 1)[0] in ("ctrl", "shift", "alt", "meta", "super"):
        key = key.split("+", 1)[1]
    return len(key) == 1 or key in names


def lint(tokens: list[str], files: list[str] | None = None) -> list[str]:
    """Every mistake in one check's steps that can be seen without running it (files: the App's file
    parameter names, for --file/--file-text/expect-file)."""
    problems, i = [], 0
    global NAMES
    NAMES = NAMES or key_names()
    while i < len(tokens):
        tok = tokens[i]
        opt = tok.split("=", 1)[0]
        if opt in OPTIONS:
            value = tok.split("=", 1)[1] if "=" in tok else (tokens[i + 1] if i + 1 < len(tokens) else "")
            param = value.split("=", 1)[0]
            if opt == "--kw" and (literal := value.split("=", 1)[1] if "=" in value else "").strip()[:1] in ("[", "{", "("):
                try:
                    ast.literal_eval(literal)
                except (ValueError, SyntaxError):
                    # the line's own quoting ate the quotes inside (--kw board=["#.", ...] → [#., ...])
                    problems.append(f"--kw {value[:50]}: not a Python literal once the line is split (quotes inside "
                                    f"were removed); wrap the whole option in single quotes: --kw '{param}=[\"a\", \"b\"]'")
            if files is not None and opt == "--kw" and param in files:
                # the 35B pointed a database at /tmp (not writable) with --kw and spent 3 steps on it
                problems.append(f"--kw {param}=...: {param} is a file parameter, and every check already gets a "
                                f"fresh file for it; leave it out (start empty), or give contents with "
                                f"--file-text {param}=TEXT")
            if files is not None and opt in ("--file", "--file-text") and param not in files:
                problems.append(f"{opt} {param}=...: {param!r} is not a file parameter of the App "
                                f"(they are: {', '.join(files) or 'none'})")
            i += 1 if "=" in tok else 2
            continue
        if tok.startswith("-"):
            problems.append(f"{tok!r} is not an option (options: {', '.join(OPTIONS)})")
        elif tok == "restart":
            pass
        elif re.search(r",(type|press|click|focus|expect|expect-not|expect-file|wait|advance):", tok):
            problems.append(f"{tok[:50]!r}: " + NEW_STEP)
        elif ":" not in tok or tok.split(":", 1)[0] not in STEP_NAMES:
            problems.append(f"{tok!r} is not a step: text with spaces needs quotes, e.g. type:\"two words\"")
        else:
            action, value = tok.split(":", 1)
            if action == "type" and value.strip().lower() in TYPED_KEYS:
                problems.append(f"{tok!r} types the word {value.strip()!r}; to press the key, press:{value.strip().lower()}")
            elif action in ("expect", "expect-not") and not value.strip():
                problems.append(f"{tok!r} has no text to look for")
            elif action in ("expect", "expect-not") and SELECTOR.match(value):
                problems.append(f"{tok!r}: expect matches text on the screen, not a CSS selector (a bare #id "
                                "works: the screen lists each shown widget as #id ...)")
            elif action == "expect-file" and files is not None and value.split("=", 1)[0] not in files:
                problems.append(f"{tok[:40]!r}: expect-file takes a file parameter's name, not a file name "
                                f"(they are: {', '.join(files) or 'none'})")
            elif action == "press" and value.startswith("#"):
                problems.append(f"{tok!r}: press takes key names; to press a button, click:{value}")
            elif action == "press" and (bad := [k for k in dict.fromkeys(keys_of(value)) if not valid_key(k, NAMES)]):
                problems.append(f"{tok!r}: {', '.join(map(repr, bad))} is not a key (keys: a, enter, tab, escape, space, up, "
                                f"ctrl+s, ...; to press a button, click:#id)")
            elif re.search(r",(type|press|click|focus|expect|expect-not|expect-file|wait|advance):", value):
                problems.append(f"{tok[:50]!r}: " + NEW_STEP)
        i += 1
    return problems


CHECK_SECONDS = int(os.environ.get("TRY_CHECK_SECONDS", "20"))


class CheckTimeout(Exception):
    pass


def _check_timed_out(signum, frame):
    raise CheckTimeout


def file_checks(config: dict, cls, path: Path) -> list[tuple[str, str | None]]:
    """(name, None if it passed else its output) for each line of a checks file."""
    out, seen = [], {}
    for n, line in enumerate(path.read_text().splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name, sep, rest = line.partition(": ")
        if sep and name.strip() in seen:
            out.append((f"line {n}", f"the name {name.strip()!r} is already used on line {seen[name.strip()]}: give "
                        "each check its own name (it is how the report tells them apart)"))
            continue
        seen.setdefault(name.strip(), n)
        if not sep or BAD_NAME.match(name.strip()):
            out.append((f"line {n}", f"not a check: {line[:80]!r}. A check line is a short name of your own, then "
                        "': ', then the steps, e.g.\n    typing marks it modified: type:hello expect:modified"))
            continue
        try:
            problems = lint(shlex.split(rest), [p["name"] for p in config.get("params") or [] if p["role"] in FILE_ROLES])
        except ValueError as e:
            problems = [f"can't split the line into steps: {e}"]
        if problems:
            out.append((name.strip(), "not run: " + "; ".join(problems)))
            continue
        buf = io.StringIO()
        OUT[0] = buf
        with contextlib.redirect_stderr(buf):
            try:
                # each check gets its own limit, so one that hangs the app fails alone (SIGALRM also
                # interrupts a handler stuck in a blocking loop, which an asyncio timeout can't)
                signal.signal(signal.SIGALRM, _check_timed_out)
                signal.alarm(CHECK_SECONDS)
                rc = try_once(config, cls, parser().parse_args(shlex.split(rest)), stop_on_fail=True)
            except CheckTimeout:
                rc = 1
                say(f"this check did not finish within {CHECK_SECONDS}s: the app hangs (an endless loop or a wait) "
                    "at the step after the last one shown above")
            except ValueError as e:  # shlex: unbalanced quotes
                rc = 2
                say(f"can't split the line into steps: {e}")
            except SystemExit:  # argparse rejected an option
                rc = 2
            finally:
                signal.alarm(0)
                OUT[0] = sys.stdout
        # Textual's own boxed traceback (stderr) repeats the CRASH summary below it: leave it out
        lines = [x for x in buf.getvalue().rstrip().splitlines() if not x.lstrip().startswith(("\u256d", "\u2502", "\u2570"))]
        # a step note (a key that did nothing, a click that missed) is often the reason the expect failed:
        # keep it when the long output is cut (json-viewer: "right did nothing" was above the last 30 lines)
        notes = [x for x in lines[:-DETAIL] if STEP_NOTE.search(x)]
        detail = "\n".join(notes + lines[-DETAIL:])
        if rc != 0 and all(t.split(":", 1)[0] in ("expect", "expect-not", "expect-file") for t in shlex.split(rest)
                           if not t.startswith("-")):
            detail = ("(this check has no steps before its expects, so it looked at a freshly started app; "
                      "it doesn't continue from the check above it)\n" + detail)
        out.append((name.strip(), None if rc == 0 else detail))
    return out


def app_keys(cls) -> list[str]:
    """The keys the app's own classes bind (not Textual's defaults), without quit."""
    keys = []
    for c in cls.__mro__:
        if c.__module__ != cls.__module__:
            continue
        for b in c.__dict__.get("BINDINGS", []):
            key, action = (b.key, b.action) if hasattr(b, "key") else (b[0], b[1])
            if action.split("(")[0].removeprefix("app.") in ("quit", "command_palette"):
                continue
            keys += [k.strip() for k in key.split(",") if k.strip()]
    return list(dict.fromkeys(keys))


NO_FOCUS = "nothing"


async def focus_targets(cls, kw) -> list[str | None]:
    """Where keys get pressed: the starting focus, then each focusable widget with an id that
    doesn't take typed text (at most 2), then nothing focused if the start focus takes text
    (printable keys typed into an Input never reach the app's bindings)."""
    from textual.widgets import Input, TextArea

    app = cls(**kw)
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        ids = [f"#{w.id}" for w in app.screen.query("*")
               if w.focusable and w.id and not w.id.startswith("-") and not isinstance(w, (Input, TextArea))]
        typing = isinstance(app.focused, (Input, TextArea))
    return [None] + ids[:2] + ([NO_FOCUS] if typing else [])


async def unclickable_buttons(cls, kw, focus: str | None, keys: list[str]) -> tuple[bool, dict]:
    """(any button seen, {(screen, id): problem}): every Button with an id on the start screen and on each screen a key
    opens must be clickable. bookmarks (passes 2 and 4): the dialog's Cancel was cut off, the model's
    check focused it and pressed enter, and a click (as a user, or the hidden tests, would do) missed."""
    from textual.widgets import Button, TabbedContent, TabPane

    seen, problems = False, {}
    where = f" with {focus} focused" if focus else ""

    def check(after: str) -> None:
        nonlocal seen
        for b in app.screen.query(Button):
            seen = True
            key = (type(app.screen).__name__, b.id)
            if not b.id or b.id.startswith("-") or not b.region.area or key in problems:
                continue  # no area: not shown at all (e.g. in a tab that isn't active), so not a layout slip
            if (why := not_clickable(app, f"#{b.id}")) is not None:
                problems[key] = (f"#{b.id} {after} can't be clicked: {why}. A user couldn't click it either: fix the "
                                 "layout (sizes of it and its container; a dialog's box needs room for every line in it)")

    app = cls(**kw)
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        check("on the start screen")
        # buttons in tabs that aren't active take no space: show each tab in turn (trip-split pass 5: the
        # Expenses tab's Add button was cut off; its checks pressed enter, the hidden test clicked)
        for tabs in list(app.screen.query(TabbedContent)):
            start = tabs.active
            for pane in list(tabs.query(TabPane)):
                if pane.id and pane.id != start:
                    tabs.active = pane.id
                    await pilot.pause()
                    check(f"(on tab {pane.id})")
            tabs.active = start
            await pilot.pause()
        base = app.screen
        for key in keys:
            if focus == NO_FOCUS:
                app.set_focus(None)
            elif focus and app.screen.query(focus):
                app.screen.query_one(focus).focus()
            await pilot.pause()
            await pilot.press(key)
            await pilot.pause()
            if not app.is_running:
                break
            if app.screen is not base:
                check(f"(after pressing {key}{where}, on {type(app.screen).__name__})")
                while app.screen is not base and len(app.screen_stack) > 1:
                    app.pop_screen()
                    await pilot.pause()
    return seen, problems


async def press_keys(cls, kw, data_files, focus: str | None, keys: list[str]) -> str | None:
    """Press each key in turn in a fresh app (FOCUS focused first). If that changed a data file,
    start again and check the start leaves the file as it was. None, or what went wrong."""
    before = files_now(data_files)
    where = f" with {focus} focused" if focus else ""
    pressed = []
    try:
        app = cls(**kw)
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            if focus == NO_FOCUS:
                app.set_focus(None)
                await pilot.pause()
            elif focus and app.screen.query(focus):
                app.screen.query_one(focus).focus()
                await pilot.pause()
            for key in keys:
                pressed.append(key)
                await pilot.press(key)
                await pilot.pause()
                if not app.is_running:
                    break
    except Exception:  # noqa: BLE001
        return f"pressing {', '.join(pressed)}{where} crashes on {pressed[-1] if pressed else 'start'}:\n" + crash_text()
    saved = files_now(data_files)
    if saved == before:
        return None
    try:
        app = cls(**kw)
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
    except Exception:  # noqa: BLE001
        return f"after pressing {', '.join(pressed)}{where} the app saved its file, then crashes when started again:\n" + crash_text()
    for param, was, now in zip(data_files, saved, files_now(data_files)):
        if was != now:
            return (f"after pressing {', '.join(pressed)}{where} the {param} file held {was}; starting the app "
                    f"again changed it to {now} (a start must load the saved file, not overwrite it)")
    return None


def builtin_checks(config: dict, cls) -> list[tuple[str, str | None]]:
    """Checks every app of this kind should pass: each bound key works (no crash) with no data file
    and with the sample file, a start keeps what was saved, and time can move."""
    params = config.get("params") or []
    files = [p for p in params if p["role"] in FILE_ROLES]
    sample = (config.get("sample_data") or "").strip()
    cases = [("no data file" if any(p["role"] == "data" for p in files) else "a fresh start", [])]
    if files and sample:
        cases.append((f"the sample {files[0]['name']} file", [f"{files[0]['name']}={sample}"]))
    keys = app_keys(cls)[:12]
    out = []

    async def fresh(file_args: list[str], run):
        """Run run(kw, data_files) on fresh files for this case."""
        tmp = Path(tempfile.mkdtemp(prefix="check-", dir=".lightness"))
        try:
            kw, data_files, _, _ = prepare(config, parser().parse_args(file_args), tmp)
            return await run(kw, data_files)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    async def case_check(file_args: list[str]) -> list[str]:
        try:
            targets = await fresh(file_args, lambda kw, _: focus_targets(cls, kw))
        except Exception:  # noqa: BLE001
            return ["the app crashes on start:\n" + crash_text()]
        problems = []
        for focus in targets:
            problem = await fresh(file_args, lambda kw, files: press_keys(cls, kw, files, focus, keys))
            if problem is not None:
                problems.append(problem)
        return problems

    for label, file_text in cases:
        if not keys:
            break
        problems = asyncio.run(case_check([f"--file-text={t}" for t in file_text] + ([] if file_text else ["--empty"])))
        out.append((f"harness: every key works, starting with {label}", "\n".join(problems[:3]) or None))

    async def buttons() -> tuple[bool, list[str]]:
        try:
            targets = await fresh(["--empty"], lambda kw, _: focus_targets(cls, kw))
        except Exception:  # noqa: BLE001 - a start crash is reported by the key check
            return False, []
        seen, problems = False, {}
        for focus in targets:
            try:
                s, p = await fresh(["--empty"], lambda kw, _: unclickable_buttons(cls, kw, focus, keys))
            except Exception:  # noqa: BLE001 - key crashes are reported by the key check
                continue
            seen = seen or s
            problems = p | problems  # the first focus that showed it
        return seen, list(problems.values())

    seen, problems = asyncio.run(buttons())
    if seen:
        out.append(("harness: every button can be clicked", "\n".join(problems[:3]) or None))
    if any(p["role"] == "clock" for p in params):
        async def time_moves():
            tmp = Path(tempfile.mkdtemp(prefix="check-", dir=".lightness"))
            try:
                kw, data_files, clock, _ = prepare(config, parser().parse_args([]), tmp)
                app = cls(**kw)
                async with app.run_test(size=(100, 30)) as pilot:
                    await pilot.pause()
                    for key in keys or [None]:
                        if key:
                            await pilot.press(key)
                        clock.t += 3600 / max(1, len(keys))
                        await pilot.pause(0.2)  # a jump, not slices: timers tick once and read it
                return None
            except Exception:  # noqa: BLE001
                return "moving the clock an hour (pressing each key on the way) crashes:\n" + crash_text()
            finally:
                shutil.rmtree(tmp, ignore_errors=True)

        out.append(("harness: time moves (an hour on the fake clock)", asyncio.run(time_moves())))

        # stopwatch (passes 3, 4, 5): pause right after time passed still showed 00:00.0 until the next timer
        # tick; try's advance: lets the timer tick, so no check of the model's could see it, and notes didn't help
        async def after_pair(k1: str, k2: str, tick: bool) -> list[str]:
            tmp = Path(tempfile.mkdtemp(prefix="check-", dir=".lightness"))
            try:
                kw, _, clock, _ = prepare(config, parser().parse_args(["--empty"]), tmp)
                app = cls(**kw)
                async with app.run_test(size=(100, 30)) as pilot:
                    await pilot.pause()
                    await pilot.press(k1)
                    await pilot.pause()
                    clock.t += 3.0625
                    if tick:
                        await pilot.pause(0.3)
                    await pilot.press(k2)
                    await pilot.pause()
                    return [line for lines in snapshot(app).values() for line in lines]
            finally:
                shutil.rmtree(tmp, ignore_errors=True)

        async def keys_show_at_once() -> str | None:
            pairs = list(dict.fromkeys([(k, k) for k in keys[:6]] + [(keys[0], k) for k in keys[1:6]]))
            for k1, k2 in pairs:
                try:
                    ticked, not_ticked = await after_pair(k1, k2, True), await after_pair(k1, k2, False)
                except Exception:  # noqa: BLE001 - crashes are reported by the key check
                    continue
                if ticked != not_ticked:
                    a, b = next(((x, y) for x, y in zip(ticked, not_ticked) if x != y), (ticked[-1:], not_ticked[-1:]))
                    return (f"pressing {k1}, letting 3 s pass, then pressing {k2} shows {cut(str(a).strip())!r} when a "
                            f"timer tick came in between, but {cut(str(b).strip())!r} when it didn't: a key must update "
                            "the screen in its own handler (call your tick/refresh method there), not wait for the next tick")
            return None

        if keys:
            out.append(("harness: a key's effect shows at once, without waiting for a timer tick",
                        asyncio.run(keys_show_at_once())))
    if seeds := [p["name"] for p in params if p["role"] == "seed"]:
        # lights-out (passes 2 and 4): the 35B made self.rng = random.Random(seed), then drew from
        # random.choice, so the same seed gave a different puzzle; no check of its own could see that
        async def start_screen():
            tmp = Path(tempfile.mkdtemp(prefix="check-", dir=".lightness"))
            try:
                kw, _, _, _ = prepare(config, parser().parse_args(["--empty"]), tmp)
                app = cls(**kw, **{name: 7 for name in seeds})
                async with app.run_test(size=(100, 30)) as pilot:
                    await pilot.pause()
                    return [line for lines in snapshot(app).values() for line in lines]
            finally:
                shutil.rmtree(tmp, ignore_errors=True)

        async def same_seed():
            try:
                first, second = await start_screen(), await start_screen()
            except Exception:  # noqa: BLE001
                return f"starting with {seeds[0]}=7 crashes:\n" + crash_text()
            if first == second:
                return None
            diff = next(((x, y) for x, y in zip(first, second) if x != y), (first[-1:], second[-1:]))
            return (f"two starts with {seeds[0]}=7 showed different screens ({cut(str(diff[0]).strip())!r}, then "
                    f"{cut(str(diff[1]).strip())!r}): draw every random number from one random.Random({seeds[0]}) kept on "
                    f"self (self.rng.choice(...)), never from the random module's own functions")

        out.append((f"harness: the same {seeds[0]} gives the same start", asyncio.run(same_seed())))
    return out


def run_checks(config: dict, cls, a) -> int:
    results = builtin_checks(config, cls) if a.builtin else []
    if a.checks:
        path = Path(a.checks)
        if path.exists():
            results += file_checks(config, cls, path)
        else:
            say(f"(no {a.checks} yet)")
    for name, problem in results:
        say(f"{'PASS' if problem is None else 'FAIL'} {name}")
        if problem is not None:
            say("\n".join("    " + line for line in problem.splitlines()))
    passed = sum(problem is None for _, problem in results)
    say(f"{passed} of {len(results)} checks pass")
    return 0 if passed == len(results) else 1


def main() -> int:
    config = json.loads((Path(__file__).parent / "try_app.json").read_text())
    a = parser().parse_args()
    cls = load_app(config)
    if a.checks or a.builtin:
        return run_checks(config, cls, a)
    return try_once(config, cls, a)


if __name__ == "__main__":
    sys.exit(main())
