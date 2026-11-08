I time my interval runs and my speedcubing solves, and I'd like a stopwatch in the terminal
instead of on my phone. Big readable time, start/pause with space, a lap button, a reset. Show the
laps in a list as I go.

## Contract

- `stopwatch.py` defines `class StopwatchApp(textual.app.App)` with
  `__init__(self, clock=time.monotonic)`; `python stopwatch.py` runs it. `clock` is a
  zero-argument callable returning seconds as a float; the app must read the time only through
  it (tests pass a fake clock).
- A widget with id `elapsed` shows the elapsed time. Under an hour it is formatted `MM:SS.d`
  (two-digit minutes, two-digit seconds, tenths), e.g. `01:05.3`. Tenths are cut, not rounded,
  like any stopwatch: 3.06 seconds shows `00:03.0`. While running it refreshes on
  its own at least 5 times per second; paused time does not count.
- Keys: `space` starts / pauses / resumes. `l` records a lap while running (ignored otherwise).
  `r` resets the time to `00:00.0` and clears the laps, but only while paused or stopped
  (ignored while running).
- A `ListView` with id `laps` has one `ListItem` per recorded lap, showing a time in the same
  format.
