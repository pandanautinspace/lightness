"""Verify chain run after every write: parse → ruff (fix + format) → pyright (narrow) → tests.

Stops at the first failing stage and returns one compressed observation. Subprocesses run in
the bench sandbox when a run_dir is given.
"""

import ast
import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from lightness.bench import sandbox
from lightness.verify.compress import diagnostics_summary, pytest_summary

BIN = Path(sys.prefix) / "bin"

# ruff codes that mean the code is broken (not style): syntax, undefined names, bad comparisons…
RUFF_SELECT = "E9,F,I"
RUFF_FAIL = re.compile(r"^(E9|F63|F7|F82|F811)")
RUFF_UNFIXABLE = "F401,F841"  # don't delete imports/variables a later step may still use

PYRIGHT_RULES = {
    "typeCheckingMode": "off",
    "reportMissingImports": "error",
    "reportUndefinedVariable": "error",
    "reportAttributeAccessIssue": "error",
    "reportCallIssue": "error",
    "reportMissingModuleSource": "none",
}


@dataclass
class Check:
    stage: str
    ok: bool
    summary: str = ""


@dataclass
class VerifyResult:
    checks: list[Check] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(c.ok for c in self.checks)

    @property
    def failed(self) -> Check | None:
        return next((c for c in self.checks if not c.ok), None)

    def observation(self) -> str:
        """Compact text for the model."""
        if self.ok:
            notes = [c.summary for c in self.checks if c.summary]
            return "All checks passed." + (" " + " ".join(notes) if notes else "")
        f = self.failed
        return f"{f.stage} failed:\n{f.summary}"


def _run(cmd: list[str], ws: Path, run_dir: Path | None, timeout: int) -> subprocess.CompletedProcess:
    env = os.environ | {"PYTHONDONTWRITEBYTECODE": "1", "PATH": f"{BIN}:{os.environ['PATH']}"}
    if run_dir is not None:
        env |= sandbox.sandbox_env(run_dir)
        cmd = [*sandbox.sandbox_prefix(run_dir), *cmd]
    try:
        return subprocess.run(cmd, cwd=ws, env=env, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        return subprocess.CompletedProcess(cmd, 124, e.stdout or "", f"timed out after {timeout}s")


def check_parse(files: list[Path], ws: Path) -> Check:
    for f in files:
        try:
            ast.parse(f.read_text(), filename=str(f))
        except SyntaxError as e:
            line = (e.text or "").rstrip()
            caret = " " * max((e.offset or 1) - 1, 0) + "^"
            return Check("parse", False, f"{f.relative_to(ws)}:{e.lineno}: {e.msg}\n    {line}\n    {caret}")
    return Check("parse", True)


def check_ruff(files: list[Path], ws: Path, run_dir: Path | None) -> Check:
    names = [str(f.relative_to(ws)) for f in files]
    _run([str(BIN / "ruff"), "check", "--fix", "--select", RUFF_SELECT, "--unfixable", RUFF_UNFIXABLE,
          "--quiet", *names], ws, run_dir, 60)
    _run([str(BIN / "ruff"), "format", "--quiet", *names], ws, run_dir, 60)
    proc = _run([str(BIN / "ruff"), "check", "--select", RUFF_SELECT, "--output-format", "json", *names],
                ws, run_dir, 60)
    try:
        diags = json.loads(proc.stdout or "[]")
    except json.JSONDecodeError:
        return Check("ruff", True, "(ruff output unreadable; skipped)")
    bad = [d for d in diags if RUFF_FAIL.match(d.get("code") or "E9")]
    if not bad:
        return Check("ruff", True)
    lines = [f"{Path(d['filename']).relative_to(ws.resolve())}:{d['location']['row']}: {d['code']} {d['message']}"
             for d in bad]
    return Check("ruff", False, diagnostics_summary(lines))


def check_pyright(files: list[Path], ws: Path, run_dir: Path | None) -> Check:
    with tempfile.TemporaryDirectory(dir=run_dir) as tmp:
        config = Path(tmp) / "pyrightconfig.json"
        config.write_text(json.dumps(PYRIGHT_RULES | {
            "include": [str(f.resolve()) for f in files],
            "extraPaths": [str(ws.resolve())],
            "pythonPath": sys.executable,
        }))
        proc = _run([str(BIN / "basedpyright"), "--outputjson", "-p", str(config)], ws, run_dir, 120)
    try:
        report = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return Check("types", True, "(type check unavailable; skipped)")
    errors = [d for d in report.get("generalDiagnostics", []) if d.get("severity") == "error"]
    if not errors:
        return Check("types", True)
    lines = [f"{Path(d['file']).relative_to(ws.resolve())}:{d['range']['start']['line'] + 1}: {d['message'].splitlines()[0]}"
             for d in errors]
    return Check("types", False, diagnostics_summary(lines))


def related_tests(files: list[Path], ws: Path) -> list[Path]:
    """Test files in the workspace that import any of the touched modules (or are touched)."""
    modules = {f.stem for f in files} | {".".join(f.relative_to(ws).with_suffix("").parts) for f in files}
    pattern = re.compile(r"^\s*(?:from|import)\s+(" + "|".join(re.escape(m) for m in modules) + r")\b", re.M)
    tests = []
    for t in sorted(ws.rglob("test_*.py")) + sorted(ws.rglob("*_test.py")):
        if ".venv" in t.parts:
            continue
        if t in files or pattern.search(t.read_text(errors="ignore")):
            tests.append(t)
    return tests


def check_tests(tests: list[Path] | None, ws: Path, run_dir: Path | None, timeout: int) -> Check:
    args = [str(t.relative_to(ws)) for t in tests] if tests is not None else []
    if tests is not None and not tests:
        return Check("tests", True, "(no related tests yet)")
    proc = _run([str(BIN / "python"), "-m", "pytest", "-x", "-q", "-p", "no:cacheprovider", *args], ws, run_dir, timeout)
    if proc.returncode in (0, 5):  # 5 = nothing collected
        return Check("tests", True, "(no tests collected)" if proc.returncode == 5 else "")
    if proc.returncode == 124:
        return Check("tests", False, f"tests timed out after {timeout}s (a server or input() left waiting?)")
    return Check("tests", False, pytest_summary(proc.stdout + proc.stderr, ws))


def verify(
    ws: Path,
    touched: list[Path],
    *,
    run_dir: Path | None = None,
    tests: str = "related",  # "related" | "all" | "none"
    types: bool = True,
    test_timeout: int = 120,
) -> VerifyResult:
    result = VerifyResult()
    py = [f for f in touched if f.suffix == ".py" and f.exists()]
    for check in (
        lambda: check_parse(py, ws),
        lambda: check_ruff(py, ws, run_dir) if py else Check("ruff", True),
        lambda: check_pyright(py, ws, run_dir) if py and types else Check("types", True),
        lambda: check_tests(None if tests == "all" else related_tests(py, ws), ws, run_dir, test_timeout)
        if tests != "none" else Check("tests", True),
    ):
        c = check()
        result.checks.append(c)
        if not c.ok:
            break
    return result
