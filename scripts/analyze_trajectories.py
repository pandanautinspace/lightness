"""Behavioural metrics for mini-swe-agent trajectories.

Usage:
    uv run python scripts/analyze_trajectories.py <run_dir> [<run_dir> ...] [--turns] [--json OUT]

A run dir is e.g. runs/20261102-184444-bare-qwen35a3-56602; every <run_dir>/<task>/0/trajectory.json
is analysed. Prints a per-task table, aggregate tables by turn third and by context band, and
per-action-kind failure rates early vs late (to separate "harder sub-problem" from "worse
behaviour"). --turns also prints one line per turn.

All detectors are heuristics on the command text and observation; see the docstrings. Counts are
per *action* (a turn may carry several actions, though in practice it is one).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import statistics
import sys
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from itertools import pairwise
from pathlib import Path

SUBMIT = "COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"

ERROR_RE = re.compile(
    r"Traceback \(most recent call last\)|^\w*Error:|\bError: |No such file or directory|"
    r"command not found|^FAILED |\b[1-9]\d* failed|SyntaxError|invalid command code|"
    r"unterminated substitute|ModuleNotFoundError|Address already in use|Permission denied|"
    r"Operation not permitted",
    re.MULTILINE,
)
SUCCESS_RE = re.compile(
    r"\b(all (the )?tests pass|tests? (now )?pass(es|ed)?|works? (correctly|perfectly|now|as expected)|"
    r"is working|now works|successfully|everything (looks|is) (good|correct|working)|"
    r"all good|fixed)\b",
    re.IGNORECASE,
)
FAIL_ACK_RE = re.compile(
    r"\b(error|fail|failed|failing|traceback|exception|wrong|issue|problem|bug|not found|"
    r"doesn't|didn't|isn't|not work)\w*",
    re.IGNORECASE,
)
# heredoc written to a file:  cat <<'EOF' > f   |  cat > f <<'EOF'  |  tee f <<EOF
HEREDOC_WRITE_RE = re.compile(
    r"(?:cat|tee)\s+(?:<<-?\s*['\"]?(\w+)['\"]?\s*>\s*(\S+)|>\s*(\S+)\s*<<-?\s*['\"]?(\w+)['\"]?"
    r"|(\S+)\s*<<-?\s*['\"]?(\w+)['\"]?)"
)
PY_WRITE_RE = re.compile(r"open\(\s*['\"]([^'\"]+)['\"]\s*,\s*['\"][wa]")
SED_I_RE = re.compile(r"\bsed\s+(-[a-zA-Z]*i[a-zA-Z]*)(\s+''|\s+\"\")?\s")
TEST_RE = re.compile(r"\bpytest\b|unittest|\bpython3?\s+\S*test\w*\.py")
APP_RUN_RE = re.compile(
    r"\bcurl\b|\bflask\s+run\b|\bpython3?\s+(-m\s+\w[\w.]*|(?!-)[^\s|;&]*\.py)|run_test\(|Pilot|"
    r"test_client\(\)"
)
# Commands that edit files in the workspace (not merely run something).
EDIT_RE = re.compile(
    r"(^|[;&|]\s*)(cat\s+(<<|>)|tee|sed\s+-i|mv|cp|rm|mkdir|touch|patch)\b|"
    r"open\([^)]*['\"][wa]|write_text",
    re.MULTILINE,
)
STATE_CHANGE_RE = re.compile(
    r"(^|[;&|]\s*)(cat|tee|sed\s+-i|mv|cp|rm|mkdir|touch|pip|uv|git\s+(checkout|apply|reset)|"
    r"chmod|ln|patch)\b|>\s*(?!/dev/null|&)\S|open\([^)]*['\"][wa]|write_text|\.save\(|"
    r"sqlite3|\.commit\(|python3?\s+(?!-c)\S+\.py",
    re.MULTILINE,
)
CTX_BANDS = [(0, 8_000, "<8K"), (8_000, 16_000, "8-16K"), (16_000, 32_000, "16-32K"), (32_000, 10**9, ">32K")]


def ctx_band(n: int) -> str:
    for lo, hi, name in CTX_BANDS:
        if lo <= n < hi:
            return name
    return "?"


def norm_path(tok: str) -> str:
    return re.sub(r"(/[^\s/'\"]+)+/", "", tok)


def file_key(path: str) -> str:
    """Identify a written file: strip the run's workspace prefix and './', keep other dirs."""
    p = re.sub(r"^.*/workspace/", "", path.strip("'\""))
    return re.sub(r"^\./", "", p)


