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

### Testing arms A/B: Haiku 4.5, kit-tui, 2026-11-04 (milestone 2)

Question: should the model write tests, and when? Three arms, chosen by `bench --tests`
(everything else identical, including the milestone-2 fixes below):

- **none (A):** notes say check the real app with the try command after each change; write
  tests only if the task asks.
- **first (B):** notes say write tests from the contract before the app, then build until they
  pass; the headless_test part is shown from the start.
- **after (C):** like none, but the first submit is refused with "write tests for the task's
  contract, run them, fix what fails, then submit" plus the headless_test part.

Setup: `mw:env,guard,kit`, Haiku 4.5 via Parley, the 9 blind kit-tui tasks × 3 runs per arm
(81 runs), step limit 150, wall limit 1800 s, each hidden test with its own 20 s timeout.
Each number is averaged over a sweep (one run of every task), then shown as the mean over the
3 sweeps with the min–max across sweeps. Batches:
`runs/kit-tui-20261104-150141-mw-env.guard.kit-tests.{none,first,after}-haiku-*`.
Reproduce with `scripts/arm_report.py none=… first=… after=…`.

| metric | none | first | after |
|---|---|---|---|
| hidden spec tests passed, % | 84.9 (78.5–94.6) | 91.0 (87.1–94.6) | 81.0 (74.2–89.2) |
| hidden intent tests passed, % | 16.7 (11.5–19.2) | 12.8 (11.5–15.4) | 20.5 (19.2–23.1) |
| runs passing every hidden test (of 9) | 0.0 (0.0–0.0) | 0.0 (0.0–0.0) | 0.0 (0.0–0.0) |
| output tokens per run | 18889 (14651–21236) | 22931 (21827–24185) | 28737 (26192–30162) |
| agent wall time per run, s | 630 (606–656) | 556 (525–595) | 743 (650–847) |
| steps per run | 86 (84–86) | 75 (73–76) | 97 (94–100) |
| steps after the last app change | 54 (45–64) | 34 (29–38) | 57 (51–68) |
| regressions caught (per sweep of 9) | 0.0 (0.0–0.0) | 0.0 (0.0–0.0) | 0.0 (0.0–0.0) |
| runs that hit the step or wall limit (of 9) | 0.3 (0.0–1.0) | 0.3 (0.0–1.0) | 1.0 (0.0–2.0) |
| infrastructure: empty replies per run | 14.5 (11.3–20.1) | 11.5 (10.4–12.4) | 20.3 (16.4–25.0) |
| infrastructure: calls ≥ 60 s (timed out and retried) per run | 0.07 (0.00–0.22) | 0.19 (0.11–0.22) | 0.19 (0.00–0.33) |

Output tokens per run by step kind (mean over all runs; time in s in brackets):

| kind | none | first | after |
|---|---|---|---|
| write:app | 7524 (50 s) | 6937 (53 s) | 8992 (67 s) |
| edit:partial | 3 (0 s) | 11 (1 s) | 7 (0 s) |
| write:test | 1929 (22 s) | 7421 (61 s) | 8870 (60 s) |
| edit:test | 0 (0 s) | 0 (0 s) | 16 (1 s) |
| run:try | 5480 (414 s) | 2977 (228 s) | 5166 (426 s) |
| run:pytest | 8 (1 s) | 386 (39 s) | 242 (19 s) |
| run:python-snippet | 1267 (30 s) | 2507 (56 s) | 2065 (42 s) |
| read:workspace | 804 (66 s) | 875 (71 s) | 721 (62 s) |
| other | 697 (39 s) | 695 (40 s) | 1075 (55 s) |

Per task: hidden spec tests passed (sum over runs) · intent · runs at a limit

| task | none | first | after |
|---|---|---|---|
| airport-lookup | 33/33 · 0/9 · 0 | 33/33 · 0/9 · 0 | 24/33 · 0/9 · 1 |
| bookmarks | 32/33 · 0/9 · 1 | 33/33 · 0/9 · 1 | 33/33 · 0/9 · 2 |
| csv-browser | 29/33 · 0/9 · 0 | 30/33 · 0/9 · 0 | 30/33 · 1/9 · 0 |
| json-viewer | 15/30 · 3/9 · 0 | 28/30 · 3/9 · 0 | 18/30 · 3/9 · 0 |
| lights-out | 19/27 · 4/9 · 0 | 26/27 · 0/9 · 0 | 19/27 · 5/9 · 0 |
| loan-calc | 33/33 · 2/9 · 0 | 31/33 · 4/9 · 0 | 29/33 · 5/9 · 0 |
| notepad | 33/33 · 0/6 · 0 | 33/33 · 0/6 · 0 | 33/33 · 0/6 · 0 |
| stopwatch | 12/24 · 1/9 · 0 | 8/24 · 0/9 · 0 | 17/24 · 0/9 · 0 |
| trip-split | 31/33 · 3/9 · 0 | 32/33 · 3/9 · 0 | 23/33 · 2/9 · 0 |

Run cost at Haiku 4.5 list prices (cache reads + uncached input + output; cache writes were not
logged yet): none ≈ $12, first ≈ $12, after ≈ $16 for 27 runs each.

**Findings**

- **first** scored the most hidden spec tests (91% vs 85% none, 81% after) with the fewest
  steps (75 vs 86 and 97), the shortest tail after the last app change (34 steps vs 54 and 57)
  and the shortest wall time. It spends tokens on tests (7.4k per run) and saves them on try
  runs (3.0k vs 5.5k). Its sweep range (87–95%) overlaps none's (79–95%), so with 3 runs
  this is a lead, not a settled result. Big per-task gains: json-viewer 28/30 vs 15/30,
  lights-out 26/27 vs 19/27; one loss: stopwatch 8/24 vs 12/24.
- **after** was the most expensive (28.7k output tokens, 743 s, 97 steps, ~$16) and scored
  lowest on spec tests. Asking for tests at the end mostly adds a test-writing phase; it caught
  little. It scored best on intent tests (21% vs 17% and 13%), but those are few (26 per sweep).
- **Regressions caught: 0 in every arm.** The model ran pytest 114 times in first and 58 in
  after; the pass → app change → fail pattern happened once, and the model then changed the
  test, not the app. The model's own tests here confirm, they don't catch.
- **No run passed every hidden test.** Intent tests (unstated preferences) stay low in all arms:
  no condition asks questions.
- Limits: the step limit bound in 1–2 runs per arm; the 1800 s wall limit bound once (after,
  1882 s). Raising the step limit to 150 left most runs submitting on their own (86/75/97 steps).
- Infrastructure noise, similar across arms: Parley's moderation guardrail blocked ~12–20
  requests per run (returned as empty replies and asked again), and ~0.1–0.2 calls per run
  stalled and were retried. One 15-minute Parley stall hit the smoke runs before the A/B.

**Recommendation (Haiku 4.5 alone):** first as the candidate default, to be confirmed on
Haiku 5.5. Drop **after**: it costs most and scores lowest. The Haiku 5.5 confirmation below
did not reproduce the lead; see its recommendation.

