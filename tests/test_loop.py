"""End-to-end loop plumbing with a scripted fake model (no server)."""

import json
from pathlib import Path

import jsonschema
import pytest

from lightness.loop.driver import Harness
from lightness.loop.state import RunState
from lightness.provider import Reply
from lightness.user import DefaultsUser

SPEC = {"goal": "greet people", "non_goals": [], "features": [{"name": "greet", "criteria": ["greet('Ann') == 'Hi Ann'"]}],
        "contract": ["python greet.py NAME prints Hi NAME"], "data_model": "none"}
PROBE = {"kind": "cli", "description": "greets", "setup_files": [], "args": ["greet.py", "Ann"], "expect_exit": 0,
         "expect_json": False}
PLAN = {"steps": [{"goal": "write greet", "files": ["greet.py"], "check": "imports", "kind": "code"},
                  {"goal": "test greet", "files": ["test_greet.py"], "check": "tests pass", "kind": "test"}]}
GREET = "import sys\n\n\ndef greet(name):\n    return f'Hi {name}'\n\n\nif __name__ == '__main__':\n    print(greet(sys.argv[1]))\n"
GREET_BUGGY = GREET.replace("Hi {name}", "Hello {name}")
TEST = "from greet import greet\n\n\ndef test_greet():\n    assert greet('Ann') == 'Hi Ann'\n"
WEAK_TEST = "from greet import greet\n\n\ndef test_greet():\n    result = greet('Ann')\n    assert result\n"


class ScriptedClient:
    def __init__(self, actions, code):
        self.actions, self.code, self.prompts = list(actions), dict(code), []

    def decide(self, messages, schema, *, purpose, **kw):
        if purpose == "workshop.classify":
            parsed = {"project_type": "cli"}
        elif purpose == "workshop.questions":
            parsed = {"questions": [{"question": "Greeting word?", "options": ["Hi", "Hello"], "default": "Hi",
                                     "impact": 3, "ambiguity": 2, "dimension": "naming"}]}
        elif purpose == "workshop.spec":
            parsed = SPEC
        elif purpose == "probes":
            parsed = {"probes": [PROBE]}
        elif purpose == "plan":
            parsed = PLAN
        elif purpose == "act":
            self.prompts.append(messages[-1]["content"])
            action, target = self.actions.pop(0)
            parsed = {"choice": {"action": action, "target": target, "why": "scripted"}}
        else:
            raise AssertionError(purpose)
        jsonschema.validate(parsed, schema)  # the menu must allow what the script does
        return Reply(json.dumps(parsed), parsed=parsed)

    def chat(self, messages, *, purpose, **kw):
        instruction = messages[-1]["content"].split("## Instruction")[1]
        target = max((k for k in self.code if k in instruction), key=len)
        return Reply(f"Here you go:\n```python\n{self.code[target].pop(0)}```\n")


@pytest.fixture
def ws(tmp_path: Path) -> Path:
    w = tmp_path / "ws"
    w.mkdir()
    (tmp_path / "pytest.ini").write_text("[pytest]\n")
    return w


def run(ws, actions, code):
    client = ScriptedClient(actions, code)
    h = Harness(client, ws, DefaultsUser(), run_dir=ws.parent, max_turns=len(actions) + 1,
                state_path=ws.parent / "state.json")
    st = h.setup("make a greeter")
    while client.actions and not st.finished:
        h.turn(st)
    if not st.finished:
        st.outcome = "script ended"
    return st, client


def test_happy_path_reaches_done(ws):
    st, _ = run(ws, [("write_file", "greet.py"), ("done_step", ""), ("write_file", "test_greet.py"),
                     ("done_step", ""), ("done", "")],
                {"greet.py": [GREET], "test_greet.py": [TEST]})
    assert st.outcome == "passed", [o.text for o in st.observations]
    assert all(s.status == "done" for s in st.plan)
    assert RunState.load(ws.parent / "state.json").outcome == "passed"


def test_bug_caught_by_tests_then_fixed_with_edit_symbol(ws):
    st, _ = run(ws, [("write_file", "greet.py"), ("done_step", ""), ("write_file", "test_greet.py"),
                     ("edit_symbol", "greet.py::greet"), ("done_step", ""), ("done", "")],
                {"greet.py": [GREET_BUGGY, "def greet(name):\n    return f'Hi {name}'\n"], "test_greet.py": [TEST]})
    failing = [o for o in st.observations if o.action == "write_file" and o.target == "test_greet.py"][0]
    assert not failing.ok and "Hello Ann" in failing.text
    assert st.outcome == "passed"
    assert "print(greet(sys.argv[1]))" in (ws / "greet.py").read_text()  # rest of file untouched