def normalise(cmd: str) -> str:
    """Near-repeat key: drop `cd X &&`, absolute path prefixes, redirections, head/tail counts, ws."""
    c = re.sub(r"^\s*cd\s+\S+\s*&&\s*", "", cmd)
    c = norm_path(c)
    c = re.sub(r"\s*2>&1", "", c)
    c = re.sub(r"\|\s*(head|tail)(\s+-n)?\s+-?\d+", "", c)
    c = re.sub(r"\btimeout\s+\d+\s+", "", c)
    c = re.sub(r"\bpython3\b", "python", c)
    c = re.sub(r"\s+", " ", c).strip()
    return c


def kind(cmd: str) -> str:
    """Coarse action kind, used for early-vs-late comparisons of like with like."""
    c = re.sub(r"^\s*cd\s+\S+\s*&&\s*", "", cmd).strip()
    if SUBMIT in c:
        return "submit"
    if c.startswith("ask_user"):
        return "ask"
    if HEREDOC_WRITE_RE.search(c.split("\n", 1)[0]) and not c.startswith("python"):
        return "write"
    if SED_I_RE.search(c):
        return "sed"
    if TEST_RE.search(c):
        return "test"
    if re.match(r"(cat|head|tail|nl|sed -n|grep|ls|find|wc|tree|pwd|which|file)\b", c):
        return "inspect"
    if re.match(r"python3?\s+(-c|<<|-\s*<<)", c) or re.match(r"python3?\s+-\s", c):
        return "python-snippet"
    if APP_RUN_RE.search(c):
        return "run-app"
    return "other"


def file_writes(cmd: str) -> list[tuple[str, str | None]]:
    """(path, content-or-None) for files written by a heredoc (content known) or python open()."""
    out: list[tuple[str, str | None]] = []
    lines = cmd.split("\n")
    i = 0
    while i < len(lines):
        m = HEREDOC_WRITE_RE.search(lines[i])
        if m and not re.match(r"\s*python", lines[i]):
            if m.group(1):
                tag, path = m.group(1), m.group(2)
            elif m.group(3):
                path, tag = m.group(3), m.group(4)
            else:
                path, tag = m.group(5), m.group(6)
            body = []
            j = i + 1
            while j < len(lines) and lines[j].strip() != tag:
                body.append(lines[j])
                j += 1
            out.append((file_key(path), "\n".join(body)))
            i = j + 1
            continue
        i += 1
    for p in PY_WRITE_RE.findall(cmd):
        out.append((file_key(p), None))
    for m in re.finditer(r"\bsed\s+-i\S*(?:\s+''|\s+\"\")?\s+.*?\s(\S+\.\w+)\s*($|[;&|])", cmd, re.MULTILINE):
        out.append((file_key(m.group(1)), None))
    return out


