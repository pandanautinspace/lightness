What the user wants but did not write down (answer questions only from this):

- The bug is in the JSON API listing (`GET /api/notes`, also `/api/search`, with
  `?page=&per_page=`). Example: with 25 notes and `per_page=10`, the response says there are
  only 2 pages, and asking for page 3 returns page 2 again, so the 5 oldest notes are never seen.
- Paging through pages 1..`pages` should show every note exactly once, in the same newest-first
  order as now. `pages` should be the real number of pages, and `has_next` should be false only
  on the last page.
- Asking for a page past the end can keep behaving as it does now (it returns the last page).
- An empty list still reports `pages: 1`.
- Response shape (`items`, `page`, `per_page`, `total`, `pages`, `has_next`) must not change.
- A regression test for this in the repo's tests would be nice but is not required.
