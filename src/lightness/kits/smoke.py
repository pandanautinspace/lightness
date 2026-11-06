"""Smoke checks: does the program start? Run by the harness after changes, in the sandbox.

Only "starts and quits without an error" is checked here; what the program does is the job
of tests and contract scenarios.
"""

import ast
import functools
import importlib
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from lightness.bench import sandbox
from lightness.kits import default_file, file_params
from lightness.verify.chain import BIN
from lightness.verify.compress import traceback_summary

TUI_SNIPPET = """
import asyncio, importlib, sys
sys.path.insert(0, ".")
mod = importlib.import_module({module!r})
cls = getattr(mod, {app_class!r}, None)
if cls is None:
    print("SMOKE: {module}.py has no class {app_class}"); sys.exit(3)
kwargs = {kwargs!r}

async def main():
    app = cls(**kwargs)
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()

from textual.css.stylesheet import StylesheetParseError
{css_func}
try:
    asyncio.run(main())
except StylesheetParseError as e:
    print("SMOKE: " + css_error_text(e)); sys.exit(3)
print("SMOKE-OK")
"""


CSS_FUNC = 'def css_error_text(exc) -> str:\n    """A Textual StylesheetParseError as plain lines: each bad CSS line and what is wrong with it."""\n    import io\n    from rich.console import Console\n    buf = io.StringIO()\n    Console(file=buf, width=100, no_color=True, color_system=None).print(exc.errors)\n    out = []\n    for line in buf.getvalue().splitlines():\n        t = line.strip()\n        if not t or t[0] in "\\u256d\\u2570":  # panel top/bottom borders\n            continue\n        if t.startswith("\\u2502"):  # a code line inside the panel: keep only the marked one\n            if "\\u2771" in t:\n                out.append("  at CSS line: " + t.strip("\\u2502 ").replace("\\u2771", "").strip())\n            continue\n        out.append("  " + t)\n    return "CSS error in the app\'s CSS:\\n" + "\\n".join(out[:24])\n'


@dataclass
class SmokeResult:
    ok: bool
    case: str  # which start was checked
    detail: str = ""


def _python(code: str, ws: Path, run_dir: Path | None, timeout: int, args: list[str] | None = None) -> subprocess.CompletedProcess:
    """Run python -c CODE (or python ARGS) in the workspace, sandboxed when run_dir is given."""
    cmd = [str(BIN / "python"), *(args if args is not None else ["-c", code])]
    env = os.environ | {"PYTHONDONTWRITEBYTECODE": "1"}
    if run_dir is not None:
        cmd = [*sandbox.sandbox_prefix(run_dir), *cmd]
        env |= sandbox.sandbox_env(run_dir)
    try:
        return subprocess.run(cmd, cwd=ws, env=env, capture_output=True, text=True, errors="replace",
                              timeout=timeout, stdin=subprocess.DEVNULL, check=False)
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(cmd, 124, "", f"did not finish starting within {timeout}s")


def tui(ws: Path, names: dict, run_dir: Path | None = None, timeout: int = 30) -> list[SmokeResult]:
    """Start the app headless with no data files, and with the sample contents in its first file.

    Every file parameter gets a path of its own in a temp dir. Data files start missing; an input
    file is a copy of the project's file of that name when there is one."""
    module, app_class = names["module"], names["app_class"]
    if not (ws / f"{module}.py").exists():
        return []
    files = file_params(names)
    base = Path(tempfile.mkdtemp(dir=(run_dir / "tmp") if run_dir else None, prefix="smoke-"))

    def paths(case: str) -> dict[str, str]:
        (base / case).mkdir()
        out = {}
        for p in files:
            out[p["name"]] = str(base / case / default_file(p))
            if p["role"] == "input" and (ws / default_file(p)).is_file():
                shutil.copy(ws / default_file(p), out[p["name"]])
        return out

    data = [p for p in files if p["role"] == "data"]
    cases: list[tuple[str, dict, str | None]] = [
        ("starting with no data file" if data else "starting", paths("fresh"), None)]
    sample = (names.get("sample_data") or "").strip()
    if files and sample:
        first = files[0]
        label = "an existing data file" if first["role"] == "data" else "an input file"
        cases.append((f"starting with {label} ({first['name']})", paths("sample"), sample))
    results = []
    for case, kwargs, content in cases:
        if content is not None:
            Path(kwargs[files[0]["name"]]).write_text(content)
        proc = _python(TUI_SNIPPET.format(module=module, app_class=app_class, kwargs=kwargs, css_func=CSS_FUNC), ws, run_dir, timeout)
        out = proc.stdout + proc.stderr
        if proc.returncode == 0 and "SMOKE-OK" in proc.stdout:
            results.append(SmokeResult(True, case))
        else:
            detail = proc.stdout[proc.stdout.index("SMOKE:") + 7:].strip() if "SMOKE:" in proc.stdout else traceback_summary(out, ws)
            if content:
                detail += f"\n(file contents: {content[:300]})"
            results.append(SmokeResult(False, case, detail))
    return results


