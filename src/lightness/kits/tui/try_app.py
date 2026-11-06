"""Try the app: start it headless, run steps, print what the screen and data file show.

Copied into the workspace by the harness; the model runs it instead of writing test code.

    python .lightness/kit/try_app.py [--file NAME=PATH] [--file-text NAME=TEXT] [--kw NAME=VALUE] STEP ...

Steps: type:TEXT  press:KEY[,KEY...]  click:#id  focus:#id  wait:SECONDS  advance:SECONDS  restart
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
import ast
import asyncio
import contextlib
import io
import importlib
import json
import math
import re
import shlex
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
        self.t = t

    def __call__(self) -> float:
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


def show_changes(before: dict[str, list[str]], after: dict[str, list[str]], files_changed: bool = False) -> None:
    if before.get("screen") != after.get("screen"):
        say(f"  (now on {after['screen'][0][8:] if 'screen' in after else 'the main screen'})")
        show(after)
        return
    changed = False
    for key, lines in after.items():
        if before.get(key) != lines:
            changed = True
            for line in lines:
                say("  " + line)
    for key in before:
        if key not in after:
            changed = True
            say(f"  {key}: (no longer shown)")
    if not changed and not files_changed:
        say("  (nothing changed)")


def screen_text(state: dict[str, list[str]]) -> str:
    return " ".join(" ".join(line.split()) for lines in state.values() for line in lines)


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
    if action == "expect":
        if found:
            return None
        if want.lower() in screen.lower():
            i = screen.lower().index(want.lower())
            return f"not on the screen (only with different case: {screen[i:i + len(want)]!r})"
        if re.match(r"^[#.][\w-]", want):
            return ("not on the screen: expect: matches text the screen shows, not a selector; use the text "
                    "that widget shows, as the screen dump below prints it")
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


def crash_text() -> str:
    exc = sys.exc_info()[1]
    if type(exc).__name__ == "StylesheetParseError":
        return "\n".join("  " + line for line in css_error_text(exc).splitlines())
    lines = traceback.format_exc().strip().splitlines()
    ours = [i for i, line in enumerate(lines) if 'File "' in line and "site-packages" not in line and "try_app" not in line]
    keep = lines[ours[-1]:] if ours else lines[-3:]
    return "\n".join("  " + line for line in keep[-6:])


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
                        await pilot.press(*value)
                    elif action == "press":
                        await pilot.press(*[k.strip() for k in value.split(",") if k.strip()])
                    elif action in ("click", "focus") and not app.screen.query(value):
                        ids = sorted(f"#{w.id}" for w in app.screen.query("*") if w.id and not w.id.startswith("-"))
                        say(f"  no widget matches {value!r} on this screen; ids here: {', '.join(ids) or 'none'}")
                        continue
                    elif action == "click":
                        if (hidden := not_clickable(app, value)) is not None:
                            say(f"  {value} can't be clicked: {hidden}. A user couldn't click it either: fix the "
                                "layout (sizes of it and its container), or focus it and press enter")
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
                        await advance(app, pilot, clock, float(value))
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


# a name that is really a step or an option: the steps were written where the name goes
BAD_NAME = re.compile(r"^(--|(type|press|click|focus|wait|advance|restart|expect|expect-not|expect-file)(:|$))")


def file_checks(config: dict, cls, path: Path) -> list[tuple[str, str | None]]:
    """(name, None if it passed else its output) for each line of a checks file."""
    out = []
    for n, line in enumerate(path.read_text().splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name, sep, rest = line.partition(": ")
        if not sep or BAD_NAME.match(name.strip()):
            out.append((f"line {n}", f"not a check: {line[:80]!r}. A check line is a short name of your own, then "
                        "': ', then the steps, e.g.\n    typing marks it modified: type:hello expect:modified"))
            continue
        buf = io.StringIO()
        OUT[0] = buf
        with contextlib.redirect_stderr(buf):
            try:
                rc = try_once(config, cls, parser().parse_args(shlex.split(rest)), stop_on_fail=True)
            except ValueError as e:  # shlex: unbalanced quotes
                rc = 2
                say(f"can't split the line into steps: {e}")
            except SystemExit:  # argparse rejected an option
                rc = 2
            finally:
                OUT[0] = sys.stdout
        lines = buf.getvalue().rstrip().splitlines()
        out.append((name.strip(), None if rc == 0 else "\n".join(lines[-DETAIL:])))
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
