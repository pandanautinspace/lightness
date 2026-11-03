"""Contract probes: machine checks derived from the spec's contract, run before `done`.

The model fills a fixed probe schema once (after the workshop); the harness runs the probes with
no model involved. They check what M0's agents misread or never ran: the app starts, the TUI
mounts, routes answer with the right status, required element ids exist, functions return the
promised shape, `--json` output parses.

Placeholders: `{tmp}` is a fresh temp dir per probe, `{port}` a free port.
"""

import json
import subprocess
import sys
import tempfile
import textwrap
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path

from lightness.bench import sandbox
from lightness.verify.procs import StartError, running

BIN = Path(sys.prefix) / "bin"

_FILES = {"type": "array", "items": {
    "type": "object",
    "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
    "required": ["path", "content"], "additionalProperties": False}}

PROBE_SCHEMA = {
    "type": "object",
    "properties": {"probes": {"type": "array", "items": {"anyOf": [
        {"type": "object", "properties": {
            "kind": {"const": "cli"},
            "description": {"type": "string"},
            "setup_files": _FILES,
            "args": {"type": "array", "items": {"type": "string"}},
            "expect_exit": {"type": "integer"},
            "expect_json": {"type": "boolean"},
        }, "required": ["kind", "description", "setup_files", "args", "expect_exit", "expect_json"],
            "additionalProperties": False},
        {"type": "object", "properties": {
            "kind": {"const": "http"},
            "description": {"type": "string"},
            "start": {"type": "array", "items": {"type": "string"}},
            "requests": {"type": "array", "items": {
                "type": "object",
                "properties": {
                    "method": {"enum": ["GET", "POST", "PUT", "DELETE"]},
                    "path": {"type": "string"},
                    "form_json": {"type": "string"},
                    "body_json": {"type": "string"},
                    "expect_status": {"type": "integer"},
                    "expect_html_ids": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["method", "path", "form_json", "body_json", "expect_status", "expect_html_ids"],
                "additionalProperties": False}},
        }, "required": ["kind", "description", "start", "requests"], "additionalProperties": False},
        {"type": "object", "properties": {
            "kind": {"const": "function"},
            "description": {"type": "string"},
            "setup_files": _FILES,
            "before": {"type": "array", "items": {"type": "array", "items": {"type": "string"}}},
            "module": {"type": "string"},
            "name": {"type": "string"},
            "args_json": {"type": "string"},
            "expect_type": {"enum": ["list", "tuple", "dict", "str", "int", "float", "bool", "none", "any"]},
            "item_len": {"type": "integer"},
        }, "required": ["kind", "description", "setup_files", "before", "module", "name", "args_json",
                        "expect_type", "item_len"], "additionalProperties": False},
        {"type": "object", "properties": {
            "kind": {"const": "tui"},
            "description": {"type": "string"},
            "module": {"type": "string"},
            "app_class": {"type": "string"},
            "init_args_json": {"type": "string"},
            "widget_ids": {"type": "array", "items": {"type": "string"}},
        }, "required": ["kind", "description", "module", "app_class", "init_args_json", "widget_ids"],
            "additionalProperties": False},
    ]}}},
    "required": ["probes"],
    "additionalProperties": False,
}


@dataclass
class ProbeResult:
    description: str
    ok: bool
    detail: str = ""


def _subst(s: str, tmp: Path, port: int | None = None) -> str:
    s = s.replace("{tmp}", str(tmp))
    return s.replace("{port}", str(port)) if port is not None else s


def _write_files(files: list[dict], tmp: Path) -> None:
    for f in files:
        p = tmp / f["path"]
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f["content"])


def _script_args(args: list[str]) -> list[str]:
    """Probes run `python <args>`; drop a leading interpreter the model wrote anyway."""
    if args and Path(args[0]).name in ("python", "python3", "python3.12"):
        return args[1:]
    return args


