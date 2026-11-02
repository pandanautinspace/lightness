Our little web shop can only export its orders as one big nested JSON file (orders with the
customer and the line items embedded in each order). I want to get that into a proper SQLite
database so I can answer the usual questions: who are our best customers, how is revenue
doing month by month, what sells best, what has a given customer ordered, and where does the
money come from. I get a fresh export every week and it overlaps with the previous ones.
There's a small example export in `sample_orders.json`.

## Contract

- `python ingest.py DUMP.json DB_PATH` loads a dump (shaped like `sample_orders.json`) into the
  SQLite database at DB_PATH, creating it if needed. Loading the same or an overlapping newer
  dump again must not duplicate anything (an order is identified by its `id`).
- Store the data normalized: customers, products, orders and line items in their own tables,
  not JSON blobs. The table layout is up to you.
- `queries.py` must provide these functions; each takes the database path first:
  - `top_customers(db_path, n=5)` → list of `(customer_id, name, total_spent)`, biggest spender first
  - `monthly_revenue(db_path)` → list of `("YYYY-MM", revenue)`, oldest month first
  - `top_products(db_path, n=5)` → list of `(sku, product_name)`, best seller first
  - `customer_history(db_path, customer_id)` → list of `(order_id, "YYYY-MM-DD", order_total)`,
    oldest first
  - `revenue_by_country(db_path)` → dict `{country_code: revenue}`
- Use only the Python standard library (`sqlite3` included).