def test_weak_test_rejected_and_not_written(ws):
    st, _ = run(ws, [("write_file", "greet.py"), ("done_step", ""), ("write_file", "test_greet.py")],
                {"greet.py": [GREET], "test_greet.py": [WEAK_TEST]})
    obs = st.observations[-1]
    assert not obs.ok and "only checks that something exists" in obs.text
    assert not (ws / "test_greet.py").exists()


def test_done_blocked_by_failing_probe(ws):
    broken = GREET.replace("print(greet(sys.argv[1]))", "raise SystemExit(2)")
    st, _ = run(ws, [("write_file", "greet.py"), ("done_step", ""), ("write_file", "test_greet.py"),
                     ("done_step", "")],
                {"greet.py": [broken], "test_greet.py": [TEST]})
    last = st.observations[-1]
    assert "Contract probe failed" in last.text and st.outcome == "script ended"


def test_context_has_spec_plan_and_recent_results(ws):
    _, client = run(ws, [("write_file", "greet.py"), ("read", "greet.py"), ("done_step", "")],
                    {"greet.py": [GREET]})
    second = client.prompts[1]
    assert "greet people" in second and "write greet" in second and "write_file greet.py → ok" in second
    assert "Environment:" in second


def test_idle_streak_removes_look_only_actions(ws):
    client = ScriptedClient([("write_file", "greet.py"), ("read", "greet.py"), ("search", "Hi"),
                             ("search", "name")], {"greet.py": [GREET]})
    h = Harness(client, ws, DefaultsUser(), run_dir=ws.parent)
    st = h.setup("make a greeter")
    for _ in range(4):
        h.turn(st)
    menu = h.menu(st)
    assert st.idle == 3 and not {"read", "read_symbol", "search", "test", "probe", "run"} & set(menu)
    assert "edit_symbol" in menu and "write_file" in menu


def test_no_symbol_reads_for_files_shown_in_full(ws):
    client = ScriptedClient([("write_file", "greet.py")], {"greet.py": [GREET]})
    h = Harness(client, ws, DefaultsUser(), run_dir=ws.parent)
    st = h.setup("make a greeter")
    h.turn(st)
    assert "greet.py" in st.current.files and "read_symbol" not in h.menu(st)


def test_step_turn_budget_forces_revision(ws):
    client = ScriptedClient([], {})
    h = Harness(client, ws, DefaultsUser(), run_dir=ws.parent)
    st = h.setup("make a greeter")
    st.current.turns = 16
    assert set(h.menu(st)) <= {"revise_plan", "ask_user"}


def test_edit_that_breaks_passing_tests_is_reverted(ws):
    st, _ = run(ws, [("write_file", "greet.py"), ("done_step", ""), ("write_file", "test_greet.py"),
                     ("edit_symbol", "greet.py::greet")],
                {"greet.py": [GREET, "def greet(name):\n    return 'nope'\n"], "test_greet.py": [TEST]})
    last = st.observations[-1]
    assert not last.ok and "edit reverted" in last.text and "test_greet" in last.text
    assert "Hi {name}" in (ws / "greet.py").read_text()
    assert str(ws) not in last.text  # paths shortened


def test_edit_failing_static_checks_is_not_applied(ws):
    st, _ = run(ws, [("write_file", "greet.py"), ("edit_symbol", "greet.py::greet")],
                {"greet.py": [GREET, "def greet(name):\n    return undefined_helper(name)\n"]})
    last = st.observations[-1]
    assert not last.ok and "edit not applied" in last.text and "F821" in last.text
    assert "Hi {name}" in (ws / "greet.py").read_text()


def test_edit_keeping_earlier_problems_is_applied(ws):
    broken = GREET + "\n\ndef shout(name):\n    return missing_helper(name)\n"
    st, _ = run(ws, [("write_file", "greet.py"), ("edit_symbol", "greet.py::greet")],
                {"greet.py": [broken, "def greet(name):\n    return f'Hey {name}'\n"]})
    last = st.observations[-1]
    assert "Hey {name}" in (ws / "greet.py").read_text()
    assert "problems from before" in last.text and "(in `shout`)" in last.text
    assert "greet.py::greet" in st.working


def test_reproduce_step_must_fail(ws):
    client = ScriptedClient([("write_file", "greet.py"), ("done_step", ""), ("write_file", "test_greet.py"),
                             ("done_step", "")], {"greet.py": [GREET], "test_greet.py": [TEST]})
    h = Harness(client, ws, DefaultsUser(), run_dir=ws.parent)
    st = h.setup("greeting is wrong")
    st.plan[1].kind = "reproduce"
    while client.actions:
        h.turn(st)
    last = st.observations[-1]
    assert not last.ok and "does not reproduce" in last.text and st.plan[1].status == "todo"
