What the user wants but did not write down (answer questions only from this):

- Cancelled and refunded orders are kept in the database but never count towards revenue,
  spend or best sellers. All other statuses (paid, shipped, completed, ...) count.
- Revenue of an order = sum of quantity × unit price over its line items, minus the order's
  discount. Shipping is not revenue.
- "Best seller" means most units sold (not most revenue); ties broken by SKU.
- Months come from the order's `created_at` date as written (UTC); no timezone conversion.
- Country codes are reported uppercase ("de" and "DE" are the same country).
- Prices sometimes arrive as strings like "19.99"; treat them as numbers.
- If a customer's name or address changes between orders, the latest order wins.
- Money values rounded to cents are fine.
