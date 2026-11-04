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
