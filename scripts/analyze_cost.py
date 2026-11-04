"""Where did time and output tokens go in a batch of runs? Usage: analyze_cost.py BATCH_DIR [--steps]"""

import collections
import json
import re
import sys
from pathlib import Path

APP_WRITE = re.compile(r"(cat|tee)\s*(<<-?\s*['\"]?\w+['\"]?\s*)?>\s*(?P<f>[\w./-]+\.py)|>\s*(?P<g>[\w./-]+\.py)\s*<<")


def classify(cmd: str, module: str | None) -> str:
    c = re.sub(r"^(cd\s+\S+\s*&&\s*)+", "", cmd.strip())
    if "COMPLETE_TASK_AND_SUBMIT" in c:
        return "submit"
    m = APP_WRITE.search(c)
    if m:
        f = (m.group("f") or m.group("g") or "").split("/")[-1]
        if "test" in f:
            return "write:test"
        if re.match(r"(debug|check|verify|final|comprehensive|integration|scratch)", f):
            return "write:debug-script"
        return "write:app"
    if "try_app.py" in c:
        return "run:try"
    if "pytest" in c:
        return "run:pytest"
    if re.search(r"site-packages|textual/|inspect\.getsource|help\(", c):
        return "read:library"
    if re.search(r"sed -i|applypatch|apply_patch|\.replace\(|str_replace|perl -pi", c):
        files = re.findall(r"[\w./-]+\.py", c)
        return "edit:test" if files and all("test" in f.split("/")[-1] for f in files) else "edit:partial"
    if re.match(r"(python3?|\.venv)\S*\s+(-c|-\s*<<|<<|-\s)", c):
        return "run:python-snippet"
    if re.match(r"python3?\s+[\w./-]+\.py", c):
        return "run:script"
    if re.match(r"(cat|nl|head|tail|sed -n|grep|ls|find|wc|pwd)\b", c):
        return "read:workspace"
    return "other"


APP_CHANGE = ("write:app", "edit:partial")
TEST_CHANGE = ("write:test", "edit:test")
FAILED = re.compile(r"^(?:FAILED|ERROR) (\S+)", re.M)
COUNTS = re.compile(r"(\d+) (passed|failed|errors?)\b")


def pytest_failures(output: str) -> set[str] | None:
    """The failing tests a pytest run reports (empty when all pass); None if it shows no summary."""
    counts = {kind.rstrip("s"): int(n) for n, kind in COUNTS.findall(output)}
    if not counts:
        return None
    names = {n.split(" - ")[0] for n in FAILED.findall(output)}
    bad = counts.get("failed", 0) + counts.get("error", 0)
    return names if len(names) >= bad else names | {f"#{i}" for i in range(bad - len(names))}


def regressions_caught(steps: list[dict]) -> int:
    """Times the model's own tests went from passing to failing after an app change, and the app
    (not the test) was changed next: tests that caught a regression the model then fixed."""
    count, prev, app_changed, pending = 0, None, False, False
    for x in steps:
        if x["kind"] in APP_CHANGE:
            count += pending
            pending, app_changed = False, True
        elif x["kind"] in TEST_CHANGE:
            pending = False
        elif x["kind"] == "run:pytest" and (failing := pytest_failures(x["obs"])) is not None:
            if prev is not None and app_changed and failing - prev:
                pending = True
            prev, app_changed = failing, False
    return count


def run_stats(d: Path) -> dict | None:
    # empty-reply tries per step: 3 for runs started before 2026-11-04 16:58, 5 after
    tries = 5 if (d / "calls.jsonl").exists() and json.loads((d / "calls.jsonl").read_text().splitlines()[0])["ts"] > 1793824700 else 3
    if not (d / "messages.json").exists():
        return None
    msgs = json.loads((d / "messages.json").read_text())
    calls = [json.loads(line) for line in (d / "calls.jsonl").read_text().splitlines()]
    agent_calls, streak = [], 0
    for c in calls:
        if c.get("purpose") != "agent" or not c.get("ok"):
            continue
        # An empty reply is asked again (up to TRIES times in a step); only the last of a streak is kept
        # in the transcript, so drop the others to keep calls and transcript steps paired.
        if c.get("finish_reason") == "content_filter" or not c.get("completion_tokens"):
            streak += 1
            if streak % tries:
                continue
        else:
            streak = 0
        agent_calls.append(c)
    events = [json.loads(line) for line in (d / "events.jsonl").read_text().splitlines()] if (d / "events.jsonl").exists() else []
    module = next((e["names"]["module"] for e in events if e.get("event") == "kit"), None)
    reasoning = {}
    if (d / "reasoning.jsonl").exists():
        for line in (d / "reasoning.jsonl").read_text().splitlines():
            r = json.loads(line)
            reasoning[r["step"]] = len(r["reasoning"])
    assistants = [m for m in msgs if m["role"] == "assistant"]
    obs = {}  # tool_call_id → observation text
    for m in msgs:
        if m["role"] == "tool":
            obs[m.get("tool_call_id")] = m.get("content") or ""
    steps = []
    for i, (m, c) in enumerate(zip(assistants, agent_calls)):
        tcs = m.get("tool_calls") or []
        cmd = json.loads(tcs[0]["function"]["arguments"]).get("command", "") if tcs else ""
        kind = classify(cmd, module) if tcs else "format-error"
        # wall time of this step = until the next agent call starts (model + command + middleware)
        nxt = agent_calls[i + 1]["ts"] - agent_calls[i + 1]["latency"] if i + 1 < len(agent_calls) else c["ts"]
        steps.append({
            "i": i + 1, "kind": kind, "out": c.get("completion_tokens") or 0, "prompt": c.get("prompt_tokens") or 0,
            "cmd_chars": len(cmd), "text_chars": len(m.get("content") or ""), "reason_chars": reasoning.get(i + 1, 0),
            "model_s": c["latency"], "gen_s": (c.get("predicted_ms") or 0) / 1000, "prefill_s": (c.get("prompt_ms") or 0) / 1000,
            "tool_s": max(0.0, nxt - c["ts"]), "cmd": cmd,
            "obs": obs.get(tcs[0].get("id"), "") if tcs else "",
        })
    return {"module": module, "steps": steps}


