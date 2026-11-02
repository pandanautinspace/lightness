from datetime import date
from html.parser import HTMLParser
from pathlib import Path

import pytest

from lightness.bench.testkit import free_port, serve

TODAY = date.today().isoformat()
THIS_MONTH = TODAY[:7]


def app(db: Path):
    port = free_port()
    return serve("app.py", "--db", str(db), "--port", str(port), port=port)


@pytest.fixture
def client(tmp_path: Path):
    with app(tmp_path / "expenses.db") as c:
        yield c


def add(client, amount=12.5, category="Food", day="2024-03-10", description="lunch", status=None):
    r = client.post("/api/expenses", json={"amount": amount, "category": category, "date": day,
                                           "description": description})
    if status is None:
        assert r.status_code == 201, r.text
        return r.json()
    return r


def listing(client, **params) -> list[dict]:
    r = client.get("/api/expenses", params=params)
    assert r.status_code == 200, r.text
    return r.json()


class PageParser(HTMLParser):
    """Collects form fields and the text inside the data-testid="expense-list" element."""

    VOID = {"input", "br", "img", "meta", "link", "hr", "col", "area", "base", "source", "wbr"}

    def __init__(self):
        super().__init__()
        self.forms: list[dict] = []
        self.labels: dict[str, str] = {}
        self._label_for: str | None = None
        self.list_found = False
        self.list_text: list[str] = []
        self._depth = 0  # >0 while inside the expense-list element

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "form":
            self.forms.append({"method": (a.get("method") or "get").lower(), "action": a.get("action") or "",
                               "fields": set(), "ids": set()})
        if tag in ("input", "select", "textarea") and self.forms:
            if a.get("name"):
                self.forms[-1]["fields"].add(a["name"])
            if a.get("id"):
                self.forms[-1]["ids"].add(a["id"])
        if self._depth and tag not in self.VOID:
            self._depth += 1
        elif a.get("data-testid") == "expense-list":
            self.list_found = True
            if tag not in self.VOID:
                self._depth = 1

    def handle_endtag(self, tag):
        if self._depth and tag not in self.VOID:
            self._depth -= 1

    def handle_data(self, data):
        if self._depth:
            self.list_text.append(data)


def parse_page(client, **params) -> PageParser:
    r = client.get("/", params=params)
    assert r.status_code == 200
    p = PageParser()
    p.feed(r.text)
    return p


def test_page_has_form_and_list(client):
    p = parse_page(client)
    assert p.list_found, 'no element with data-testid="expense-list"'
    posting = [f for f in p.forms if f["method"] == "post" and f["action"].rstrip("/").endswith("/expenses")]
    assert posting, "no POST form with action /expenses"
    assert {"amount", "category", "date", "description"} <= posting[0]["fields"]


def test_create_and_list(client):
    e = add(client, amount=12.5, category="Food", day="2024-03-10", description="lunch")
    assert isinstance(e["id"], int)
    assert e["amount"] == pytest.approx(12.5)
    assert (e["category"], e["date"], e["description"]) == ("Food", "2024-03-10", "lunch")
    items = listing(client)
    assert len(items) == 1
    assert items[0]["id"] == e["id"] and items[0]["amount"] == pytest.approx(12.5)


def test_update(client):
    e = add(client)
    r = client.put(f"/api/expenses/{e['id']}", json={"amount": 20, "description": "dinner"})
    assert r.status_code == 200, r.text
    assert r.json()["amount"] == pytest.approx(20)
    (item,) = listing(client)
    assert item["amount"] == pytest.approx(20)
    assert item["description"] == "dinner"
    assert item["category"] == "Food" and item["date"] == "2024-03-10"


def test_delete_and_unknown_ids(client):
    keep = add(client, description="keep")
    gone = add(client, description="gone")
    assert client.delete(f"/api/expenses/{gone['id']}").status_code in (200, 204)
    assert [i["id"] for i in listing(client)] == [keep["id"]]
    assert client.delete(f"/api/expenses/{gone['id']}").status_code == 404
    assert client.put("/api/expenses/9999", json={"amount": 5}).status_code == 404


def test_bad_amount_rejected(client):
    for amount in ["abc", "", None, "12abc"]:
        body = {"category": "Food", "date": "2024-03-10", "description": "x"}
        if amount is not None:
            body["amount"] = amount
        r = client.post("/api/expenses", json=body)
        assert 400 <= r.status_code < 500, amount
    assert listing(client) == []


