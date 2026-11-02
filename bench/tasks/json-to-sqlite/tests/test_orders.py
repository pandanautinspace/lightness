import copy
import json
import sqlite3
from pathlib import Path

import pytest

from lightness.bench.testkit import import_from_workspace, run_cli

CUSTOMERS = {
    "C-1": ("Ana Lima", "ana@example.com", "Porto", "PT"),
    "C-2": ("Ben Okafor", "ben@example.co.uk", "Leeds", "GB"),
    "C-3": ("Chloé Durand", "chloe@example.fr", "Lyon", "FR"),
    "C-4": ("Dan Weber", "dan@example.de", "Köln", "de"),
}
PRODUCTS = {
    "MUG-01": ("Ceramic mug", 12.5),
    "TEE-02": ("Logo T-shirt", "20.00"),
    "CAP-03": ("Baseball cap", 15),
    "BAG-04": ("Tote bag", 8.0),
    "BOOK-05": ("Dot-grid notebook", "6.00"),
}
# (order id, created_at, customer, [(sku, qty)], status)
ORDERS = [
    ("A-1001", "2024-01-05T09:12:00Z", "C-1", [("MUG-01", 2), ("BAG-04", 1)], "completed"),
    ("A-1002", "2024-01-17T15:40:10Z", "C-2", [("TEE-02", 1)], "shipped"),
    ("A-1003", "2024-01-31T23:10:00Z", "C-3", [("CAP-03", 2), ("BOOK-05", 3)], "completed"),
    ("A-1004", "2024-02-02T08:00:00Z", "C-1", [("TEE-02", 2)], "paid"),
    ("A-1005", "2024-02-14T12:30:00Z", "C-4", [("MUG-01", 4)], "completed"),
    ("A-1006", "2024-02-20T19:05:00Z", "C-2", [("BOOK-05", 5), ("BAG-04", 2)], "shipped"),
    ("A-1007", "2024-03-03T10:00:00Z", "C-3", [("TEE-02", 1), ("MUG-01", 1)], "completed"),
    ("A-1008", "2024-03-09T16:45:00Z", "C-1", [("CAP-03", 1)], "completed"),
]


def make_order(oid, created, cust, items, status, shipping=0, discount=None):
    name, email, city, country = CUSTOMERS[cust]
    order = {
        "id": oid,
        "created_at": created,
        "status": status,
        "customer": {"id": cust, "name": name, "email": email,
                     "address": {"street": "1 Main St", "city": city, "country": country}},
        "items": [{"sku": s, "name": PRODUCTS[s][0], "quantity": q, "unit_price": PRODUCTS[s][1]} for s, q in items],
    }
    if shipping:
        order["shipping"] = shipping
    if discount is not None:
        order["discount"] = discount
    return order


def base_orders() -> list[dict]:
    return [make_order(*o) for o in ORDERS]


def write_dump(path: Path, orders: list[dict]) -> Path:
    path.write_text(json.dumps({"exported_at": "2024-03-31T06:00:00Z", "orders": orders}, ensure_ascii=False),
                    encoding="utf-8")
    return path


def ingest(dump: Path, db: Path):
    r = run_cli("ingest.py", str(dump), str(db))
    assert r.returncode == 0, r.stderr
    return r


@pytest.fixture
def db(tmp_path: Path) -> Path:
    db = tmp_path / "shop.db"
    ingest(write_dump(tmp_path / "dump.json", base_orders()), db)
    return db


@pytest.fixture
def q():
    return import_from_workspace("queries")


def as_dict(rows) -> dict:
    return {r[0]: r for r in rows}


def test_ingest_creates_normalized_tables(db):
    con = sqlite3.connect(db)
    tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    counts = {t: con.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in tables}
    con.close()
    assert len(tables) >= 3, tables
    assert 4 in counts.values(), f"no table with one row per customer: {counts}"
    assert 8 in counts.values(), f"no table with one row per order: {counts}"
    assert 12 in counts.values(), f"no table with one row per line item: {counts}"


def test_top_customers(db, q):
    rows = q.top_customers(str(db), 3)
    assert [r[0] for r in rows] == ["C-1", "C-3", "C-2"]
    assert [float(r[2]) for r in rows] == pytest.approx([88.0, 80.5, 66.0], abs=0.01)
    assert rows[1][1] == "Chloé Durand"
    assert len(q.top_customers(str(db))) == 4