def _py(args: list[str], ws: Path, run_dir: Path | None, timeout: int = 60) -> subprocess.CompletedProcess:
    cmd = [str(BIN / "python"), *args]
    env = None
    if run_dir is not None:
        cmd = [*sandbox.sandbox_prefix(run_dir), *cmd]
        import os
        env = os.environ | sandbox.sandbox_env(run_dir) | {"PYTHONDONTWRITEBYTECODE": "1"}
    try:
        return subprocess.run(cmd, cwd=ws, capture_output=True, text=True, timeout=timeout, env=env)
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(cmd, 124, "", f"timed out after {timeout}s (waiting for input?)")


def _tail(text: str, n: int = 12) -> str:
    return "\n".join(text.strip().splitlines()[-n:])


def _tmpdir(run_dir: Path | None) -> Path:
    base = (run_dir / "tmp") if run_dir is not None else None
    if base is not None:
        base.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(dir=base))


def run_cli(p: dict, ws: Path, run_dir: Path | None) -> ProbeResult:
    tmp = _tmpdir(run_dir)
    _write_files(p["setup_files"], tmp)
    proc = _py(_script_args([_subst(a, tmp) for a in p["args"]]), ws, run_dir)
    if proc.returncode != p["expect_exit"]:
        return ProbeResult(p["description"], False,
                           f"exit code {proc.returncode}, expected {p['expect_exit']}\n{_tail(proc.stderr or proc.stdout)}")
    if p["expect_json"]:
        try:
            json.loads(proc.stdout)
        except json.JSONDecodeError as e:
            return ProbeResult(p["description"], False, f"stdout is not valid JSON ({e.msg}): {proc.stdout[:200]!r}")
    return ProbeResult(p["description"], True)


