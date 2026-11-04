"""The hidden-test grader: one hanging test must not sink the others."""

from lightness.bench.run import verify
from lightness.bench.tasks import Task

TESTS = '''
import time

def test_one():
    assert True

def test_two():
    assert True

def test_hangs():
    while True:
        time.sleep(0.1)

def test_intent_three():
    assert True

def test_fails():
    assert False
'''


def test_a_hanging_test_fails_alone(tmp_path):
    task_dir = tmp_path / "task"
    (task_dir / "tests").mkdir(parents=True)
    (task_dir / "tests" / "test_x.py").write_text(TESTS)
    ws = tmp_path / "ws"
    ws.mkdir()
    task = Task("x", task_dir, "tui", "easy", agent_timeout_sec=60, verify_timeout_sec=60)
    v = verify(task, ws, tmp_path / "run", test_timeout=3)
    assert (v["tests_total"], v["tests_passed"]) == (5, 3)
    assert (v["intent_total"], v["intent_passed"]) == (1, 1)
    assert not v["pass"]
    assert "test_hangs TIMEOUT" in (tmp_path / "run" / "verify" / "pytest.log").read_text()
