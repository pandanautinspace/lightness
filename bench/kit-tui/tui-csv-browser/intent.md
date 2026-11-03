What the user wants but did not write down (answer questions only from this):

- Columns whose (non-empty) values are all numbers sort numerically, not alphabetically
  (so 9 comes before 10, and 4.25 before 4.3).
- Empty cells always go to the bottom when sorting, whichever direction.
- The filter can target one column with `column:text`, e.g. `author:le guin` only matches the
  author column (column name case-insensitive). If there's no column with that name, the whole
  text is just searched normally.
- Text sorts case-insensitively.
- It's read-only; no editing or saving.
