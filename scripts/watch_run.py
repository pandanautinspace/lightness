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


FOLLOW, TOTAL = False, 0


def main(arg: str) -> None:
    batch = Path(arg)
    run = None
    seen = 0
    done: set = set()
    while True:
        if run is None or not (run / "steps.jsonl").exists():
            run = newest_run(batch)
        steps = run / "steps.jsonl"
        if steps.exists():
            lines = steps.read_text().splitlines()
            for line in lines[seen:]:
                s = json.loads(line)
                cmd = " ".join(s["command"].split())[:110]
                text = s["output"] + "\n" + "\n".join(s.get("notes", []))
                print(f"[{run.parent.name} {s['step']:>3} {s['t']:>4}s] {cmd}  => {summary(text)}", flush=True)
            seen = len(lines)
        if (run / "messages.json").exists():
            print(f"[{run.parent.name}] RUN ENDED after {seen} steps", flush=True)
            if not FOLLOW:
                return
            done.add(run)
            while True:  # a batch: wait for the next run to start, or the batch to finish
                nxt = newest_run(batch)
                if nxt not in done and nxt != run:
                    run, seen = nxt, 0
                    break
                if (batch / "results.jsonl").exists() and len((batch / "results.jsonl").read_text().splitlines()) >= TOTAL:
                    print("BATCH DONE", flush=True)
                    return
                time.sleep(3)
            continue
        time.sleep(3)


if __name__ == "__main__":
    if len(sys.argv) > 2:  # watch_run.py BATCH_DIR N: follow every run of a batch of N runs
        FOLLOW, TOTAL = True, int(sys.argv[2])
    main(sys.argv[1])
