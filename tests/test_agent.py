import json
import os
import time
from pathlib import Path

import pytest

from lightness.agent import middleware as mw
from lightness.agent.loop import SUBMIT, TranscriptAgent
from lightness.bench import sandbox
from lightness.bench.agents import bench_env
from lightness.provider import Reply


class FakeClient:
    """Replies with one bash call per turn from a script."""

    def __init__(self, commands):
        self.commands, self.seen = list(commands), []

    def chat(self, messages, **kw):
        self.seen.append([dict(m) for m in messages])
        if not self.commands:
            return Reply(text="", usage={"prompt_tokens": 10})
        cmd = self.commands.pop(0)
        call = {"id": f"c{len(self.seen)}", "type": "function",
                "function": {"name": "bash", "arguments": json.dumps({"command": cmd})}}
        return Reply(text="ok", tool_calls=[call], usage={"prompt_tokens": 10})


@pytest.fixture
def ws(tmp_path: Path) -> Path:
    w = tmp_path / "ws"
    w.mkdir()
    return w


def agent(ws, commands, middleware=(), step_limit=20, guard=False):
    run_dir = ws.parent
    env = os.environ | bench_env() | sandbox.sandbox_env(run_dir)
    client = FakeClient(commands)
    return TranscriptAgent(client, ws, run_dir, env, middleware=list(middleware), step_limit=step_limit,
                           guard_commands=guard), client


def tool_outputs(client):
    return [m["content"] for m in client.seen[-1] if m["role"] == "tool"]


def write(path, text):
    return f"cat <<'EOF' > {path}\n{text}EOF"


def test_runs_commands_and_submits(ws):
    a, client = agent(ws, ["echo hi > a.txt", SUBMIT, "echo never"])
    res = a.run("make a.txt")
    assert res.submitted and res.steps == 2
    assert (ws / "a.txt").read_text() == "hi\n"
    assert '"returncode": 0' in tool_outputs(client)[0]


def test_missing_tool_call_gets_format_error(ws):
    a, client = agent(ws, [], step_limit=2)
    res = a.run("x")
    assert not res.submitted and res.status == "LimitsExceeded"
    assert "no bash tool call" in client.seen[-1][-1]["content"]


def test_checks_report_static_problem_without_rewriting(ws):
    code = "def f( x ):\n    return undefined_name + x\n"
    a, client = agent(ws, [write("core.py", code), "true"], [mw.Checks()])
    a.run("x")
    out = tool_outputs(client)[0]
    assert "automatic checks on core.py" in out and "undefined_name" in out
    assert (ws / "core.py").read_text() == code  # check-only: never reformatted


def test_checks_report_newly_failing_tests(ws):
    good = "def add(a, b):\n    return a + b\n"
    test = "from core import add\n\n\ndef test_add():\n    assert add(1, 2) == 3\n"
    a, client = agent(ws, [write("core.py", good), write("test_core.py", test),
                           "sed -i '' 's/a + b/a - b/' core.py", "true"], [mw.Checks()])
    a.run("x")
    outs = tool_outputs(client)
    assert "Tests: all pass" in outs[1]
    assert "newly failing after this change: test_core.py::test_add" in outs[2]


def test_gate_refuses_while_tests_fail_then_gives_up(ws):
    test = "def test_x():\n    assert False\n"
    a, client = agent(ws, [write("test_x.py", test), SUBMIT, SUBMIT, SUBMIT], [mw.SubmitGate(limit=2)])
    res = a.run("x")
    assert res.submitted and res.steps == 4
    assert "Not submitted" in tool_outputs(client)[1]


def test_repeat_guard(ws):
    a, client = agent(ws, ["ls", "ls", "true"], [mw.RepeatGuard()])
    a.run("x")
    outs = tool_outputs(client)
    assert "[note]" not in outs[0] and "2 times" in outs[1]


def test_compaction_shortens_old_outputs(ws):
    a, client = agent(ws, ["python -c \"print('x' * 3000)\""] * 8 + ["true"], [mw.Compaction(threshold=0, keep=2)])
    a.run("x")
    outs = tool_outputs(client)
    assert "shortened by the harness" in outs[0] and "shortened" not in outs[-1]


