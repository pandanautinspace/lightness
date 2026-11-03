from pathlib import Path

import pytest

from lightness.verify.chain import related_tests, verify


@pytest.fixture
def ws(tmp_path: Path) -> Path:
    w = tmp_path / "ws"
    w.mkdir()
    (w / "pytest.ini").write_text("[pytest]\n")
    return w


def write(ws: Path, name: str, text: str) -> Path:
    p = ws / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return p


def test_clean_code_passes_and_gets_formatted(ws):
    f = write(ws, "core.py", "def add(a,b):\n  return a+b\n")
    r = verify(ws, [f])
    assert r.ok, r.observation()
    assert f.read_text() == "def add(a, b):\n    return a + b\n"


def test_syntax_error_reported_with_caret(ws):
    f = write(ws, "core.py", "def add(a, b)\n    return a + b\n")
    r = verify(ws, [f])
    assert r.failed.stage == "parse" and "core.py:1" in r.observation() and "^" in r.observation()


def test_undefined_name_fails_ruff(ws):
    f = write(ws, "core.py", "def f():\n    return undefined_thing + 1\n")
    r = verify(ws, [f])
    assert r.failed.stage == "ruff" and "F821" in r.observation()


def test_unused_import_is_kept_not_failed(ws):
    f = write(ws, "core.py", "import os\n\n\ndef f():\n    return 1\n")
    assert verify(ws, [f]).ok
    assert "import os" in f.read_text()


def test_missing_module_attribute_fails_types(ws):
    write(ws, "core.py", "def parse(s):\n    return float(s)\n")
    f = write(ws, "cli.py", "import core\n\n\ndef main():\n    return core.parse_amount('1')\n")
    r = verify(ws, [f])
    assert r.failed.stage == "types" and "parse_amount" in r.observation()


def test_missing_import_fails_types(ws):
    f = write(ws, "core.py", "import yamlish_not_installed\n\nX = yamlish_not_installed.load\n")
    r = verify(ws, [f])
    assert r.failed.stage == "types" and "yamlish_not_installed" in r.observation()


def test_related_failing_test_is_compressed(ws):
    f = write(ws, "dates.py", "def parse(s):\n    return s\n")
    write(ws, "test_dates.py", "from dates import parse\n\n\ndef test_iso():\n    assert parse('30-Mar-2024') == '2024-03-30'\n")
    write(ws, "test_other.py", "def test_unrelated():\n    assert False\n")
    r = verify(ws, [f])
    assert r.failed.stage == "tests"
    obs = r.observation()
    assert "FAILED test_iso" in obs and "test_unrelated" not in obs


def test_related_tests_selection(ws):
    a = write(ws, "pkg/store.py", "X = 1\n")
    write(ws, "tests/test_store.py", "from pkg.store import X\n")
    write(ws, "tests/test_misc.py", "import json\n")
    assert [t.name for t in related_tests([a], ws)] == ["test_store.py"]


def test_no_tests_is_ok_with_note(ws):
    f = write(ws, "core.py", "X = 1\n")
    r = verify(ws, [f])
    assert r.ok and "no related tests" in r.observation()


def test_runs_inside_sandbox(ws):
    run_dir = ws.parent
    f = write(ws, "dates.py", "def parse(s):\n    return s\n")
    write(ws, "test_dates.py", "from dates import parse\n\n\ndef test_ok():\n    assert parse('x') == 'x'\n")
    r = verify(ws, [f], run_dir=run_dir)
    assert r.ok, r.observation()


def test_package_tests_count_as_related(ws):
    a = write(ws, "pkg/store.py", "X = 1\n")
    write(ws, "pkg/__init__.py", "")
    write(ws, "tests/test_app.py", "from pkg import store\n")
    assert [t.name for t in related_tests([a], ws)] == ["test_app.py"]


def test_suite_runs_when_nothing_is_related(ws):
    f = write(ws, "core.py", "X = 1\n")
    write(ws, "test_other.py", "def test_unrelated():\n    assert False\n")
    r = verify(ws, [f])
    assert r.failed is not None and r.failed.stage == "tests"