# Names a Textual subclass is meant to define: handlers, hooks and class-level settings.
OVERRIDES = {"compose", "render", "BINDINGS", "CSS", "CSS_PATH", "DEFAULT_CSS", "TITLE", "SUB_TITLE", "SCREENS",
             "MODES", "COMMANDS", "AUTO_FOCUS", "can_focus", "can_focus_children", "check_action"}
OVERRIDE_PREFIXES = ("on_", "action_", "watch_", "validate_", "compute_", "key_", "_on_", "_watch_")


@functools.cache
def _textual_names(cls: type) -> tuple[frozenset[str], frozenset[str]]:
    """(every name a cls instance has, the reactives among them). Instance names include attributes
    set in __init__ (like App._running), so it tries an instance first."""
    from textual.reactive import Reactive

    try:
        names = set(dir(cls()))
    except Exception:  # noqa: BLE001 - a base that needs arguments: its class names will do
        names = set(dir(cls))
    reactives = {k for c in cls.__mro__ for k, v in vars(c).items() if isinstance(v, Reactive)}
    return frozenset(names), frozenset(reactives)


def _textual_bases(tree: ast.Module) -> dict[str, type]:
    """Classes in the module whose bases resolve to a Textual App, Screen or Widget → that Textual class."""
    from textual.app import App
    from textual.widget import Widget  # Screen is a Widget

    imported: dict[str, str] = {}  # local name → dotted textual path
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("textual"):
            for a in node.names:
                imported[a.asname or a.name] = f"{node.module}.{a.name}"
        elif isinstance(node, ast.Import):
            for a in node.names:
                if a.name.startswith("textual"):
                    imported[a.asname or a.name.split(".")[0]] = a.asname and a.name or a.name.split(".")[0]

    def lookup(dotted: str):
        parts = dotted.split(".")
        for i in range(len(parts), 0, -1):
            try:
                obj = importlib.import_module(".".join(parts[:i]))
            except ImportError:
                continue
            for attr in parts[i:]:
                obj = getattr(obj, attr, None)
            return obj
        return None

    def dotted(expr) -> str | None:
        if isinstance(expr, ast.Name):
            return expr.id
        if isinstance(expr, ast.Attribute) and (head := dotted(expr.value)):
            return f"{head}.{expr.attr}"
        return None

    classes = {n.name: n for n in tree.body if isinstance(n, ast.ClassDef)}
    found: dict[str, type] = {}

    def resolve(cls: ast.ClassDef, seen=()) -> type | None:
        for base in cls.bases:
            name = dotted(base)
            if name is None:
                continue
            head, _, rest = name.partition(".")
            if head in classes and not rest and head not in seen:
                if (hit := resolve(classes[head], (*seen, head))) is not None:
                    return hit
            elif head in imported:
                obj = lookup(imported[head] + ("." + rest if rest else ""))
                if isinstance(obj, type) and issubclass(obj, (App, Widget)):
                    return obj
        return None

    for name, cls in classes.items():
        if (hit := resolve(cls)) is not None:
            found[name] = hit
    return found


