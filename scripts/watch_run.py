"""Follow a run live, one line per step: python scripts/watch_run.py RUN_DIR (a task's run dir, or a
batch dir: the newest run under it). Exits when the run ends (results line or messages.json)."""

import json
import re
import sys
import time
from pathlib import Path


def newest_run(path: Path) -> Path:
    if (path / "steps.jsonl").exists() or (path / "calls.jsonl").exists():
        return path
    runs = sorted(path.glob("*/*/calls.jsonl"), key=lambda p: p.stat().st_mtime)
    return runs[-1].parent if runs else path


def summary(output: str) -> str:
    """The parts of an output worth seeing at a glance."""
    out = []
    if m := re.search(r'"returncode": (\d+)', output):
        out.append(f"rc={m.group(1)}")
    if m := re.search(r"\[automatic checks\] (\d+ of \d+ checks pass)", output):
        out.append(m.group(1))
    if "crashes when starting" in output:
        out.append("START-CRASH")
    if m := re.search(r"FAILED expect[^\n]{0,60}", output):
        out.append(m.group(0))
    if "No checks.txt yet" in output:
        out.append("NO-CHECKS-NUDGE")
    if "Not submitted" in output:
        out.append("SUBMIT-REFUSED")
    return " | ".join(out)


def main(arg: str) -> None:
    batch = Path(arg)
    run = None
    seen = 0
    while True:
        if run is None or not (run / "steps.jsonl").exists():
            run = newest_run(batch)
        steps = run / "steps.jsonl"
        if steps.exists():
            lines = steps.read_text().splitlines()
            for line in lines[seen:]:
                s = json.loads(line)
                cmd = " ".join(s["command"].split())[:110]
                print(f"[{run.parent.name} {s['step']:>3} {s['t']:>4}s] {cmd}  => {summary(s['output'])}", flush=True)
            seen = len(lines)
        if (run / "messages.json").exists():
            print(f"[{run.parent.name}] RUN ENDED after {seen} steps", flush=True)
            return
        time.sleep(3)


if __name__ == "__main__":
    main(sys.argv[1])