@dataclass
class Act:
    turn: int  # 1-based assistant turn
    cmd: str
    rc: int | None
    out: str
    truncated: bool
    prompt_tokens: int
    completion_tokens: int
    think_chars: int
    kind: str
    failed: bool = False
    timeout: bool = False
    edits: bool = False
    exact_repeat: bool = False
    near_repeat: bool = False
    repeat_of_failed: bool = False
    idle_repeat: bool = False
    stale: bool = False
    misread_success: bool = False
    rewrite_same_content: bool = False
    rewrite_to_old_version: bool = False
    sed_i: bool = False
    sed_bsd_ok: bool = False
    sed_failed: bool = False
    sed_noop: bool = False
    heredoc_files: list[str] = field(default_factory=list)
    written_files: list[str] = field(default_factory=list)
    is_test: bool = False
    runs_app: bool = False
    think_dup_ratio: float = 0.0
    think_overlap_prev: float = 0.0


def shingles(text: str, n: int = 6) -> set[int]:
    w = re.findall(r"\w+", text.lower())
    return {hash(tuple(w[i : i + n])) for i in range(max(0, len(w) - n + 1))}


def dup_sentence_ratio(text: str) -> float:
    sents = [s.strip().lower() for s in re.split(r"(?<=[.!?:])\s+|\n+", text) if len(s.strip()) > 25]
    if not sents:
        return 0.0
    c = Counter(sents)
    return sum(v - 1 for v in c.values()) / len(sents)


def parse(path: Path) -> list[Act]:
    t = json.loads(path.read_text())
    msgs = t["messages"]
    by_id = {m.get("tool_call_id"): m for m in msgs if m.get("role") == "tool"}
    acts: list[Act] = []
    turn = 0
    for idx, m in enumerate(msgs):
        if m.get("role") != "assistant":
            continue
        turn += 1
        extra = m.get("extra", {})
        usage = extra.get("response", {}).get("usage", {}) or {}
        think = m.get("reasoning_content") or ""
        actions = extra.get("actions", [])
        for k, a in enumerate(actions):
            obs = by_id.get(a.get("tool_call_id"))
            if obs is None:  # fall back to positional
                nxt = msgs[idx + 1 + k] if idx + 1 + k < len(msgs) else {}
                obs = nxt if nxt.get("role") in ("tool", "user") else {}
            content = obs.get("content", "") if obs else ""
            if isinstance(content, list):
                content = " ".join(x.get("text", "") for x in content if isinstance(x, dict))
            rc, out, trunc = None, content, False
            try:
                j = json.loads(content)
                rc = j.get("returncode")
                trunc = "output_head" in j
                out = j.get("output") or (j.get("output_head", "") + "\n...\n" + j.get("output_tail", ""))
            except (json.JSONDecodeError, AttributeError, TypeError):
                rc = (obs or {}).get("extra", {}).get("returncode")
            acts.append(
                Act(
                    turn=turn,
                    cmd=a["command"],
                    rc=rc,
                    out=out or "",
                    truncated=trunc,
                    prompt_tokens=usage.get("prompt_tokens", 0) or 0,
                    completion_tokens=usage.get("completion_tokens", 0) or 0,
                    think_chars=len(think) if k == 0 else 0,
                    kind=kind(a["command"]),
                )
            )
        if not actions:  # format error turn
            acts.append(Act(turn, "", None, "", False, usage.get("prompt_tokens", 0) or 0,
                            usage.get("completion_tokens", 0) or 0, len(think), "no-action"))
        first = acts[len(acts) - max(1, len(actions))]
        first._think = think  # type: ignore[attr-defined]
    annotate(acts)
    return acts