def test_monthly_revenue(db, q):
    rows = q.monthly_revenue(str(db))
    assert [r[0] for r in rows] == ["2024-01", "2024-02", "2024-03"]
    assert [float(r[1]) for r in rows] == pytest.approx([101.0, 136.0, 47.5], abs=0.01)


def test_top_products_shape(db, q):
    rows = q.top_products(str(db), 2)
    assert len(rows) == 2
    for sku, name in rows:
        assert PRODUCTS[sku][0] == name
    assert "MUG-01" in [r[0] for r in rows]
    assert {r[0] for r in q.top_products(str(db), 10)} == set(PRODUCTS)


def test_customer_history(db, q):
    rows = q.customer_history(str(db), "C-1")
    assert [(r[0], r[1]) for r in rows] == [("A-1001", "2024-01-05"), ("A-1004", "2024-02-02"), ("A-1008", "2024-03-09")]
    assert [float(r[2]) for r in rows] == pytest.approx([33.0, 40.0, 15.0], abs=0.01)
    assert list(q.customer_history(str(db), "C-999")) == []


def test_revenue_by_country(db, q):
    merged: dict[str, float] = {}
    for code, revenue in q.revenue_by_country(str(db)).items():
        merged[code.upper()] = merged.get(code.upper(), 0) + float(revenue)
    assert merged == pytest.approx({"PT": 88.0, "GB": 66.0, "FR": 80.5, "DE": 50.0}, abs=0.01)


def test_reimport_overlapping_dump_does_not_duplicate(db, tmp_path, q):
    ingest(write_dump(tmp_path / "dump.json", base_orders()), db)
    newer = base_orders()[-2:] + [make_order("A-1009", "2024-03-20T11:00:00Z", "C-4", [("BAG-04", 2)], "completed")]
    ingest(write_dump(tmp_path / "newer.json", newer), db)
    totals = {r[0]: float(r[2]) for r in q.top_customers(str(db), 10)}
    assert totals == pytest.approx({"C-1": 88.0, "C-2": 66.0, "C-3": 80.5, "C-4": 66.0}, abs=0.01)
    assert [float(r[1]) for r in q.monthly_revenue(str(db))] == pytest.approx([101.0, 136.0, 63.5], abs=0.01)
    assert len(q.customer_history(str(db), "C-1")) == 3


def test_intent_cancelled_and_refunded_orders_do_not_count(tmp_path, q):
    orders = base_orders() + [
        make_order("A-1010", "2024-03-12T09:00:00Z", "C-2", [("TEE-02", 10)], "cancelled"),
        make_order("A-1011", "2024-03-15T09:00:00Z", "C-4", [("CAP-03", 9)], "refunded"),
    ]
    db = tmp_path / "shop.db"
    ingest(write_dump(tmp_path / "dump.json", orders), db)
    totals = {r[0]: float(r[2]) for r in q.top_customers(str(db), 10)}
    assert totals.get("C-2") == pytest.approx(66.0, abs=0.01)
    assert totals.get("C-4") == pytest.approx(50.0, abs=0.01)
    assert float(q.monthly_revenue(str(db))[-1][1]) == pytest.approx(47.5, abs=0.01)
    assert [r[0] for r in q.top_products(str(db), 2)] == ["BOOK-05", "MUG-01"]


def test_intent_shipping_excluded_discount_subtracted(tmp_path, q):
    orders = base_orders()
    orders[0]["shipping"] = 4.9  # A-1001, C-1
    orders.append(make_order("A-1012", "2024-03-25T09:00:00Z", "C-3", [("CAP-03", 2)], "completed",
                             shipping=5.0, discount=10))
    db = tmp_path / "shop.db"
    ingest(write_dump(tmp_path / "dump.json", orders), db)
    totals = {r[0]: float(r[2]) for r in q.top_customers(str(db), 10)}
    assert totals["C-1"] == pytest.approx(88.0, abs=0.01)
    assert totals["C-3"] == pytest.approx(100.5, abs=0.01)
    assert float(q.monthly_revenue(str(db))[-1][1]) == pytest.approx(67.5, abs=0.01)


def test_intent_best_sellers_by_units(db, q):
    assert [r[0] for r in q.top_products(str(db), 3)] == ["BOOK-05", "MUG-01", "TEE-02"]
