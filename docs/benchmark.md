# lightness bench — spec v0

Goal: measure whether the harness makes a given model better, cheaper, or faster at genuinely
useful small Python projects. Same model, two conditions: **bare** (mini-swe-agent loop) vs
**lightness**. Later: big hosted models in both conditions.

## Task format (Harbor / Terminal-Bench compatible)

```
bench/tasks/<id>/
  instruction.md     # vague narrative + a short "Contract" section
  intent.md          # hidden: what the "user" actually wants (for the simulated user)
  task.toml          # category, difficulty, timeout, ports, judge rubric
  environment/       # requirements.txt or Dockerfile, seed files / seed repo
  tests/             # hidden: test.sh, test_*.py, e2e_*.py, fixtures
  solution/          # reference solution; oracle must pass 100%
```

**Two-tier specs.** The *contract* fixes only the seams tests need (entry point, CLI flags,
`create_app(db_path)`, `--json` output, a few `data-testid`s). Everything else is left vague on
purpose. Hidden tests check behaviour, never exact strings; tolerant matchers for "reasonable
assumption" checks.

**Simulated user.** The spec workshop and `ask_user` need someone to answer. Each task has a
hidden `intent.md` (preferences the narrative leaves out, e.g. "amounts in EUR, categories are
fixed, no login"). A fixed judge model answers questions from `intent.md` only, and says "no
preference" when it isn't covered. Some hidden tests check intent-only details, so asking the
right questions is rewarded. Also run every task in *no-user* mode (defaults policy) to measure
how much the workshop helps. The bare baseline gets the same answering channel if it asks.

## Runner

1. Copy `environment/` into a fresh workspace.
2. Run the agent (bare or lightness) against the same model endpoint, with wall-clock and token
   budgets. Agent never sees `tests/` or `solution/`.
3. Copy in `tests/`, run the verifier in a separate step, write reward + metrics.

Isolation: Docker (OrbStack/Colima), `--network none` for the agent except a local wheel
mirror; base image with Python 3.12, uv, pytest, httpx, Playwright+Chromium, Textual. Model
server stays on the host (`host.docker.internal`). Dev mode: per-task uv venv (fast, not for
reported numbers).

## Grading by category

- **Scripts / data:** hidden pytest against the CLI or contract functions, fixture inputs.
- **Web apps:** start server on a free port, poll health, httpx API checks (CRUD, persistence
  across restart, bad input) + Playwright flows via required `data-testid`s. No layout asserts.
- **TUI:** Textual `App.run_test()` Pilot. Tk: test the logic module, smoke-launch the GUI.
- **Repo edits:** fail-to-pass tests + the repo's own regression suite; flag files touched out of
  scope.
- **LLM judge (secondary only, never pass/fail):** fixed big model, 5 binary rubric items
  (spec coverage, sensible handling of vague parts, UX, code quality, usage docs), screenshots +
  code; 10% hand spot-check.

## Metrics (JSONL per run)

- Outcome: pass, test-pass fraction, regressions, judge score
- Cost: prompt/completion tokens, model calls, wall-clock, tok/s, $ for hosted
- Process: repair iterations, restarts, malformed outputs, context overflows, timeouts,
  give-ups, out-of-scope edits
- Workshop: questions asked, intent-only tests passed, assumptions that contradicted intent
- Variance: n=5 runs per task (T>0). Report pass@1 mean ± bootstrap CI, pass@5, pass^5
  (reliability). Paired per-task comparison. With ~25 tasks, deltas <10pp are noise.

## Tasks (26)

**Scripts / CLI**
1. `file-organizer` — sort dir by type/date; `--dry-run`; safe on collisions and symlinks
2. `md-notes-search` — index notes folder; ranked search, tag filter, `--json`
3. `dup-finder` — hash-based duplicates; hardlink/delete with dry-run default
4. `log-summarizer` — messy nginx log → "useful summary" (top-N, status, hourly)
5. `bulk-renamer` — pattern-template renames with an undo journal
6. `backup-rotator` — dated tarballs, daily/weekly retention from TOML, injectable clock

**Data**
7. `csv-cleaner` — bank export with mixed dates, currency strings, dupes → clean CSV + report
8. `receipts-to-ledger` — merge 3 differently-shaped CSVs, rule-file categorization
9. `json-to-sqlite` — normalize a JSON dump into tables; 5 query functions
10. `budget-report` — monthly charts (PNG) + HTML report from a ledger

**Small web apps (Flask/FastAPI + SQLite)**
11. `expense-tracker` — CRUD, categories, monthly totals, web UI
12. `notes-app` — markdown notes with search and tags
13. `url-shortener` — click stats, input validation
14. `habit-tracker` — streak logic with date edge cases
15. `recipe-scaler` — scale servings + unit conversion API
16. `kanban-board` — move cards between columns, persisted

**TUI / GUI**
17. `textual-todo` — add/complete/filter, JSON persistence
18. `tui-file-browser` — preview pane + fuzzy filter
19. `pomodoro-tui` — timer state machine, injectable clock
20. `tk-unit-converter` — logic module + GUI smoke launch

**Repo edits (seeded 300–1500 LOC repos with tests)**
21. `add-feature` — CSV export for the expense app
22. `bugfix` — pagination off-by-one from a vague bug report
23. `refactor` — split a 600-line script into a package, CLI behaviour unchanged
24. `add-tests` — test an untested module; mutation-score threshold
25. `migrate` — argparse → Typer (or sqlite3 → SQLAlchemy), behaviour preserved
26. `dependency-break` — fix app after a pinned library's breaking API change

**Calibration sets (borrowed):** Aider Polyglot Python subset (34) for the edit loop;
~30-task sample of BigCodeBench-Hard for library-heavy scripts.

## M0 starter subset (8)

`file-organizer`, `md-notes-search`, `csv-cleaner`, `json-to-sqlite`, `expense-tracker`,
`textual-todo`, `bugfix`, `add-feature` — one or two per category, enough to get a baseline
signal before building the harness.
