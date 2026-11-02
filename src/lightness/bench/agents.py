"""Agents the bench can run. Each takes a workspace + instruction and edits files in place."""

import os
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

from lightness.bench import sandbox
from lightness.bench.tasks import Task


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

    def __init__(self, model: dict, step_limit: int = 100):
        self.model = model
        self.step_limit = step_limit

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
        class SandboxedEnvironment(LocalEnvironment):
            def execute(self, action: dict, cwd: str = "", *, timeout: int | None = None):
                action = action | {"command": sandbox.wrap_shell(action.get("command", ""), log_dir)}
                return super().execute(action, cwd, timeout=timeout)

        env = SandboxedEnvironment(
            cwd=str(ws),
            env=cfg["environment"]["env"] | bench_env() | sandbox.sandbox_env(log_dir),
            timeout=120,
        )
        agent = DefaultAgent(model, env, **agent_cfg)
        start = time.time()
        try:
            info = agent.run(task.instruction)
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
        return res
