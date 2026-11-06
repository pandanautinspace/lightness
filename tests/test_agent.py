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
    message = client.seen[-1][-1]["content"]
    assert "no bash tool call" in message and SUBMIT not in message and '{"command": "ls"}' in message


def test_format_error_shows_the_try_command_when_the_kit_gave_one(ws):
    from lightness.agent.loop import format_error

    (ws / ".lightness" / "kit").mkdir(parents=True)
    (ws / ".lightness" / "kit" / "try_app.py").write_text("")
    message = format_error(ws)
    assert '{"command": "python .lightness/kit/try_app.py"}' in message and SUBMIT not in message


def test_empty_replies_are_retried_and_never_stored_empty(ws):
    a, client = agent(ws, [], step_limit=1)
    a.run("x")
    assert len(client.seen) == 5  # asked five times in the one step
    assert client.seen[-1][-1]["role"] != "assistant"
    a, client = agent(ws, [], step_limit=2)
    a.run("x")
    stored = [m for m in client.seen[-1] if m["role"] == "assistant"]
    assert stored and all(m["content"] == "(empty response)" for m in stored)


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
    assert "run_test()" in out and "try_app.py" not in out


def test_guard_points_to_try_app_when_the_kit_gave_one(ws):
    (ws / ".lightness" / "kit").mkdir(parents=True)
    (ws / ".lightness" / "kit" / "try_app.py").write_text("")
    a, client = agent(ws, [write("app.py", TUI), "python app.py", "true"], guard=True)
    a.run("x")
    assert "python .lightness/kit/try_app.py" in tool_outputs(client)[1]


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


NOTES = {"module": "notes", "app_class": "NotesApp", "title": "Notes",
         "params": [{"name": "data_path", "role": "data", "file": "notes.json"}],
         "empty_value": "[]", "sample_data": '[{"text": "a"}]'}


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


def test_kit_refuses_to_submit_an_app_that_crashes_on_start(ws):
    break_mount = "sed -i '' 's/        self.refresh_view()/        self.refresh_view()\\n        1 \\/ 0/' notes.py"
    fix_mount = "sed -i '' '/1 \\/ 0/d' notes.py"
    run_dir = ws.parent
    env = os.environ | bench_env() | sandbox.sandbox_env(run_dir)
    client = KitClient([break_mount, SUBMIT, fix_mount, SUBMIT, "echo never"], NOTES)
    res = TranscriptAgent(client, ws, run_dir, env, middleware=[mw.Kit()], step_limit=10).run("notes app")
    assert res.submitted and res.steps == 4
    refused = [m["content"] for m in client.seen[-1] if m["role"] == "tool"][1]
    assert refused.startswith("Not submitted: the app crashes on start.") and "ZeroDivisionError" in refused


def test_kit_lets_a_working_app_submit(ws):
    run_dir = ws.parent
    env = os.environ | bench_env() | sandbox.sandbox_env(run_dir)
    client = KitClient([SUBMIT], NOTES)
    res = TranscriptAgent(client, ws, run_dir, env, middleware=[mw.Kit()], step_limit=3).run("notes app")
    assert res.submitted and res.steps == 1


def test_smoke_passes_every_file_parameter(ws):
    from lightness.kits import smoke

    sandbox.sandbox_env(ws.parent)  # makes the run dir's tmp/
    (ws / "places.csv").write_text("ams\n")
    (ws / "both.py").write_text(
        "from pathlib import Path\nfrom textual.app import App\n\n\nclass Both(App):\n"
        "    def __init__(self, places_path, saved_path):\n        super().__init__()\n"
        "        assert Path(places_path).read_text() == 'ams\\n'\n"
        "        assert not Path(saved_path).exists() or Path(saved_path).read_text() == '[1]'\n")
    names = {"module": "both", "app_class": "Both", "sample_data": "",
             "params": [{"name": "places_path", "role": "input", "file": "places.csv"},
                        {"name": "saved_path", "role": "data", "file": "saved.json"}]}
    results = smoke.tui(ws, names, ws.parent)
    assert [(r.ok, r.case) for r in results] == [(True, "starting with no data file")]
    names = {**names, "params": names["params"][::-1], "sample_data": "[1]"}  # data first: gets the sample
    results = smoke.tui(ws, names, ws.parent)
    assert [r.case for r in results if r.ok] == ["starting with no data file",
                                                 "starting with an existing data file (saved_path)"]


def test_kit_skips_existing_code(ws):
    (ws / "app.py").write_text("print(1)\n")
    client = KitClient(["true"], NOTES)
    run_dir = ws.parent
    env = os.environ | bench_env() | sandbox.sandbox_env(run_dir)
    TranscriptAgent(client, ws, run_dir, env, middleware=[mw.Kit()], step_limit=2).run("change it")
    assert not (ws / "notes.py").exists() and "Starting point" not in client.seen[0][1]["content"]


def test_text_tool_call_recovery():
    from lightness.agent.loop import text_tool_call

    assert text_tool_call('Run it:\n```bash\n{"command": "ls -la"}\n```') == "ls -la"
    assert text_tool_call('{"name": "bash", "parameters": {"command": "python a.py"}}') == "python a.py"
    assert text_tool_call("Let me look.\n```bash\ncat a.py\n```\n") == "cat a.py"
    assert text_tool_call("Plan: first ```bash\nls\n``` then ```bash\npwd\n```") is None  # two: unclear
    assert text_tool_call('{"state": {"a": 1}}') is None
    assert text_tool_call("No command here.") is None