def test_bad_date_rejected(client):
    for bad in ["2024-13-45", "yesterday", "10/03/2024", ""]:
        r = add(client, day=bad, status="any")
        assert 400 <= r.status_code < 500, bad
    assert listing(client) == []
    e = add(client)
    r = client.put(f"/api/expenses/{e['id']}", json={"date": "2024-02-30"})
    assert 400 <= r.status_code < 500
    assert listing(client)[0]["date"] == "2024-03-10"


def test_filter_by_month_and_category(client):
    add(client, category="Food", day="2024-03-01")
    add(client, category="Transport", day="2024-03-31")
    add(client, category="Food", day="2024-04-01")
    assert {i["date"] for i in listing(client, month="2024-03")} == {"2024-03-01", "2024-03-31"}
    assert {i["date"] for i in listing(client, category="Food")} == {"2024-03-01", "2024-04-01"}
    both = listing(client, month="2024-03", category="Food")
    assert [i["date"] for i in both] == ["2024-03-01"]
    assert len(listing(client)) == 3


def test_summary_totals(client):
    add(client, amount=10.10, category="Food", day="2024-05-02")
    add(client, amount=0.20, category="Food", day="2024-05-20")
    add(client, amount=30, category="Transport", day="2024-05-31")
    add(client, amount=99, category="Food", day="2024-06-01")
    r = client.get("/api/summary", params={"month": "2024-05"})
    assert r.status_code == 200
    s = r.json()
    assert s["month"] == "2024-05"
    assert s["total"] == pytest.approx(40.30, abs=0.005)
    assert s["by_category"]["Food"] == pytest.approx(10.30, abs=0.005)
    assert s["by_category"]["Transport"] == pytest.approx(30, abs=0.005)
    assert s["by_category"].get("Rent", 0) == 0
    empty = client.get("/api/summary", params={"month": "2023-01"}).json()
    assert empty["total"] == 0


def test_persists_across_restart(tmp_path):
    db = tmp_path / "expenses.db"
    with app(db) as c:
        a = add(c, description="first")
        b = add(c, description="second")
        c.put(f"/api/expenses/{b['id']}", json={"amount": 7})
        c.delete(f"/api/expenses/{a['id']}")
    with app(db) as c:
        (item,) = listing(c)
        assert item["id"] == b["id"]
        assert item["amount"] == pytest.approx(7)
        assert item["description"] == "second"


def test_form_post_creates_expense(client):
    r = client.post("/expenses", data={"amount": "8.40", "category": "Food", "date": TODAY,
                                       "description": "bakery run"})
    assert r.status_code < 400, r.text
    (item,) = listing(client)
    assert item["amount"] == pytest.approx(8.4) and item["description"] == "bakery run"
    client.post("/expenses", data={"amount": "lots", "category": "Food", "date": TODAY,
                                         "description": "nope"})
    assert len(listing(client)) == 1


def test_page_lists_added_expenses(client):
    add(client, day=TODAY, description="zucchini soup")
    add(client, day=TODAY, category="Transport", description="tram ticket")
    p = parse_page(client)
    text = " ".join(p.list_text)
    assert "zucchini soup" in text and "tram ticket" in text
    filtered = " ".join(parse_page(client, month=THIS_MONTH, category="Transport").list_text)
    assert "tram ticket" in filtered


def test_intent_newest_first(client):
    a = add(client, day="2024-03-05", description="a")
    b = add(client, day="2024-03-20", description="b")
    c = add(client, day="2024-03-05", description="c")
    d = add(client, day="2024-01-01", description="d")
    assert [i["id"] for i in listing(client)] == [b["id"], c["id"], a["id"], d["id"]]


def test_intent_fixed_categories(client):
    for cat in ["Food", "Rent", "Transport", "Utilities", "Entertainment", "Health", "Other"]:
        add(client, category=cat)
    for bad in ["Yachts", "", "Groceries"]:
        r = add(client, category=bad, status="any")
        assert 400 <= r.status_code < 500, bad
    assert len(listing(client)) == 7
    r = add(client, amount=-5, status="any")
    assert 400 <= r.status_code < 500
    r = add(client, amount=0, status="any")
    assert 400 <= r.status_code < 500


def test_intent_euro_two_decimals(client):
    add(client, amount=12.5, day=TODAY, description="pizza")
    add(client, amount=3, day=TODAY, description="coffee")
    text = " ".join(parse_page(client).list_text)
    assert "€" in text or "EUR" in text
    assert "12.50" in text or "12,50" in text
    assert "3.00" in text or "3,00" in text
