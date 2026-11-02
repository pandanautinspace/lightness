"""Questions about the shop, answered from the SQLite database built by ingest.py."""

import sqlite3

# Revenue of an order: items minus discount, no shipping; cancelled/refunded orders never count.
ORDER_REVENUE = """
    SELECT o.id, o.customer_id, o.created_at,
           COALESCE((SELECT SUM(i.quantity * i.unit_price) FROM order_items i WHERE i.order_id = o.id), 0)
             - o.discount AS revenue
    FROM orders o
    WHERE o.status NOT IN ('cancelled', 'canceled', 'refunded')
"""


def _query(db_path, sql: str, params=()) -> list[tuple]:
    con = sqlite3.connect(db_path)
    try:
        return con.execute(sql, params).fetchall()
    finally:
        con.close()


def top_customers(db_path, n=5) -> list[tuple[str, str, float]]:
    rows = _query(db_path, f"""
        SELECT c.id, c.name, SUM(r.revenue) AS spent
        FROM ({ORDER_REVENUE}) r JOIN customers c ON c.id = r.customer_id
        GROUP BY c.id ORDER BY spent DESC, c.id LIMIT ?""", (n,))
    return [(cid, name, round(spent, 2)) for cid, name, spent in rows]


def monthly_revenue(db_path) -> list[tuple[str, float]]:
    rows = _query(db_path, f"""
        SELECT substr(r.created_at, 1, 7) AS month, SUM(r.revenue)
        FROM ({ORDER_REVENUE}) r GROUP BY month ORDER BY month""")
    return [(month, round(total, 2)) for month, total in rows]


def top_products(db_path, n=5) -> list[tuple[str, str]]:
    return _query(db_path, """
        SELECT p.sku, p.name
        FROM order_items i
        JOIN orders o ON o.id = i.order_id
        JOIN products p ON p.sku = i.sku
        WHERE o.status NOT IN ('cancelled', 'canceled', 'refunded')
        GROUP BY p.sku ORDER BY SUM(i.quantity) DESC, p.sku LIMIT ?""", (n,))


def customer_history(db_path, customer_id) -> list[tuple[str, str, float]]:
    rows = _query(db_path, """
        SELECT o.id, substr(o.created_at, 1, 10),
               COALESCE((SELECT SUM(i.quantity * i.unit_price) FROM order_items i WHERE i.order_id = o.id), 0)
                 - o.discount
        FROM orders o WHERE o.customer_id = ? ORDER BY o.created_at, o.id""", (customer_id,))
    return [(oid, day, round(total, 2)) for oid, day, total in rows]


def revenue_by_country(db_path) -> dict[str, float]:
    rows = _query(db_path, f"""
        SELECT COALESCE(c.country, '??'), SUM(r.revenue)
        FROM ({ORDER_REVENUE}) r JOIN customers c ON c.id = r.customer_id
        GROUP BY 1 ORDER BY 2 DESC""")
    return {country: round(total, 2) for country, total in rows}