@pytest.mark.parametrize("tests", ["none", "first", "after", "checks"])
def test_kit_testing_arms(ws, tests):
    run_dir = ws.parent
    env = os.environ | bench_env() | sandbox.sandbox_env(run_dir)
    client = KitClient([SUBMIT, SUBMIT, "echo never"], NOTES)
    res = TranscriptAgent(client, ws, run_dir, env, middleware=[mw.Kit(tests)], step_limit=5).run("notes app")
    first_user = client.seen[0][1]["content"]
    assert "{testing}" not in first_user
    assert ("Before writing the app, write tests" in first_user) == (tests == "first")
    assert ("Write test files only if the task asks" in first_user) == (tests in ("none", "after"))
    assert ("### Part `headless_test`" in first_user) == (tests == "first")
    assert ("## Checks" in first_user and "expect-file:data_path=" in first_user) == (tests == "checks")
    # the checks arm puts Checks before the try command and doesn't ask for trying by hand
    assert ("run the steps a user would" in first_user) == (tests != "checks")
    assert ("Try what the task describes" in first_user) == (tests != "checks")
    if tests == "checks":
        assert first_user.index("## Checks") < first_user.index("## Trying the app")
    if tests == "after":  # the first submit asks for tests and shows the guide; the second goes through
        assert res.submitted and res.steps == 2
        reply = tool_outputs(client)[0]
        assert reply.startswith(mw.TESTS_AFTER) and "### Part `headless_test`" in reply
    else:
        assert res.submitted and res.steps == 1


def test_kit_checks_arm_reports_regressions_and_refuses_one_submit(ws):
    checks = write("checks.txt", "count: --file-text data_path='[{\"text\": \"a\"}]' expect:\"1 notes\"\n"
                                 "empty: expect-not:\"notes\"\n")
    show_count = """sed -i '' 's/update("")/update(f"{len(self.data)} notes" if self.data else "")/' notes.py"""
    off_by_one = """sed -i '' 's/len(self.data)} notes" if self.data else ""/len(self.data) + 1} notes"/' notes.py"""
    run_dir = ws.parent
    env = os.environ | bench_env() | sandbox.sandbox_env(run_dir)
    client = KitClient([checks, show_count, off_by_one, SUBMIT, SUBMIT, "echo never"], NOTES)
    res = TranscriptAgent(client, ws, run_dir, env, middleware=[mw.Kit("checks")], step_limit=8).run("notes app")
    outs = tool_outputs(client)
    assert "[automatic checks] 1 of 2 checks pass.\nFAIL count\n" in outs[0] and "FAILED expect:1 notes" in outs[0]
    assert "[automatic checks] 2 of 2 checks pass.\n" + mw.CHECKS_ALL_PASS in outs[1]
    assert mw.CHECKS_ALL_PASS not in outs[0]
    assert "FAIL count (passed before this change)" in outs[2] and "FAIL empty (passed before this change)" in outs[2]
    assert outs[3].startswith(mw.CHECKS_REFUSED) and "0 of 2 checks pass" in outs[3]
    assert res.submitted and res.steps == 5  # refused once only
    events = [json.loads(line) for line in (run_dir / "events.jsonl").read_text().splitlines()]
    assert [e["regressions"] for e in events if e.get("event") == "kit.checks"] == [[], [], ["count", "empty"]]


def test_bench_labels_the_testing_arm():
    from lightness.bench.agents import MiddlewareAgent

    assert MiddlewareAgent("haiku", ["env", "guard", "kit"], tests="after").name == "mw-env.guard.kit-tests.after"
    assert MiddlewareAgent("haiku", ["env"]).name == "mw-env"
    assert MiddlewareAgent("haiku", ["kit"]).step_limit == 150
    with pytest.raises(ValueError):
        MiddlewareAgent("haiku", ["env"], tests="first")


def test_submit_accepts_a_cd_prefix_and_explains_near_misses(ws):
    from lightness.agent.loop import SUBMIT_HINT, is_submit

    assert is_submit(SUBMIT) and is_submit("cd . && " + SUBMIT) and is_submit("cd /x && cd y && " + SUBMIT)
    assert is_submit('echo "COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"')
    assert not is_submit("python app.py && " + SUBMIT) and not is_submit(SUBMIT + " now")
    a, client = agent(ws, [SUBMIT + " now", "cd . && " + SUBMIT, "echo never"])
    res = a.run("submit")
    assert res.submitted and res.steps == 2
    assert tool_outputs(client)[0].endswith(SUBMIT_HINT)


def test_kit_checks_arm_asks_for_checks_when_the_app_changes_without_them(ws):
    show_count = """sed -i '' 's/update("")/update("x")/' notes.py"""
    run_dir = ws.parent
    env = os.environ | bench_env() | sandbox.sandbox_env(run_dir)
    client = KitClient([show_count, SUBMIT, "echo never"], NOTES)
    client.answers["kit.classify"] = {"kind": "cli"}  # a task naming Textual is a tui whatever the model says
    TranscriptAgent(client, ws, run_dir, env, middleware=[mw.Kit("checks")], step_limit=4).run("a Textual notes app")
    outs = tool_outputs(client)
    assert mw.CHECKS_MISSING in outs[0]


def test_kit_checks_arm_reports_after_a_checks_rewrite_with_the_same_results(ws):
    checks = write("checks.txt", "empty: expect-not:\"notes\"\n")
    same = write("checks.txt", "# the start\nempty: expect-not:\"notes\"\n")  # same results
    run_dir = ws.parent
    env = os.environ | bench_env() | sandbox.sandbox_env(run_dir)
    client = KitClient([checks, same, SUBMIT, "echo never"], NOTES)
    TranscriptAgent(client, ws, run_dir, env, middleware=[mw.Kit("checks")], step_limit=5).run("notes app")
    outs = tool_outputs(client)
    assert "[automatic checks] 1 of 1 checks pass." in outs[0]
    assert "[automatic checks] 1 of 1 checks pass." in outs[1]  # rewritten, same results: still reported
