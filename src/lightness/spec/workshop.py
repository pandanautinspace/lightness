"""Spec workshop: turn a vague request into a spec by asking the few questions that matter.

classify → generate candidate questions (guided by the catalog's dimensions) → rank by
impact × ambiguity → ask the top K → write the spec with every assumption listed.
"""

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

import yaml

from lightness.provider import Client
from lightness.user import UserChannel

CATALOG = Path(__file__).with_name("catalog")
PROJECT_TYPES = ["cli", "data-script", "webapp", "tui", "repo-change"]


@dataclass
class Question:
    question: str
    options: list[str]
    default: str
    impact: int
    ambiguity: int
    dimension: str

    @property
    def score(self) -> int:
        return self.impact * self.ambiguity


@dataclass
class Decision:
    question: str
    answer: str
    status: str  # "confirmed" (user answered) | "defaulted" (asked, no preference) | "assumed" (not asked)


@dataclass
class Spec:
    task: str
    project_type: str
    goal: str
    non_goals: list[str]
    features: list[dict]  # {"name": str, "criteria": [str]}
    contract: list[str]
    data_model: str
    decisions: list[Decision] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)

    @classmethod
    def from_json(cls, text: str) -> "Spec":
        d = json.loads(text)
        d["decisions"] = [Decision(**x) for x in d.get("decisions", [])]
        return cls(**d)


def load_catalog(project_type: str) -> dict:
    return yaml.safe_load((CATALOG / f"{project_type}.yaml").read_text())


def repo_summary(ws: Path, max_files: int = 60) -> str:
    """Cheap orientation for repo-change tasks: file tree, README head, test names."""
    files = sorted(p for p in ws.rglob("*") if p.is_file() and not any(
        part.startswith(".") or part == "__pycache__" for part in p.relative_to(ws).parts))
    lines = ["Files:"] + [f"  {p.relative_to(ws)} ({len(p.read_bytes())} bytes)" for p in files[:max_files]]
    readme = next((p for p in files if p.name.lower().startswith("readme")), None)
    if readme:
        lines += ["", "README (start):", *readme.read_text(errors="ignore").splitlines()[:25]]
    tests = [f"  {p.relative_to(ws)}: " + ", ".join(
        line.split("(")[0].replace("def ", "").strip()
        for line in p.read_text(errors="ignore").splitlines() if line.lstrip().startswith("def test_"))
        for p in files if p.name.startswith("test_")]
    if tests:
        lines += ["", "Existing tests:", *tests]
    return "\n".join(lines)


# --- model calls ------------------------------------------------------------------------------

CLASSIFY_SCHEMA = {
    "type": "object",
    "properties": {"project_type": {"enum": PROJECT_TYPES}},
    "required": ["project_type"],
    "additionalProperties": False,
}


def classify(client: Client, task: str, has_existing_code: bool) -> str:
    if has_existing_code:
        return "repo-change"
    reply = client.decide(
        [{"role": "user", "content": (
            "Classify this software request.\n"
            "- cli: a command-line tool that acts on files or prints results\n"
            "- data-script: a script that reads, cleans, transforms or loads data\n"
            "- webapp: a web application or HTTP API\n"
            "- tui: an interactive terminal UI\n\n"
            f"Request:\n{task}")}],
        CLASSIFY_SCHEMA, purpose="workshop.classify")
    return reply.parsed["project_type"]


QUESTIONS_SCHEMA = {
    "type": "object",
    "properties": {"questions": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "question": {"type": "string"},
            "options": {"type": "array", "items": {"type": "string"}},
            "default": {"type": "string"},
            "impact": {"enum": [1, 2, 3]},
            "ambiguity": {"enum": [1, 2, 3]},
            "dimension": {"type": "string"},
        },
        "required": ["question", "options", "default", "impact", "ambiguity", "dimension"],
        "additionalProperties": False,
    }}},
    "required": ["questions"],
    "additionalProperties": False,
}

QUESTIONS_PROMPT = """You are preparing to build software for a user. Before writing code, find the
decisions this request leaves open, where different reasonable choices would produce different
behaviour the user would notice.

Request:
{task}
{context}
Project type: {project_type}. Areas that often need deciding for this type:
{dimensions}

List up to {max_q} questions. Rules:
- Ask about what the user will see or experience (names, rules, formats, orderings, special
  cases), never about how to implement it. Bad: "How should file types be mapped to categories?"
  Good: "Which category folders do you want, and which file types go in each?"
- Only ask what the request does not already answer. Never ask about anything in a Contract section.
- Be concrete and specific to this request, not "Any naming preferences?".
- Give 2-4 concrete options with real example values, and your best-guess default.
- impact: 3 = changes visible behaviour or output a lot, 1 = cosmetic.
- ambiguity: 3 = several options are equally plausible, 1 = the default is almost certainly right.
- dimension: which area above it belongs to."""


