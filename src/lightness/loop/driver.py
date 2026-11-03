"""The guarded loop: each turn the model picks one action from a menu that is valid right now.

workshop → probes → plan → turns (context rebuilt from state; constrained action choice; the action
runs as a macro with verification) → done only when tests and contract probes pass.
"""

import re
import subprocess
import time
from pathlib import Path

from lightness.bench import sandbox
from lightness.edit.fences import FenceError, extract_code
from lightness.edit.symbols import SymbolError, get_symbol, list_symbols, replace_symbol
from lightness.loop import prompts
from lightness.loop.state import RunState, Step
from lightness.provider import Client, DecisionError
from lightness.spec.workshop import load_catalog, run_workshop
from lightness.user import UserChannel
from lightness.verify.chain import BIN, all_tests, check_tests, failing_tests, verify
from lightness.verify.compress import shorten_paths, traceback_summary
from lightness.verify.probes import PROBE_SCHEMA, run_probes, summarize
from lightness.verify.testlint import lint_tests

LOOK_ONLY = {"read", "read_symbol", "search", "test", "probe", "run"}
MAX_IDLE = 3  # look-only actions in a row before only acting is allowed
STEP_TURNS = 15  # turns on one step before a plan revision is forced

PATH_RE = r"^[A-Za-z0-9_][A-Za-z0-9_./-]*\.(py|txt|md|json|toml|csv|html|css|js|cfg|ini|yaml|yml)$"

ACTION_DOCS = {
    "read": "read FILE: show a file (outline if long). You must read a file before editing its symbols.",
    "read_symbol": "read_symbol FILE::NAME: show one function/class in full.",
    "search": "search TEXT: find lines containing TEXT in project files.",
    "write_file": "write_file PATH: write a whole file (new files, or small files). Checked automatically.",
    "edit_symbol": "edit_symbol FILE::NAME: rewrite one existing function/class/method. Checked automatically.",
    "add_symbol": "add_symbol FILE: add new functions/classes to the end of an existing file.",
    "run": "run ARGS: run `python ARGS` once (60s limit, no background processes).",
    "test": "test TARGET: run a test file, or 'all'.",
    "probe": "probe: run the contract checks (starts/stops apps for you).",
    "ask_user": "ask_user QUESTION: ask the user (only if the spec truly doesn't say).",
    "revise_plan": "revise_plan: rewrite the remaining plan steps.",
    "done_step": "done_step: the current step is finished (its check is run first).",
    "done": "done: the whole task is finished (all tests and contract checks are run first).",
}


def list_symbols_safe(source: str) -> list[str]:
    try:
        return list_symbols(source)
    except SyntaxError:
        return []


