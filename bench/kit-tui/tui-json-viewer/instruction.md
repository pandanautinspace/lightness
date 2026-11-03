I deal with big nested JSON files (API responses, config dumps) and scrolling through them in
`less` is painful. Make me a Textual viewer: the JSON as a collapsible tree on the left, and on
the right the details of whatever I'm on — where it is in the document and what its value is.
There's a `sample.json` in the folder to try it with.

## Contract

- `jview.py` defines `class JsonViewerApp(textual.app.App)` with `__init__(self, json_path)`;
  `python jview.py FILE.json` runs it. The file is only read, never written.
- A `Tree` with id `tree`. Its root node (shown) is the whole document, starts expanded, and the
  cursor starts on it. Every object / array node has one child per member, in document order
  (children may be created lazily, but must exist once the node is expanded). A child's label
  starts with its key for object members, or with `[i]` (e.g. `[0]`) for array elements.
- Whenever the tree cursor moves to a node:
  - a widget with id `path` shows that node's path: `$` for the root, then `.key` for object
    members and `[i]` for array elements, e.g. `$.users[0].name`;
  - a widget with id `detail` (a `Static`/`Label`, or a `TextArea`) shows that node's value as
    JSON text (pretty-printed is fine), e.g. `"Ada"`, `36`, `null`, or the whole sub-object.