def annotate(acts: list[Act]) -> None:
    seen_exact: set[str] = set()
    seen_norm: set[str] = set()
    failed_norm: set[str] = set()
    seen_out: set[str] = set()
    last_seen: dict[str, int] = {}
    last_edit = -1
    versions: dict[str, list[str]] = defaultdict(list)
    prev_think_sh: list[set[int]] = []
    for i, a in enumerate(acts):
        if a.kind == "no-action":
            continue
        a.failed = (a.rc not in (0, None)) or bool(ERROR_RE.search(a.out))
        a.timeout = a.rc == -1 or "timed out" in a.out.lower() or "TimeoutExpired" in a.out
        n = normalise(a.cmd)
        a.exact_repeat = a.cmd in seen_exact
        a.near_repeat = (not a.exact_repeat) and n in seen_norm
        a.repeat_of_failed = n in failed_norm
        # a repeat is "idle" when no file was edited since the previous occurrence
        a.idle_repeat = n in last_seen and last_edit <= last_seen[n]
        a.edits = bool(EDIT_RE.search(re.sub(r"^\s*cd\s+\S+\s*&&\s*", "", a.cmd)))
        if a.edits:
            last_edit = i
        last_seen[n] = i
        seen_exact.add(a.cmd)
        seen_norm.add(n)
        if a.failed:
            failed_norm.add(n)
        changes = bool(STATE_CHANGE_RE.search(re.sub(r"^\s*cd\s+\S+\s*&&\s*", "", a.cmd)))
        o = a.out.strip()
        a.stale = (not changes) and o in seen_out and a.kind != "submit"
        seen_out.add(o)
        # sed
        sm = SED_I_RE.search(a.cmd)
        if sm:
            a.sed_i = True
            a.sed_bsd_ok = bool(sm.group(2))
            a.sed_failed = a.failed and "sed" in a.out
            a.sed_noop = (not a.failed) and bool(re.search(r"s/[^/]*\\n", a.cmd))
        # file versions
        for path, body in file_writes(a.cmd):
            a.written_files.append(path)
            if body is not None:
                a.heredoc_files.append(path)
                h = hashlib.sha1(body.encode()).hexdigest()
                vs = versions[path]
                if vs and vs[-1] == h:
                    a.rewrite_same_content = True
                elif h in vs:
                    a.rewrite_to_old_version = True
                vs.append(h)
            else:
                versions[path].append(f"opaque-{i}")
        a.is_test = bool(TEST_RE.search(a.cmd)) and a.kind != "write"
        a.runs_app = a.kind in ("run-app",) or (
            a.kind == "python-snippet" and bool(re.search(r"test_client|run_test|Pilot|subprocess", a.cmd))
        )
        think = getattr(a, "_think", "")
        if think:
            a.think_dup_ratio = dup_sentence_ratio(think)
            sh = shingles(think)
            if sh and prev_think_sh:
                a.think_overlap_prev = max(len(sh & p) / len(sh) for p in prev_think_sh)
            prev_think_sh.append(sh)
    # misread: previous action failed, this turn's reasoning claims success without acknowledging failure
    for prev, a in pairwise(acts):
        think = getattr(a, "_think", "")
        if prev.failed and think and SUCCESS_RE.search(think[:600]) and not FAIL_ACK_RE.search(think[:600]):
            a.misread_success = True


RATE_FIELDS = ["exact_repeat", "near_repeat", "idle_repeat", "repeat_of_failed", "failed", "stale", "misread_success",
               "rewrite_same_content", "rewrite_to_old_version"]


