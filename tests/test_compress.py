from pathlib import Path

from lightness.verify.compress import diagnostics_summary, pytest_summary, traceback_summary

WS = Path("/work/ws")

TRACEBACK = """Traceback (most recent call last):
  File "/work/ws/clean.py", line 88, in <module>
    main()
  File "/work/ws/clean.py", line 71, in main
    rows = [parse_row(r) for r in reader]
  File "/usr/lib/python3.12/csv.py", line 116, in __next__
    row = next(self.reader)
  File "/work/ws/clean.py", line 40, in parse_date
    raise ValueError(f"unknown date format: {s!r}")
ValueError: unknown date format: '30-Mar-2024'
"""

PYTEST = """F.F                                                                      [100%]
=================================== FAILURES ===================================
______________________ test_dates_parsed_from_every_format _____________________

    def test_dates_parsed_from_every_format(tmp_path):
        rows = clean(tmp_path)
>       assert rows["Gym membership"] == "2024-03-30"
E       KeyError: 'Gym membership'

/work/ws/tests/test_clean.py:42: KeyError
_____________________________ test_summary_totals ______________________________

    def test_summary_totals():
>       assert 1 == 2
E       assert 1 == 2

/work/ws/tests/test_clean.py:60: AssertionError
=========================== short test summary info ============================
FAILED tests/test_clean.py::test_dates_parsed_from_every_format - KeyError: 'Gym membership'
FAILED tests/test_clean.py::test_summary_totals - assert 1 == 2
2 failed, 1 passed in 0.31s
"""


def test_traceback_keeps_only_workspace_frames_and_error():
    s = traceback_summary(TRACEBACK, WS)
    assert "clean.py:40 in parse_date" in s and "clean.py:88 in <module>: main()" in s
    assert "csv.py" not in s
    assert s.splitlines()[-1] == "ValueError: unknown date format: '30-Mar-2024'"


def test_pytest_first_failure_only():
    s = pytest_summary(PYTEST, WS)
    assert s.splitlines()[0] == "FAILED test_dates_parsed_from_every_format (+1 more failing)"
    assert "E       KeyError: 'Gym membership'" in s
    assert "at tests/test_clean.py:42 (KeyError)" in s
    assert "test_summary_totals" not in s


def test_pytest_collection_error():
    out = "ERROR tests/test_x.py - ModuleNotFoundError: No module named 'clean'\n1 error in 0.1s\n"
    assert "ModuleNotFoundError" in pytest_summary(out, WS)


def test_diagnostics_dedup_and_cap():
    d = [f"a.py:{i}: undefined name 'x'" for i in range(12)] + ["a.py:0: undefined name 'x'"]
    s = diagnostics_summary(d, limit=5)
    assert s.count("undefined") == 5 and "and 7 more" in s


def test_traceback_summary_keeps_a_syntax_errors_line_and_caret():
    from pathlib import Path
    from lightness.verify.compress import traceback_summary

    text = ('Traceback (most recent call last):\n  File "<string>", line 5, in <module>\n'
            '  File "<frozen importlib._bootstrap>", line 488, in _call_with_frames_removed\n'
            '  File "/w/lookup.py", line 2\n    x = (1,\n        ^\nSyntaxError: \'(\' was never closed')
    assert traceback_summary(text, Path("/w")) == "lookup.py:2:\n    x = (1,\n        ^\nSyntaxError: '(' was never closed"
