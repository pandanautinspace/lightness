# M0 trajectory analysis: where the bare agent goes wrong

2026-11-02. The data is 16 Qwen3.6-35B-A3B runs (8 `bare`, 8 `bare-ask`, 549 turns) plus one
Qwen3.8-27B run (`file-organizer`, 8 turns). There is one run per task, so every rate is from a
small sample.

- "Measured" means counted by `scripts/analyze_trajectories.py`, which uses heuristics on the
  command text and its output.
- "Inferred" means my reading of the transcripts. I read all the failing runs in full.
- Hidden-test scores are the regraded ones from the [M0 diagnostic](m0-bare-diagnostic.md).

## 1. Does the model get dumber as the transcript grows?

**Not measurably, up to about 55K tokens.** Other things produce the impression.

### Measured

All 17 runs pooled, 573 actions. Each run's turns are split into thirds; separately, actions
are grouped by prompt size at that turn.

| | early | mid | late | <8K | 8–16K | 16–32K | >32K |
|---|---|---|---|---|---|---|---|
| actions | 206 | 188 | 179 | 167 | 182 | 180 | 44 |
| failing action (rc≠0 or error text) | 21% | 21% | **11%** | 19% | 18% | 18% | 20% |
| exact repeat of an earlier command | 1% | 9% | 8% | 1% | 9% | 7% | 7% |
| idle repeat (no file edited since the last time) | 2% | 4% | 3% | 2% | 5% | 3% | 2% |
| repeat of a command that failed before | 2% | 3% | 3% | 2% | 3% | 1% | 9% |
| thinking per turn, median / mean (chars) | 97 / 653 | 116 / 516 | 123 / 361 | 91 / 703 | 127 / 437 | 126 / 420 | 120 / 545 |
| thinking 6-gram overlap with earlier turns | .02 | .05 | .05 | .02 | .04 | .04 | .10 |

Failure rates within the same action kind, early → late:

| Action kind | Early | Late |
|---|---|---|
| inspection commands | 15/98 | 4/33 |
| app runs | 8/35 | 6/40 |
| python snippets | 10/20 | 7/39 |
| file writes | 2/33 | 2/21 |

- **Errors cluster early**, while the agent probes the environment and writes first drafts.
- **Late repeats are mostly deliberate.** Exact repeats rise, but idle repeats stay flat. The
  extra repeats are re-runs after an edit and re-reads of files.
- **Thinking doesn't grow or loop.** The duplicate-sentence ratio is 0 in every bucket.
- **The >32K band is too small to read.** It is 44 actions from 4 runs, and its
  repeat-of-failed hits are mostly legitimate re-runs after fixes (expense-tracker turns 21, 24).

### Inferred, from the longest runs

- **textual-todo (bare, 70 turns): one genuine case of forgetting.**
  - Turn 19 learns "you can't reuse a Textual app across multiple `run_test` contexts".
  - Turn 65 repeats the mistake, and turn 66 re-derives the same diagnosis almost word for word.
  - Turn 68 repeats turn 22's shared-test-file mistake.
- **expense-tracker (bare).** The late turns are its most efficient. At turns 22–24 it reads the
  server log, makes a one-line `sed` fix, and gets 53/53 passing.
- **expense-tracker (ask).** The worst confusion is mid-run (turns 16–26, 19–23K context). A
  server left behind by a timed-out command kept serving old code. The agent guessed "Python
  caching" before it found the PID.

**Confounds.** Late turns are a different mix of actions. Only runs that hit hard sub-problems
get long. Only one run passed 50K. So this cannot rule out degradation at larger contexts or on
the 27B.

**What looks like "dumber over time":**

1. **A verification tail.** 205 of 549 turns (37%) come after the last edit to a non-test source
   file. In `file-organizer` that is 22 of 25 turns. These turns re-run checks that already pass
   and `cat` files. None of them caught a hidden failure.
2. **Rabbit holes.** In textual-todo, turns 26–43 read Textual's source on the theory that
   "ListView consumes space". The real cause was `index is None`, found at turn 46.
3. **Hidden environment state**: the stale server above.

**A direct test.** Replay a mid-run decision with the full history and with a rebuilt short
context.

## 2. Other measurements (16 runs on the 35B)

| Metric | Value |
|---|---|
| Failing actions | 101. 22 are in textual-todo, mostly its own throwaway test scripts |
| Command timeouts | 7 in 3 runs, all a Flask server started with `&`. About 14 min of wall time |
| Heredoc file writes | 87, up to 6 per file. The 28K-char `app.py` was rewritten 3× to fix one function each time. 2 rewrites of `todo.py` were byte-identical (turns 14, 60) |
| `sed -i` | 8 uses. 1 GNU-form failure (bugfix turn 18) and 1 silent no-op from `\n` in the pattern (ask/md-notes-search turn 40); each was fixed the next turn |
| Truncated outputs | 2, harmless |
| pytest runs / ad-hoc runs of its own code | 24 / 161 |
| First command probes a path that doesn't exist | 14/16 runs (`/app`, `/home/user`, `/testbed`, `/workspace`, `/`) |
| `ask_user` calls | 0 |

Thinking is short: a median of about 100 characters per turn. A few large blocks, all early,
take most of the thinking tokens:

- ask/textual-todo turn 8: 30K characters, drafting the app it then writes out again in the
  command;
- bugfix turn 13: 11.6K characters, restating the same argument 3–4 times;
- 27B turns 2, 5 and 7: 32K, 21K and 11K characters.