**Milestone-2 changes in effect for all arms:** per-test grader timeout (csv-browser was 0/0 on
every hosted model; it now grades normally); format-error message shows a try call instead of
the submit command (wording is a default, not settled); submit refused while the app crashes on
start; constructor params as a list with roles (data, input, clock, seed, plus `other` for
plain values such as lights-out's `board`, which none of the four roles fit); try_app fake clock
with `advance:S` (it starts at 1000, not 0: a clock at 0 trips `if self.started_at:` checks
that real monotonic time never triggers); start-check warnings for names Textual already uses.
Not covered: apps that call `time.monotonic()` directly instead of the injected clock.

**Generalization review.** Every kit text changed in this milestone, and why it holds for any
Textual app rather than one bench task:

| text | change | general because |
|---|---|---|
| `notes.md`, time bullet | read time only through the clock parameter; work out the display from it on each tick; random numbers from `random.Random(seed)`; don't wait long stretches with `set_timer` | Textual fact: timers count real seconds; applies to every timed or random app |
| `notes.md`, testing bullet | per arm, from `kit.toml [testing]` | a testing rule, no app-specific content |
| `kit.toml` names | `params` list with roles; `empty_value` / `sample_data` help reworded | describes constructor arguments of any app (files read, files kept, clocks, seeds, other values) |
| `try.md` | `--file` / `--file-text`, `advance:`, `wait:` is real time, the app's own params listed; dropped "don't write test files" | documents the tool; the params line is rendered from each app's own contract |
| `parts/headless_test.py` | rewritten around observed mistakes; neutral example app (named counters) | each item is a Textual or pytest fact (asyncio.run, focus, Input vs bindings, ListView rebuild, `_notifications`, fake clock) or a testing rule (expected values from the task) |
| shell template | renders every param; `# read only`, clock and seed comments; a param named like an App attribute is stored as `<name>_arg` | generated from the contract; the rename avoids a Textual clash for any app |
| harness messages | format error shows one try call; "Not submitted: the app crashes on start."; "Before submitting: write tests…" (arm after); clash warning "X sets self.Y, which Textual's Z already uses"; try_app's messages for `--data` with several files and `advance` without a clock | about the harness or Textual, never about a task |
| smoke check | warns on names that clash with Textual's App, Screen or Widget, computed from `dir()` at check time | reported cases (`_running`, `visible`) are examples; the check itself has no list of names |

None of these mention a bench task's fields, keys or file formats. The one task-shaped
datum is in this report's tables, not in any kit text.

### Confirmation: none vs first on Haiku 5.5, 2026-11-04

Same setup as above (code at `4cd2bbf`), `--model haiku55` (claude-haiku-5-5 via Parley),
none and first only, 9 tasks × 3 runs per arm (54 runs). Moderation blocks were asked again up
to 5 times per step. Batches: `runs/kit-tui-20261104-160452-mw-env.guard.kit-tests.{none,first}-haiku55-*`.

| metric | none | first |
|---|---|---|
| hidden spec tests passed, % | 94.6 (91.4–96.8) | 94.3 (84.9–98.9) |
| hidden intent tests passed, % | 33.3 (30.8–34.6) | 24.4 (15.4–30.8) |
| runs passing every hidden test (of 9) | 0.0 (0.0–0.0) | 0.3 (0.0–1.0) |
| output tokens per run | 13337 (11926–15380) | 14182 (10590–19062) |
| agent wall time per run, s | 437 (381–530) | 445 (240–679) |
| steps per run | 53 (46–67) | 60 (31–102) |
| steps after the last app change | 47 (40–60) | 53 (24–95) |
| regressions caught (per sweep of 9) | 0.0 (0.0–0.0) | 0.0 (0.0–0.0) |
| runs that hit the step or wall limit (of 9) | 1.7 (1.0–2.0) | 2.7 (1.0–5.0) |
| infrastructure: empty replies per run | 33.1 (28.8–35.6) | 22.4 (18.1–26.6) |
| infrastructure: calls ≥ 60 s (timed out and retried) per run | 0.07 (0.00–0.22) | 0.04 (0.00–0.11) |

Output tokens per run by step kind (mean over all runs; time in s in brackets):

| kind | none | first |
|---|---|---|
| write:app | 2048 (14 s) | 2144 (14 s) |
| edit:partial | 63 (1 s) | 31 (2 s) |
| write:test | 0 (0 s) | 618 (6 s) |
| edit:test | 0 (0 s) | 0 (0 s) |
| run:try | 5619 (312 s) | 3803 (200 s) |
| run:pytest | 0 (0 s) | 203 (24 s) |
| run:python-snippet | 497 (14 s) | 3259 (100 s) |
| read:workspace | 89 (7 s) | 168 (9 s) |
| other | 592 (59 s) | 778 (58 s) |

Per task: hidden spec tests passed (sum over runs) · intent · runs at a limit

| task | none | first |
|---|---|---|
| airport-lookup | 33/33 · 0/9 · 1 | 33/33 · 0/9 · 1 |
| bookmarks | 33/33 · 0/9 · 1 | 33/33 · 0/9 · 1 |
| csv-browser | 30/33 · 0/9 · 2 | 30/33 · 0/9 · 0 |
| json-viewer | 18/30 · 8/9 · 0 | 28/30 · 6/9 · 1 |
| lights-out | 27/27 · 6/9 · 0 | 27/27 · 6/9 · 3 |
| loan-calc | 33/33 · 6/9 · 0 | 22/33 · 4/9 · 1 |
| notepad | 33/33 · 0/6 · 0 | 33/33 · 0/6 · 0 |
| stopwatch | 24/24 · 3/9 · 0 | 24/24 · 0/9 · 0 |
| trip-split | 33/33 · 3/9 · 1 | 33/33 · 3/9 · 1 |

Run cost from the logged tokens (cache reads $0.01, cache writes $0.125, uncached input $0.10,
output $0.50 per MTok; cache rates assumed at the usual 0.1× / 1.25× of input): none $0.83,
first $0.85 for 27 runs each, about $0.03 per run (Haiku 4.5: ~$0.45).

**Findings**

- **The lead did not replicate.** Spec tests: none 94.6% (91–97), first 94.3% (85–99). first
  varied more between sweeps, scored lower on intent tests (24% vs 33%) and hit the step limit
  more often (8 runs vs 5).
- **One per-task difference repeats on both models: json-viewer** (first 28/30 vs none 18/30
  here; 28/30 vs 15/30 on Haiku 4.5). On Haiku 5.5, first lost loan-calc (22/33 vs 33/33).
- Haiku 5.5 beats Haiku 4.5 in every arm (spec 94–95% vs 81–91%, intent 24–33% vs 13–21%)
  with fewer steps (53–60 vs 75–97) and about a fifteenth of the cost.
- In first, Haiku 5.5 wrote little test code (0.6k tokens of test files and 34 pytest runs over
  27 runs, against 7.4k and 114 for Haiku 4.5); much of its work went through python snippets.
  Regressions caught were again 0.
- Steps after the last app change are high (47–53 of 53–60), partly because app edits made
  through python snippets aren't counted as app changes by `analyze_cost.py`; treat that row as
  an upper bound.
- Moderation blocks were higher than on Haiku 4.5 (22–33 per run, asked again up to 5 times).

**Recommendation:** keep **none** as the default. On Haiku 5.5, first costs the same, scores
the same on spec tests, lower on intent tests, and is less predictable; its Haiku 4.5 lead
looks like a model-specific effect. Worth following up: why first helps json-viewer on both
models (likely the tests pin the tree/detail contract early). Next confirmation is on the
local 35B and 9B, where the cost question doesn't arise.

### Look on the local 35B: none vs first, 2026-11-04 (4 tasks × 1 run)

A limited, one-run look, not a confirmation. `--model qwen35a3` (local llama-server, one slot),
code at `13a5b7d`. Tasks: json-viewer, loan-calc, stopwatch and airport-lookup. Batches:
`runs/kit-tui-20261104-{164803,174221}-mw-env.guard.kit-tests.{none,first}-qwen35a3-*`.

| metric (mean over 4 runs) | none | first |
|---|---|---|
| hidden spec tests passed, % | 95.0 | 95.0 |
| hidden intent tests passed, % | 8.3 | 8.3 |
| output tokens per run | 31091 | 23522 |
| agent wall time per run, s | 799 | 555 |
| steps per run | 60 | 42 |
| runs that did not submit | 2 (json-viewer ContextOverflow, stopwatch TimeExceeded at 1886 s) | 0 |
| test-file output tokens per run / regressions caught | 0 / 0 | 10096 / 0 |

| task | none | first |
|---|---|---|
| airport-lookup | 11/11 · 0/3 | 11/11 · 0/3 |
| json-viewer | 10/10 · 0/3 | 10/10 · 0/3 |
| loan-calc | 11/11 · 1/3 | 11/11 · 1/3 |
| stopwatch | 6/8 · 0/3 | 6/8 · 0/3 |

**Findings**

- **Scores are identical.** Both arms fail exactly the same hidden tests on every task
  (stopwatch: minutes format and pause/resume; json-viewer: all three intent tests).
- **first never blew up; otherwise it was slower.** Its lower mean wall time (555 s vs 799 s)
  comes entirely from the two runs none failed to submit (json-viewer context overflow at
  840 s, stopwatch wall limit at 1886 s). On the two tasks both arms submitted, first took
  about 2.7× as long (loan-calc 730 s vs 263 s, airport-lookup 686 s vs 269 s), mostly writing
  tests. With one run per task, the blow-ups may be noise; on Haiku 5.5 first hit limits more
  often, not less.
- The 35B matches Haiku 5.5 on spec tests for these tasks (95% vs 90% for Haiku 5.5 none on the
  same 4 tasks), but is far behind on intent tests (8% vs 47%).
- The "calls ≥ 60 s" row is left out: on the local server long calls are slow generation, not
  timeouts.

**Recommendation:** unchanged, keep **none** as the default. If the time and limit savings on
the 35B matter, the next step is 3 runs per task on these 4 tasks (about 4.5 hours locally).

### Checks arm (`--tests checks`), 2026-11-04

Why: on the 35B, writing pytest files cost about 13k output tokens per run (the whole file
written again 3–6 times at ~50 tokens/s) and caught no regressions. In this arm the harness
does the test work:

- **The harness's own checks**, from the kit's names alone, run after every change and cost the
  model nothing: every key the app binds works without crashing (at the start focus, on up to
  two focusable non-text widgets, and with nothing focused when the start focus takes text),
  with no data file and with the sample file; if a key saved a file, starting again leaves it
  as saved; and an hour on the fake clock doesn't crash. These are facts about any TUI app.
- **The model's checks** are one line each in `checks.txt`, in the try command's step syntax
  plus `expect:TEXT`, `expect-not:TEXT` and `expect-file:PARAM=TEXT` (format in
  `kits/tui/checks.md`). Each runs in a fresh app.
- After each change to the app or `checks.txt` (once the app starts), the harness runs both and
  reports what changed, marking checks that passed before and fail now. The first submit is
  refused while checks fail. Events: `kit.checks` (with `regressions`) and `kit.checks_refused`.

Other arms are unchanged except that the try command's `advance` now waits only for the app's
own timers (not Textual's, e.g. the Input cursor blink), which makes `advance` faster.

#### Screen: none vs checks on Haiku 5.5 (9 tasks × 1 run), 2026-11-04

Code at `c68dafc`, `--model haiku55`, one run per task per arm. Batches:
`runs/kit-tui-20261104-202430-mw-env.guard.kit-tests.{none,checks}-haiku55-*`.

| metric (mean over 9 runs) | none | checks |
|---|---|---|
| hidden spec tests passed, % | 98.9 | 98.9 |
| hidden intent tests passed, % | 30.8 | 30.8 |
| output tokens per run | 15252 | 10215 |
| agent wall time per run, s | 521 | 284 |
| steps per run | 79 | 31 |
| runs that hit the step limit | 3 | 1 |
| regressions the harness checks reported, after an app change / passing again later | – | 6 / 6 |
| cost for the 9 runs | $0.38 | $0.19 |

Output tokens by kind: checks spent 2.7k per run writing and editing `checks.txt` and 0.9k on
try commands; none spent 8.1k on try commands and 1.5k on python snippets.

**Findings**

- **Same scores, about half the time and cost.** Every task scored the same spec tests in both
  arms; intent tests moved by one on two tasks each way. Wall time fell even on runs that
  submitted (median 181 s vs 469 s): instead of trying the app by hand step after step, the
  model wrote its checks once and let the harness run them.
- **The first regressions caught in any arm.** In 3 of 9 runs an app rewrite broke checks that
  had passed (notepad: the quit-with-unsaved-changes dialog; stopwatch: a crash when time moved,
  found by the harness's own check; bookmarks: add-then-restart and cancel edit). All 6 passed
  again later. A fourth report (lights-out) followed a rewrite of `checks.txt`, not of the app;
  since `9d4f108` such reports no longer count as regressions.
- **The one limit run was a loop bug**, not the arm: bookmarks sent
  `cd . && echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT` 106 times and the loop only accepted the
  exact command. The same bug cost the Haiku 5.5 first arm loan-calc (131 such submits).
  Fixed in `a6ac561`: a leading `cd DIR &&` is accepted, and other commands containing the
  marker get a note saying how to submit. none's three limit runs were not this bug.
- No submit was refused: every run's checks passed by the time it submitted.

Next: the same screen on the local 35B (the reason for this arm), then 3 runs per task if it holds.

#### Screen: none vs checks on the local 35B (4 tasks × 1 run), 2026-11-04

qwen35a3 on the 4-task subset (json-viewer, loan-calc, stopwatch, airport-lookup), code at
`8b8828c`. Both arms were run fresh: the `advance` and submit fixes changed `none` too. Batches
`runs/kit-tui-20261104-{205419,212836}-mw-env.guard.kit-tests.{checks,none}-qwen35a3-*`.

| metric (mean per run) | none | checks | earlier none | earlier first |
|---|---|---|---|---|
| hidden spec tests passed, % | 95.0 | 92.5 | 95.0 | 95.0 |
| hidden intent tests passed, % | 8.3 | 33.3 | 8.3 | 8.3 |
| output tokens per run | 26559 | 19928 | 31091 | 23522 |
| agent wall time per run, s | 574 | 499 | 799 | 555 |
| steps per run | 38 | 53 | 60 | 42 |
| steps after the last app change | 13 | 30 | 21 | 22 |
| runs at a limit | 0 | 0 | 1 | 0 |

Per task, spec · intent: json-viewer 10/10 · 0/3 vs 10/10 · 2/3; loan-calc 11/11 · 1/3 vs
11/11 · 2/3; stopwatch 6/8 · 0/3 in both; airport-lookup 11/11 · 0/3 vs 10/11 · 0/3.

**Findings**

- **Faster, but less so than on Haiku.** checks was 13% faster and used 25% fewer output
  tokens than the fresh none run. Most of the gain came from writing the app fewer times
  (4.8k tokens vs 8.7k) and reading fewer files (1.9k vs 7.2k). Writing `checks.txt` cost 2.9k
  tokens (81 s) per run, and try commands went up (7.8k vs 5.7k).
- **The 35B did not use the arm as intended.** In all 4 runs it wrote the app first and
  `checks.txt` later (step 16–35), and it kept running try_app by hand after its checks passed.
  That is why steps after the last app change rose from 13 to 30. No regression was reported
  and no submit was refused.
- **checks passed more hidden tests in total: 41 of 52 vs 39 of 52.** json-viewer (12/13) and
  loan-calc (13/14) each missed only one test, against 10/13 and 12/14 under none. The gain is
  all in intent tests (4 of 12 vs 1 of 12). airport-lookup lost one spec test (10/14 vs 11/14),
  and stopwatch was the same (6/11). Every earlier 35B run, in any arm, got 1 of 12 intent
  tests, so this is the first time the score has moved. It is still 1 run per task.
- The fresh none run was faster than the earlier one (574 s vs 799 s) and had no blown runs.
  The earlier run had a ContextOverflow and a TimeExceeded; the `advance` fix likely helped.

### Single-run iteration on the local 35B, checks arm, 2026-11-05/06

Method (replaces full benches until runs are consistent): run one task live, watch each step
with `scripts/watch_run.py BATCH [N]`, and stop as soon as the model is stuck for 3 or more
steps. Fix what made it stuck (in the harness, kit text or try_app, never tuned to that
task), commit, then run a *different* task. A full bench comes only once every task completes
cleanly and efficiently. Command:

    LIGHTNESS_THINK=4096 .venv/bin/python -m lightness.bench.run --agent mw:env,guard,kit \
      --suite kit-tui --model qwen35a3 --tests checks --tasks TASK --runs 1

`scripts/run_stats.py BATCH...` prints the per-run numbers below. `LIGHTNESS_THINK` caps thinking per step (default: the server's 8192); 4096 was used from
`d038b54` on.

**Pass 1** (`c487024` → `4335020`, about 28 stopped runs): every task was run until it
finished without a stall, fixing as it went. **Pass 2** (`eee5787` → `3d0c884`): all 9 tasks
again on the fixed code, to see whether they now finish first time. Final runs of pass 2:

| task | spec | intent | wall s | steps | app rewrites | thinking cut off |
|---|---|---|---|---|---|---|
| airport-lookup | 11/11 | 0/3 | 134 | 8 | 2 | 0 |
| bookmarks | 11/11 | 0/3 | 753 | 15 | 4 | 1 |
| csv-browser | 7/11 | 0/3 | 155 | 9 | 3 | 0 |
| json-viewer | 10/10 | 1/3 | 597 | 17 | 5 | 1 |
| lights-out | 8/9 | 0/3 | 1086 | 28 | 4 | 1 |
| loan-calc | 11/11 | 1/3 | 254 | 7 | 1 | 0 |
| notepad | 11/11 | 0/2 | 256 | 8 | 1 | 0 |
| stopwatch | 6/8 | 0/3 | 711 | 10 | 5 | 1 |
| trip-split | 11/11 | 1/3 | 708 | 12 | 3 | 1 |
| **total** | **86/93** | **3/26** | **4654** | 114 | 28 | 5 |

All 9 submitted, none at a limit. Pass 1's final runs scored 88/93 spec, 3/26 intent, in
3313 s; each of those was the run right after that task's fixes. Only 5 of 9 tasks finished
first time in pass 2: json-viewer was stopped 4 times, trip-split twice, notepad and
stopwatch once each, each for a new stall that was then fixed (`4335020` … `3d0c884`).

**What made the 35B stuck** (one or more stopped runs each; the fix is in the commit log):

- *Wrong picture of the task.* A task naming Textual classified as a cli app; a file
  argument read as a data file when it was input (or the reverse); no `input.txt` to try the
  app with. Fixes: Textual in the task means tui; role help in kit.toml; `fill_input_files`.
- *Checks it could not write.* Quoting, steps glued with commas, a step used as the check
  name, `press:#id` instead of `click:#id`, unknown keys, file options naming a parameter the
  app doesn't have, `--file` given text instead of a path, `\n` inside `--file-text`. Fix:
  every line is linted before it runs, all mistakes are listed at once, each with the
  correct form. Three lint rules were too strict at first (bare `#id`, `.word`, lines copied
  from the dump) and made the model write workarounds; the rules now reject only real
  selectors.
- *State it could not see.* The dump didn't show Input classes (validity), empty widgets,
  Select options, the title, which grid cell had the cursor, tree rows, how to switch tabs,
  or SQLite contents. Each is now one line of the dump. A key that only moved a list cursor
  now says so.
- *Textual API guesses* (Tree `select_node` toggles, Select `placeholder`, TabPane mounting,
  `widget.classes.add`, `event.node`, web CSS, `ctrl+end` in TextArea, DataTable columns).
  Each guess cost 3+ steps of crash and retry. Fix: a cheat-sheet line checked against the
  installed Textual, plus readable errors: CSS errors show the bad line, an AttributeError
  lists the closest real names, and the start check lists every undefined name at once (ruff
  F821) instead of one crash per run.
- *Silence and loops.* An app change that moved no check got no report, so the model
  rewrote again; after all checks passed it kept running try_app by hand. Fixes: a one-line
  "fixed none, broke none" report, and after two such changes a pointer to suspect the checks
  themselves; nudges after three try commands in a row and after idle steps once all pass;
  a missing `checks.txt` is asked for before more app code.
- *A check that hangs* (an app stuck in a handler) used to time out the whole checks run.
  Fix: each check has its own 20 s limit (`TRY_CHECK_SECONDS`).
- *Lost thinking.* With an 8192-token budget the model drafted whole apps in its thinking,
  was cut off, and started again. Fixes: `LIGHTNESS_THINK=4096`, an env note to write code
  straight into files, and a harness note when thinking was cut off.

**Where the time goes now.** Steps are few (median 10) but slow: about 40 s each, nearly all of it
output. Across pass 2, thinking was 49% of output characters (219k) and commands 51%
(228k), and the commands are mostly whole-file rewrites: 28 app rewrites and about 37
`checks.txt` rewrites, no `sed` or patch edits at all. 5 of 9 runs still had thinking cut off
at 4096 tokens despite the note. The slow tasks (lights-out, bookmarks, trip-split,
stopwatch, json-viewer) are the ones that rewrote the app 3–5 times.

**Not yet looked at:** csv-browser lost 4 spec tests and stopwatch 2 although both
submitted normally, so their checks miss something the contract asks for; intent stays at
about 1 in 9.

**Next:** speed experiments, one variable at a time on 2–3 of the slow tasks: (1)
`LIGHTNESS_THINK=2048`; (2) steer edits toward small in-place changes instead of whole-file
rewrites. Then a third consistency pass over all 9, and the full 9 × 3 bench only once a
pass finishes every task first time.

### Speed experiment A: thinking budget 2048 vs 4096, 2026-11-07 (interim)

Method: the slow tasks at `LIGHTNESS_THINK=2048`, one run each, compared with their pass-2 run at
4096, using the same stall rule (stop at 3+ stuck steps, fix, rotate). `scripts/run_stats.py` now
also prints decode speed (`7586bae`). **Decode speed is a confounder:** on battery in Low Power
Mode the 35B decodes at ~27-33 tok/s, on AC at ~50-57 tok/s, and pass 2 had both. Wall times are
only compared at a similar tok/s; output tokens are compared always.

Completed runs (pass 2 at 4096 → this run at 2048):

| task | code | spec | out tokens | wall s (tok/s) | app rewrites | think cut | thinking chars |
|---|---|---|---|---|---|---|---|
| trip-split | `7586bae` (= pass 2) | 11/11 → 11/11 | 18.1k → 17.2k | 708 (32) → 734 (31) | 3 → 5 | 1 → 1 | 28.9k → 18.6k |
| stopwatch | `7586bae` (= pass 2) | 6/8 → 6/8 | 15.5k → 9.7k | 711 (27) → 418 (32) | 5 → 5 | 1 → 0 | 33.5k → 10.7k |
| bookmarks | `d343ab6` | 11/11 → 11/11 | 23.3k → 14.4k | 753 (50) → 419 (51) | 4 → 4 | 1 → 0 | 34.7k → 11.2k |
| lights-out | `06c90af` | 8/9 → 9/9 | 28.6k → 9.4k | 1086 (29) → 224 (53) | 4 → 2 | 1 → 0 | 58.0k → 12.1k |

Stopped runs: 9 (json-viewer 4 times at 2048, bookmarks twice, lights-out once; and two 4096
controls on the fixed code, lights-out and bookmarks). Each stop had a harness gap behind it,
fixed in `f61388d` … `3268916` (below).

**Findings.** At 2048 the thinking per step roughly halves and, in 3 of 4 completed runs, total
output drops by 37-67% with the same or a better spec score. Commands don't shrink: the model
spends the same on whole-file rewrites (trip-split rewrote the app 5 times instead of 3).
Thinking is still cut off in about half the runs (1 per run at most), so 2048 doesn't remove
cut-offs, it makes each one cheaper. But **the comparison is not clean**: bookmarks and
lights-out ran on code with this session's fixes, and json-viewer never finished at 2048 (4
attempts; the last stall, probing tree rows one try at a time past two nudges, followed a
thinking cut-off). Whether 2048 adds stalls can't be told from these runs, so the default stays
4096 until paired runs on the same code settle it.

**Stalls found and fixed** (each stopped a run; all generic to the tui category):

- 12 of 18 checks "not run" (lint errors), the report said only "4 of 18 pass", and the model
  rewrote the app twice: the summary now counts checks that didn't run and says an app change
  can't fix them (`f61388d`).
- Exploring tree keys one try at a time past the single tries nudge: the nudge now asks to
  write what was learned into checks.txt and repeats briefly on each further try (`76c6813`).
  Not enough on its own (json-viewer run 4 ignored it twice).
- A grid of cells that all render `.` while CSS classes hold the state was drawn as all dots;
  only classes 1-2 cells had were listed. The grid is now drawn by class when the text doesn't
  vary (`4d849aa`), and every cell of a class gets its own line, rarest class first (`1144ba1`),
  so `expect:"class on: #cell-0-1"` works with any number of lit cells.
- `widget.text = ...` on a Static silently does nothing (`b55c5f3`); a value parameter
  (`board=[...]`) once classified as a data file (`f981836`).
- List + modal apps: `list_actions`' async `refresh_view` vs `modal`'s sync callback led to
  `call_from_thread`, an unawaited call and `create_task` in turn. The modal part's callback is
  now `async def`, and the cheat sheet says where `call_from_thread` belongs (`55079ea`).
- Hand-counted `press:down,down,...` (up to 27) miscounted, and the model then changed the app's
  tree expansion to fit its checks: `press:down*15` repeats a key, and a step glued on with a
  comma gets a message naming the fix (`06c90af`).
- After all checks passed, running `try_app --checks` by hand for 3-4 steps (stopwatch,
  lights-out): that now gets "nothing new: submit or add a check" (`d343ab6`).
- A failing check's detail showed its last 15 lines, which a long tree dump filled, cutting the
  `FAILED expect...` line: it now starts at the first FAILED line (`023bd3b`).
- checks.txt rewritten byte-identically twice (meant as a one-line fix), with no report since
  nothing changed: an identical rewrite of the app or checks.txt is now said so (`3268916`).

**Not the harness:** stopwatch's 2 lost spec tests are rounding, not missing checks: the app
prints tenths with `:04.1f` (3.0625 → `00:03.1`) and the hidden tests expect truncation
(`00:03.0`, `10:00.0`). The contract only says "tenths", so the task is ambiguous there.

**Next:** experiment B (small in-place edits) as a switch, so B-off and B-on run on the same
code at 4096; the B-off runs double as A's 4096 controls.

### Speed experiment B: small in-place edits, 2026-11-07

Method: one switch, `LIGHTNESS_EDIT=1`, so B-on and B-off run on the same code (thinking at 4096).
Same stall rule. Three versions, each tried on 1-2 tasks before the next:

- **v1** (`33f2662`): `.lightness/kit/edit.py`, a SEARCH/REPLACE helper fed by a heredoc (each block
  must match exactly once, else nothing changes and the closest lines are shown; a .py file that
  compiled must still compile), a "Changing a file" section in the kit context, and checks.md /
  the thinking cut-off note pointing to it.
- **v2** (`fad3b35`): also a note after any whole-file write of the app or checks.txt that changed
  only a few lines ("That wrote all 126 lines of stopwatch.py again to change 12 of them...").
- **v3** (`8eecbf6`): a native `edit_file(path, old_text, new_text)` tool next to `bash`
  (exact-substring replace, must occur once). A call runs as `python .lightness/kit/edit.py --json`,
  so middleware and logs see an ordinary command.

| run | code | spec | out tokens | wall s (tok/s) | steps | app rewrites | edits |
|---|---|---|---|---|---|---|---|
| trip-split v1 | `33f2662` | 11/11 | 15.9k | 383 (54) | 10 | 3 | 0 |
| stopwatch v2 | `fad3b35` | 6/8 | 11.4k | 257 (58) | 11 | 4 | 0 |
| trip-split v3 | `a03beea` | 11/11 | 11.5k | 394 (55) | 16 | 2 | 7 |
| json-viewer v3 | `a7ccb67` | 10/10 | 5.1k | 116 (57) | 9 | 1 | 3 |
| lights-out v3 | `8c04a2c` | 9/9 | 25.6k (6.1k without the runaway) | 618 (48) | 8 | 2 | 1 |
| json-viewer off (control) | `a7ccb67` | stopped at step 9 | | | | | |

Also stopped with v3: bookmarks (step 12), stopwatch (step 9), lights-out (step 9); each for a
harness gap (below), not for an edit.

**Findings.**

- **Text doesn't move the habit; a tool does.** With v1 and v2 the 35B never once used the edit
  command: it fixed a one-line missing import by rewriting all of split.py, and v2's note fired
  three times in a stopwatch run without one edit. With v3's native tool it edited from the first
  fix on, in every run: 19 `edit_file` calls across 6 runs, all applied, none failed to match,
  no broken files. Qwen coder models are trained on a str_replace-style editor tool; a heredoc
  helper is a new habit, a tool call is an old one.
- **checks.txt is still mostly rewritten whole;** the app is edited. trip-split v3 edited
  checks.txt three times, the others rewrote it.
- **Cheaper, not always faster.** trip-split: 15.9k → 11.5k output tokens at the same speed, but
  wall time stayed ~390 s because it took 16 shorter steps instead of 10 (each step also pays for
  the checks run and prefill). json-viewer finished first time with v3 (9 steps, 116 s) while its
  B-off control on the same code stalled probing tree keys, but that's one pair.
- Not clean enough to call a measured speed-up, but no sign of harm (no failed or damaging
  edits, spec 30/30 on completed v3 runs), so the third pass runs with `LIGHTNESS_EDIT=1`.

**Stalls found and fixed during B** (generic to the tui category):

- `type:enter` typed the word "enter": the lint names `press:enter` (`a03beea`).
- A stopwatch showing the banked time instead of the running one: "after advance:10: (nothing
  changed)" read as "advance doesn't run the timers". After `advance:` the dump now says how far the
  clock moved, that the timers ran, and how often the app read the clock (`29932fd`).
- `--kw board=["#####", ...]` without outer quotes lost its inner quotes to the line split and was
  passed as a string: the lint catches a list/dict that no longer parses; and a class every grid
  cell has (an all-lit board) is now named, not dropped as structural (`a7ccb67`).
- Probing `press:right` on a tree: the tree header names its keys (`8c04a2c`).
- **A runaway:** one lights-out reply wrote `space,` 9466 times in a check line, 19.5k tokens in
  385 s (the largest real command in 724 calls was ~2.5k tokens). A command with a short piece
  repeated 200+ times is now not run and is collapsed in the transcript, and agent output is capped
  at the thinking budget + 8k tokens (`19b4505`).

**Next:** third consistency pass over all 9 tasks with `LIGHTNESS_EDIT=1 LIGHTNESS_THINK=4096`.

### Third consistency pass, 2026-11-07 (interim)

Method: all 9 tasks with `LIGHTNESS_EDIT=1 LIGHTNESS_THINK=4096`, run as one batch and watched live;
on a stall (3+ steps without progress) the batch is stopped, the cause fixed, and the batch
restarted with the remaining tasks and the stopped one moved to the end (so the next run is a
different task). The goal was every task finishing on its first attempt; it didn't get there.

| task | first attempt | code | spec | out tokens | wall s | steps | edits |
|---|---|---|---|---|---|---|---|
| airport-lookup | finished | `c0a6baa` | 11/11 | 6.5k | 171 | 9 | 0 |
| csv-browser | finished | `3f6bcb6` | 9/11 | 8.2k | 187 | 14 | 5 |
| trip-split | finished | `f67a3cb` | 11/11 | 11.6k | 342 | 16 | 9 |
| bookmarks | stopped (step 12, 13 on retry) | | | | | | |
| json-viewer | stopped (step 10); retry finished | `ab95cba` | **4/10** | 7.2k | 167 | 13 | 2 |
| lights-out | stopped (step 13, 9 on retry) | | | | | | |
| loan-calc | stopped (step 18, after all checks passed) | | | | | | |
| notepad | stopped (step 8) | | | | | | |
| stopwatch | stopped (step 9) | | | | | | |

3 of 9 finished first time (pass 2: 5 of 9), all at ~55 tok/s on AC, all well under pass 2's
times. Every stop had a new, generic cause:

- `--kw db_path=/tmp/...` for a file parameter: linted (`3f6bcb6`).
- An `edit_file` call that sent the whole file as old_text with empty new_text (meant as a submit):
  refused (`1b2b3ec`).
- Probing a tree one try at a time past two nudges (json-viewer, third run with this pattern): the
  5th try command in a row with nothing changed is now refused until something changes; a checks
  report against the untouched shell says the app isn't written yet (`50d5687`). Middleware can
  now refuse a command.
- `023bd3b` had cut the "#cell-2-2 can't be clicked: ... cut off" line that explains a FAILED
  click: lines naming a step's own problem are kept (`e867bf7`).
- "Let me submit the final output" followed by `cat app.py` (twice): notes that say "submit now"
  name the submit command (`66fa052`).
- `Static.update("[modified]")` renders empty (markup): the dump names text lost to a non-style
  [tag], and the cheat sheet says how to show brackets (`72df98c`).
- The same start crash after a change was silent (the start check only reported changes), with
  the cause (`self._start_time`, Textual's own) named once in a warning: it now says "still
  crashes the same way", warnings first (`f67a3cb`).
- `focus:#search press:a` typed "a" into the search box: the dump says the key went into the Input
  as text and bindings don't fire there (`ab95cba`).
- A list-of-rows board passed as one comma string: the try header shows each `--kw` value with its
  type (`25fcda7`).
- Validation checks typed `abc` into `Input(type="number")`, which drops those keys silently
  ("(nothing changed)"): the dump says which keys an Input with `type=`/`restrict=` dropped
  (`7a0c6ff`; loan-calc retry, stopped at step 11).

**Checks that pass while the contract fails.** json-viewer's retry passed all 13 of its checks
and only 4/10 spec tests: its #path showed `Path: $.regions`, and `expect:"$.regions"` matches any
part of the screen. csv-browser lost 2 spec tests the same way. checks.md now says how to check a
widget's exact text with the dump's own format, `expect:"#path: '$.a'"` (`2be8685`). This is the
"checks miss something the contract asks for" issue from pass 2; it is now the main gap in spec
score, not stalls.

**Edits in pass 3:** 16 `edit_file` calls in the 4 finished runs; one destructive call (above),
caught by the model the next step; no other failed or damaging edits.

**Retries (same pass, after the fixes above):**

| task | retry result | code | spec | out tokens | wall s | steps | edits |
|---|---|---|---|---|---|---|---|
| json-viewer | finished | `ab95cba` | 4/10 (exact text, above) | 7.2k | 167 | 13 | 2 |
| notepad | finished | `7a0c6ff` | 11/11 | 10.6k | 272 | 18 | 10 |
| stopwatch | finished | `7a0c6ff` | 6/8 (the rounding ambiguity) | 17.8k | 422 | 11 | 6 |
| bookmarks | stopped 3 times (steps 12, 13, 14) | | | | | | |
| lights-out | stopped 3 times (steps 13, 9, 14) | | | | | | |
| loan-calc | stopped twice (steps 18, 11) | | | | | | |

More stops and fixes in the retries: an Input with `type="number"` silently dropping typed keys
(`7a0c6ff`); the markup note's `markup=False` read as an `update()` argument, now said plainly
(`48fb4c0`); "every cell has class: cell" probed as a per-cell line (`e91e52f`).

**Where it stands.** 6 of 9 tasks have now finished on this code line (3 first time, 3 on a
retry), at 167-422 s each on AC power; bookmarks, lights-out and loan-calc have not finished in
pass 3. Every stop in the pass (14) had a cause the harness could make visible or prevent, and
each is fixed for the whole category, but each new run still finds a new one: the stalls are now
spread over many small, different gaps (a widget detail, a check-language corner, a Textual
quirk) rather than a few big ones. Two things stand out for next time:

- **Spec loss without stalls:** substring checks pass apps whose widgets show the wrong exact text
  (json-viewer 4/10). The exact-text form (`2be8685`) is untested in a run yet.
- **"Say submit, do something else":** twice the model announced a submit and emitted another
  call; `66fa052` names the command in the notes, untested in a run yet.

**Next:** a fourth pass from `e91e52f` over all 9 with the same settings, the stall rule, and the
same batch method; the full 9 × 3 bench only after a pass where every task finishes first time
(ask the user first).

### Fourth consistency pass, 2026-11-08

**Method.** All 9 tasks as comma-separated `--tasks` batches, `LIGHTNESS_EDIT=1 LIGHTNESS_THINK=4096`,
`--tests checks`, qwen35a3 on AC power, watched step by step under the stall rule. On a stall the
batch was stopped, the cause fixed for the whole category and committed, and the batch restarted
with the remaining tasks and the stopped one last. Before the pass, every hidden spec failure of
passes 2 and 3 was read to separate spec ambiguity from model mistakes. Since kit files are copied
per task, a fix lands only in later tasks of the next batch, so the rows below come from three code
points (column "code").

**Spec fixes (bench tasks).**

- stopwatch lost the same 2 tests in all 4 earlier runs: the app rounded tenths (3.06 s →
  `00:03.1`), the tests cut them. The contract now says tenths are cut, not rounded (`f05a3ae`).
  In pass 4 the model wrote cut-tenths checks and passed both tests.
- trip-split: "enter adds the name and clears the input; blank input adds nothing" left open
  whether a blank entry is cleared; the hidden test expects it. Now said (`7967fc3`).
- csv-browser's `sort_by` test helper pressed `right` until the cursor reached the column, forever
  when the table had a row cursor: 4 tests timed out (20 s each) in every csv-browser run since
  11-06. It now gives up after 20 presses and fails in ~1 s with a message; the oracle still
  passes 14/14 (`8898f3c`).
- loan-calc's zero rate is left as is: the formula is undefined at 0, but that case is tested only
  as an intent test (the user would expect interest-free), on purpose.

**Results.**

| task | first try | code | spec | intent | steps | wall s | out tokens |
|---|---|---|---|---|---|---|---|
| lights-out | finished | `322a96e` | 8/9 | 0/3 | 9 | 273 | 10.9k |
| stopwatch | finished | `322a96e` | 7/8 | 0/3 | 12 | 198 | 6.1k |
| notepad | finished | `bc6883f` | 11/11 | 0/2 | 6 | 82 | 2.9k |
| csv-browser | finished | `bc6883f` | 9/11 | 0/3 | 7 | 163 | 6.7k |
| airport-lookup | finished | `bc6883f` | 10/11 | 0/3 | 11 | 185 | 6.6k |
| trip-split | finished | `bc6883f` | 10/11 | 1/3 | 9 | 461 | 15.8k |
| loan-calc | finished | `bc6883f` | 11/11 | 1/3 | 10 | 260 | 9.8k |
| bookmarks | finished | `bc6883f` | 10/11 | 0/3 | 13 | 588 | 14.1k |
| json-viewer | stopped 3 times (steps 14, 14, 18) | | | | | | |

8 of 9 finished on their first attempt in this pass (pass 3: 3 of 9), including the three that
never finished in pass 3 (bookmarks, lights-out, loan-calc). Spec: 76/83 on the 8 finished.
loan-calc and bookmarks were each stopped once early (steps 3 and 10) before their counted run.

**Stops and fixes.**

- loan-calc wrote `expect:"$#payment"` and `expect-not:"$"`: my exact-text tip's example was a
  JSONPath (`$.a`), and the model copied the `$` as syntax. Neutral example (`a14cf24`).
- bookmarks did `result = await self.push_screen(dialog)`, which is always None: every add saved
  nothing, and 3 try steps went to the enter handler. The start check now warns (`322a96e`); in
  the counted run the model wrote the same line, read the warning, and switched to a callback.
- json-viewer wrote `expect:"#path '$'"` (no colon), later `expect:"#path: $"` (no quotes), for 3
  steps each: the failure now says the screen has `#path: '$'` and to write it so (`48ae9bf`,
  `10c8477`). The exact-text form itself worked: it caught the `Path: $` prefix that cost pass 3
  six spec tests, and the model fixed the app.
- json-viewer annotated with `Tree.Node` (no such thing) in all 3 runs and fixed it one crash per
  step: the start check now lists every line using a missing class attribute (`c0dfae3`), and the
  cheat sheet names `TreeNode` (`b5e38d8`). It also rebuilt each node's path from labels and
  parents, crashing on None; the tree part says to put the path in `node.data` (`636ca39`).
- json-viewer's last stop: 6 steps at 11/18 of its own (wrong) checks, going try, try, `cat`, edit,
  try, try; each `cat` reset the three-tries nudge. A command that changes nothing no longer
  resets it (`4d91a3b`).

**Spec loss in finished runs, by cause, and the fix for each** (none of these stalled a run):

- lights-out drew from `random.choice` after making `self.rng = random.Random(seed)` (also in pass
  2): built-in check, the same seed gives the same start (`c9a6c0d`).
- stopwatch's pause showed `00:00.0` right after the clock moved (also in pass 3): try's
  `advance:` lets the timer tick, so no check could see it. The timer part and notes say a key that
  changes what's shown updates the screen itself (`bc6883f`).
- bookmarks' Cancel button was cut off by its dialog (also in pass 2); the model's check focused it
  and pressed enter, as try's click note suggested. Built-in check, every button on every screen a
  key opens can be clicked; the note no longer suggests focus+enter (`7086603`).
- airport-lookup saved a favourite but didn't redraw the ★: checks.md says a key that changes
  saved data gets a file check and a screen check (`ec498d9`).
- csv-browser used a row cursor (every run since 11-06) though the task asks for a cell cursor: the
  table header names the cursor kind ("row cursor: left/right do nothing", `6318a83`).
- Also: the grid dump names the first and last cell id (`35853e5`); a SyntaxError now shows its
  file:line, line and caret instead of just "invalid syntax" (`ee1a87c`).

All 9 references pass the new built-in checks; the seed and button checks fail the pass-4 apps
that lost those tests.

**Edits.** Every run used `edit_file` for most changes; whole-file rewrites still happen after a
missed edit or for larger reworks (trip-split, lights-out, json-viewer).

**Intent** stays low (2/23 on the 8 finished): the hidden intent tests (undo, hours format, newest lap first, numeric
sort) ask for things the contract doesn't, and the checks arm only covers the contract.

**Next:** a fifth pass from `b5e38d8` over all 9, json-viewer last, with no fixes expected to land
mid-pass, to see first-try consistency on one code version. The full 9 × 3 bench only after a pass
where every task finishes first time (ask the user first).

### Fifth consistency pass, 2026-11-08

**Method.** As pass 4: all 9 tasks in batches from `cbb0892`, `LIGHTNESS_EDIT=1 LIGHTNESS_THINK=4096`,
`--tests checks`, qwen35a3 on AC, the stall rule, fixes between batches (column "code" is the code a
row ran on).

| task | first try | code | spec | intent | steps | wall s | out tokens |
|---|---|---|---|---|---|---|---|
| trip-split | finished | `cbb0892` | 7/11 | 0/3 | 21 | 447 | 14.5k |
| airport-lookup | finished | `cbb0892` | 11/11 | 0/3 | 16 | 512 | 19.5k |
| notepad | finished | `d750f8a` | 11/11 | 0/2 | 6 | 136 | 5.7k |
| loan-calc | finished | `d750f8a` | 11/11 | 2/3 | 12 | 322 | 12.5k |
| bookmarks | finished | `d750f8a` | 10/11 | 2/3 | 22 | 613 | 17.2k |
| stopwatch | finished | `d750f8a` | 7/8 | 0/3 | 9 | 389 | 14.5k |
| lights-out | finished | `d750f8a` | 9/9 | 2/3 | 14 | 269 | 10.4k |
| json-viewer | stopped (step 10); retry finished | `e02fc57` | 10/10 | 0/3 | 14 | 503 | 18.8k |
| csv-browser | stopped (steps 10, 8); third run finished | `e02fc57` | 9/11 | 0/3 | 9 | 168 | 6.6k |

7 of 9 finished on their first attempt (pass 4: 8 of 9, pass 3: 3 of 9); all 9 finished within the
pass. Spec on the first-try runs 66/72; with the two retries 85/93. json-viewer reached full spec for
the first time (pass 3: 4/10; pass 4: never finished). Intent 6/26. Runs got longer than in pass 4
(airport-lookup 185 → 512 s): the model now writes 15-30 checks and often rewrites checks.txt whole.

**Stops and fixes.**

- csv-browser: sort checks pressed `right` on a row-cursor table, 4 steps at 14/16. A key that does
  nothing on a table (left/right on a row cursor) now says so, and such step notes are kept in a failing
  check's report (`d750f8a`). The root cause was the kit itself: the DataTable part and the cheat sheet
  both showed `cursor_type="row"` as the way to make a table; they now explain the choice (`8ba3eff`).
- json-viewer: 30 checks pressing `right` to open tree nodes, stuck at 12/30 for 4 steps. The same
  note for a Tree, one key at a time (in `press:right,down` the down hid the dead right), and step
  notes now survive try's own cut of a long failing check (`914d907`).
- csv-browser retry: a 15-row table filled the failing check's 15-line screen, so `#count` (what the
  expect was about) never showed; 3 steps of CSS edits looking for it. The report now keeps every
  widget line and cuts table/list/tree rows first (`e02fc57`).

**Spec loss in finished runs, and the fix for each.**

- trip-split's Add button (in the Expenses tab) was cut off by its container; the button check from
  pass 4 skipped it because hidden tabs take no space. It now shows each tab in turn (`2f4d9bc`).
- stopwatch lost the pause test for the third pass running; the text added in pass 4 (`bc6883f`) did
  not change what the model wrote. Built-in check: for pairs of keys with 3 s between, the screen must
  be the same whether or not a timer tick came first (`f3c9325`).
- bookmarks' search left all rows shown for `PYTHON`; its checks only expected the one match:
  checks.md now says a filter check needs two records and both sides (`af07fb0`).
- csv-browser: the row cursor above (2 sort tests now fail fast, from `8898f3c`).

**Other fixes.** loan-calc made two app changes at 0/16 with new failure text each time, so the
"suspect the checks" nudge (which waited for identical results) never came; it now counts app changes
that pass no more checks. Its expected payments were mental arithmetic (798.82 for 536.82); checks.md
says to compute numbers with a command (both `af07fb0`; the model found that itself the next step).
The exact-text hint also covers the screen's quotes around quoted text (`c3102ac`).

All 9 references pass every built-in check after these changes (seed, buttons in every tab, keys
without a tick).

**Next:** a sixth pass from `c3102ac`. 7 of 9 first-try is short of the bar for the full 9 × 3 bench
(every task first time); both misses this pass were the row cursor and tree keys, now addressed at the
source.

### Sixth consistency pass, 2026-11-08

**Method.** As passes 4-5, from `c3102ac`; fixes between batches.

| task | first try | code | spec | intent | steps | wall s | out tokens |
|---|---|---|---|---|---|---|---|
| json-viewer | finished | `c3102ac` | 10/10 | 1/3 | 16 | 344 | 13.7k |
| csv-browser | finished | `c3102ac` | 10/11 (11/11 on the fixed test) | 0/3 | 10 | 111 | 4.1k |
| stopwatch | finished | `c3102ac` | 8/8 | 0/3 | 13 | 454 | 16.5k |
| trip-split | finished | `c3102ac` | 11/11 | 1/3 | 9 | 204 | 6.7k |
| bookmarks | finished | `c3102ac` | 11/11 | 0/3 | 9 | 443 | 12.7k |
| lights-out | finished | `c3102ac` | 9/9 | 1/3 | 9 | 161 | 7.0k |
| notepad | finished | `bf8b7f1` | 8/11 | 0/2 | 8 | 125 | 4.9k |
| airport-lookup | finished | `bf8b7f1` | 11/11 | 0/3 | 7 | 126 | 4.4k |
| loan-calc | stopped (step 8); retry finished | `bf8b7f1` | 10/11 | 1/3 | 10 | 192 | 7.7k |

8 of 9 first try, all 9 within the pass. Spec 88/93 (89/93 counting csv-browser on the fixed test),
the best so far; json-viewer, stopwatch (the pause test, lost in passes 3-5) and csv-browser's sort
tests all pass now. Runs were shorter than in pass 5 (7-16 steps, 111-454 s).

**Stop.** loan-calc spent 4 steps grepping try_app.py for an `expect-class` step to check `-invalid`:
checks.md now says CSS classes are on the widget's line and are checked with `expect:` (`bf8b7f1`).

**Fixes between batches.**

- csv-browser's spec test for sorting a date column wanted the first four values non-empty, which
  depends on where empty cells sort; that is the intent test's question, not the contract's. The spec
  test ignores empty cells now (oracle 14/14; `585a14f`).
- The shell imports `on` (4 runs crashed on `@on` without it; `5ffc0f7`).
- `expect:"#id 'text'"` without the colon is taken as `#id: 'text'`: json-viewer dropped the colon in
  nearly every run and kept it dropped after the hint named the right form (`8994010`).
- **A false pass:** notepad's `status.update("[modified]")` showed nothing (markup), and its check
  `expect:"modified"` passed on the dump's markup note, which quotes the lost text; 3 spec tests
  failed. Expects no longer match the harness's own notes (`c8b2acd`).

**Remaining spec loss:** loan-calc accepted 2.5 years (the contract asks for a whole number; its checks
never tried a fraction); notepad's false pass above.

**Next:** a seventh pass from `c8b2acd`. If every task finishes first time, the full 9 × 3 bench
(asking the user first).

### Seventh consistency pass, 2026-11-08

**Method.** As before, from `c8b2acd`; fixes between batches.

| task | first try | code | spec | intent | steps | wall s | out tokens |
|---|---|---|---|---|---|---|---|
| json-viewer | finished | `0f0bec2` | 10/10 | 1/3 | 23 | 377 | 16.3k |
| csv-browser | finished | `0f0bec2` | 11/11 | 0/3 | 13 | 268 | 10.8k |
| bookmarks | finished | `0f0bec2` | 11/11 | 0/3 | 16 | 779 | 16.6k |
| stopwatch | finished | `0f0bec2` | 8/8 | 0/3 | 9 | 259 | 8.5k |
| airport-lookup | finished | `0f0bec2` | 11/11 | 0/3 | 11 | 212 | 7.4k |
| lights-out | finished | `0f0bec2` | 9/9 | 2/3 | 20 | 679 | 27.1k |
| trip-split | finished | `0f0bec2` | 9/11 | 0/3 | 17 | 375 | 13.0k |
| loan-calc | stopped (step 14); retry finished | `0f0bec2` | 11/11 | 1/3 | 9 | 267 | 10.2k |
| notepad | stopped (step 12); retry finished | `0f0bec2` | 11/11 | 0/2 | 8 | 141 | 5.0k |

7 of 9 first try, all 9 within the pass; spec 91/93, the best yet (every task at full spec but
trip-split). Intent 4/26. Some runs got long (lights-out 679 s, bookmarks 779 s): many whole-file
rewrites of checks.txt and long thinking per step.

**Stops.** Both were API look-ups, not loops: loan-calc's own validator called `self.error()` and then
probed the Validator API for 3 steps (the crash hint already named `failure`/`success`); notepad probed
TextArea for 4 steps to move the cursor in code. The cheat sheet now shows both (`74c3dcd`,
`0f0bec2`). Each probe was 2-4 s, so these stops cost little time, but by the stall rule they count.

**Fixes.**

- json-viewer wrote every check as a comment (`# check: ...`) and the report said "0 of 0 checks
  pass ... submit now"; it now says what a check line is and never says submit (`891bf0c`).
- A check line argparse rejects (an option after the steps) showed a raw usage dump; it is a "not run"
  line mistake now (`16dc1f1`).

**Spec loss:** trip-split's balances table crashed (`Widget.remove(x)`) once an expense was added; its
checks never looked at balances after adding one. A built-in "show each tab with the sample file" check
was tried and dropped: that crash only happens after an add.

**Where it stands.** Over passes 5-7 spec went 85 → 88 → 91 of 93, and every task now finishes within
a pass. The first-try misses in passes 6 and 7 are all short API look-ups (CSS class checks, Validator,
TextArea cursor) the cheat sheet didn't cover; each now does. Whether a burst of 2-4 s probes should
count as a stall is a judgement call for the user; under the rule as written, no pass has had all 9
first-try yet (best: 8 of 9 in passes 4 and 6).

**Next:** the user decides between another pass and the full 9 × 3 bench.

### Full bench, 9 tasks × 3 runs, local 35B, checks arm, 2026-11-08

**Method.** One batch, `--tasks all --runs 3`, code at `9517d15`, `LIGHTNESS_EDIT=1
LIGHTNESS_THINK=4096`, batch `runs/kit-tui-20261108-184049-mw-env.guard.kit-tests.checks-qwen35a3-70576`.
No stops: every run went to the end. After each run the logs were audited for anything that would make
the result useless (exit status, verify errors or timeouts, test counts against the expected ones,
failed model calls, harness tracebacks, repeated commands, submitting with failing checks), and every
failing hidden test was read. **Power:** the first ~10 runs ran on battery at ~30 tok/s instead of
~53, so wall times of airport-lookup, bookmarks, csv-browser and json-viewer/0 are not comparable with
earlier passes; compare output tokens.

**Audit.** All 27 runs submitted; no verify error, timeout, failed model call or harness traceback,
and every run has the expected test count. One hidden-test bug was found and fixed (`25eb8e5`):
loan-calc's garbage-input tests typed letters into the principal and required `-invalid`, but an
`Input(type="number")`, which our own `parts/input_form.py` teaches, refuses the letters and stays
empty, which the contract allows. The oracle still passes 14/14, and the three loan-calc runs were
re-scored from their saved workspaces into `results.rescored.jsonl` (run 0: 10/11 → 11/11 spec);
`results.jsonl` is left as run.

Spec and intent per run (spec without the intent tests; rescored):

| task | spec | intent | wall s | out tokens |
|---|---|---|---|---|
| airport-lookup | 10/11 10/11 11/11 | 0 0 0 /3 | 209 369 638 (battery) | 4.6k 7.7k 14.7k |
| bookmarks | 11/11 9/11 11/11 | 0 0 0 /3 | 1121 962 1449 (battery) | 22.7k 20.6k 22.0k |
| csv-browser | 11/11 11/11 9/11 | 0 1 1 /3 | 175 395 1270 (battery) | 3.9k 10.3k 35.0k |
| json-viewer | 10/10 3/10 6/10 | 2 1 0 /3 | 1149 433 190 | 24.0k 16.1k 8.0k |
| lights-out | 9/9 8/9 9/9 | 2 1 1 /3 | 217 349 299 | 9.1k 15.0k 12.8k |
| loan-calc | 11/11 11/11 11/11 | 1 1 1 /3 | 255 225 270 | 10.7k 9.1k 10.7k |
| notepad | 11/11 11/11 11/11 | 0 0 0 /2 | 190 445 106 | 6.9k 20.6k 3.7k |
| stopwatch | 8/8 8/8 8/8 | 0 0 0 /3 | 1072 319 603 | 44.2k 11.0k 23.1k |
| trip-split | 11/11 11/11 11/11 | 1 1 1 /3 | 573 782 315 | 18.5k 25.4k 10.2k |

**Totals:** spec 261/279 (93.5%), 20 of 27 runs at full spec; intent 15/78. Four tasks were at full spec
in all three runs (loan-calc, notepad, stopwatch, trip-split).

**Where the spec loss is.** Every lost spec test is a real app bug, and in every case the model's own
checks passed while the bug was there: the checks could not fail.

- json-viewer/1 (3/10): the app used id `detail-pane` where the task says `detail`; every check
  used the app's id. json-viewer/2 (6/10): `#detail` showed `repr` (`'Bob'`), not JSON; five checks only
  expected `#detail` (it exists) and the string check matched the tree label.
- csv-browser/2 (9/11): a sync `action_sort` called the async `refresh_view()` without `await`, so
  sorting never happened; the sort checks only expected the row count. The run also spent ~15 steps
  probing the DataTable API (`cursor_coordinate.column_key`, which doesn't exist).
- bookmarks/1 (9/11): an unscoped App `on_input_changed` also caught the add dialog's Inputs, so the
  last URL typed became the search filter; the add checks only ran from an empty store.
- lights-out/1 (8/9): with no board the app never drew a random puzzle at start; the built-in seed
  check passed because an all-dark board is the same every time.
- airport-lookup/0,1 (10/11): `#detail` didn't follow the highlight.

**Slow runs.** stopwatch/0 (38 steps, 44k tokens) spent ~11 min on lap checks timed exactly on a
tenth: float clock math lands just under (10.3 s → `00:10.2`) and truncation flips them; it ignored
three "stop exploring" nudges. csv-browser/2 is the other (above).

**Next, all general (none tuned to a task):**

1. A built-in check that every widget id the task names exists in the app, naming the near miss
   (`#detail-pane`).
2. Checks that can't fail: a note when an expect is only `#id`, when a bare text expect matched a widget
   other than the one the check is about, and when a press step changed nothing on screen.
3. A smoke lint for a call to an `async def` method of the same class that is never awaited.
4. Cheat sheet: messages from a modal's widgets bubble to the App, so scope handlers
   (`@on(Input.Changed, "#search")`).
5. Seed built-in: a note when seeds 1, 2 and 3 all give the same start.
6. checks.md: advance timers by values clear of a display boundary (3.06 s, not 3.0).
