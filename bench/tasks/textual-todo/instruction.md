I live in the terminal and want a small todo list there instead of yet another browser tab.
Make me a Textual app where I can type a todo and hit enter, tick things off (and un-tick them
when I was too optimistic), throw away ones I don't need, and switch between seeing everything,
just what's left, or just what's done. It has to remember my list between runs.

## Contract

- `todo.py` defines `class TodoApp(textual.app.App)` with `__init__(self, data_path)`;
  `python todo.py [PATH]` runs it (default `todos.json`).
- The list is stored in the JSON file at `data_path` as a list of `{"title": str, "done": bool}`,
  saved after every change. A missing file means an empty list.
- An `Input` with id `new-todo`: pressing enter adds its text as a new todo and clears it.
  Blank input adds nothing.
- A `ListView` with id `todo-list` containing one `ListItem` per todo currently shown, which
  displays the todo's title.
- Keys while the list has focus act on the highlighted todo: `space` toggles done,
  `d` deletes it. `f` cycles the filter: all → active (not done) → done → all.