def summarise(task: str, acts: list[Act]) -> dict:
    real = [a for a in acts if a.kind != "no-action"]
    turns = max((a.turn for a in acts), default=0)
    rewrites = Counter(p for a in real for p in a.heredoc_files)
    thinks = [a.think_chars for a in acts if a.think_chars]
    ctx = [a.prompt_tokens for a in acts]
    streak = best = 0
    for a in real:
        streak = streak + 1 if a.stale else 0
        best = max(best, streak)
    return {
        "task": task,
        "turns": turns,
        "actions": len(real),
        "exact_rep": sum(a.exact_repeat for a in real),
        "near_rep": sum(a.near_repeat for a in real),
        "failed": sum(a.failed for a in real),
        "idle_rep": sum(a.idle_repeat for a in real),
        "rep_failed": sum(a.repeat_of_failed for a in real),
        "timeouts": sum(a.timeout for a in real),
        "stale": sum(a.stale for a in real),
        "max_stale_run": best,
        "misread?": sum(a.misread_success for a in real),
        "heredoc_writes": sum(len(a.heredoc_files) for a in real),
        "max_rewrites": max(rewrites.values(), default=0),
        "rewrites_by_file": dict(rewrites.most_common()),
        "same_rewrite": sum(a.rewrite_same_content for a in real),
        "revert_rewrite": sum(a.rewrite_to_old_version for a in real),
        "sed_i": sum(a.sed_i for a in real),
        "sed_gnu_form": sum(a.sed_i and not a.sed_bsd_ok for a in real),
        "sed_fail": sum(a.sed_failed for a in real),
        "sed_noop?": sum(a.sed_noop for a in real),
        "tests": sum(a.is_test for a in real),
        "app_runs": sum(a.runs_app for a in real),
        "ask_user": sum(a.kind == "ask" for a in real),
        "truncated": sum(a.truncated for a in real),
        "think_med": int(statistics.median(thinks)) if thinks else 0,
        "think_max": max(thinks, default=0),
        "ctx_max": max(ctx, default=0),
        # turns spent after the last edit to a non-test source file (verification tail)
        "tail_after_last_src_edit": turns - max(
            (a.turn for a in real for p in a.written_files
             if p.endswith(".py") and "test" not in p.rsplit("/", 1)[-1]),
            default=turns),
        "ctx_final": ctx[-1] if ctx else 0,
    }


def bucket_table(rows: list[tuple[str, Act]], keyfn, order: list[str]) -> list[dict]:
    groups: dict[str, list[Act]] = defaultdict(list)
    for _, a in rows:
        if a.kind != "no-action":
            groups[keyfn(a)].append(a)
    out = []
    for k in order:
        g = groups.get(k, [])
        if not g:
            continue
        thinks = [a.think_chars for a in g if a.think_chars]
        overl = [a.think_overlap_prev for a in g if a.think_chars]
        dups = [a.think_dup_ratio for a in g if a.think_chars]
        r = {"bucket": k, "n": len(g)}
        for f in RATE_FIELDS:
            r[f] = sum(getattr(a, f) for a in g) / len(g)
        r["think_med"] = int(statistics.median(thinks)) if thinks else 0
        r["think_mean"] = int(statistics.mean(thinks)) if thinks else 0
        r["think_overlap"] = statistics.mean(overl) if overl else 0
        r["think_dup"] = statistics.mean(dups) if dups else 0
        out.append(r)
    return out


def kind_table(rows: list[tuple[str, Act]], thirds: dict[int, str]) -> list[dict]:
    """Failure rate per action kind, early vs late, to compare like with like."""
    agg: dict[tuple[str, str], list[Act]] = defaultdict(list)
    for _, a in rows:
        if a.kind in ("no-action", "submit"):
            continue
        agg[(a.kind, thirds[id(a)])].append(a)
    out = []
    for kd in sorted({k for k, _ in agg}):
        r = {"kind": kd}
        for th in ("early", "mid", "late"):
            g = agg.get((kd, th), [])
            r[th] = f"{sum(a.failed for a in g)}/{len(g)}" if g else "-"
            r[th + "_rep"] = f"{sum(a.exact_repeat or a.near_repeat for a in g)}/{len(g)}" if g else "-"
        out.append(r)
    return out


