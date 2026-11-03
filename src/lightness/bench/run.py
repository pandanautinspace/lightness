"""Bench runner: workspace → agent → hidden-test verifier → metrics.

    uv run python -m lightness.bench.run --agent oracle
    uv run python -m lightness.bench.run --agent bare --model qwen27 --tasks file-organizer --runs 3
"""

import json
import os
import shutil
import subprocess
import sys
import time
import tomllib
import xml.etree.ElementTree as ET
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

import typer

from lightness.bench import sandbox
from lightness.bench.agents import BareAgent, NullAgent, OracleAgent, bench_env
from lightness.bench.tasks import REPO_ROOT, Task, all_task_ids, load_task

app = typer.Typer(add_completion=False)


def make_agent(name: str, model: str | None):
    if name == "oracle":
        return OracleAgent()
    if name == "null":
        return NullAgent()
    models = tomllib.loads((REPO_ROOT / "models.toml").read_text())
    if not model or model not in models:
        raise typer.BadParameter(f"--model must be one of {list(models)}")
    if name == "bare":
        return BareAgent(models[model])
    if name == "bare-ask":
        return BareAgent(models[model], ask=True)
    raise typer.BadParameter(f"unknown agent {name}")


def verify(task: Task, ws: Path, run_dir: Path) -> dict:
    """Run hidden tests against a scratch copy of the workspace. Agent never sees tests/."""
    vdir = run_dir.resolve() / "verify"
    vws = vdir / "workspace"
    shutil.copytree(ws, vws)
    shutil.copytree(task.tests, vdir / "tests")
    report = vdir / "report.xml"
    # Hidden tests execute agent-written code, so they run sandboxed too.
    env = os.environ | bench_env() | sandbox.sandbox_env(vdir) | {"BENCH_WORKSPACE": str(vws)}
    try:
        proc = subprocess.run(
            [*sandbox.sandbox_prefix(vdir),
             sys.executable, "-m", "pytest", "tests", "-q", "-p", "no:cacheprovider", f"--junitxml={report}"],
            cwd=vdir, env=env, capture_output=True, text=True, timeout=task.verify_timeout_sec,
        )
        (vdir / "pytest.log").write_text(proc.stdout + proc.stderr)
    except subprocess.TimeoutExpired:
        return {"pass": False, "verify_error": "timeout", "tests_total": 0, "tests_passed": 0}
    if not report.exists():
        return {"pass": False, "verify_error": "no report", "tests_total": 0, "tests_passed": 0}

    total = passed = intent_total = intent_passed = 0
    for case in ET.parse(report).getroot().iter("testcase"):
        ok = not any(child.tag in ("failure", "error", "skipped") for child in case)
        is_intent = case.get("name", "").startswith("test_intent_")
        total += 1
        passed += ok
        intent_total += is_intent
        intent_passed += ok and is_intent
    return {
        "pass": total > 0 and passed == total,
        "tests_total": total,
        "tests_passed": passed,
        "test_fraction": passed / total if total else 0.0,
        "intent_total": intent_total,
        "intent_passed": intent_passed,
    }


@app.command()
def main(
    agent: str = typer.Option("oracle", help="oracle | null | bare | bare-ask"),
    model: str = typer.Option(None, help="key in models.toml"),
    tasks: str = typer.Option("all", help="comma-separated task ids, or 'all'"),
    runs: int = typer.Option(1, help="runs per task"),
    out: Path = typer.Option(REPO_ROOT / "runs"),
):
    task_ids = all_task_ids() if tasks == "all" else tasks.split(",")
    agent_obj = make_agent(agent, model)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    batch_dir = out / f"{stamp}-{agent}-{model or 'none'}-{os.getpid()}"
    batch_dir.mkdir(parents=True)
    results_path = batch_dir / "results.jsonl"

    for tid in task_ids:
        task = load_task(tid)
        for i in range(runs):
            run_dir = batch_dir / tid / str(i)
            ws = run_dir / "workspace"
            seed = task.environment / "seed"
            if seed.exists():
                shutil.copytree(seed, ws)
            else:
                ws.mkdir(parents=True)
            subprocess.run(["git", "init", "-q"], cwd=ws)  # lets us diff what the agent changed

            t0 = time.time()
            res = agent_obj.run(task, ws, run_dir)
            v = verify(task, ws, run_dir)
            row = {"task": tid, "run": i, "agent": agent, "model": model, **asdict(res), **v,
                   "total_sec": round(time.time() - t0, 1)}
            with results_path.open("a") as f:
                f.write(json.dumps(row) + "\n")
            mark = "PASS" if v["pass"] else "fail"
            asked = len(res.extra.get("questions", []))
            typer.echo(f"{mark} {tid}#{i} tests {v['tests_passed']}/{v['tests_total']} "
                       f"intent {v.get('intent_passed', 0)}/{v.get('intent_total', 0)} asked={asked} "
                       f"status={res.exit_status} calls={res.model_calls} {row['total_sec']}s")

    rows = [json.loads(line) for line in results_path.read_text().splitlines()]
    n_pass = sum(r["pass"] for r in rows)
    typer.echo(f"\n{n_pass}/{len(rows)} passed → {results_path}")


if __name__ == "__main__":
    app()
