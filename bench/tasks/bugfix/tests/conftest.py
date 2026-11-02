"""Hidden-test fixtures: same names as the seed repo's conftest, but the app comes from the
workspace under test (BENCH_WORKSPACE), so the seed's regression tests run unmodified."""

import sys

import pytest

from lightness.bench.testkit import workspace

sys.path.insert(0, str(workspace()))

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
