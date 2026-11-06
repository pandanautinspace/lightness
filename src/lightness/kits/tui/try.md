## Trying the app

To see what the app does, run it with the harness's try command. Don't write debug scripts
for this, and don't read its source: `python .lightness/kit/try_app.py --help` lists every step
and option.

    python .lightness/kit/try_app.py [--file-text NAME=TEXT] [--file NAME=PATH] STEP ...

It starts `{module}.py` headless, runs the steps, and prints what the screen shows after each
step: lists with the highlighted row, tables, trees, inputs, labels, the focused widget, dialogs,
notifications, then the contents of each data file. A crash prints the error.

{params}

- Steps: `type:TEXT`, `press:KEY,KEY,...` (enter, space, up, down, tab, escape, ctrl+q, letters),
  `click:#id`, `focus:#id`, `wait:SECONDS` (real time), `advance:SECONDS` (moves the fake clock
  forward, then lets the app's timers run), `restart` (start again with the same files).
- To replace what an input holds: `focus:#id press:end,ctrl+u type:NEW` (ctrl+u clears to the left).
- To pick in a Select: `focus:#id press:enter,down,enter` (enter opens its list, down moves to the
  next option, enter chooses); the screen then shows `#id select: VALUE`.
- To switch tabs: `click:#--content-tab-PANE` (the screen lists them on the tabs line).
- `--file-text NAME=TEXT` starts file parameter NAME with a file holding TEXT; `--file NAME=PATH`
  with a copy of a file. With only one file parameter, `--data TEXT` and `--data-from PATH` do
  the same. `--kw NAME=VALUE` passes an extra App argument (e.g. a seed).
- Example: `python .lightness/kit/try_app.py --file-text NAME='...' focus:#some-list press:down,space restart`

{goal}
