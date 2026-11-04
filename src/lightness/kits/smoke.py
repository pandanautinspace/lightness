"""Smoke checks: does the program start? Run by the harness after changes, in the sandbox.

Only "starts and quits without an error" is checked here; what the program does is the job
of tests and contract scenarios.
"""

import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from lightness.bench import sandbox
from lightness.verify.chain import BIN
from lightness.verify.compress import traceback_summary

TUI_SNIPPET = """
import asyncio, importlib, sys
sys.path.insert(0, ".")
mod = importlib.import_module({module!r})
cls = getattr(mod, {app_class!r}, None)
if cls is None:
    print("SMOKE: {module}.py has no class {app_class}"); sys.exit(3)
path = {path!r}

async def main():
    app = cls(path) if path else cls()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()

asyncio.run(main())
print("SMOKE-OK")
"""


@dataclass
class SmokeResult:
    ok: bool
    case: str  # which start was checked
    detail: str = ""


def _python(code: str, ws: Path, run_dir: Path | None, timeout: int) -> subprocess.CompletedProcess:
    cmd = [str(BIN / "python"), "-c", code]
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
    """Start the app headless with no data file, and with the sample data if there is one."""
    module, app_class = names["module"], names["app_class"]
    if not (ws / f"{module}.py").exists():
        return []
    cases: list[tuple[str, str | None, str | None]] = []
    has_path = bool(names.get("data_arg"))
    base = Path(tempfile.mkdtemp(dir=(run_dir / "tmp") if run_dir else None, prefix="smoke-"))
    name = names.get("data_default") or "data.json"
    cases.append(("starting with no data file", str(base / "missing" / name) if has_path else None, None))
    sample = (names.get("sample_data") or "").strip()
    if has_path and sample:
        cases.append(("starting with an existing data file", str(base / name), sample))
    (base / "missing").mkdir(parents=True, exist_ok=True)
    results = []
    for case, path, content in cases:
        if content is not None and path is not None:
            Path(path).write_text(content)
        proc = _python(TUI_SNIPPET.format(module=module, app_class=app_class, path=path), ws, run_dir, timeout)
        out = proc.stdout + proc.stderr
        if proc.returncode == 0 and "SMOKE-OK" in proc.stdout:
            results.append(SmokeResult(True, case))
        else:
            detail = out.strip().splitlines()[-1] if "SMOKE:" in out else traceback_summary(out, ws)
            if content:
                detail += f"\n(data file contents: {content[:300]})"
            results.append(SmokeResult(False, case, detail))
    return results


def summarize(results: list[SmokeResult], target: str) -> str:
    bad = [r for r in results if not r.ok]
    if not bad:
        return f"{target} starts cleanly ({'; '.join(r.case for r in results)})."
    return "\n".join(f"{target} crashes when {r.case}:\n{r.detail}" for r in bad)