class _Ids(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids: set[str] = set()

    def handle_starttag(self, tag, attrs):
        for k, v in attrs:
            if k in ("id", "data-testid", "name") and v:
                self.ids.add(v)


def run_http(p: dict, ws: Path, run_dir: Path | None) -> ProbeResult:
    tmp = _tmpdir(run_dir)
    try:
        with running(_script_args([_subst(a, tmp) for a in p["start"]]), ws, run_dir=run_dir) as srv:
            for r in p["requests"]:
                kwargs = {}
                if r["form_json"]:
                    kwargs["data"] = json.loads(r["form_json"])
                if r["body_json"]:
                    kwargs["json"] = json.loads(r["body_json"])
                resp = srv.client.request(r["method"], r["path"], **kwargs)
                label = f"{r['method']} {r['path']}"
                if resp.status_code != r["expect_status"]:
                    return ProbeResult(p["description"], False,
                                       f"{label} returned {resp.status_code}, expected {r['expect_status']}\n"
                                       f"{resp.text[:300]}\nserver log:\n{_tail(srv.output(), 8)}")
                if r["expect_html_ids"]:
                    parser = _Ids()
                    parser.feed(resp.text)
                    missing = [i for i in r["expect_html_ids"] if i not in parser.ids]
                    if missing:
                        return ProbeResult(p["description"], False, f"{label}: missing element ids {missing}")
    except StartError as e:
        return ProbeResult(p["description"], False, f"{e}\n{_tail(e.output)}")
    return ProbeResult(p["description"], True)


_FUNC_SNIPPET = textwrap.dedent("""
    import importlib, inspect, json, sys
    sys.path.insert(0, ".")
    mod = importlib.import_module({module!r})
    fn = getattr(mod, {name!r}, None)
    if fn is None:
        print("MISSING"); sys.exit(0)
    args = json.loads({args!r}) if {args!r} else None
    if args is None:
        print("OK none"); sys.exit(0)
    out = fn(*(args if isinstance(args, list) else [args]))
    kind = type(out).__name__
    first = out[0] if isinstance(out, (list, tuple)) and out else None
    print("OK", kind, len(first) if isinstance(first, (list, tuple)) else -1, repr(out)[:300])
""")


def run_function(p: dict, ws: Path, run_dir: Path | None) -> ProbeResult:
    tmp = _tmpdir(run_dir)
    _write_files(p["setup_files"], tmp)
    for step in p["before"]:
        proc = _py([_subst(a, tmp) for a in step], ws, run_dir)
        if proc.returncode != 0:
            return ProbeResult(p["description"], False, f"setup `{' '.join(step)}` failed:\n{_tail(proc.stderr)}")
    code = _FUNC_SNIPPET.format(module=p["module"], name=p["name"], args=_subst(p["args_json"], tmp))
    proc = _py(["-c", code], ws, run_dir)
    out = proc.stdout.strip()
    if proc.returncode != 0:
        return ProbeResult(p["description"], False, f"calling {p['module']}.{p['name']} raised:\n{_tail(proc.stderr)}")
    if out == "MISSING":
        return ProbeResult(p["description"], False, f"{p['module']}.{p['name']} does not exist")
    if out == "OK none":
        return ProbeResult(p["description"], True)
    _, kind, first_len, rep = out.split(" ", 3)
    want = {"none": "NoneType"}.get(p["expect_type"], p["expect_type"])
    if p["expect_type"] != "any" and kind != want:
        return ProbeResult(p["description"], False, f"returned {kind}, expected {p['expect_type']}: {rep}")
    if p["item_len"] >= 0 and int(first_len) not in (-1, p["item_len"]):
        return ProbeResult(p["description"], False,
                           f"items have {first_len} fields, expected {p['item_len']}: {rep}")
    return ProbeResult(p["description"], True)


_TUI_SNIPPET = textwrap.dedent("""
    import asyncio, importlib, json, sys
    sys.path.insert(0, ".")
    mod = importlib.import_module({module!r})
    App = getattr(mod, {cls!r})
    init = json.loads({args!r} or "[]")
    app = App(*(init if isinstance(init, list) else [init]))
    async def main():
        async with app.run_test() as pilot:
            await pilot.pause()
            missing = []
            for wid in {ids!r}:
                try:
                    app.query_one("#" + wid)
                except Exception:
                    missing.append(wid)
            print("MISSING_IDS", json.dumps(missing))
    asyncio.run(main())
""")


def run_tui(p: dict, ws: Path, run_dir: Path | None) -> ProbeResult:
    tmp = _tmpdir(run_dir)
    code = _TUI_SNIPPET.format(module=p["module"], cls=p["app_class"],
                               args=_subst(p["init_args_json"], tmp), ids=p["widget_ids"])
    proc = _py(["-c", code], ws, run_dir, timeout=60)
    if proc.returncode != 0:
        return ProbeResult(p["description"], False, f"app failed to mount:\n{_tail(proc.stderr)}")
    line = next((x for x in proc.stdout.splitlines() if x.startswith("MISSING_IDS")), None)
    missing = json.loads(line.split(" ", 1)[1]) if line else []
    if missing:
        return ProbeResult(p["description"], False, f"widgets not found by id: {missing}")
    return ProbeResult(p["description"], True)


RUNNERS = {"cli": run_cli, "http": run_http, "function": run_function, "tui": run_tui}


def run_probes(probes: list[dict], ws: Path, run_dir: Path | None = None) -> list[ProbeResult]:
    results = []
    for p in probes:
        try:
            results.append(RUNNERS[p["kind"]](p, ws, run_dir))
        except Exception as e:  # a malformed probe must not crash the harness
            results.append(ProbeResult(p.get("description", p["kind"]), False, f"probe error: {type(e).__name__}: {e}"))
    return results


def summarize(results: list[ProbeResult]) -> str:
    bad = [r for r in results if not r.ok]
    if not bad:
        return f"All {len(results)} contract probes passed."
    first = bad[0]
    more = f" (+{len(bad) - 1} more failing)" if len(bad) > 1 else ""
    return f"Contract probe failed{more}: {first.description}\n{first.detail}"
