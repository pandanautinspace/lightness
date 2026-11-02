def test_list_is_newest_first(client, make_note):
    for i in range(3):
        make_note(f"note {i}")
    data = client.get("/api/notes").get_json()
    assert data["total"] == 3
    assert data["page"] == 1
    assert [n["title"] for n in data["items"]] == ["note 2", "note 1", "note 0"]


def test_list_empty(client):
    data = client.get("/api/notes").get_json()
    assert data["items"] == []
    assert data["total"] == 0
    assert data["pages"] == 1


def test_pagination(client, make_note):
    for i in range(20):
        make_note(f"note {i}")
    first = client.get("/api/notes?page=1&per_page=10").get_json()
    second = client.get("/api/notes?page=2&per_page=10").get_json()
    assert first["pages"] == 2
    assert first["has_next"] is True
    assert second["has_next"] is False
    assert len(first["items"]) == len(second["items"]) == 10
    ids = [n["id"] for n in first["items"] + second["items"]]
    assert len(set(ids)) == 20


def test_per_page_is_capped(client, make_note):
    for i in range(3):
        make_note(f"note {i}")
    data = client.get("/api/notes?per_page=1000").get_json()
    assert data["per_page"] == 100
    assert len(data["items"]) == 3


def test_bad_paging_params(client):
    assert client.get("/api/notes?page=abc").status_code == 400
    assert client.get("/api/notes?page=0").status_code == 400
    assert client.get("/api/notes?per_page=-5").status_code == 400


def test_filter_by_tag(client, make_note):
    make_note("work 1", tags=["work"])
    make_note("home 1", tags=["home"])
    make_note("work 2", tags=["Work", "urgent"])
    data = client.get("/api/notes?tag=WORK").get_json()
    assert data["total"] == 2
    assert {n["title"] for n in data["items"]} == {"work 1", "work 2"}
