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


KIT_CLASSIFY = {
    "type": "object",
    "properties": {"kind": {"enum": ["tui", "cli", "data-script", "webapp", "other"]}},
    "required": ["kind"],
    "additionalProperties": False,
}


TESTS_AFTER = ("Not submitted yet. Before submitting: write tests for the task's contract (guide below), run them, "
               "fix what fails, then submit.")


CHECKS_REFUSED = ("Not submitted yet: some checks fail. Fix the app, or a check in checks.txt that disagrees with "
                  "the task, then submit again.")
CHECKS_ALL_PASS = "If checks.txt covers every item of the task's contract, submit now; otherwise add the missing checks."
CHECKS_SHOWN, CHECK_LINES = 4, 15  # failing checks shown in full, and lines of each


def checks_text(results: dict[str, str | None], regressions: list[str]) -> str:
    failing = {n: v for n, v in results.items() if v is not None}
    lines = [f"{len(results) - len(failing)} of {len(results)} checks pass."]
    for n, detail in list(failing.items())[:CHECKS_SHOWN]:
        lines.append(f"FAIL {n}" + (" (passed before this change)" if n in regressions else ""))
        lines += ["  " + line for line in detail.splitlines()[-CHECK_LINES:]]
    if len(failing) > CHECKS_SHOWN:
        lines.append(f"Also failing: {', '.join(list(failing)[CHECKS_SHOWN:])}")
    if not failing:
        lines.append(CHECKS_ALL_PASS)
    return "\n".join(lines)


