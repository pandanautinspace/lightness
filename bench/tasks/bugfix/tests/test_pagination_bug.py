"""Fail-to-pass: paging through a list whose size is not a multiple of per_page."""

import pytest


def walk(client, url):
    """Follow pages 1..pages and return every item id seen, in order."""
    first = client.get(f"{url}&page=1").get_json()
    ids = [n["id"] for n in first["items"]]
    for page in range(2, first["pages"] + 1):
        data = client.get(f"{url}&page={page}").get_json()
        ids += [n["id"] for n in data["items"]]
    return first, ids


@pytest.mark.parametrize("count,per_page", [(25, 10), (7, 3), (21, 20)])
def test_paging_sees_every_note_exactly_once(client, make_note, count, per_page):
    created = [make_note(f"note {i}")["id"] for i in range(count)]
    first, ids = walk(client, f"/api/notes?per_page={per_page}")
    assert first["total"] == count
    assert first["pages"] == -(-count // per_page)
    assert len(ids) == len(set(ids)), "a note shows up on two pages"
    assert sorted(ids) == sorted(created), "some notes never show up"


def test_last_partial_page(client, make_note):
    created = [make_note(f"note {i}")["id"] for i in range(25)]
    last = client.get("/api/notes?per_page=10&page=3").get_json()
    assert last["page"] == 3
    assert last["has_next"] is False
    assert sorted(n["id"] for n in last["items"]) == sorted(created[:5])  # oldest five
    second = client.get("/api/notes?per_page=10&page=2").get_json()
    assert second["has_next"] is True


def test_paging_filtered_by_tag(client, make_note):
    tagged = [make_note(f"t{i}", tags=["work"])["id"] for i in range(13)]
    for i in range(4):
        make_note(f"other {i}", tags=["home"])
    first, ids = walk(client, "/api/notes?tag=work&per_page=5")
    assert first["total"] == 13
    assert sorted(ids) == sorted(tagged)


def test_paging_search_results(client, make_note):
    hits = [make_note(f"python {i}")["id"] for i in range(11)]
    make_note("unrelated")
    first, ids = walk(client, "/api/search?q=python&per_page=4")
    assert sorted(ids) == sorted(hits)
