## How to build this app (decided already; follow unless the task says otherwise)

- **State is plain Python data on the app** (lists/dicts, numbers, strings). Widgets only show it.
  Every change goes: update the data → save (if the app keeps data) → `refresh_view()`.
  Never read state back out of widgets.
- **Save exactly the format the task describes.** Don't add helper fields (indexes, selection,
  ids the task didn't ask for) to saved data; keep those on the app only.
- **Create widgets in `compose()`; fill them in `refresh_view()`.** Don't mount or query widgets
  in `__init__`. Anything that touches widgets runs from `on_mount` or later.
- **One module, one App class**, plus a `main()` that reads the optional path argument.
  The class name, `__init__` parameters, widget ids and keys must match the task's contract exactly.
- **Keys:** item actions (s, x, e, …) as App `BINDINGS` act on the highlighted item while a
  list or table has focus. They do not fire while an `Input` or `TextArea` has focus (those take
  printable keys). Decide which widget has focus when, and set it explicitly.
- **Missing or broken data files are normal:** start empty, never crash.
- **Timers and randomness are injected** (a `now` callable, a seed) so tests are deterministic.
- **Test the real app headlessly** with `run_test()` (see the `headless_test` part). Cover:
  starting with no data file, starting with an existing file, every key in the contract, and a
  restart after a change. Check the saved file's exact contents. Don't test by calling methods on
  an app that was never started, and don't run the app in the foreground: there is no terminal.