def fmt(rows: list[dict], cols: list[str]) -> str:
    def cell(v):
        if isinstance(v, float):
            return f"{v:.2f}"
        return str(v)

    if not rows:
        return "(no data)"
    w = {c: max(len(c), *(len(cell(r.get(c, ""))) for r in rows)) for c in cols}
    lines = [" | ".join(c.ljust(w[c]) for c in cols), "-+-".join("-" * w[c] for c in cols)]
    for r in rows:
        lines.append(" | ".join(cell(r.get(c, "")).ljust(w[c]) for c in cols))
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dirs", nargs="+", type=Path)
    ap.add_argument("--turns", action="store_true", help="print per-turn lines")
    ap.add_argument("--json", type=Path, help="write all metrics to this file")
    args = ap.parse_args()

    summaries, rows, thirds = [], [], {}
    for rd in args.run_dirs:
        for tj in sorted(rd.glob("*/*/trajectory.json")):
            task = f"{rd.name.split('-')[3] if rd.name.count('-') >= 3 else rd.name}/{tj.parent.parent.name}"
            acts = parse(tj)
            s = summarise(task, acts)
            pr = rd / tj.parent.parent.name / "0" / "verify" / "pytest.log"
            if pr.exists():
                m = re.search(r"(\d+) passed", pr.read_text())
                f = re.search(r"(\d+) failed", pr.read_text())
                s["hidden"] = f"{m.group(1) if m else 0}/{int(m.group(1) if m else 0) + int(f.group(1) if f else 0)}"
            summaries.append(s)
            n = max(a.turn for a in acts) if acts else 1
            for a in acts:
                rows.append((task, a))
                thirds[id(a)] = ("early", "mid", "late")[min(2, (a.turn - 1) * 3 // n)]
            if args.turns:
                print(f"\n## {task}")
                for a in acts:
                    flags = [f for f in RATE_FIELDS + ["truncated", "is_test", "runs_app", "sed_i"] if getattr(a, f)]
                    print(f"t{a.turn:>3} ctx={a.prompt_tokens:>6} think={a.think_chars:>5} rc={a.rc} "
                          f"{a.kind:<14} {','.join(flags):<40} {a.cmd.splitlines()[0][:90] if a.cmd else ''}")

    cols = ["task", "hidden", "turns", "exact_rep", "near_rep", "idle_rep", "failed", "rep_failed", "timeouts", "stale", "max_stale_run",
            "misread?", "heredoc_writes", "max_rewrites", "same_rewrite", "revert_rewrite", "sed_i", "sed_gnu_form",
            "sed_fail", "sed_noop?", "tests", "app_runs", "ask_user", "truncated", "think_med", "think_max", "ctx_max",
            "tail_after_last_src_edit"]
    print("# Per task  (hidden = verify/pytest.log as written at run time; later regrades are not reflected)\n")
    print(fmt(summaries, cols))
    print("\n# Heredoc rewrites per file (files written >1 time)\n")
    for s in summaries:
        multi = {k: v for k, v in s["rewrites_by_file"].items() if v > 1}
        if multi:
            print(f"{s['task']}: {multi}")

    bcols = ["bucket", "n"] + RATE_FIELDS + ["think_med", "think_mean", "think_overlap", "think_dup"]
    print("\n# By turn third (within each trajectory), all trajectories pooled\n")
    print(fmt(bucket_table(rows, lambda a: thirds[id(a)], ["early", "mid", "late"]), bcols))
    print("\n# By context band (prompt tokens at that turn)\n")
    print(fmt(bucket_table(rows, lambda a: ctx_band(a.prompt_tokens), [b[2] for b in CTX_BANDS]), bcols))
    long_tasks = {s["task"] for s in summaries if s["turns"] >= 30}
    print(f"\n# By turn third, long trajectories only (>=30 turns: {len(long_tasks)})\n")
    print(fmt(bucket_table([r for r in rows if r[0] in long_tasks], lambda a: thirds[id(a)],
                           ["early", "mid", "late"]), bcols))
    print("\n# Same action kind, early vs late: failed/n and repeat/n\n")
    print(fmt(kind_table(rows, thirds), ["kind", "early", "mid", "late", "early_rep", "mid_rep", "late_rep"]))

    if args.json:
        args.json.write_text(json.dumps({
            "summaries": summaries,
            "turns": [{"task": t, **{k: v for k, v in asdict(a).items() if k != "out"}} for t, a in rows],
        }, indent=1))


if __name__ == "__main__":
    sys.exit(main())
