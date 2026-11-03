import json
import textwrap
from pathlib import Path

import jsonschema
import pytest

from lightness.verify.probes import PROBE_SCHEMA, run_probes, summarize


@pytest.fixture
def ws(tmp_path: Path) -> Path:
    w = tmp_path / "ws"
    w.mkdir()
    (tmp_path / "pytest.ini").write_text("[pytest]\n")
    return w


def write(ws: Path, name: str, code: str) -> None:
    (ws / name).write_text(textwrap.dedent(code))


def one(probes, ws, sandboxed=True):
    jsonschema.validate({"probes": probes}, PROBE_SCHEMA)
    return run_probes(probes, ws, ws.parent if sandboxed else None)


CLI = {"kind": "cli", "description": "plan as json", "setup_files": [{"path": "in/a.txt", "content": "x"}],
       "args": ["tool.py", "{tmp}/in", "--json"], "expect_exit": 0, "expect_json": True}


def test_cli_ok_and_bad_json(ws):
    write(ws, "tool.py", """
        import json, sys, os
        print(json.dumps(sorted(os.listdir(sys.argv[1]))))
    """)
    assert one([CLI], ws)[0].ok
    write(ws, "tool.py", "import sys\nprint('a.txt -> Docs/a.txt')\n")
    r = one([CLI], ws)[0]
    assert not r.ok and "not valid JSON" in r.detail


def test_cli_wrong_exit_shows_stderr(ws):
    write(ws, "tool.py", "raise SystemExit('boom: bad folder')\n")
    r = one([CLI], ws)[0]
    assert not r.ok and "exit code 1" in r.detail and "boom" in r.detail


FLASK_APP = """
    import sys
    from flask import Flask
    app = Flask(__name__)

    @app.get("/")
    def index():
        return '<form><input name="amount"></form><ul {attr}></ul>'

    @app.post("/api/expenses")
    def add():
        return {{"id": 1}}, 201

    if __name__ == "__main__":
        app.run(port=int(sys.argv[sys.argv.index("--port") + 1]))
"""

HTTP = {"kind": "http", "description": "app serves index and API", "start": ["app.py", "--port", "{port}"],
        "requests": [
            {"method": "GET", "path": "/", "form_json": "", "body_json": "", "expect_status": 200,
             "expect_html_ids": ["expense-list", "amount"]},
            {"method": "POST", "path": "/api/expenses", "form_json": "", "body_json": '{"amount": 5}',
             "expect_status": 201, "expect_html_ids": []}]}


def test_http_ok(ws):
    write(ws, "app.py", FLASK_APP.format(attr='data-testid="expense-list"'))
    r = one([HTTP], ws)[0]
    assert r.ok, r.detail


def test_http_missing_element_id(ws):
    write(ws, "app.py", FLASK_APP.format(attr='class="list"'))
    r = one([HTTP], ws)[0]
    assert not r.ok and "expense-list" in r.detail


def test_http_server_crash_reported(ws):
    write(ws, "app.py", "import nonexistent_module_xyz\n")
    r = one([HTTP], ws)[0]
    assert not r.ok and "exited" in r.detail and "nonexistent_module_xyz" in r.detail


FUNC = {"kind": "function", "description": "top_products returns (sku, name) pairs",
        "setup_files": [{"path": "orders.json", "content": '[{"sku": "A", "name": "Apple", "qty": 3}]'}],
        "before": [["ingest.py", "{tmp}/orders.json", "{tmp}/db.json"]],
        "module": "queries", "name": "top_products", "args_json": '["{tmp}/db.json", 5]',
        "expect_type": "list", "item_len": 2}


def test_function_shape(ws):
    write(ws, "ingest.py", "import shutil, sys\nshutil.copy(sys.argv[1], sys.argv[2])\n")
    write(ws, "queries.py", """
        import json
        def top_products(db, n):
            rows = json.load(open(db))
            return [(r["sku"], r["name"], r["qty"]) for r in rows][:n]
    """)
    r = one([FUNC], ws)[0]
    assert not r.ok and "3 fields, expected 2" in r.detail
    write(ws, "queries.py", """
        import json
        def top_products(db, n):
            return [(r["sku"], r["name"]) for r in json.load(open(db))][:n]
    """)
    assert one([FUNC], ws)[0].ok


def test_function_missing_or_raising(ws):
    write(ws, "ingest.py", "import shutil, sys\nshutil.copy(sys.argv[1], sys.argv[2])\n")
    write(ws, "queries.py", "def other():\n    pass\n")
    assert "does not exist" in one([FUNC], ws)[0].detail
    write(ws, "queries.py", "def top_products(db, n):\n    raise KeyError('qty')\n")
    assert "KeyError" in one([FUNC], ws)[0].detail


TUI = {"kind": "tui", "description": "todo app mounts with its widgets", "module": "todo", "app_class": "TodoApp",
       "init_args_json": '["{tmp}/todos.json"]', "widget_ids": ["new-todo", "todo-list"]}

TUI_APP = """
    from textual.app import App
    from textual.widgets import Input, ListView

    class TodoApp(App):
        def __init__(self, path):
            super().__init__()
            self.path = path

        def compose(self):
            yield Input(id="new-todo")
            yield ListView(id="todo-list")

        def on_mount(self):
            {focus}
"""


def test_tui_mounts(ws):
    write(ws, "todo.py", TUI_APP.format(focus='self.set_focus(self.query_one("#new-todo"))'))
    r = one([TUI], ws)[0]
    assert r.ok, r.detail


def test_tui_crash_on_mount_is_caught(ws):
    # The M0 textual-todo failure: set_focus given a string instead of a widget.
    write(ws, "todo.py", TUI_APP.format(focus='self.set_focus("new-todo")'))
    r = one([TUI], ws)[0]
    assert not r.ok and "focusable" in r.detail


def test_summary_and_malformed_probe(ws):
    results = run_probes([{"kind": "cli", "description": "broken"}], ws)
    assert not results[0].ok and "probe error" in results[0].detail
    assert "Contract probe failed" in summarize(results)
    assert summarize([]) == "All 0 contract probes passed."
