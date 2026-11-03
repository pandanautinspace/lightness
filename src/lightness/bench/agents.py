"""Agents the bench can run. Each takes a workspace + instruction and edits files in place."""

import os
import shlex
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

from lightness.bench import sandbox
from lightness.bench.tasks import Task
from lightness.provider import Client
from lightness.user import SimulatedUser


@dataclass
class AgentResult:
    exit_status: str
    wall_sec: float
    model_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    format_errors: int = 0
    extra: dict = field(default_factory=dict)


def bench_env() -> dict[str, str]:
    """Environment for agent commands: the bench venv's python first on PATH."""
    venv_bin = Path(os.environ.get("VIRTUAL_ENV", Path(__file__).resolve().parents[3] / ".venv")) / "bin"
    return {"PATH": f"{venv_bin}:{os.environ['PATH']}", "PYTHONDONTWRITEBYTECODE": "1"}


class NullAgent:
    """Does nothing. Every task should fail under it; otherwise its tests are too weak."""

    name = "null"

    def run(self, task: Task, ws: Path, log_dir: Path) -> AgentResult:
        return AgentResult("Submitted", 0.0)


class OracleAgent:
    """Copies the reference solution. Used to validate that a task's tests are passable."""

    name = "oracle"

    def run(self, task: Task, ws: Path, log_dir: Path) -> AgentResult:
        start = time.time()
        shutil.copytree(task.solution, ws, dirs_exist_ok=True)
        return AgentResult("Submitted", time.time() - start)


class BareAgent:
    """mini-swe-agent's default bash-only loop against an OpenAI-compatible endpoint."""

    name = "bare"

    def __init__(self, model: dict, step_limit: int = 100, ask: bool = False, max_questions: int = 5):
        self.model = model
        self.step_limit = step_limit
        self.ask = ask
        self.max_questions = max_questions
        if ask:
            self.name = "bare-ask"

    def run(self, task: Task, ws: Path, log_dir: Path) -> AgentResult:
        import yaml
        from minisweagent.agents.default import DefaultAgent
        from minisweagent.config import builtin_config_dir
        from minisweagent.environments.local import LocalEnvironment
        from minisweagent.models.litellm_model import LitellmModel

        cfg = yaml.safe_load((builtin_config_dir / "mini.yaml").read_text())
        agent_cfg = cfg["agent"] | {
            "step_limit": self.step_limit,
            "cost_limit": 0,
            "wall_time_limit_seconds": task.agent_timeout_sec,
            "output_path": log_dir / "trajectory.json",
        }
        agent_cfg.pop("mode", None)
        model = LitellmModel(
            **cfg["model"]
            | {
                "model_name": f"openai/{self.model['model']}",
                "model_kwargs": {"api_base": self.model["base_url"], "api_key": "local"},
                "cost_tracking": "ignore_errors",
            }
        )
        user = None
        instruction = task.instruction
        if self.ask:
            user = SimulatedUser(
                Client(self.model["base_url"], self.model["model"], log_path=log_dir / "calls.jsonl"), task.intent
            )
            instruction += ASK_INSTRUCTIONS.format(n=self.max_questions)
        max_questions = self.max_questions

        class SandboxedEnvironment(LocalEnvironment):
            def execute(self, action: dict, cwd: str = "", *, timeout: int | None = None):
                command = action.get("command", "")
                if user is not None and command.strip().startswith("ask_user"):
                    return {"output": answer_ask_user(command, user, max_questions), "returncode": 0, "exception_info": ""}
                action = action | {"command": sandbox.wrap_shell(command, log_dir)}
                return super().execute(action, cwd, timeout=timeout)

        env = SandboxedEnvironment(
            cwd=str(ws),
            env=cfg["environment"]["env"] | bench_env() | sandbox.sandbox_env(log_dir),
            timeout=120,
        )
        agent = DefaultAgent(model, env, **agent_cfg)
        start = time.time()
        try:
            info = agent.run(instruction)
            status = info.get("exit_status", "")
        except Exception as e:  # keep the run; the verifier still grades whatever was written
            status = f"Crashed:{type(e).__name__}"
        res = AgentResult(status, time.time() - start, model_calls=agent.n_calls)
        for msg in agent.messages:
            extra = msg.get("extra", {})
            usage = (extra.get("response") or {}).get("usage") if isinstance(extra.get("response"), dict) else None
            if usage:
                res.prompt_tokens += usage.get("prompt_tokens") or 0
                res.completion_tokens += usage.get("completion_tokens") or 0
            if extra.get("interrupt_type") == "FormatError":
                res.format_errors += 1
        if user is not None:
            res.extra["questions"] = [
                {"q": e.question, "a": e.answer.text, "covered": e.answer.covered} for e in user.log
            ]
        return res


ASK_INSTRUCTIONS = """

## Asking the user

If the request leaves something important unclear, you can ask the user by running
`ask_user "your question"` as a command. You may ask at most {n} questions; ask only about
things that change what you build."""


