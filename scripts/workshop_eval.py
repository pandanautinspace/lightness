"""Offline check of the spec workshop: how many hidden intent bullets end up correctly in the spec?

    uv run python scripts/workshop_eval.py qwen35a3 [--user sim|defaults] [--tasks a,b] [--k 5]

No code is written. Writes spec.md/spec.json/judgement.json per task under runs/workshop-*/.
"""

import argparse
import json
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

from lightness.bench.tasks import REPO_ROOT, all_task_ids, load_task
from lightness.provider import Client
from lightness.spec.workshop import render, run_workshop
from lightness.user import DefaultsUser, SimulatedUser

JUDGE_SCHEMA = {
    "type": "object",
    "properties": {"verdict": {"enum": ["yes", "partial", "no", "contradicts"]}, "evidence": {"type": "string"}},
    "required": ["verdict", "evidence"],
    "additionalProperties": False,
}
SCORE = {"yes": 1.0, "partial": 0.5, "no": 0.0, "contradicts": 0.0}


def intent_bullets(intent: str) -> list[str]:
    bullets: list[str] = []
    for line in intent.splitlines():
        if line.startswith("- "):
            bullets.append(line[2:].strip())
        elif line.startswith("  ") and bullets:
            bullets[-1] += " " + line.strip()
    return bullets


def judge(client: Client, spec_md: str, requirement: str) -> dict:
    reply = client.decide(
        [{"role": "user", "content": (
            "Does this spec state the requirement below, with the same specifics?\n"
            "- yes: the spec states it (same names, values, rules)\n"
            "- partial: the spec covers the topic but some specifics are missing or vaguer\n"
            "- no: the spec doesn't address it\n"
            "- contradicts: the spec states something incompatible\n\n"
            f"Requirement:\n{requirement}\n\nSpec:\n{spec_md}\n\n"
            "Give the verdict and quote the spec line you based it on (or 'none').")}],
        JUDGE_SCHEMA, purpose="judge", max_tokens=400, temperature=0)
    return reply.parsed


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("model")
    ap.add_argument("--user", choices=["sim", "defaults"], default="sim")
    ap.add_argument("--tasks", default="all")
    ap.add_argument("--k", type=int, default=5)
    args = ap.parse_args()

    out = REPO_ROOT / "runs" / f"workshop-{datetime.now():%Y%m%d-%H%M%S}-{args.model}-{args.user}"
    task_ids = all_task_ids() if args.tasks == "all" else args.tasks.split(",")
    totals = []
    for tid in task_ids:
        task = load_task(tid)
        tdir = out / tid
        tdir.mkdir(parents=True)
        client = Client.from_registry(args.model, log_path=tdir / "calls.jsonl")
        user = SimulatedUser(client, task.intent) if args.user == "sim" else DefaultsUser()
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            if (task.environment / "seed").exists():
                shutil.copytree(task.environment / "seed", ws, dirs_exist_ok=True)
            spec = run_workshop(client, user, task.instruction, ws=ws, max_asked=args.k)
        md = render(spec)
        (tdir / "spec.md").write_text(md)
        (tdir / "spec.json").write_text(spec.to_json())

        verdicts = []
        for b in intent_bullets(task.intent):
            v = judge(client, md, b)
            verdicts.append({"requirement": b, **v})
        (tdir / "judgement.json").write_text(json.dumps(verdicts, indent=2))
        coverage = sum(SCORE[v["verdict"]] for v in verdicts) / max(len(verdicts), 1)
        asked = len(user.log)
        covered = sum(e.answer.covered for e in user.log)
        totals.append(coverage)
        marks = "".join({"yes": "Y", "partial": "p", "no": ".", "contradicts": "X"}[v["verdict"]] for v in verdicts)
        print(f"{tid:16} coverage {coverage:4.0%}  [{marks}]  asked {asked} (answered {covered})  "
              f"type={spec.project_type}")
    print(f"\nmean coverage {sum(totals) / len(totals):.0%} → {out}")


if __name__ == "__main__":
    main()