def _own_names(cls: ast.ClassDef) -> list[tuple[str, str]]:
    """(name, how) for what the class defines: methods, class attributes and self.X assignments."""
    out, reactives = [], set()
    for node in cls.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.append((node.name, "method"))
        targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, ast.AnnAssign) else []
        for t in targets:
            if isinstance(t, ast.Name):
                value = node.value
                call = value.func if isinstance(value, ast.Call) else None
                fname = call.id if isinstance(call, ast.Name) else call.attr if isinstance(call, ast.Attribute) else ""
                if fname in ("reactive", "var", "Reactive"):
                    reactives.add(t.id)
                else:
                    out.append((t.id, "class"))

    def walk(node):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef):
                continue
            targets = child.targets if isinstance(child, ast.Assign) else [child.target] if isinstance(child, ast.AnnAssign) else []
            flat = [e for t in targets for e in (t.elts if isinstance(t, (ast.Tuple, ast.List)) else [t])]
            for t in flat:
                if isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name) and t.value.id == "self":
                    out.append((t.attr, "self"))
            walk(child)

    walk(cls)
    return [(n, how) for n, how in dict.fromkeys(out) if n not in reactives]


def clashes(ws: Path, names: dict) -> list[str]:
    """Warnings for names the app's Textual subclasses set or define that Textual's base already
    uses (e.g. self._running on an App): those silently break the app. Never blocks."""
    path = ws / f"{names['module']}.py"
    try:
        tree = ast.parse(path.read_text())
    except (OSError, SyntaxError, ValueError):
        return []
    classes = {n.name: n for n in tree.body if isinstance(n, ast.ClassDef)}
    warnings = []
    for cls_name, base in _textual_bases(tree).items():
        taken, reactives = _textual_names(base)
        seen = set()
        for name, how in _own_names(classes[cls_name]):
            if (name in seen or name not in taken or name in reactives or name in OVERRIDES
                    or name.startswith(OVERRIDE_PREFIXES) or name.isupper() or (name.startswith("__") and name.endswith("__"))):
                continue
            seen.add(name)
            what = {"self": f"sets self.{name}", "method": f"defines {name}()", "class": f"defines {name}"}[how]
            hint = f"self.my_{name.lstrip('_')}" if how != "method" else f"my_{name.lstrip('_')}()"
            warnings.append(f"warning: {cls_name} {what}, which Textual's {base.__name__} already uses; "
                            f"rename it (e.g. {hint}).")
    return warnings


def summarize(results: list[SmokeResult], target: str) -> str:
    bad = [r for r in results if not r.ok]
    if not bad:
        return f"{target} starts cleanly ({'; '.join(r.case for r in results)})."
    return "\n".join(f"{target} crashes when {r.case}:\n{r.detail}" for r in bad)


CHECKS_FILE = "checks.txt"
TRY = ".lightness/kit/try_app.py"


def checks(ws: Path, run_dir: Path | None = None, timeout: int = 180) -> dict[str, str | None] | None:
    """Run the harness's own checks and the model's checks.txt through the try command:
    {check name: None if it passed, else what it printed}. None if they could not run."""
    if not (ws / TRY).exists():
        return None
    args = [TRY, "--builtin"] + (["--checks", CHECKS_FILE] if (ws / CHECKS_FILE).exists() else [])
    proc = _python("", ws, run_dir, timeout, args)
    results: dict[str, str | None] = {}
    name = None
    for line in proc.stdout.splitlines():
        verdict, _, rest = line.partition(" ")
        if verdict in ("PASS", "FAIL") and rest:
            name = rest
            results[name] = None if verdict == "PASS" else ""
        elif name is not None and results[name] is not None and line.startswith("    "):
            results[name] += line[4:] + "\n"
    if proc.returncode == 124:
        return {"the checks could not run": f"they did not finish within {timeout}s (a check that waits, or an app that hangs)"}
    if not results and proc.returncode != 0:
        detail = (proc.stdout + proc.stderr).strip().splitlines()[-1:] or ["no output"]
        return {"the checks could not run": detail[0]}
    return results
