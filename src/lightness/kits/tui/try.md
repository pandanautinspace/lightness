## Trying the app

To see what the app does, run it with the harness's try command. Don't write test files or
debug scripts for this:

    python .lightness/kit/try_app.py [--data 'FILE CONTENTS'] STEP ...

It starts `{module}.py` headless (with a fresh data file, if the app keeps one), runs the steps,
and prints what the screen shows after each step: lists with the highlighted row, tables, trees,
inputs, labels, the focused widget, dialogs, notifications, and the data file's contents.
A crash prints the error.

- Steps: `type:TEXT`, `press:KEY,KEY,...` (enter, space, up, down, tab, escape, ctrl+q, letters),
  `click:#id`, `focus:#id`, `wait:SECONDS`, `restart` (start again with the same data file).
- `--data 'TEXT'` starts with this data file; `--data-from FILE` copies one;
  `--kw NAME=VALUE` passes an extra App argument (e.g. a seed).
- Example: `python .lightness/kit/try_app.py --data '...' focus:#some-list press:down,space restart`

Try what the task describes: each key in the contract, starting with no data file and with
existing data, and a restart after a change. Compare what it prints with what the task asks for.
