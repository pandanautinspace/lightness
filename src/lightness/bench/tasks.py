"""Loading benchmark tasks from bench/tasks/<id>/."""

import tomllib
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
TASKS_DIR = REPO_ROOT / "bench" / "tasks"


@dataclass
class Task:
    id: str
    path: Path
    category: str
    difficulty: str
    agent_timeout_sec: int
    verify_timeout_sec: int

    @property
    def instruction(self) -> str:
        return (self.path / "instruction.md").read_text()

    @property
    def intent(self) -> str:
        p = self.path / "intent.md"
        return p.read_text() if p.exists() else ""

    @property
    def environment(self) -> Path:
        return self.path / "environment"

    @property
    def tests(self) -> Path:
        return self.path / "tests"

    @property
    def solution(self) -> Path:
        return self.path / "solution"


def load_task(task_id: str) -> Task:
    path = TASKS_DIR / task_id
    meta = tomllib.loads((path / "task.toml").read_text())
    return Task(
        id=task_id,
        path=path,
        category=meta["category"],
        difficulty=meta.get("difficulty", "medium"),
        agent_timeout_sec=meta.get("agent_timeout_sec", 1800),
        verify_timeout_sec=meta.get("verify_timeout_sec", 300),
    )


def all_task_ids() -> list[str]:
    return sorted(p.name for p in TASKS_DIR.iterdir() if (p / "task.toml").exists())
