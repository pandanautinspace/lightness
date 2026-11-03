# Kits: starting points per app type

Status: design, 2026-11-03. Part of M1 Phase B (see [m1-plan.md](m1-plan.md)).

## Why

Small models fail in predictable ways that a harness can absorb (from the textual-todo
analysis: 0/3 on the 35B and 0/3 on the 9B with the plain loop):

| Model shortcoming | Seen as | Kit lever |
|---|---|---|
| Weak reasoning about design | loading data before widgets exist; UI-only fields saved to the data file; untestable structure | **design notes**: the decisions made once, up front |
| Missing or stale library knowledge | `set_focus("id")`, invalid CSS, invented kwargs, 60 steps reading library source | **shell** that already does the hard parts right, plus a **verified cheat sheet** |
| Late or no feedback from the real program | apps never started; tests on unmounted objects; grep-the-source "verification" | **smoke check** from step 1, because the shell already runs |
| Output-token cost | first full-file writes are ~15% of output | the harness writes the shell, the model fills it in |

## Rules (non-negotiable)

1. **Breadth over the benchmark.** A kit covers the archetypes of its category (below), not
   the shape of any benchmark task. It is written from library docs and general patterns,
   never from a task's solution.
2. **Shell + parts.** The shell holds only what every app in the category shares. Anything
   archetype-specific is a *part*: a small, runnable, verified example the model can read
   and copy.
3. **Separate test set.** Kits are developed and measured on `bench/kit-<category>/`, written
   blind by a separate agent with one task per archetype. The main benchmark (dev and
   held-out) is never used to tune kits. Results are reported per archetype.
4. **Never worse than no kit.** The classifier can say "no kit"; we measure kit vs no kit,
   including on tasks the kit fits poorly.
5. **Kits can't rot.** Every shell, part and cheat-sheet snippet is exercised by our test
   suite against the installed library versions.
6. **Small.** One file per shell where possible. The guarded loop's scaffolding (a `core/`
   package and symbol edits) made the model over-build; kits must not.

## What a kit contains

| Piece | Who uses it | Form |
|---|---|---|
| `shell.py.tmpl` | the harness writes it into the workspace, filling in contract names | a working, minimal program |
| `notes.md` | shown in the task message | design answers: where state lives, lifecycle, saving, keys, testing |
| `cheatsheet.md` | shown in the task message | short API notes, each verified against the installed version |
| `parts/*.py` | the model reads them on demand (`cat`); an index is shown | runnable examples, one pattern each |
| smoke runner | the harness, after each change | "does it start?", for this kind of app |
| `kit.toml` | the harness | names to fill, parts index with when-to-use lines |

Repo-change tasks have no kit; their counterpart is context surfacing (repo map, tests,
how to run).

## Archetypes and parts

From the archetype research (Textual examples and awesome-textualize, clig.dev, Typer and
argparse docs, the Flask tutorial and patterns, karan/Projects, build-your-own-x).

### tui (Textual), built first

| # | Archetype | Core parts |
|---|---|---|
| T1 | CRUD list manager (bookmarks, notes, contacts) | list-actions, modal, json-store |
| T2 | Table browser / record viewer | data-table, filter, file-loader |
| T3 | Form / calculator / converter | input-form |
| T4 | Dashboard / monitor (periodic refresh) | periodic-refresh, worker |
| T5 | Viewer / navigator (tree + pane) | tree-detail, file-loader |
| T6 | Search / lookup | filter, worker, data-table or list-actions |
| T7 | Multi-screen / tabbed | screens-tabs, modal |
| T8 | Game / grid simulation | grid-game, periodic-refresh |
| T9 | Editor / text tool | text-editor, modal |

Shell concerns: App subclass with inline CSS, bindings, compose/on_mount, state on the app
as plain data, a load/save adapter with a path argument, `refresh_view()`, `notify()` for
errors, `main()` taking `[PATH]`, headless tests with `run_test()`.

### cli

Archetypes: text filter; calculator/converter; generator; personal data store with
subcommands; file-system utility (dry-run); validator/checker (exit codes); format converter;
workflow runner; report printer. Parts: subcommands, io-stream (`-` = stdin), output-format
(`--json`, rich table), exit-code/error boundary, dry-run + confirm, json/sqlite store,
fs-walk, config-file, progress, seeded random.

### data-script

Archetypes: clean/normalize; aggregate report; join/reconcile; load into sqlite; query →
report; reshape/convert; validate/profile; log parsing; batch over files. Parts: csv io
(`utf-8-sig`, `newline=""`), json/jsonl io, coercion + row validation with a reject sink,
group-by helpers, join-by-key, sqlite load (upsert, transaction), sqlite query/export,
report writer, flatten/reshape, regex line parser, per-file error isolation.

### webapp (Flask)

Archetypes: CRUD with forms; JSON API; form → result; auth-gated multi-user; URL shortener;
dashboard over data; polls/guestbook; file upload; hybrid HTML + JSON. Parts: app factory +
sqlite `get_db`/`init_db`, base layout + flash, CRUD routes (post-redirect-get), form
validation, JSON API with error handlers, auth, shortcode/redirect, table view with
filter/sort/paginate, CSV download, upload handling, fetch-js snippet.

**Open decision: widget framework for UI-centric webapps.** Writing HTML/JS/CSS is a large
error surface for small models. A widget framework gives the same widgets-plus-state model as
Textual, with fewer output tokens. Candidates: Streamlit (most familiar to models; rerun model
and `session_state` are confusing; `AppTest` for headless tests; no JSON routes), NiceGUI
(event-driven like Textual; FastAPI underneath, so JSON routes too; `User` test fixture),
Gradio (function in/out; suits form → result). Benchmark contracts that specify HTTP routes
still need Flask, so the likely split is a widget framework for CRUD, dashboards and
form → result, and Flask for JSON APIs and hybrids. Decide with a probe: the 9B and 35B
writing small apps in each, with and without kit notes.

Shared across kits: json-store and sqlite-store, validation helpers, table/report rendering.

## Evaluation

- `bench/kit-tui/`: 9 tasks, one per archetype, written blind.
- Conditions: `mw:env,guard` vs `mw:env,guard,kit`, on the 35B and the 9B; then
  textual-todo as an out-of-set check.
- Report pass rate and tests passed per archetype, output tokens, wall time, and kit
  failures (smoke false alarms, parts the model misused).

### First result: textual-todo, 2026-11-03 (3 runs each; not a clean test, it informed the notes)

| | tests passed | wall | output tokens |
|---|---|---|---|
| 35B `mw:env,guard` | 10, 1, 10 / 11 | ~420 s | ~19k |
| 35B `mw:env,guard,kit` | 10, 10, 10 / 11 | ~1070 s | ~37k |
| 9B `mw:env,guard` | 9, 1, 9 / 11 (all hit the 64k context) | ~1110 s | ~31k |
| 9B `mw:env,guard,kit` | 10, 10, 10 / 11 (1 hit the context) | ~1680 s | ~45k |

- The one failure in every run is the hidden-preference test (done items sorted to the
  bottom); no condition asked questions, so 10/11 is the ceiling here.
- The 1/11 runs crashed on a Widget constructor misuse: the kit's shell prevents this.
- The kit's extra cost is model-written tests: 35–67k chars of test files per 35B run
  (9B: ~140k) against 14–35k for the app. The notes and the headless_test part push
  "cover every scenario" and the model rewrites whole test files. Next: harness-owned
  contract scenarios, so the model supplies data, not test code.
