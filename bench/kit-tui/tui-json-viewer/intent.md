What the user wants but did not write down (answer questions only from this):

- Leaf labels show the value next to the key so I can skim without clicking, e.g.
  `name: "Ada"` or `[1]: 42` (strings in quotes, `null`/`true`/`false` as in JSON).
- Object and array labels show how many items they hold, e.g. `users [3]` or `limits {3}`.
- If the file isn't valid JSON, don't crash: show a clear error message (mentioning that the
  JSON is invalid / the parse error) instead of the tree contents.
- Only the root starts expanded; deeper levels open when I ask.
- No editing, no saving.
