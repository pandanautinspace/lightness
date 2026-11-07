"""Speed numbers for finished runs: python scripts/run_stats.py BATCH_OR_RUN_DIR ...

One line per task run: result, wall time, steps, output tokens, app and checks.txt rewrites,
in-place edits (sed/patch/python), try commands, steps whose thinking was cut off, how output
splits between thinking and commands, and the agent calls' decode speed (tok/s) and generation
seconds. Decode speed roughly halves on battery in Low Power Mode, so compare wall times only
between runs at a similar tok/s (or compare output tokens). A batch dir expands to every run under it."""

import json
import sys
from pathlib import Path


def runs(path: Path) -> list[Path]:
    if (path / "steps.jsonl").exists():
        return [path]
    return sorted(p.parent for p in path.glob("*/*/steps.jsonl"))


def result(run: Path) -> dict:
    res = run.parent.parent / "results.jsonl"
    if res.exists():
        for line in res.read_text().splitlines():
            r = json.loads(line)
            if r["task"] == run.parent.name and str(r["run"]) == run.name:
                return r
    return {}


def main(paths: list[str]) -> None:
    for run in [r for p in paths for r in runs(Path(p))]:
        steps = [json.loads(line) for line in (run / "steps.jsonl").read_text().splitlines()]
        head = [s["command"].split("\n")[0] for s in steps]
        app = sum(1 for h in head if "<<" in h and "checks.txt" not in h and not h.lstrip().startswith("python"))
        checks = sum(1 for h in head if "checks.txt" in h and ("<<" in h or ">" in h))
        edits = sum(1 for h in head if h.lstrip().startswith(("sed ", "patch", "python3 - <<", "python - <<")))
        tries = sum(1 for h in head if "try_app" in h)
        cut = sum(1 for s in steps if any("cut off" in n for n in s.get("notes", [])))
        think = 0
        if (run / "reasoning.jsonl").exists():
            think = sum(len(json.loads(line).get("reasoning") or "") for line in (run / "reasoning.jsonl").read_text().splitlines())
        cmd = sum(len(s["command"]) for s in steps)
        calls = [json.loads(line) for line in (run / "calls.jsonl").read_text().splitlines()] if (run / "calls.jsonl").exists() else []
        agent = [c for c in calls if c.get("purpose") == "agent" and c.get("predicted_ms")]
        gen = sum(c["predicted_ms"] for c in agent) / 1000
        speed = sum(c["completion_tokens"] for c in agent) / gen if gen else 0
        r = result(run)
        score = (f"spec {r['tests_passed'] - r.get('intent_passed', 0)}/{r['tests_total'] - r.get('intent_total', 0)}"
                 f" intent {r.get('intent_passed')}/{r.get('intent_total')}") if r else "no result (stopped)"
        wall = int(r["wall_sec"]) if r else steps[-1]["t"] if steps else 0
        out = r.get("completion_tokens", "?")
        print(f"{run.parent.name[4:]:15} {r.get('exit_status', '-'):10} {score:24} wall={wall:5}s steps={len(steps):3} "
              f"out_tok={out} app_rewrites={app} checks_writes={checks} edits={edits} tries={tries} think_cut={cut} "
              f"think/cmd_chars={think}/{cmd} gen_s={gen:.0f} tok/s={speed:.0f}")


if __name__ == "__main__":
    main(sys.argv[1:])
