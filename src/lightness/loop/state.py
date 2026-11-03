"""Run state: everything the harness knows, persisted after every turn so a run can resume."""

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from lightness.spec.workshop import Spec


@dataclass
class Step:
    id: int
    goal: str
    files: list[str]
    check: str
    status: str = "todo"  # todo | done | failed
    attempts: int = 0  # failed verifications on this step
    turns: int = 0  # turns spent while this was the current step
    kind: str = "code"  # code | reproduce | test | final


@dataclass
class Observation:
    turn: int
    action: str
    target: str
    ok: bool
    text: str


@dataclass
class RunState:
    task: str
    spec: Spec | None = None
    probes: list[dict] = field(default_factory=list)
    plan: list[Step] = field(default_factory=list)
    files_read: list[str] = field(default_factory=list)
    observations: list[Observation] = field(default_factory=list)
    facts: list[str] = field(default_factory=list)
    tried: list[str] = field(default_factory=list)  # one line per abandoned attempt on the current step
    turn: int = 0
    idle: int = 0  # consecutive look-only actions (read/search/test/probe/run) since the last write
    working: list[str] = field(default_factory=list)  # recently read FILE::SYMBOL, shown in full each turn
    last_change_turn: int = 0
    seen: dict[str, str] = field(default_factory=dict)  # read target -> content digest when shown
    noop: dict[str, int] = field(default_factory=dict)  # edit target -> last_change_turn when it was a no-op
    turn_action_target: str = ""
    failing_cache: tuple[int, list[str]] | None = None  # (last_change_turn, failing test ids) for revert
    green_since: int | None = None  # turn at which everything last passed with no change since
    finished: bool = False
    outcome: str = ""

    @property
    def current(self) -> Step | None:
        return next((s for s in self.plan if s.status == "todo"), None)

    def observe(self, action: str, target: str, ok: bool, text: str) -> Observation:
        o = Observation(self.turn, action, target, ok, text)
        self.observations.append(o)
        return o

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2))

    @classmethod
    def load(cls, path: Path) -> "RunState":
        d = json.loads(path.read_text())
        d["spec"] = Spec.from_json(json.dumps(d["spec"])) if d.get("spec") else None
        d["plan"] = [Step(**s) for s in d["plan"]]
        d["observations"] = [Observation(**o) for o in d["observations"]]
        return cls(**d)
