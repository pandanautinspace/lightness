def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "ok"


def test_create_and_get_note(client, make_note):
    note = make_note("Groceries", "milk, eggs", ["home", "Shopping"])
    assert note["id"] > 0
    assert note["tags"] == ["home", "shopping"]

    resp = client.get(f"/api/notes/{note['id']}")
    assert resp.status_code == 200
    got = resp.get_json()
    assert got["title"] == "Groceries"
    assert got["body"] == "milk, eggs"
    assert got["created_at"] == got["updated_at"]


def test_create_requires_title(client):
    assert client.post("/api/notes", json={"body": "no title"}).status_code == 400
    assert client.post("/api/notes", json={"title": "   "}).status_code == 400
    assert client.post("/api/notes", data="not json").status_code == 400


def test_get_missing_note_is_404(client):
    resp = client.get("/api/notes/999")
    assert resp.status_code == 404
    assert "error" in resp.get_json()


def test_update_note(client, make_note):
    note = make_note("Draft", "v1", ["work"])
    resp = client.patch(f"/api/notes/{note['id']}", json={"body": "v2", "tags": ["work", "done"]})
    assert resp.status_code == 200
    updated = resp.get_json()
    assert updated["title"] == "Draft"
    assert updated["body"] == "v2"
    assert updated["tags"] == ["done", "work"]


def test_update_rejects_empty_title(client, make_note):
    note = make_note("Keep me")
    assert client.put(f"/api/notes/{note['id']}", json={"title": ""}).status_code == 400
    assert client.get(f"/api/notes/{note['id']}").get_json()["title"] == "Keep me"


def test_delete_note(client, make_note):
    note = make_note("Temporary")
    assert client.delete(f"/api/notes/{note['id']}").status_code == 204
    assert client.get(f"/api/notes/{note['id']}").status_code == 404
    assert client.delete(f"/api/notes/{note['id']}").status_code == 404


def test_tags_with_counts(client, make_note):
    make_note("a", tags=["work"])
    make_note("b", tags=["work", "ideas"])
    make_note("c", tags=["ideas", "home"])
    make_note("d", tags=["work"])
    tags = client.get("/api/tags").get_json()
    assert tags[0] == {"name": "work", "count": 3}
    assert {"name": "ideas", "count": 2} in tags
    assert {"name": "home", "count": 1} in tags


def test_search(client, make_note):
    make_note("Python tips", "use enumerate")
    make_note("Shopping", "buy a python book")
    make_note("Garden", "water the plants")
    data = client.get("/api/search?q=python").get_json()
    assert data["total"] == 2
    assert {n["title"] for n in data["items"]} == {"Python tips", "Shopping"}
    assert client.get("/api/search").status_code == 400