TUI = "from textual.app import App\nfrom textual.widgets import Label\n\n\nclass A(App):\n    def compose(self):\n        yield Label('hi')\n\n\nA().run()\n"


def test_guard_stops_interactive_app_quickly(ws):
    a, client = agent(ws, [write("app.py", TUI), "echo before && python app.py", "true"], guard=True)
    t = time.time()
    a.run("x")
    out = tool_outputs(client)[1]
    assert time.time() - t < 20
    assert "interactive full-screen app" in out and "before" in out and "\\u001b[?1049h" not in out


def test_guard_background_process_does_not_block(ws):
    a, client = agent(ws, ["sleep 60 & echo started", "true"], guard=True)
    t = time.time()
    a.run("x")
    out = tool_outputs(client)[0]
    assert time.time() - t < 10
    assert "started" in out and "stopped processes this command left running" in out


def test_guard_plain_command_unchanged(ws):
    a, client = agent(ws, ["echo hi; exit 3", "true"], guard=True)
    a.run("x")
    out = json.loads(tool_outputs(client)[0])
    assert out == {"returncode": 3, "output": "hi\n"}


class KitClient(FakeClient):
    """FakeClient that also answers the kit's decide() calls."""

    def __init__(self, commands, names):
        super().__init__(commands)
        self.answers = {"kit.classify": {"kind": "tui"}, "kit.names": names, "kit.parts": {"parts": ["list_actions"]}}

    def decide(self, messages, schema, *, purpose, **kw):
        return Reply(text="", parsed=self.answers[purpose])


NOTES = {"module": "notes", "app_class": "NotesApp", "title": "Notes", "storage": "json", "data_arg": "data_path",
         "data_default": "notes.json", "empty_value": "[]", "sample_data": '[{"text": "a"}]'}


def test_kit_writes_shell_and_reports_start_changes(ws):
    break_css = "sed -i '' 's/height: 1fr;/height: 1fr; colour: red;/' notes.py"
    fix_css = "sed -i '' 's/ colour: red;//' notes.py"
    run_dir = ws.parent
    env = os.environ | bench_env() | sandbox.sandbox_env(run_dir)
    client = KitClient(["ls", break_css, fix_css, "true"], NOTES)
    task = "Make a notes app. Contract: notes.py defines NotesApp(data_path)."
    TranscriptAgent(client, ws, run_dir, env, middleware=[mw.Kit()], step_limit=5).run(task)
    first_user = client.seen[0][1]["content"]
    assert "I created `notes.py`" in first_user and "## Trying the app" in first_user
    assert "### Part `headless_test`" not in first_user
    config = json.loads((ws / ".lightness" / "kit" / "try_app.json").read_text())
    assert config["module"] == "notes" and (ws / ".lightness" / "kit" / "try_app.py").exists()
    assert "### Part `list_actions`" in first_user and "### Part `modal`" not in first_user
    assert (ws / ".lightness" / "kit" / "parts" / "modal.py").exists()
    outs = tool_outputs(client)
    assert "[automatic start check]" not in outs[0]  # fine from the start: nothing to say
    assert "crashes when starting with no data file" in outs[1]
    assert "notes.py starts cleanly" in outs[2]


def test_kit_smoke_catches_crash_on_existing_data(ws):
    load_bug = ("sed -i '' 's/        self.refresh_view()/        self.refresh_view()\\n"
                "        self.first = self.data[0][\"title\"] if self.data else None/' notes.py")
    run_dir = ws.parent
    env = os.environ | bench_env() | sandbox.sandbox_env(run_dir)
    client = KitClient([load_bug, "true"], NOTES)
    TranscriptAgent(client, ws, run_dir, env, middleware=[mw.Kit()], step_limit=3).run("notes app")
    out = tool_outputs(client)[0]
    assert "crashes when starting with an existing data file" in out and "KeyError" in out
    assert "no data file" not in out


def test_kit_skips_existing_code(ws):
    (ws / "app.py").write_text("print(1)\n")
    client = KitClient(["true"], NOTES)
    run_dir = ws.parent
    env = os.environ | bench_env() | sandbox.sandbox_env(run_dir)
    TranscriptAgent(client, ws, run_dir, env, middleware=[mw.Kit()], step_limit=2).run("change it")
    assert not (ws / "notes.py").exists() and "Starting point" not in client.seen[0][1]["content"]
