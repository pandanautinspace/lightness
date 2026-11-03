"""Prompt text for the loop: plan, probes, turn context, and code-writing calls.

Context is rebuilt from state every turn (no growing transcript) and kept under a character
budget, roughly 4 characters per token.
"""

import json
from pathlib import Path

from lightness.edit.symbols import outline
from lightness.loop.state import RunState
from lightness.spec.workshop import Spec, render

ENVIRONMENT = """Environment:
- The project is the current directory. Use relative paths. There is nothing at /testbed, /app or /workspace.
- Python 3.12 with: pytest, flask, textual, httpx, rich, typer, and the standard library. No network: never pip install.
- Temporary files go under $TMPDIR (tests: use pytest's tmp_path). Never start servers in the background;
  the `probe` and `test` actions start and stop them for you."""

CHAR_BUDGET = 45_000  # ~12K tokens

PLAN_SCHEMA = {
    "type": "object",
    "properties": {"steps": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "goal": {"type": "string"},
            "files": {"type": "array", "items": {"type": "string"}},
            "check": {"type": "string"},
        },
        "required": ["goal", "files", "check"],
        "additionalProperties": False,
    }}},
    "required": ["steps"],
    "additionalProperties": False,
}


def spec_digest(spec: Spec) -> str:
    return render(spec)


def plan_prompt(spec: Spec, tree: str) -> str:
    return f"""Plan how to build this spec as a short list of small steps (3-8).

{spec_digest(spec)}
Current files:
{tree or "(empty directory)"}

Rules:
- Order: core logic first (pure functions, no I/O), then tests for the acceptance criteria, then the
  user-facing shell (CLI / web routes / TUI), then a final check against the whole spec.
- For changes to existing code: find the code involved, change it, then add tests for the change.
- Keep modules small; separate logic from I/O so it can be tested directly.
- files: the files each step creates or changes (relative paths). Test files are named test_*.py.
- check: how we'll know the step worked (which tests pass, which command runs)."""


def probes_prompt(spec: Spec) -> str:
    return f"""Turn this spec's contract into a few automatic checks (2-6) that run the finished program.

{spec_digest(spec)}
Probe kinds:
- cli: run `python <args>`; files under {{tmp}} are created from setup_files first; checks exit code
  and (optionally) that stdout is JSON.
- http: start the server with `python <start args>` (use {{port}} for the port, {{tmp}} for data files),
  then send requests and check status codes and (for HTML pages) that element ids/names exist.
- function: optionally run setup commands (`before`), then call module.name(*args_json) and check the
  return type and, for lists/tuples of tuples, how many fields each item has (item_len, -1 = any).
- tui: create the Textual app class with init_args_json and check it mounts and has the widget ids.
Only check what the contract states. Use {{tmp}} for every path the program reads or writes.
Use "" for unused string fields and [] for unused lists."""


def file_tree(ws: Path, limit: int = 80) -> str:
    files = sorted(p for p in ws.rglob("*") if p.is_file() and not any(
        part.startswith(".") or part in ("__pycache__", "tmp") for part in p.relative_to(ws).parts))
    lines = [f"{p.relative_to(ws)} ({len(p.read_bytes())} bytes)" for p in files[:limit]]
    if len(files) > limit:
        lines.append(f"... {len(files) - limit} more")
    return "\n".join(lines)


def _outline_or_body(path: Path, max_lines: int = 150) -> str:
    text = path.read_text(errors="replace")
    if path.suffix == ".py" and len(text.splitlines()) > max_lines:
        try:
            return "(outline; bodies elided)\n" + outline(text)
        except SyntaxError:
            pass
    return text


def turn_prompt(st: RunState, ws: Path, menu_doc: str) -> str:
    step = st.current
    parts = [ENVIRONMENT, "", spec_digest(st.spec) if st.spec else f"Task:\n{st.task}"]
    plan = "\n".join(f"{'→' if s is step else ' '} [{s.status}] {s.id}. {s.goal} (files: {', '.join(s.files)}; "
                     f"check: {s.check})" for s in st.plan)
    parts += ["## Plan", plan or "(no plan)", "", "## Files", file_tree(ws) or "(none yet)"]
    if step:
        for f in step.files:
            p = ws / f
            if p.exists() and f in st.files_read:
                parts += ["", f"## {f}", "```", _outline_or_body(p), "```"]
    if st.facts:
        parts += ["", "## Learned facts", *[f"- {x}" for x in st.facts[-8:]]]
    if st.tried:
        parts += ["", "## Already tried on this step (did not work)", *[f"- {x}" for x in st.tried[-4:]]]
    recent = st.observations[-3:]
    if recent:
        parts += ["", "## Recent results"]
        for o in recent:
            parts += [f"[turn {o.turn}] {o.action} {o.target} → {'ok' if o.ok else 'FAILED'}", o.text[:2500], ""]
    parts += ["", "## Your move", menu_doc,
              "Choose the single next action. Keep `why` to one sentence."]
    text = "\n".join(parts)
    if len(text) > CHAR_BUDGET:  # trim file bodies first by switching to outlines, then cut
        text = text[:CHAR_BUDGET] + "\n...(truncated)"
    return text


CODE_PROMPT = """{environment}

{spec}
## Current step
{step}

## Files
{tree}
{context}
{facts}
## Instruction
{instruction}

Reply with exactly one fenced ```python code block and nothing else."""


def code_prompt(st: RunState, ws: Path, instruction: str, context: str) -> str:
    step = st.current
    step_text = f"{step.goal}\nfiles: {', '.join(step.files)}\ncheck: {step.check}" if step else "(final fixes)"
    facts = ("## Learned facts\n" + "\n".join(f"- {x}" for x in st.facts[-8:]) + "\n") if st.facts else ""
    return CODE_PROMPT.format(environment=ENVIRONMENT, spec=spec_digest(st.spec) if st.spec else st.task,
                              step=step_text, tree=file_tree(ws), context=context, facts=facts,
                              instruction=instruction)


def other_outlines(ws: Path, exclude: str, limit_chars: int = 8000) -> str:
    """Outlines of other project modules, so new code imports real names."""
    out, used = [], 0
    for p in sorted(ws.rglob("*.py")):
        rel = str(p.relative_to(ws))
        if rel == exclude or any(part.startswith(".") or part == "tmp" for part in p.relative_to(ws).parts):
            continue
        try:
            o = outline(p.read_text(errors="replace"))
        except SyntaxError:
            continue
        block = f"\n## {rel} (outline)\n```python\n{o}```\n"
        if used + len(block) > limit_chars:
            break
        out.append(block)
        used += len(block)
    return "".join(out)


def as_json(obj) -> str:
    return json.dumps(obj, indent=1)
