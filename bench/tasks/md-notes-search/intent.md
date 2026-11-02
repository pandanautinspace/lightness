What the user wants but did not write down (answer questions only from this):

- Searching for several words means notes must contain *all* of them (AND), not any of them.
- Matching ignores case and accents: "cafe" finds "Café", "munchen" finds "München".
- Giving `--tag` more than once means the note must have *all* those tags.
- Tags are case-insensitive (`#Work` and `work` are the same tag) and shown lowercase.
- A note's tags are the union of its front-matter tags and its inline `#tags`.
- Markdown headings (`# Title`) and URL fragments (`page#section`) are not tags.
- Title: front-matter `title:` if present, else the first `# heading`, else the file name.
- A note whose title contains the search words should rank above notes that only mention
  them in passing.
- Hidden folders (like `.obsidian` or `.trash`) are ignored.