def main():
    batch = Path(sys.argv[1])
    show_steps = "--steps" in sys.argv
    rows = [json.loads(line) for line in (batch / "results.jsonl").read_text().splitlines()]
    results = {(r["task"], r["run"]): r for r in rows}
    total_kind_out = collections.Counter()
    total_kind_n = collections.Counter()
    total_kind_s = collections.Counter()
    totals = collections.Counter()
    print(f"# {batch.name}\n")
    print(f"{'task#run':22} {'steps':>5} {'out':>7} {'reason%':>7} {'gen s':>6} {'pre s':>6} {'model s':>7} {'tool s':>6} "
          f"{'app writes':>10} {'last app chg':>12} spec")
    for run_dir in sorted(batch.glob("*/[0-9]*")):
        st = run_stats(run_dir)
        if st is None:
            continue
        s = st["steps"]
        r = results.get((run_dir.parent.name, int(run_dir.name)), {})
        label = f"{run_dir.parent.name}#{run_dir.name}"
        out = sum(x["out"] for x in s)
        # reasoning share: reasoning chars / (reasoning + visible output chars), as a proxy of token share
        rc = sum(x["reason_chars"] for x in s)
        vc = sum(x["cmd_chars"] + x["text_chars"] for x in s)
        app_steps = [x["i"] for x in s if x["kind"] in APP_CHANGE]
        writes = sum(1 for x in s if x["kind"] == "write:app")
        spec = f"{r.get('tests_passed', 0) - r.get('intent_passed', 0)}/{r.get('tests_total', 0) - r.get('intent_total', 0)}"
        print(f"{label:22} {len(s):5} {out:7} {100 * rc / max(1, rc + vc):6.0f}% {sum(x['gen_s'] for x in s):6.0f} "
              f"{sum(x['prefill_s'] for x in s):6.0f} {sum(x['model_s'] for x in s):7.0f} {sum(x['tool_s'] for x in s):6.0f} "
              f"{writes:10} {(max(app_steps) if app_steps else 0):12} {spec} regressions={regressions_caught(s)}")
        for x in s:
            total_kind_out[x["kind"]] += x["out"]
            total_kind_n[x["kind"]] += 1
            total_kind_s[x["kind"]] += x["model_s"] + x["tool_s"]
        totals["out"] += out
        totals["steps"] += len(s)
        totals["tail_steps"] += len(s) - (max(app_steps) if app_steps else 0)
        totals["tail_out"] += sum(x["out"] for x in s if app_steps and x["i"] > max(app_steps))
        totals["rc"] += rc
        totals["vc"] += vc
        if show_steps:
            for x in s:
                print(f"    {x['i']:3} {x['kind']:18} out={x['out']:5} reason={x['reason_chars']:5} "
                      f"model={x['model_s']:5.1f}s tool={x['tool_s']:5.1f}s  {x['cmd'][:90]!r}")
    print(f"\ntotal steps {totals['steps']}, output tokens {totals['out']}, "
          f"reasoning ≈{100 * totals['rc'] / max(1, totals['rc'] + totals['vc']):.0f}% of output chars")
    print(f"after the last app change: {totals['tail_steps']} steps, {totals['tail_out']} output tokens "
          f"({100 * totals['tail_out'] / max(1, totals['out']):.0f}%)\n")
    print(f"{'kind':20} {'steps':>6} {'out tokens':>10} {'share':>6} {'tok/step':>8} {'time s':>7}")
    for k, v in total_kind_out.most_common():
        print(f"{k:20} {total_kind_n[k]:6} {v:10} {100 * v / max(1, totals['out']):5.0f}% {v // max(1, total_kind_n[k]):8} {total_kind_s[k]:7.0f}")


if __name__ == "__main__":
    main()