## 3. Failure-mode taxonomy

Frequency is over the 16 runs on the 35B. "Hidden" means the mode caused a hidden-test
failure.

| Mode | Freq. | Example | Impact | M1 mechanism |
|---|---|---|---|---|
| **Self-confirming verification**: test data mirrors the implementation's assumptions; asserts presence not content; mocks hide the UI | Cause of hidden failures in 4 runs | ask/textual-todo turns 15–16 mock `refresh_todos`, so the app is never mounted and `set_focus("new-todo")` crashes on start (**0/11**) · ask/expense-tracker checks only that `expense-list` exists (it is filled by JS, so it is empty) and checks only `amount` after a PUT (`description` gets wiped) · md-notes-search turns 7–10 test only flow-style `tags: [..]` | **Main source of non-intent failures** | Partly: acceptance tests from criteria; verify chain. Gap: nothing stops mocks or presence-only tests |
| **Misreading output against the contract** | 6 cases, 5 runs | ask/json-to-sqlite turns 15 and 25 tick "✓" on 3-tuples where the contract says `(sku, product_name)` · file-organizer turn 17: the plan shows a move, apply prints `SKIP`, agent says "Safety works perfectly" · md-notes-search turn 20: "AND logic – … at least one of the tags" | Hidden failures in 3 runs | Only if a criterion encodes it |
| **Says X, does Y** | 2 | textual-todo turn 14: "adjust the code to be safer", writes a byte-identical file · csv-cleaner turn 21: says it will collapse internal whitespace, doesn't | 1 hidden failure | Not addressed: report a no-op write as an observation |
| **Hallucinated API** | 7 cases, 3 runs | `set_focus("new-todo")` · `async with pilot` (turn 19) · `Label.text` (turn 49) · SQLite expression index (expense-tracker turn 4) | One run at 0/11; the rest cost turns | Partly: pyright for unresolved attributes. Gap: argument-type errors |
| **Wrong beliefs about the environment** | Path probes in 14/16 runs; `pip install` in 4; `/tmp` writes (sandbox-blocked) in 12 | ask/expense-tracker turns 9–26: `/tmp` database, then the stale server · textual-todo turn 3: `pip install textual` | Time; 10 turns lost to the stale server | Partly: fixed prefix and file tree. Gap: background processes, temp-dir policy |
| **Debugging its own scaffolding** | 3 runs | textual-todo turns 15–22, 49–59, 65–68: pilot API, app reuse, shared JSON file | ~30 turns | Partly: `write_tests`, attempt cap. Gap: known-good fixtures |
| **Whole-file rewrites** | 87 writes | expense-tracker turns 17 and 20: about 7.5K tokens each to change one function | Tokens; big on the 27B | `edit_symbol` |
| **Verification tail** | 37% of turns | file-organizer: last edit at turn 3, submits at turn 25 | Time | Partly: `done` gating. Gap: nothing ends the "all green" loop |
| **Repetition and loops** | 34 exact, 19 idle repeats; longest stale run 2 | add-feature: `cat notesapp/cli.py` at turns 5, 12, 15 | Small | The 3× guard would rarely fire. OK as a backstop |
| **Tool-format friction** | 2 sed problems; pipes hide return codes | ask/textual-todo turn 2: `pip … \| tail` gives rc 0 with "command not found" | Small | Removed by strict mode, which has no free `bash` |
| **Gold-plating** (27B) | 1/1 | Handling for FIFOs and symlinks, 77 tests plus a stress suite, then time-out | Missed the limit | Thinking budget; non-goals in the spec |

**The thinking itself** is useful but thin. The large blocks are design done ahead of time or
circling restatement, not analysis of the output that just came back. Twice the thinking and the
stated action disagree (csv-cleaner turn 21, md-notes-search turn 20). I saw no rambling loops.

## 4. Recommendations not in the M1 plan

1. **Smoke runs owned by the harness, before `done`.** Mount the Textual app with
   `run_test()`, `GET /` through `test_client`, run the CLI with `--help`. This would have
   caught the 0/11 crash and the empty list at no model cost.
2. **Contract probes.** Derive checks from the task's Contract section (tuple arity, keys,
   status codes, element ids) and run them in the verify chain. This catches the
   `top_products` and plan-vs-apply failures.
3. **Lint the model's tests.** Reject tests that mock the module under test or only assert
   presence. Require each test to fail against a stub.
4. **Process manager in `run`.** Allocate a free port, wait for a health check, and always kill
   the process afterwards; never block on `&`. This saves about 14 minutes of timeouts and the
   stale-server chase.
5. **Pyright argument-type rules** for library calls.
6. **Post-green cap.** After the tests pass with no changes, allow at most 2 re-verification
   turns, then only `done`.
7. **Learned facts in the "tried so far" summary.** Lessons like "an app can't be reused across
   `run_test`", not only attempts. This addresses the one forgetting case.
8. **Known-good test fixtures in the catalog**: pilot, test_client, tmp_path. This is a minimal
   slice of the deferred scaffolds.

## Method notes

- **`failed`** is rc≠0 or error text. It over-counts errors that the agent's own tests provoke on
  purpose.
- **`idle_repeat`** is the same normalised command (dropping `cd X &&`, path prefixes and
  head/tail counts) with no file-editing command since its last occurrence.
- **`misread`** is a regex heuristic and weak (2 hits). The misread rows above are coded by
  hand.
- **Turn numbers** count assistant messages from 1. Add `--turns` for per-turn flags.
