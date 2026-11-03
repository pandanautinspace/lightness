What the user wants but did not write down (answer questions only from this):

- The list is sorted by title, alphabetically and case-insensitively (not in insertion order).
- If I type a URL without a scheme (`example.com/page`), store it as `https://example.com/page`.
  URLs that already have a scheme (`http://`, `https://`, `ftp://`, ...) are kept as typed.
- If I leave the title blank, use the URL (after adding the scheme) as the title.
- Tags are trimmed and lowercased, duplicates dropped, stored like `python,reading`.
- Deleting doesn't need a confirmation.
- Show the URL (and tags) next to the title in the list, dimmed.
