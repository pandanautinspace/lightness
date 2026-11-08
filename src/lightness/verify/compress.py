"""Turn raw tool output into a short observation a small model can act on.

Keep the first failure only, the frames that point into the workspace, and the assertion
detail; drop everything else.
"""

import re
from pathlib import Path

MAX_LINES = 40

_FRAME = re.compile(r'^\s*File "(?P<file>[^"]+)", line (?P<line>\d+), in (?P<func>.+)$')
# a SyntaxError's last frame: no "in func", then the source line and a caret under the problem
_SYNTAX_FRAME = re.compile(r'^\s*File "(?P<file>[^"]+)", line (?P<line>\d+)$')
_PYTEST_LOC = re.compile(r"^(?P<file>[^\s:]+\.py):(?P<line>\d+): (?P<err>\w+)")


def _rel(path: str, ws: Path) -> str | None:
    if path.startswith("<"):  # <frozen importlib...>, <string> (the harness's own snippet): not the app
        return None
    try:
        return str(Path(path).resolve().relative_to(ws.resolve()))
    except (ValueError, OSError):
        # <frozen importlib...> and <string> (the harness's own snippet) are noise, not the app
        return None if path.startswith(("/", "<")) else path


def _cap(lines: list[str]) -> str:
    if len(lines) > MAX_LINES:
        lines = lines[: MAX_LINES - 1] + [f"... ({len(lines) - MAX_LINES + 1} more lines)"]
    return "\n".join(lines)


def traceback_summary(text: str, ws: Path) -> str:
    """Last exception of a Python traceback, with only workspace frames (file:line, func, code)."""
    lines = text.rstrip().splitlines()
    starts = [i for i, line in enumerate(lines) if line.startswith("Traceback (most recent call last)")]
    if not starts:
        return _cap(lines[-MAX_LINES:])
    block = lines[starts[-1]:]
    out, i = [], 1
    while i < len(block):
        m = _FRAME.match(block[i])
        if m:
            rel = _rel(m["file"], ws)
            nxt = block[i + 1] if i + 1 < len(block) else ""
            code = nxt.strip() if nxt and not _FRAME.match(nxt) and not _SYNTAX_FRAME.match(nxt) else ""
            if rel:
                out.append(f"{rel}:{m['line']} in {m['func']}: {code}")
            i += 2 if code else 1
            continue
        m = _SYNTAX_FRAME.match(block[i])
        if m and (rel := _rel(m["file"], ws)):
            # airport-lookup: the start check said only "SyntaxError: invalid syntax", and the 35B rewrote the file
            out.append(f"{rel}:{m['line']}:")
            i += 1
            while i < len(block) and block[i].startswith(" "):
                out.append(block[i])
                i += 1
            continue
        if not block[i].startswith(" "):
            out.extend(block[i:])
            break
        i += 1
    return _cap(out or block[-5:])


def pytest_summary(output: str, ws: Path) -> str:
    """First failing test from `pytest -q` output: name, E-lines, workspace locations."""
    lines = output.splitlines()
    summary = [line for line in lines if re.match(r"^\d+ (passed|failed)|^=+ .*(passed|failed|error)", line)]
    header = next((i for i, line in enumerate(lines) if re.match(r"^_{3,} .+ _{3,}$", line)), None)
    if header is None:
        errs = [line for line in lines if line.startswith(("ERROR", "E ", "ImportError", "ModuleNotFoundError"))]
        return _cap((errs or lines[-15:]) + summary[-1:])
    end = next((j for j in range(header + 1, len(lines)) if re.match(r"^(_{3,} .+ _{3,}|=+ )", lines[j])), len(lines))
    section = lines[header:end]
    name = section[0].strip("_ ")
    elines = [line for line in section if line.startswith("E ")]
    locs = []
    for line in section:
        m = _PYTEST_LOC.match(line)
        if m:
            rel = _rel(m["file"], ws) or m["file"]
            locs.append(f"{rel}:{m['line']} ({m['err']})")
    failed = sum(1 for line in lines if line.startswith("FAILED") or line.startswith("ERROR "))
    out = [f"FAILED {name}" + (f" (+{failed - 1} more failing)" if failed > 1 else "")]
    out += elines[:20] or [line for line in section[1:] if line.strip()][-10:]
    out += [f"at {loc}" for loc in locs[-3:]]
    return _cap(out)


def diagnostics_summary(diags: list[str], limit: int = 8) -> str:
    """List of 'file:line: message' strings, deduplicated, capped."""
    seen, out = set(), []
    for d in diags:
        if d not in seen:
            seen.add(d)
            out.append(d)
    extra = f"\n... and {len(out) - limit} more" if len(out) > limit else ""
    return "\n".join(out[:limit]) + extra


def shorten_paths(text: str, ws: Path, run_dir: Path | None = None) -> str:
    """Replace absolute workspace/run paths with ./ and $TMP/ so the model sees what matters."""
    for base, short in ((ws.resolve(), "./"), (ws, "./")):
        text = text.replace(str(base) + "/", short).replace(str(base), ".")
    if run_dir is not None:
        for base in (run_dir.resolve() / "tmp", run_dir / "tmp", run_dir.resolve(), run_dir):
            text = text.replace(str(base) + "/", "$TMP/").replace(str(base), "$TMP")
    return text
