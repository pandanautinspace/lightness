"""Middleware for the transcript agent. Each piece can be switched on alone, so it can be measured
against the bare baseline; keep only what helps.
"""

import hashlib
import json
from pathlib import Path

from lightness.agent.loop import Ctx, Middleware
from lightness.loop import prompts
from lightness.provider import DecisionError
from lightness.spec.workshop import render, run_workshop
from lightness.user import UserChannel
from lightness.verify.chain import all_tests, check_tests, failing_tests, verify
from lightness.verify.compress import shorten_paths
from lightness.verify.probes import PROBE_SCHEMA, run_probes, summarize

SKIP_DIRS = {"__pycache__", "tmp", ".git", ".venv", "node_modules"}


def py_files(ws: Path) -> dict[str, tuple[int, int]]:
    """Python files in the workspace → (mtime_ns, size)."""
    out = {}
    for p in ws.rglob("*.py"):
        rel = p.relative_to(ws)
        if not any(part in SKIP_DIRS or part.startswith(".") for part in rel.parts):
            st = p.stat()
            out[str(rel)] = (st.st_mtime_ns, st.st_size)
    return out


class Workshop(Middleware):
    """Ask the user the questions that matter before any code, and put the spec in the task."""

    name = "workshop"

    def __init__(self, user: UserChannel, max_asked: int = 5):
        self.user, self.max_asked = user, max_asked

    def start(self, ctx: Ctx) -> str | None:
        spec = run_workshop(ctx.client, self.user, ctx.task, ws=ctx.ws, max_asked=self.max_asked)
        ctx.data["spec"] = spec
        ctx.log("workshop", questions=len(getattr(self.user, "log", [])))
        return ("## Agreed spec\n\nThe user and I worked out these details before you start. Where they are "
                "more specific than the issue, follow them exactly.\n\n" + render(spec))


ENV_NOTES = """## Environment notes

- The project is the current directory. Use relative paths; there is no /testbed, /app, /workspace or /root.
- Python 3.12 with textual, rich, typer, flask, httpx, pytest and the standard library is already installed.
  There is no pip and no network: never try to install anything.
- /tmp is not writable. Put scratch files in the project directory or under $TMPDIR.
- Commands have no terminal and no stdin: interactive programs (Textual apps, input(), a server in the
  foreground) can't be driven directly. Test Textual apps headlessly with App.run_test(), CLIs by running
  them with arguments, and Flask apps with app.test_client()."""


class EnvNotes(Middleware):
    """State the facts about the environment the models keep getting wrong (pip, /tmp, /testbed, no tty)."""

    name = "env"

    def start(self, ctx: Ctx) -> str | None:
        return ENV_NOTES


class Checks(Middleware):
    """After a command changes Python files: static checks on those files, and the test suite's
    status with any tests the change newly broke. The model gets this without asking for it."""

    name = "checks"

    def before_command(self, ctx: Ctx, command: str) -> None:
        ctx.data["checks.before"] = py_files(ctx.ws)

    def after_command(self, ctx: Ctx, command: str, output: dict) -> str | None:
        before, now = ctx.data.get("checks.before", {}), py_files(ctx.ws)
        changed = sorted(f for f, sig in now.items() if before.get(f) != sig)
        if not changed:
            return None
        notes = []
        r = verify(ctx.ws, [ctx.ws / f for f in changed], run_dir=ctx.run_dir, tests="none", fix=False)
        if not r.ok:
            notes.append(r.observation())
        if all_tests(ctx.ws):
            prev = ctx.data.get("checks.failing")
            failing = failing_tests(ctx.ws, ctx.run_dir)
            if failing is None:
                notes.append("Tests: the test suite could not run (collection or import error). Run pytest to see why.")
            else:
                ctx.data["checks.failing"] = failing
                new = sorted(failing - prev) if prev is not None else []
                fixed = sorted(prev - failing) if prev is not None else []
                line = f"Tests: {len(failing)} failing" if failing else "Tests: all pass"
                if new:
                    line += f"; newly failing after this change: {', '.join(new[:5])}"
                if fixed:
                    line += f"; now passing: {', '.join(fixed[:5])}"
                notes.append(line)
        ctx.log("checks", changed=changed, ok=r.ok)
        if not notes:
            return None
        text = f"[automatic checks on {', '.join(changed[:5])}]\n" + "\n".join(notes)
        return shorten_paths(text, ctx.ws, ctx.run_dir)


