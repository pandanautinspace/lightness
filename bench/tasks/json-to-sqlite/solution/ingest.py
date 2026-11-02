"""Load a nested JSON order dump into a normalized SQLite database (idempotent upserts)."""

import argparse
import json
import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS customers (
    id TEXT PRIMARY KEY, name TEXT, email TEXT, street TEXT, city TEXT, country TEXT,
    last_seen TEXT
);
CREATE TABLE IF NOT EXISTS products (sku TEXT PRIMARY KEY, name TEXT);
CREATE TABLE IF NOT EXISTS orders (
    id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL REFERENCES customers(id),
    created_at TEXT NOT NULL,
    status TEXT NOT NULL,
    shipping REAL NOT NULL DEFAULT 0,
    discount REAL NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS order_items (
    order_id TEXT NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    line INTEGER NOT NULL,
    sku TEXT NOT NULL REFERENCES products(sku),
    quantity INTEGER NOT NULL,
    unit_price REAL NOT NULL,
    PRIMARY KEY (order_id, line)
);
CREATE INDEX IF NOT EXISTS idx_orders_customer ON orders(customer_id);
"""


def money(value) -> float:
    if value is None or value == "":
        return 0.0
    return float(str(value).replace(",", "").strip().lstrip("$€£"))


def connect(db_path) -> sqlite3.Connection:
    con = sqlite3.connect(db_path)
    con.execute("PRAGMA foreign_keys = ON")
    con.executescript(SCHEMA)
    return con


def upsert_order(con: sqlite3.Connection, order: dict) -> None:
    cust = order.get("customer") or {}
    addr = cust.get("address") or {}
    created = str(order["created_at"])
    country = (addr.get("country") or "").strip().upper() or None
    # latest order wins for name/address changes
    con.execute(
        """INSERT INTO customers (id, name, email, street, city, country, last_seen)
           VALUES (?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(id) DO UPDATE SET name=excluded.name, email=excluded.email,
               street=excluded.street, city=excluded.city, country=excluded.country,
               last_seen=excluded.last_seen
           WHERE excluded.last_seen >= customers.last_seen""",
        (str(cust["id"]), cust.get("name"), cust.get("email"), addr.get("street"), addr.get("city"),
         country, created),
    )
    con.execute(
        """INSERT INTO orders (id, customer_id, created_at, status, shipping, discount)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(id) DO UPDATE SET customer_id=excluded.customer_id, created_at=excluded.created_at,
               status=excluded.status, shipping=excluded.shipping, discount=excluded.discount""",
        (str(order["id"]), str(cust["id"]), created, str(order.get("status", "")).lower(),
         money(order.get("shipping")), money(order.get("discount"))),
    )
    con.execute("DELETE FROM order_items WHERE order_id = ?", (str(order["id"]),))
    for line, item in enumerate(order.get("items") or [], start=1):
        con.execute(
            "INSERT INTO products (sku, name) VALUES (?, ?) ON CONFLICT(sku) DO UPDATE SET name=excluded.name",
            (item["sku"], item.get("name")),
        )
        con.execute(
            "INSERT INTO order_items (order_id, line, sku, quantity, unit_price) VALUES (?, ?, ?, ?, ?)",
            (str(order["id"]), line, item["sku"], int(item.get("quantity", 1)), money(item.get("unit_price"))),
        )


def load(json_path, db_path) -> int:
    data = json.loads(Path(json_path).read_text(encoding="utf-8"))
    orders = data["orders"] if isinstance(data, dict) else data
    con = connect(db_path)
    with con:
        for order in sorted(orders, key=lambda o: str(o.get("created_at", ""))):
            upsert_order(con, order)
    con.close()
    return len(orders)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dump", type=Path)
    parser.add_argument("db", type=Path)
    args = parser.parse_args()
    n = load(args.dump, args.db)
    print(f"loaded {n} orders into {args.db}")


if __name__ == "__main__":
    main()