def generate_questions(client: Client, task: str, project_type: str, context: str = "",
                       max_q: int = 10, reason_budget: int = 1024) -> list[Question]:
    cat = load_catalog(project_type)
    dims = "\n".join(f"- {d['id']}: {d['hint']}" for d in cat["dimensions"])
    reply = client.decide(
        [{"role": "user", "content": QUESTIONS_PROMPT.format(
            task=task, context=f"\nExisting code:\n{context}\n" if context else "",
            project_type=project_type, dimensions=dims, max_q=max_q)}],
        QUESTIONS_SCHEMA, purpose="workshop.questions", reason_budget=reason_budget, max_tokens=3000)
    return [Question(**q) for q in reply.parsed["questions"]][:max_q]


SPEC_SCHEMA = {
    "type": "object",
    "properties": {
        "goal": {"type": "string"},
        "non_goals": {"type": "array", "items": {"type": "string"}},
        "features": {"type": "array", "items": {
            "type": "object",
            "properties": {"name": {"type": "string"}, "criteria": {"type": "array", "items": {"type": "string"}}},
            "required": ["name", "criteria"],
            "additionalProperties": False,
        }},
        "contract": {"type": "array", "items": {"type": "string"}},
        "data_model": {"type": "string"},
    },
    "required": ["goal", "non_goals", "features", "contract", "data_model"],
    "additionalProperties": False,
}

SPEC_PROMPT = """Write a precise spec for this software request.

Request:
{task}
{context}
Decisions (use every one of these exactly; they override your own preferences):
{decisions}

Write:
- goal: one or two sentences.
- non_goals: things explicitly not being built (keep the scope small).
- features: each with acceptance criteria that are concrete and checkable: exact names, formats,
  orderings, edge cases. Every decision above must appear in at least one criterion, stated exactly.
- contract: the external interface as exact items (commands and flags, function signatures with
  return shapes, routes with status codes, element ids). Copy any Contract section verbatim.
- data_model: the data the program stores or produces, briefly."""


def write_spec(client: Client, task: str, project_type: str, decisions: list[Decision],
               context: str = "", reason_budget: int = 1024) -> Spec:
    lines = "\n".join(f"- {d.question} → {d.answer}" for d in decisions) or "- (none)"
    reply = client.decide(
        [{"role": "user", "content": SPEC_PROMPT.format(
            task=task, context=f"\nExisting code:\n{context}\n" if context else "", decisions=lines)}],
        SPEC_SCHEMA, purpose="workshop.spec", reason_budget=reason_budget, max_tokens=4000)
    return Spec(task=task, project_type=project_type, decisions=decisions, **reply.parsed)


# --- orchestration ----------------------------------------------------------------------------

def run_workshop(client: Client, user: UserChannel, task: str, *, ws: Path | None = None,
                 max_asked: int = 5) -> Spec:
    has_code = ws is not None and any(p.suffix == ".py" for p in ws.rglob("*.py"))
    context = repo_summary(ws) if has_code else ""
    project_type = classify(client, task, has_code)
    questions = generate_questions(client, task, project_type, context)
    ranked = sorted(questions, key=lambda q: q.score, reverse=True)

    decisions = []
    for i, q in enumerate(ranked):
        if i < max_asked:
            ans = user.ask(q.question, q.options, q.default)
            status = "confirmed" if ans.covered else "defaulted"
            decisions.append(Decision(q.question, ans.text if ans.covered else q.default, status))
        else:
            decisions.append(Decision(q.question, q.default, "assumed"))
    return write_spec(client, task, project_type, decisions, context)


def render(spec: Spec) -> str:
    out = [f"# Spec ({spec.project_type})", "", "## Goal", spec.goal, ""]
    if spec.non_goals:
        out += ["## Non-goals", *[f"- {g}" for g in spec.non_goals], ""]
    out += ["## Features"]
    for f in spec.features:
        out += [f"### {f['name']}", *[f"- [ ] {c}" for c in f["criteria"]], ""]
    out += ["## Contract", *[f"- {c}" for c in spec.contract], "", "## Data model", spec.data_model, ""]
    out += ["## Decisions", "| Question | Answer | Status |", "|---|---|---|"]
    out += [f"| {d.question} | {d.answer} | {d.status} |" for d in spec.decisions]
    return "\n".join(out) + "\n"
