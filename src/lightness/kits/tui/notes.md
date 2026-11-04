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
- **Time and randomness come in through `__init__`**: read the time only through the clock
  parameter (a callable returning seconds), and on each timer tick work out what to show from
  it; draw random numbers from `random.Random(seed)`. Then the try command's `advance:SECONDS`
  and tests move time without waiting. Don't wait for long stretches with `set_timer` (it counts
  real seconds); check the clock on a short `set_interval` instead.
- **Check the real app with the try command** (below) after each change: run the steps a user
  would, and compare what it prints with the task. Don't test by calling methods on an app that
  was never started, and don't run the app in the foreground: there is no terminal.
