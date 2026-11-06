## Textual 8 notes (checked against the installed version)

- `self.set_focus(widget)` takes a widget, not an id: `self.query_one("#x").focus()`.
  `set_focus("#x")` crashes with `'str' object has no attribute 'focusable'`.
- `query_one("#id", WidgetType)`; a missing match raises `NoMatches` (widgets not composed yet,
  or a wrong id).
- Mounting into a widget that isn't mounted yet raises `MountError`: build children in
  `compose()` or pass them to the constructor, e.g. `ListView(ListItem(Label("a")), ...)`.
- `Input.Submitted` has `.input`, `.value`, `.validation_result`; handler
  `on_input_submitted(self, event)`. Clear with `event.input.value = ""`. Scope with
  `@on(Input.Submitted, "#id")`.
- CSS classes: `widget.add_class("x")`, `widget.remove_class("x")`, `widget.set_class(flag, "x")`
  (on when flag is true). `widget.classes` is a read-only frozenset: no `.add`/`.discard`.
- Events have no `.node`. The widget that sent a message is `event.control` (any widget message:
  `Input.Submitted`, `Button.Pressed`, `ListView.Selected`, ...); also `event.input`, `event.button`.
- Mouse clicks: `from textual import events`, then `def on_click(self, event: events.Click)` on the
  App (or the widget); `event.widget` is the widget clicked (e.g. `event.widget.id == "cell-1-2"`).
  There is no `Static.Click`.
- Tabs: build them in `compose()` with `with TabbedContent(id="tabs"):` and, inside,
  `with TabPane("People", id="people"):` then `yield` that tab's widgets. Don't pass TabPane
  objects to `TabbedContent(...)` (its arguments are titles) and don't mount into a TabPane from
  `on_mount` (`MountError`). Switch tabs with `self.query_one("#tabs", TabbedContent).active = "people"`.
- `Select(options, prompt="Payer", id=...)`: `options` (a list of `(label, value)`) is required, possibly
  `[]` (then keep the default `allow_blank=True`: empty options with `allow_blank=False` crash); there is no `placeholder=`. Options that change: `select.set_options([...])`, then set
  `select.value` to one of them (any other value raises `InvalidSelectValueError`; `set_options`
  resets the value to `Select.NULL`, the empty value).
- `Tree`: `tree.select_node(node)` posts `NodeSelected`, which toggles that node open/closed
  (so calling it on the root you just expanded collapses it). To move the cursor without
  toggling, use `tree.move_cursor(node)`. Tree keys: `up`/`down` move through the visible rows,
  `space` opens/closes a node, `enter` selects (and toggles); plain `left`/`right` do nothing.
- `ListView`: `await lv.clear()`, `await lv.append(ListItem(Label(text)))`, `await lv.extend(...)`,
  `lv.index`, `lv.highlighted_child`; events `ListView.Selected` (enter) and `ListView.Highlighted`.
  After clear + extend, `index` is `None`: set it again.
- `DataTable`: `add_column(label, key=...)` once; `add_row(*cells, key=...)`; `clear()` keeps the
  columns; `cursor_type="row"`; `coordinate_to_cell_key(table.cursor_coordinate).row_key.value`.
  Columns: `table.columns` is a dict `{ColumnKey: Column}` (`key.value` is the str key,
  `col.label.plain` the label); `table.ordered_columns` lists them in order. The cursor's column
  key: `table.coordinate_to_cell_key(table.cursor_coordinate).column_key.value`.
- `Binding(key, action, description, priority=False)`; action strings can take arguments:
  `"move(-1, 0)"`. `ctrl+q` quits by default; `ctrl+c` does not.
- Modals: `class Ask(ModalScreen[bool])` … `self.dismiss(result)`; open with
  `self.push_screen(Ask(), callback)`. `push_screen_wait` only works inside an `@work` worker.
- Timers: `self.set_interval(seconds, fn, pause=False)` returns a `Timer` (`.pause()`, `.resume()`).
- Threads: `@work(thread=True, exclusive=True)`; update widgets via `self.call_from_thread(fn, ...)`.
- `self.notify(text, severity="error", markup=False)` for messages containing user data.
- Don't name attributes after Textual's own (`visible`, `display`, `size`, `region`, `children`,
  `parent`, `name`, `id`, `classes`, `styles`, `screen`, `app`): it breaks the widget.
- CSS: Textual CSS, not web CSS. Pseudo-classes: `:focus`, `:hover`, `:disabled`, `:dark`,
  `:even`/`:odd`, `:first-child`, `:last-child` (no `:focused`, `:active`, `:selected`, `:checked`).
  A highlighted list item has class `-highlight` (`ListItem.-highlight`). Units: `fr`, `%`, `auto`,
  cells (no `px`); `layout: horizontal | vertical | grid`. Invalid CSS crashes the app at start.
  No `font-size`, `font-weight`, `display: flex` or `align-self`: bold is `text-style: bold`,
  centring is `content-align: center middle` (a widget's text) or `align: center middle` (a
  container's children), and big numbers are the `Digits` widget, not a font size.
- Headless tests: `async with app.run_test() as pilot:` → `await pilot.press("a", "enter")`,
  `await pilot.click("#id")`, `await pilot.pause()`. No pytest-asyncio: wrap in `asyncio.run(...)`.
