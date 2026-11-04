"""Compare testing arms: one batch dir per arm → markdown tables for docs/kits.md.

    scripts/arm_report.py ARM=BATCH_DIR ...   (e.g. none=runs/kit-tui-...-tests.none-haiku-123)

Each metric is averaged over a sweep (one run of every task), then shown as the mean over the
sweeps with the min–max across sweeps.
"""

import collections
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from analyze_cost import APP_CHANGE, regressions_caught, run_stats  # noqa: E402

KINDS = ("write:app", "edit:partial", "write:test", "edit:test", "run:try", "run:pytest", "run:python-snippet",
         "read:workspace", "other")
LIMITS = ("LimitsExceeded", "TimeExceeded")


def run_metrics(run_dir: Path, row: dict) -> dict:
    st = run_stats(run_dir) or {"steps": []}
    steps = st["steps"]
    app_steps = [x["i"] for x in steps if x["kind"] in APP_CHANGE]
    kinds_out, kinds_s = collections.Counter(), collections.Counter()
    for x in steps:
        kind = x["kind"] if x["kind"] in KINDS else "other"
        kinds_out[kind] += x["out"]
        kinds_s[kind] += x["model_s"] + x["tool_s"]
    return {
        "spec_passed": row["tests_passed"] - row.get("intent_passed", 0),
        "spec_total": row["tests_total"] - row.get("intent_total", 0),
        "intent_passed": row.get("intent_passed", 0),
        "intent_total": row.get("intent_total", 0),
        "pass": row["pass"],
        "out": row.get("completion_tokens", 0),
        "wall": row.get("wall_sec", 0.0),
        "steps": len(steps),
        "tail": len(steps) - max(app_steps) if app_steps else len(steps),
        "regressions": regressions_caught(steps),
        "limit": row.get("exit_status") in LIMITS,
        "kinds_out": kinds_out,
        "kinds_s": kinds_s,
        "status": row.get("exit_status"),
    }


def load(batch: Path) -> dict[tuple[str, int], dict]:
    rows = [json.loads(line) for line in (batch / "results.jsonl").read_text().splitlines()]
    return {(r["task"], r["run"]): run_metrics(batch / r["task"] / str(r["run"]), r) for r in rows}


def spread(values: list[float], fmt: str = "{:.0f}") -> str:
    if not values:
        return "–"
    mean = statistics.mean(values)
    if len(values) == 1:
        return fmt.format(mean)
    return f"{fmt.format(mean)} ({fmt.format(min(values))}–{fmt.format(max(values))})"


def sweeps(runs: dict) -> dict[int, list[dict]]:
    out = collections.defaultdict(list)
    for (_, i), m in runs.items():
        out[i].append(m)
    return dict(sorted(out.items()))


def per_sweep(runs: dict, f) -> list[float]:
    return [f(ms) for ms in sweeps(runs).values()]


def rate(ms, key):
    total = sum(m[f"{key}_total"] for m in ms)
    return 100 * sum(m[f"{key}_passed"] for m in ms) / total if total else 0.0


def main() -> None:
    arms = {}
    for arg in sys.argv[1:]:
        name, _, path = arg.partition("=")
        arms[name] = load(Path(path))
    names = list(arms)
    mean = lambda key: lambda ms: statistics.mean(m[key] for m in ms)  # noqa: E731
    total = lambda key: lambda ms: sum(m[key] for m in ms)  # noqa: E731
    metrics = [
        ("hidden spec tests passed, %", lambda ms: rate(ms, "spec"), "{:.1f}"),
        ("hidden intent tests passed, %", lambda ms: rate(ms, "intent"), "{:.1f}"),
        ("runs passing every hidden test (of 9)", total("pass"), "{:.1f}"),
        ("output tokens per run", mean("out"), "{:.0f}"),
        ("agent wall time per run, s", mean("wall"), "{:.0f}"),
        ("steps per run", mean("steps"), "{:.0f}"),
        ("steps after the last app change", mean("tail"), "{:.0f}"),
        ("regressions caught (per sweep of 9)", total("regressions"), "{:.1f}"),
        ("runs that hit the step or wall limit (of 9)", total("limit"), "{:.1f}"),
    ]
    print(f"| metric | {' | '.join(names)} |\n|---|{'---|' * len(names)}")
    for label, f, fmt in metrics:
        print(f"| {label} | {' | '.join(spread(per_sweep(arms[a], f), fmt) for a in names)} |")

    print(f"\nOutput tokens per run by step kind (mean over all runs; time in s in brackets):\n")
    print(f"| kind | {' | '.join(names)} |\n|---|{'---|' * len(names)}")
    for kind in KINDS:
        cells = []
        for a in names:
            ms = list(arms[a].values())
            out = statistics.mean(m["kinds_out"][kind] for m in ms)
            secs = statistics.mean(m["kinds_s"][kind] for m in ms)
            cells.append(f"{out:.0f} ({secs:.0f} s)")
        print(f"| {kind} | {' | '.join(cells)} |")

    tasks = sorted({t for a in names for t, _ in arms[a]})
    print(f"\nPer task: hidden spec tests passed (sum over runs) · intent · runs at a limit\n")
    print(f"| task | {' | '.join(names)} |\n|---|{'---|' * len(names)}")
    for t in tasks:
        cells = []
        for a in names:
            ms = [m for (task, _), m in sorted(arms[a].items()) if task == t]
            cells.append(f"{sum(m['spec_passed'] for m in ms)}/{sum(m['spec_total'] for m in ms)} · "
                         f"{sum(m['intent_passed'] for m in ms)}/{sum(m['intent_total'] for m in ms)} · "
                         f"{sum(m['limit'] for m in ms)}")
        print(f"| {t.removeprefix('tui-')} | {' | '.join(cells)} |")


if __name__ == "__main__":
    main()