class Kit(Middleware):
    """Start new apps from the kit for their type: the harness writes a working shell, shows the
    design notes, a cheat sheet and the parts index, and checks the app still starts after each
    change. Repo changes and apps no kit fits get nothing."""

    name = "kit"

    def __init__(self, tests: str = "none"):
        """tests: the testing arm. none: try the app, tests only if the task asks; first: write tests
        from the contract before the app; after: on the first submit, ask for tests before submitting;
        checks: write the contract as one-line checks the harness runs after every change, along
        with its own generic checks."""
        from lightness.kits import TEST_ARMS

        if tests not in TEST_ARMS:
            raise ValueError(f"tests must be one of {TEST_ARMS}")
        self.tests = tests

    def start(self, ctx: Ctx) -> str | None:
        from lightness import kits

        if any(py_files(ctx.ws)):
            return None  # existing code: no starting point to give
        spec = ctx.data.get("spec")
        task = ctx.task + (("\n\n" + render(spec)) if spec else "")
        try:
            kind = ctx.client.decide([{"role": "user", "content": (
                "What kind of program does this request ask for?\n"
                "- tui: an interactive terminal app (full-screen, keys)\n"
                "- cli: a command-line tool that runs once and exits\n"
                "- data-script: a script that reads, transforms or loads data files\n"
                "- webapp: a web app or HTTP API\n"
                "- other: none of these fits well\n\n" + task)}],
                KIT_CLASSIFY, purpose="kit.classify").parsed["kind"]
        except DecisionError:
            return None
        kit = kits.load_kit(kind)
        ctx.log("kit.classify", kind=kind, available=kit is not None)
        if kit is None:
            return None
        try:
            names = ctx.client.decide([{"role": "user", "content": kit.names_prompt(task)}], kit.names_schema,
                                      purpose="kit.names", max_tokens=1500).parsed
            shell = kits.render_shell(kit, names)
        except (DecisionError, ValueError) as e:
            ctx.log("kit.failed", error=str(e)[:300])
            return None
        index = "\n".join(f"- {p.name}: {p.when}" for p in kit.parts)
        try:
            chosen = ctx.client.decide([{"role": "user", "content": (
                f"Which of these patterns will this app need? Pick at most 3.\n\n{index}\n\n## Task\n{task}")}],
                {"type": "object", "properties": {"parts": {"type": "array", "maxItems": 3, "items": {
                    "enum": [p.name for p in kit.parts]}}}, "required": ["parts"], "additionalProperties": False},
                purpose="kit.parts").parsed["parts"]
        except DecisionError:
            chosen = []
        always = kit.meta.get("always", []) + (["headless_test"] if self.tests == "first" else [])
        chosen = list(dict.fromkeys(always + chosen))
        (ctx.ws / kits.shell_path(kit, names)).write_text(shell)
        parts_dir = ctx.ws / ".lightness" / "kit" / "parts"
        parts_dir.mkdir(parents=True, exist_ok=True)
        for p in kit.parts:
            (parts_dir / p.path.name).write_text(p.path.read_text())
        if kit.try_tool:
            (parts_dir.parent / kit.try_tool.name).write_text(kit.try_tool.read_text())
            (parts_dir.parent / kit.try_tool.with_suffix(".json").name).write_text(json.dumps(names))
        ctx.data["kit"] = (kit, names)
        ctx.log("kit", kind=kind, names=names, parts=chosen, tests=self.tests)
        return kits.context(kit, names, ".lightness/kit/parts", chosen, self.tests)

    def after_command(self, ctx: Ctx, command: str, output: dict) -> str | None:
        from lightness.kits import smoke

        if "kit" not in ctx.data or ctx.data["kit"][0].category != "tui":
            return None
        kit, names = ctx.data["kit"]
        notes = []
        sig = repr(sorted(py_files(ctx.ws).items()))
        if sig != ctx.data.get("kit.sig"):  # something changed since the last smoke check
            ctx.data["kit.sig"] = sig
            results = smoke.tui(ctx.ws, names, ctx.run_dir)
            ctx.data["kit.smoke_ok"] = all(r.ok for r in results)
            if results:
                warnings = smoke.clashes(ctx.ws, names)
                text = "\n".join([smoke.summarize(results, f"{names['module']}.py"), *warnings])
                previous, ctx.data["kit.smoke"] = ctx.data.get("kit.smoke"), text
                ctx.log("smoke", ok=all(r.ok for r in results), warnings=len(warnings))
                if text != previous and not (previous is None and all(r.ok for r in results) and not warnings):
                    notes.append("[automatic start check] " + text)  # only changes (never an initial "fine")
        if self.tests == "checks" and (report := self._checks(ctx)):
            notes.append(report)
        return shorten_paths("\n\n".join(notes), ctx.ws, ctx.run_dir) if notes else None

    def _run_checks(self, ctx: Ctx) -> dict | None:
        """Run the harness's checks and checks.txt if the app or checks.txt changed since the last run
        (and the app starts); returns the new results, or None when nothing ran."""
        from lightness.kits import smoke

        if not ctx.data.get("kit.smoke_ok") or not (ctx.ws / f"{ctx.data['kit'][1]['module']}.py").exists():
            return None
        checks_file = ctx.ws / smoke.CHECKS_FILE
        stat = checks_file.stat() if checks_file.exists() else None
        sig = (ctx.data.get("kit.sig"), stat and (stat.st_mtime_ns, stat.st_size))
        if sig == ctx.data.get("kit.checks_sig"):
            return None
        ctx.data["kit.checks_sig"] = sig
        return smoke.checks(ctx.ws, ctx.run_dir)

    def _checks(self, ctx: Ctx) -> str | None:
        """The checks arm: after a change, rerun the checks and report what changed, marking checks
        that passed before and fail now."""
        from lightness.kits import smoke

        now = self._run_checks(ctx)
        if now is None:
            return None
        prev = ctx.data.get("kit.checks")
        ctx.data["kit.checks"] = now
        app_changed = ctx.data.get("kit.checks_app") != ctx.data.get("kit.sig")
        ctx.data["kit.checks_app"] = ctx.data.get("kit.sig")
        # a check that passed before fails now after the app changed (not after the check itself changed)
        regressions = [n for n, v in now.items() if v is not None and prev and n in prev and prev[n] is None
                       and app_changed]
        ctx.log("kit.checks", passed=sum(v is None for v in now.values()),
                failing=[n for n, v in now.items() if v is not None], regressions=regressions)
        if now == prev:
            return None
        if prev is None and all(v is None for v in now.values()) and not (ctx.ws / smoke.CHECKS_FILE).exists():
            return None  # only the harness's checks, all passing: nothing to say yet
        return "[automatic checks] " + checks_text(now, regressions)

    def on_submit(self, ctx: Ctx) -> str | None:
        """Refuse to submit an app that crashes on start (no limit: the step and wall limits apply)."""
        from lightness.kits import smoke

        if "kit" not in ctx.data or ctx.data["kit"][0].category != "tui":
            return None
        names = ctx.data["kit"][1]
        bad = [r for r in smoke.tui(ctx.ws, names, ctx.run_dir) if not r.ok]
        if bad:
            ctx.log("smoke.submit_refused")
            return shorten_paths("Not submitted: the app crashes on start.\n"
                                 + smoke.summarize(bad, f"{names['module']}.py"), ctx.ws, ctx.run_dir)
        if self.tests == "checks" and not ctx.data.get("kit.checks_refused"):
            ctx.data["kit.smoke_ok"] = True
            if (now := self._run_checks(ctx)) is not None:
                ctx.data["kit.checks"] = now
            failing = [n for n, v in (ctx.data.get("kit.checks") or {}).items() if v is not None]
            if failing:
                ctx.data["kit.checks_refused"] = True
                ctx.log("kit.checks_refused", failing=failing)
                return shorten_paths(CHECKS_REFUSED + "\n" + checks_text(ctx.data["kit.checks"], []), ctx.ws, ctx.run_dir)
        if self.tests == "after" and not ctx.data.get("kit.tests_asked"):
            from lightness.kits import part_text

            ctx.data["kit.tests_asked"] = True
            ctx.log("kit.tests_asked")
            guide = next(p for p in ctx.data["kit"][0].parts if p.name == "headless_test")
            return (TESTS_AFTER + "\n" + part_text(guide))
        return None