def answer_ask_user(command: str, user: SimulatedUser, max_questions: int) -> str:
    if len(user.log) >= max_questions:
        return "You have used all your questions. Decide for yourself."
    rest = command.strip()[len("ask_user"):].strip()
    try:
        parts = shlex.split(rest)
        question = " ".join(parts) if parts else rest
    except ValueError:
        question = rest.strip("\"'")
    if not question:
        return 'Usage: ask_user "your question"'
    return user.ask(question).text


class LightnessAgent:
    """The lightness harness: workshop → probes → plan → guarded loop."""

    def __init__(self, model: dict, model_name: str, *, user: str = "sim", max_turns: int = 60):
        self.model, self.model_name, self.user_kind, self.max_turns = model, model_name, user, max_turns
        self.name = "lightness" if user == "sim" else "lightness-auto"

    def run(self, task: Task, ws: Path, log_dir: Path) -> AgentResult:
        import json

        from lightness.loop.driver import Harness
        from lightness.user import DefaultsUser

        calls = log_dir / "calls.jsonl"
        client = Client.from_registry(self.model_name, log_path=calls)
        user = SimulatedUser(client, task.intent) if self.user_kind == "sim" else DefaultsUser()
        harness = Harness(client, ws, user, run_dir=log_dir, max_turns=self.max_turns,
                          wall_limit=task.agent_timeout_sec, state_path=log_dir / "state.json")
        start = time.time()
        try:
            st = harness.run(task.instruction)
            status = st.outcome or "unfinished"
        except Exception as e:  # keep the run; the verifier still grades whatever was written
            import traceback
            (log_dir / "crash.txt").write_text(traceback.format_exc())
            status = f"Crashed:{type(e).__name__}"
        res = AgentResult(status, time.time() - start)
        rows = [json.loads(line) for line in calls.read_text().splitlines()] if calls.exists() else []
        agent_rows = [r for r in rows if r["purpose"] not in ("simuser",)]
        res.model_calls = len(agent_rows)
        res.prompt_tokens = sum(r.get("prompt_tokens") or 0 for r in agent_rows)
        res.completion_tokens = sum(r.get("completion_tokens") or 0 for r in agent_rows)
        res.format_errors = sum(1 for r in agent_rows if r["purpose"].endswith(":retry"))
        res.extra["questions"] = [{"q": e.question, "a": e.answer.text, "covered": e.answer.covered} for e in user.log]
        return res


class MiddlewareAgent:
    """The bare agent's loop with lightness middleware switched on by name (mw:checks,gate,...)."""

    FEATURES = ("env", "workshop", "kit", "checks", "gate", "repeat", "compact", "guard")  # guard: command runner

    def __init__(self, model_name: str, features: list[str], step_limit: int = 100):
        unknown = set(features) - set(self.FEATURES)
        if unknown:
            raise ValueError(f"unknown middleware {sorted(unknown)}; choose from {self.FEATURES}")
        self.model_name, self.features, self.step_limit = model_name, features, step_limit
        self.name = "mw" + ("-" + ".".join(features) if features else "")

    def run(self, task: Task, ws: Path, log_dir: Path) -> AgentResult:
        import json

        from lightness.agent import middleware as mw
        from lightness.agent.loop import TranscriptAgent

        calls = log_dir / "calls.jsonl"
        client = Client.from_registry(self.model_name, log_path=calls)
        user = SimulatedUser(client, task.intent)
        build = {"env": mw.EnvNotes, "workshop": lambda: mw.Workshop(user), "kit": mw.Kit, "checks": mw.Checks, "gate": mw.SubmitGate,
                 "repeat": mw.RepeatGuard, "compact": mw.Compaction}
        middleware = [build[f]() for f in self.FEATURES if f in self.features and f in build]  # fixed order
        env = os.environ | bench_env() | sandbox.sandbox_env(log_dir) | {
            "PAGER": "cat", "MANPAGER": "cat", "LESS": "-R", "PIP_PROGRESS_BAR": "off", "TQDM_DISABLE": "1"}
        agent = TranscriptAgent(client, ws, log_dir, env, middleware=middleware, step_limit=self.step_limit,
                                wall_limit=task.agent_timeout_sec, guard_commands="guard" in self.features)
        start = time.time()
        try:
            status = agent.run(task.instruction).status
        except Exception as e:  # keep the run; the verifier still grades whatever was written
            import traceback
            (log_dir / "crash.txt").write_text(traceback.format_exc())
            status = f"Crashed:{type(e).__name__}"
        res = AgentResult(status, time.time() - start)
        rows = [json.loads(line) for line in calls.read_text().splitlines()] if calls.exists() else []
        agent_rows = [r for r in rows if r["purpose"] not in ("simuser",)]
        res.model_calls = len(agent_rows)
        res.prompt_tokens = sum(r.get("prompt_tokens") or 0 for r in agent_rows)
        res.completion_tokens = sum(r.get("completion_tokens") or 0 for r in agent_rows)
        events = log_dir / "events.jsonl"
        res.format_errors = events.read_text().count('"format_error"') if events.exists() else 0
        res.extra["questions"] = [{"q": e.question, "a": e.answer.text, "covered": e.answer.covered} for e in user.log]
        return res
