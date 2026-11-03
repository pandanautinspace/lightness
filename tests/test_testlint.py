from lightness.verify.testlint import lint_tests

MODS = {"todo", "app"}


def test_good_test_passes():
    src = "from app import parse\n\ndef test_parse():\n    assert parse('1,5') == 1.5\n"
    assert lint_tests(src, MODS) == []


def test_mocking_code_under_test_rejected():
    # The M0 textual-todo pattern: patch the app's own method so the UI never really runs.
    src = (
        "from unittest.mock import patch\nfrom todo import TodoApp\n\n"
        "def test_add():\n    with patch.object(TodoApp, 'refresh_todos'):\n        assert TodoApp('x').items == []\n"
    )
    assert any("mocks the code under test" in p for p in lint_tests(src, MODS))
    src2 = "import app\n\ndef test_x(monkeypatch):\n    monkeypatch.setattr(app, 'load', lambda: [])\n    assert app.total() == 0\n"
    assert any("mocks" in p for p in lint_tests(src2, MODS))
    src3 = "from unittest.mock import patch\n\ndef test_x():\n    with patch('app.db.connect'):\n        assert 1 == 1\n"
    assert any("mocks" in p for p in lint_tests(src3, MODS))


def test_mocking_external_things_is_fine():
    src = "import time\nimport app\n\ndef test_x(monkeypatch):\n    monkeypatch.setattr(time, 'time', lambda: 0)\n    assert app.stamp() == 0\n"
    assert lint_tests(src, MODS) == []


def test_presence_only_rejected():
    # The M0 expense-tracker pattern: check the list element exists, not what's in it.
    src = "def test_page(client):\n    html = client.get('/').text\n    assert html\n    assert len(html) > 0\n"
    assert any("only checks that something exists" in p for p in lint_tests(src, MODS))


def test_no_assert_rejected_but_raises_ok():
    assert any("no assert" in p for p in lint_tests("def test_x():\n    run()\n", MODS))
    src = "import pytest\n\ndef test_bad():\n    with pytest.raises(ValueError):\n        parse('x')\n"
    assert lint_tests(src, MODS) == []


def test_no_tests_and_syntax_error():
    assert lint_tests("x = 1\n", MODS) == ["no test functions found (names must start with test_)"]
    assert "does not parse" in lint_tests("def test_(:\n", MODS)[0]
