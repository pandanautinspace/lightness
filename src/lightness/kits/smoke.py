"""Smoke checks: does the program start? Run by the harness after changes, in the sandbox.

Only "starts and quits without an error" is checked here; what the program does is the job
of tests and contract scenarios.
"""

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
        proc = _python(TUI_SNIPPET.format(module=module, app_class=app_class, kwargs=kwargs), ws, run_dir, timeout)
        out = proc.stdout + proc.stderr
        if proc.returncode == 0 and "SMOKE-OK" in proc.stdout:
            results.append(SmokeResult(True, case))
        else:
            detail = out.strip().splitlines()[-1] if "SMOKE:" in out else traceback_summary(out, ws)
            if content:
                detail += f"\n(file contents: {content[:300]})"
            results.append(SmokeResult(False, case, detail))
    return results


def summarize(results: list[SmokeResult], target: str) -> str:
    bad = [r for r in results if not r.ok]
    if not bad:
        return f"{target} starts cleanly ({'; '.join(r.case for r in results)})."
    return "\n".join(f"{target} crashes when {r.case}:\n{r.detail}" for r in bad)
