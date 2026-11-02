import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from notesapp import create_app  # noqa: E402


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "notes.db"


@pytest.fixture
def app(db_path):
    app = create_app(str(db_path))
    app.config["TESTING"] = True
    return app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def make_note(client):
    def _make(title="note", body="", tags=None):
        resp = client.post("/api/notes", json={"title": title, "body": body, "tags": tags or []})
        assert resp.status_code == 201, resp.get_json()
        return resp.get_json()

    return _make