class SubmitGate(Middleware):
    """Refuse a submission while tests fail or the spec's contract probes fail (at most `limit` times)."""

    name = "gate"

    def __init__(self, limit: int = 2):
        self.limit = limit

    def start(self, ctx: Ctx) -> str | None:
        spec = ctx.data.get("spec")
        if spec is None:
            return None
        try:
            ctx.data["probes"] = ctx.client.decide([{"role": "user", "content": prompts.probes_prompt(spec)}],
                                                   PROBE_SCHEMA, purpose="probes", max_tokens=3000).parsed["probes"]
        except DecisionError:
            ctx.data["probes"] = []
        (ctx.run_dir / "probes.json").write_text(json.dumps(ctx.data["probes"], indent=1))  # for auditing refusals
        return None

    def on_submit(self, ctx: Ctx) -> str | None:
        refused = ctx.data.get("gate.refused", 0)
        if refused >= self.limit:
            return None
        problems = []
        if all_tests(ctx.ws):
            c = check_tests(None, ctx.ws, ctx.run_dir, 180)
            if not c.ok:
                problems.append("Tests fail:\n" + c.summary)
        probes = ctx.data.get("probes") or []
        if probes:
            results = run_probes(probes, ctx.ws, ctx.run_dir)
            if not all(r.ok for r in results):
                problems.append("The program does not meet the agreed contract:\n" + summarize(results))
        if not problems:
            return None
        ctx.data["gate.refused"] = refused + 1
        return shorten_paths("Not submitted. Before submitting, fix these:\n\n" + "\n\n".join(problems)
                             + "\n\nThen submit again.", ctx.ws, ctx.run_dir)


class RepeatGuard(Middleware):
    """Point out when the model runs the same command again with nothing changed in between."""

    name = "repeat"

    def before_command(self, ctx: Ctx, command: str) -> None:
        state = hashlib.sha1(repr(sorted(py_files(ctx.ws).items())).encode()).hexdigest()
        key = (command.strip(), state)
        seen = ctx.data.setdefault("repeat.seen", {})
        seen[key] = seen.get(key, 0) + 1
        ctx.data["repeat.count"] = seen[key]

    def after_command(self, ctx: Ctx, command: str, output: dict) -> str | None:
        n = ctx.data.get("repeat.count", 1)
        if n < 2:
            return None
        ctx.log("repeat", n=n)
        return (f"[note] You have now run this exact command {n} times with no file changes in between; "
                "the result will not change. Try something different.")


class Compaction(Middleware):
    """Past a token threshold, shorten old command outputs (keep the last `keep` in full). Done in one
    sweep so the prompt prefix stays cacheable between sweeps."""

    name = "compact"

    def __init__(self, threshold: int = 24000, keep: int = 6, head: int = 400):
        self.threshold, self.keep, self.head = threshold, keep, head

    def before_call(self, ctx: Ctx) -> None:
        if ctx.last_prompt_tokens < self.threshold:
            return
        tools = [m for m in ctx.messages if m["role"] == "tool"]
        cut = 0
        for m in tools[:-self.keep]:
            if len(m["content"]) > self.head * 2:
                m["content"] = m["content"][:self.head] + "\n...[older output shortened by the harness]"
                cut += 1
        if cut:
            ctx.log("compact", messages=cut, prompt_tokens=ctx.last_prompt_tokens)