class Harness:
    def __init__(self, client: Client, ws: Path, user: UserChannel, *, run_dir: Path | None = None,
                 max_turns: int = 60, wall_limit: float = 1800, max_questions: int = 5, state_path: Path | None = None):
        self.client, self.ws, self.user, self.run_dir = client, ws, user, run_dir
        self.max_turns, self.wall_limit, self.max_questions = max_turns, wall_limit, max_questions
        self.state_path = state_path
        self.start = time.time()
        self.recent_actions: list[tuple[str, str, int]] = []  # (action, target, last_change_turn)

    # --- setup ------------------------------------------------------------------------------

    def setup(self, task: str) -> RunState:
        st = RunState(task)
        st.spec = run_workshop(self.client, self.user, task, ws=self.ws, max_asked=self.max_questions)
        try:
            st.probes = self.client.decide([{"role": "user", "content": prompts.probes_prompt(st.spec)}],
                                           PROBE_SCHEMA, purpose="probes", max_tokens=3000).parsed["probes"]
        except DecisionError:
            st.probes = []
        st.plan = self.make_plan(st)
        self.save(st)
        return st

    def make_plan(self, st: RunState, note: str = "") -> list[Step]:
        prompt = prompts.plan_prompt(st.spec, prompts.file_tree(self.ws)) + (f"\n\n{note}" if note else "")
        steps = self.client.decide([{"role": "user", "content": prompt}], prompts.PLAN_SCHEMA,
                                   purpose="plan", reason_budget=1024, max_tokens=2000).parsed["steps"]
        start = max((s.id for s in st.plan), default=0)
        limit = 3 if st.spec and st.spec.project_type == "repo-change" else 8
        return [Step(start + i + 1, s["goal"], [f for f in s["files"] if re.match(PATH_RE, f)], s["check"])
                for i, s in enumerate(steps[:limit])]

    # --- menu ---------------------------------------------------------------------------------

    def files(self) -> list[str]:
        return [l.split(" (")[0] for l in prompts.file_tree(self.ws, limit=200).splitlines() if not l.startswith("...")]

    def symbols(self, st: RunState) -> list[str]:
        out = []
        for f in st.files_read:
            p = self.ws / f
            if p.suffix == ".py" and p.exists():
                try:
                    out += [f"{f}::{s}" for s in list_symbols(p.read_text())]
                except SyntaxError:
                    pass
        return out

    def menu(self, st: RunState) -> dict[str, dict]:
        """Allowed actions → JSON schema for their target."""
        files = self.files()
        py_read = [f for f in st.files_read if f.endswith(".py") and (self.ws / f).exists()]
        syms = self.symbols(st)
        tests = [f for f in files if Path(f).name.startswith("test_")]
        string = {"type": "string"}
        m: dict[str, dict] = {}
        if st.green_since is not None and st.turn - st.green_since >= 2:
            return {"done": {"const": ""}}
        unseen_files = [f for f in files if st.seen.get(f) != self._digest(f)]
        unseen_syms = [x for x in syms if x not in st.working or st.seen.get(x) != self._digest(x.split("::")[0])]
        if unseen_files:
            m["read"] = {"enum": unseen_files}
        if unseen_syms:
            m["read_symbol"] = {"enum": unseen_syms}
        m["search"] = string
        m["write_file"] = {"type": "string", "pattern": PATH_RE}
        if syms:
            m["edit_symbol"] = {"enum": syms}
        if py_read:
            m["add_symbol"] = {"enum": py_read}
        m["run"] = string
        if tests:
            m["test"] = {"enum": tests + ["all"]}
        if st.probes:
            m["probe"] = {"const": ""}
        if len(self.user.log) < self.max_questions:
            m["ask_user"] = string
        m["revise_plan"] = {"const": ""}
        if st.current:
            m["done_step"] = {"const": ""}
        else:
            m["done"] = {"const": ""}
        step = st.current
        if step and step.turns > STEP_TURNS:
            return {k: v for k, v in m.items() if k in ("revise_plan", "ask_user")} or {"revise_plan": {"const": ""}}
        if st.idle >= MAX_IDLE or self._looping():
            for k in LOOK_ONLY:
                m.pop(k, None)
        return m

    def _looping(self) -> bool:
        """Same action+target three times with no file change in between."""
        if len(self.recent_actions) < 3:
            return False
        last = self.recent_actions[-3:]
        return len({(a, t) for a, t, _ in last}) == 1 and len({c for _, _, c in last}) == 1

    @staticmethod
    def schema(menu: dict[str, dict]) -> dict:
        return {"type": "object", "properties": {"choice": {"anyOf": [
            {"type": "object", "properties": {"action": {"const": a}, "target": t, "why": {"type": "string"}},
             "required": ["action", "target", "why"], "additionalProperties": False}
            for a, t in menu.items()]}}, "required": ["choice"], "additionalProperties": False}

    # --- loop ---------------------------------------------------------------------------------

    def run(self, task: str) -> RunState:
        st = self.setup(task)
        while not st.finished:
            self.turn(st)
        return st

    def turn(self, st: RunState) -> None:
        st.turn += 1
        if st.turn > self.max_turns or time.time() - self.start > self.wall_limit:
            st.finished, st.outcome = True, "budget"
            self.save(st)
            return
        m = self.menu(st)
        doc = "\n".join(f"- {ACTION_DOCS[a]}" for a in m)
        failed_last = bool(st.observations) and not st.observations[-1].ok
        try:
            choice = self.client.decide(
                [{"role": "user", "content": prompts.turn_prompt(st, self.ws, doc)}], self.schema(m),
                purpose="act", reason_budget=1024 if failed_last else 0, max_tokens=400).parsed["choice"]
        except DecisionError as e:
            st.observe("invalid", "", False, str(e)[:300])
            self.save(st)
            return
        action, target = choice["action"], choice["target"]
        self.recent_actions.append((action, target, st.last_change_turn))
        if st.current:
            st.current.turns += 1
        st.idle = st.idle + 1 if action in LOOK_ONLY else 0
        handler = getattr(self, f"do_{action}")
        ok, text = handler(st, target)
        text = shorten_paths(text, self.ws, self.run_dir)
        st.observe(action, target, ok, text)
        self.after(st, action, ok, text)
        self.save(st)

    def after(self, st: RunState, action: str, ok: bool, text: str) -> None:
        step = st.current
        if action in ("write_file", "edit_symbol", "add_symbol") and not ok and step:
            step.attempts += 1
            if step.attempts >= 3:  # restart the step with a short memory of what failed
                st.tried.append(f"turn {st.turn}: {text.splitlines()[0][:200] if text else 'failed'}")
                step.attempts = 0
                st.observations = st.observations[:-3]  # drop the failing transcript from context

    # --- actions ------------------------------------------------------------------------------

    def _digest(self, rel: str) -> str:
        import hashlib
        p = self.ws / rel
        return hashlib.sha1(p.read_bytes()).hexdigest()[:12] if p.is_file() else ""

    def _mark_read(self, st: RunState, f: str) -> None:
        if f not in st.files_read:
            st.files_read.append(f)

    def do_read(self, st, target):
        p = self.ws / target
        if not p.is_file():
            return False, f"{target} does not exist"
        self._mark_read(st, target)
        st.seen[target] = self._digest(target)
        return True, prompts._outline_or_body(p)[:6000]

    def do_read_symbol(self, st, target):
        f, name = target.split("::", 1)
        try:
            body = get_symbol((self.ws / f).read_text(), name)
        except (SymbolError, OSError) as e:
            return False, str(e)
        st.working = [w for w in st.working if w != target][-2:] + [target]
        st.seen[target] = self._digest(f)
        return True, f"(now shown in full under 'Working set' every turn)\n{body}"[:4000]

    def do_search(self, st, target):
        if not target.strip():
            return False, "empty search"
        hits = []
        for f in self.files():
            p = self.ws / f
            for i, line in enumerate(p.read_text(errors="ignore").splitlines(), 1):
                if target.lower() in line.lower():
                    hits.append(f"{f}:{i}: {line.strip()[:160]}")
        return True, "\n".join(hits[:30]) or "no matches"

    def _code(self, st, instruction: str, context: str, purpose: str) -> str:
        reply = self.client.chat([{"role": "user", "content": prompts.code_prompt(st, self.ws, instruction, context)}],
                                 purpose=purpose, max_tokens=8000)
        return reply.text

    def _commit(self, st, rel: str, new_text: str) -> tuple[bool, str]:
        p = self.ws / rel
        if not p.resolve().is_relative_to(self.ws.resolve()):
            return False, "refused: path outside the project"
        if p.exists() and p.read_text() == new_text:
            return False, "no change made: the new content is identical to the current file"
        if Path(rel).name.startswith("test_"):
            project = [f for f in self.files() if f.endswith(".py") and not Path(f).name.startswith("test_")]
            modules = {Path(f).stem for f in project} | {f.split("/")[0] for f in project if "/" in f}
            problems = lint_tests(new_text, modules)
            if problems:
                return False, "test file rejected (not written):\n" + "\n".join(f"- {x}" for x in problems)
        old_text = p.read_text() if p.exists() else None
        guard = old_text is not None and not Path(rel).name.startswith("test_") and bool(all_tests(self.ws))
        before = self._failing(st) if guard else None
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(new_text)
        self._mark_read(st, rel)
        st.last_change_turn, st.green_since = st.turn, None
        result = verify(self.ws, [p], run_dir=self.run_dir)
        if before is not None and result.failed is not None and result.failed.stage == "tests":
            after = failing_tests(self.ws, self.run_dir)
            broken = sorted(after - before) if after is not None else ["(test collection)"]
            if broken:  # never make things worse: undo edits that break tests that passed before
                p.write_text(old_text)
                return False, ("edit reverted: it broke tests that passed before: " + ", ".join(broken[:5])
                               + "\n" + result.observation())
        st.failing_cache = None
        return result.ok, result.observation()

    def _failing(self, st) -> set[str] | None:
        """Failing tests right now, cached until the next file change."""
        if st.failing_cache is None or st.failing_cache[0] != st.last_change_turn:
            st.failing_cache = (st.last_change_turn, sorted(failing_tests(self.ws, self.run_dir) or []))
        return set(st.failing_cache[1])

    def do_write_file(self, st, target):
        p = self.ws / target
        is_test = Path(target).name.startswith("test_")
        current = f"\n## Current {target}\n```python\n{p.read_text()}```\n" if p.exists() else ""
        fixture = ""
        if is_test and st.spec:
            fixture = "\n## Test pattern to follow\n```python\n" + load_catalog(st.spec.project_type).get("test_fixture", "") + "```\n"
        instruction = (f"Write the complete file {target}."
                       + (" Test the acceptance criteria with exact expected values; never mock this project's own code." if is_test else ""))
        try:
            code = extract_code(self._code(st, instruction, prompts.other_outlines(self.ws, target) + current + fixture,
                                           "write_file"), Path(target).name)
        except FenceError as e:
            return False, f"could not use the reply: {e}"
        return self._commit(st, target, code)

    def do_edit_symbol(self, st, target):
        f, name = target.split("::", 1)
        src = (self.ws / f).read_text()
        try:
            body = get_symbol(src, name)
        except SymbolError as e:
            return False, str(e)
        instruction = f"Rewrite `{name}` in {f}. Return the complete new definition of `{name.split('.')[-1]}` only (plus any new imports it needs)."
        context = prompts.other_outlines(self.ws, f) + f"\n## Current `{name}` in {f}\n```python\n{body}```\n"
        try:
            new = replace_symbol(src, name, extract_code(self._code(st, instruction, context, "edit_symbol")))
        except (FenceError, SymbolError) as e:
            return False, f"could not apply the edit: {e}"
        return self._commit(st, f, new)

    def do_add_symbol(self, st, target):
        src = (self.ws / target).read_text()
        instruction = f"Write the new function(s)/class to add at the end of {target}. Return only the new code."
        context = f"\n## {target} (outline)\n```python\n{prompts._outline_or_body(self.ws / target)}```\n"
        try:
            code = extract_code(self._code(st, instruction, context, "add_symbol"))
        except FenceError as e:
            return False, f"could not use the reply: {e}"
        clashes = set(list_symbols_safe(code)) & set(list_symbols_safe(src))
        if clashes:
            return False, f"already defined in {target}: {', '.join(sorted(clashes))}; use edit_symbol instead"
        return self._commit(st, target, src.rstrip("\n") + "\n\n\n" + code)

    def do_run(self, st, target):
        if "&" in target or target.strip().startswith(("pip", "-m pip")):
            return False, "refused: no background processes or installs"
        import shlex
        try:
            args = shlex.split(target)
        except ValueError as e:
            return False, f"could not parse arguments: {e}"
        cmd = [str(BIN / "python"), *args]
        env = None
        if self.run_dir is not None:
            import os
            cmd = [*sandbox.sandbox_prefix(self.run_dir), *cmd]
            env = os.environ | sandbox.sandbox_env(self.run_dir)
        try:
            proc = subprocess.run(cmd, cwd=self.ws, capture_output=True, text=True, timeout=60, env=env, stdin=subprocess.DEVNULL)
        except subprocess.TimeoutExpired:
            return False, "timed out after 60s (waiting for input, or a server? use probe for servers)"
        out = (proc.stdout + ("\n" + traceback_summary(proc.stderr, self.ws) if proc.stderr.strip() else ""))
        lines = out.strip().splitlines()
        text = "\n".join(lines[:40]) + (f"\n... ({len(lines) - 40} more lines)" if len(lines) > 40 else "")
        return proc.returncode == 0, f"exit code {proc.returncode}\n{text}"

    def do_test(self, st, target):
        tests = None if target == "all" else [self.ws / target]
        c = check_tests(tests, self.ws, self.run_dir, 120)
        return c.ok, c.summary or "tests passed"

    def do_probe(self, st, target):
        results = run_probes(st.probes, self.ws, self.run_dir)
        return all(r.ok for r in results), summarize(results)

    def do_ask_user(self, st, target):
        a = self.user.ask(target)
        if a.covered:
            st.facts.append(f"User said ({target}): {a.text}")
        return True, a.text

    def do_revise_plan(self, st, target):
        done = [s for s in st.plan if s.status == "done"]
        last = st.observations[-1].text[:1500] if st.observations else ""
        note = ("Steps already done:\n" + "\n".join(f"- {s.goal}" for s in done)
                + f"\nLatest result:\n{last}\nPlan only the remaining work.")
        st.plan = done + self.make_plan(st, note)
        st.tried = []
        return True, "plan revised:\n" + "\n".join(f"{s.id}. {s.goal}" for s in st.plan if s.status == "todo")

    def _full_check(self, st) -> tuple[bool, str]:
        c = check_tests(None, self.ws, self.run_dir, 180)
        if not c.ok:
            return False, c.summary
        if st.probes:
            results = run_probes(st.probes, self.ws, self.run_dir)
            if not all(r.ok for r in results):
                return False, summarize(results)
        return True, "All tests and contract checks pass."

    def do_done_step(self, st, target):
        step = st.current
        files = [self.ws / f for f in step.files if (self.ws / f).exists()]
        missing = [f for f in step.files if not (self.ws / f).exists()]
        if missing:
            return False, f"step files not written yet: {', '.join(missing)}"
        if files:
            r = verify(self.ws, files, run_dir=self.run_dir)
            if not r.ok:
                return False, r.observation()
        if step.attempts or st.tried:
            st.facts.append(f"Step {step.id} ({step.goal[:60]}) needed fixes: {(st.tried or ['see history'])[-1][:150]}")
        step.status, st.tried = "done", []
        if not st.current:
            ok, text = self._full_check(st)
            if ok:
                st.green_since = st.turn
            return True, f"step {step.id} done. Final check: {text}"
        return True, f"step {step.id} done; next: {st.current.goal}"

    def do_done(self, st, target):
        ok, text = self._full_check(st)
        if ok:
            st.finished, st.outcome = True, "passed"
        elif st.green_since is not None:
            st.green_since = None
        return ok, text

    def save(self, st: RunState) -> None:
        if self.state_path:
            st.save(self.state_path)
