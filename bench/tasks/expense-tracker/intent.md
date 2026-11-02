What the user wants but did not write down (answer questions only from this):

- Single user, no login.
- Currency is EUR. Amounts are shown in the page with a euro sign and exactly 2 decimals
  (12.5 is shown as "12.50"). Amounts are stored and summed to the cent.
- Amounts must be greater than zero.
- Categories are a fixed list, exactly: Food, Rent, Transport, Utilities, Entertainment,
  Health, Other. Any other category is rejected (4xx). The form uses a dropdown of these.
- Lists are newest first: by date descending, and for the same date the most recently added
  first. This applies to both the page and `GET /api/expenses`.
- The page shows the current month by default, with a way to pick another month and a
  category, and shows the month's total per category.
- Description is optional (empty string if not given).
