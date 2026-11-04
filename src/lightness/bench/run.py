"""Bench runner: workspace → agent → hidden-test verifier → metrics.

    uv run python -m lightness.bench.run --agent oracle
    uv run python -m lightness.bench.run --agent bare --model qwen27 --tasks file-organizer --runs 3
    uv run python -m lightness.bench.run --agent mw:workshop,checks,gate --model qwen35a3
"""

import json
import os
import shutil
import subprocess
import sys
import threading
import time
import tomllib
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

import typer

from lightness.bench import sandbox
from lightness.bench.agents import (
    BareAgent,
    LightnessAgent,
    MiddlewareAgent,
    NullAgent,
    OracleAgent,
    bench_env,
)
from lightness.bench.tasks import REPO_ROOT, Task, all_task_ids, load_task

app = typer.Typer(add_completion=False)


def make_agent(name: str, model: str | None, tests: str = "none"):
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
    if name == "lightness":
        return LightnessAgent(models[model], model)
    if name == "lightness-auto":
        return LightnessAgent(models[model], model, user="defaults")
    if name == "mw" or name.startswith("mw:"):
        features = [f for f in name.partition(":")[2].split(",") if f]
        try:
            return MiddlewareAgent(model, features, tests=tests)
        except ValueError as e:
            raise typer.BadParameter(str(e)) from None
    raise typer.BadParameter(f"unknown agent {name}")


def _check_tests(name: str, tests: str) -> None:
    if tests != "none" and not name.startswith("mw"):
        raise typer.BadParameter("--tests applies to mw agents with the kit")


TEST_TIMEOUT = 20  # seconds per hidden test; a test that hangs fails alone


def verify(task: Task, ws: Path, run_dir: Path, test_timeout: float = TEST_TIMEOUT) -> dict:
    """Run hidden tests against a scratch copy of the workspace. Agent never sees tests/.

    Each test runs in its own pytest process with its own timeout, so one hanging test fails
    without taking the others down with it."""
    vdir = run_dir.resolve() / "verify"
    vws = vdir / "workspace"
    shutil.copytree(ws, vws)
    shutil.copytree(task.tests, vdir / "tests")
    reports = vdir / "reports"
    reports.mkdir()
    # Hidden tests execute agent-written code, so they run sandboxed too.
    env = os.environ | bench_env() | sandbox.sandbox_env(vdir) | {"BENCH_WORKSPACE": str(vws)}

    def pytest(args: list[str], timeout: float) -> subprocess.CompletedProcess | None:
        try:
            return subprocess.run([*sandbox.sandbox_prefix(vdir), sys.executable, "-m", "pytest", *args,
                                   "-q", "-p", "no:cacheprovider"],
                                  cwd=vdir, env=env, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return None

    collected = pytest(["tests", "--collect-only"], task.verify_timeout_sec)
    if collected is None:
        return {"pass": False, "verify_error": "timeout", "tests_total": 0, "tests_passed": 0}
    ids = [line for line in collected.stdout.splitlines() if "::" in line and not line.startswith(" ")]
    log, cases = [], []  # cases: (name, ok)
    if collected.returncode != 0 or not ids:  # collection errors: one run, so they show up as errors
        ids = ["tests"]
    for i, node in enumerate(ids):
        report = reports / f"{i}.xml"
        proc = pytest([node, f"--junitxml={report}"], test_timeout if node != "tests" else task.verify_timeout_sec)
        if proc is None:
            log.append(f"{node} TIMEOUT after {test_timeout}s")
            cases.append((node.rpartition("::")[2], False))
            continue
        log.append(proc.stdout + proc.stderr)
        if report.exists():
            for case in ET.parse(report).getroot().iter("testcase"):
                ok = not any(child.tag in ("failure", "error", "skipped") for child in case)
                cases.append((case.get("name", ""), ok))
    (vdir / "pytest.log").write_text("\n".join(log))
    if not cases:
        return {"pass": False, "verify_error": "no report", "tests_total": 0, "tests_passed": 0}

    total = len(cases)
    passed = sum(ok for _, ok in cases)
    intent_total = sum(name.startswith("test_intent_") for name, _ in cases)
    intent_passed = sum(ok and name.startswith("test_intent_") for name, ok in cases)
    return {
        "pass": passed == total,
        "tests_total": total,
        "tests_passed": passed,
        "test_fraction": passed / total,
        "intent_total": intent_total,
        "intent_passed": intent_passed,
    }


@app.command()
def main(
    agent: str = typer.Option("oracle", help="oracle | null | bare | bare-ask | lightness | lightness-auto"),
    model: str = typer.Option(None, help="key in models.toml"),
    tasks: str = typer.Option("all", help="comma-separated task ids, or 'all'"),
    suite: str = typer.Option("tasks", help="task folder under bench/: tasks (main benchmark), kit-tui, ..."),
    runs: int = typer.Option(1, help="runs per task"),
    jobs: int = typer.Option(1, help="runs at once (keep 1 for a local server: it serves one request at a time)"),
    tests: str = typer.Option("none", help="kit testing arm: none | first | after (see docs/kits.md)"),
    out: Path = typer.Option(REPO_ROOT / "runs"),
):
    task_ids = all_task_ids(suite) if tasks == "all" else tasks.split(",")
    _check_tests(agent, tests)
    agent_obj = make_agent(agent, model, tests)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    prefix = "" if suite == "tasks" else f"{suite}-"
    batch_dir = out / f"{prefix}{stamp}-{agent_obj.name}-{model or 'none'}-{os.getpid()}"
    batch_dir.mkdir(parents=True)
    results_path = batch_dir / "results.jsonl"

    lock = threading.Lock()

    def one(tid: str, i: int) -> None:
        task = load_task(tid, suite)
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
        row = {"task": tid, "run": i, "agent": agent, "model": model, "tests": tests, **asdict(res), **v,
               "total_sec": round(time.time() - t0, 1)}
        mark = "PASS" if v["pass"] else "fail"
        asked = len(res.extra.get("questions", []))
        with lock:
            with results_path.open("a") as f:
                f.write(json.dumps(row) + "\n")
            typer.echo(f"{mark} {tid}#{i} tests {v['tests_passed']}/{v['tests_total']} "
                       f"intent {v.get('intent_passed', 0)}/{v.get('intent_total', 0)} asked={asked} "
                       f"status={res.exit_status} calls={res.model_calls} {row['total_sec']}s")

    todo = [(tid, i) for tid in task_ids for i in range(runs)]
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        for future in [pool.submit(one, tid, i) for tid, i in todo]:
            future.result()

    rows = [json.loads(line) for line in results_path.read_text().splitlines()]
    n_pass = sum(r["pass"] for r in rows)
    typer.echo(f"\n{n_pass}/{len(rows)} passed → {results_path}")


if __name__ == "__main__":
    app()
