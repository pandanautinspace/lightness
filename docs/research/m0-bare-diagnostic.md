# M0 diagnostic: bare agent on the starter tasks

2026-11-02. One run per task, so these are diagnostics, not a baseline. They are meant to
check the tasks and to show where a bare agent loses, before we build the harness.

## Setup

- Agent: mini-swe-agent 2.4.6, default `mini.yaml` prompt, bash tool only, local environment
  wrapped in the bench sandbox (`sandbox-exec`, see `src/lightness/bench/sandbox.sb`).
- Server: llama-server 0.8.0, `scripts/serve.sh` settings (Q8 KV cache, 64K context, Qwen
  sampling, thinking budget 8192).
- Models: Qwen3.6-35B-A3B UD-Q5_K_M (all 8 tasks); Qwen3.8-27B UD-Q5_K_M + MTP draft
  (`file-organizer` only).
- Hardware: M5 Pro, 48GB.

## Speed

| | 27B dense (+MTP) | 35B-A3B MoE |
|---|---|---|
| Generation, short / 10K / 30K context | 27 / 24 / 18 tok/s | 64 / 58 / 49 tok/s |
| Prompt processing (10–30K) | 260–300 tok/s | 1,000–1,400 tok/s |
| One call: 30K context + 600 tokens out | 125 s | 36 s |

MTP draft acceptance on the 27B was about 80%.

## 27B smoke run: file-organizer

- Result: 9/9 tests passed (before the task was tightened), but the run hit the 30-minute limit
  without submitting. 8 calls, 39K completion tokens, 162K prompt tokens.
- Where the tokens went:
  - Whole-file rewrites through heredocs: `organize.py` and the agent's own tests, twice each.
  - Two thinking blocks of about 5–8K tokens; one hit the 8K budget.
- 0 malformed tool calls.

## 35B-A3B: all 8 tasks

Scores are after the test-fairness fixes below (file-organizer and csv-cleaner were regraded).

| Task | Result | Tests | Intent tests | Calls | Prompt tokens | Completion tokens | Minutes |
|---|---|---|---|---|---|---|---|
| add-feature | PASS | 26/26 | 3/3 | 26 | 358K | 9K | 3.1 |
| bugfix | PASS | 23/23 | – | 27 | 287K | 8K | 2.8 |
| expense-tracker | fail | 12/14 | 1/3 | 31 | 753K | 31K | 14.4 |
| json-to-sqlite | fail | 8/10 | 1/3 | 21 | 225K | 11K | 4.0 |
| textual-todo | fail | 9/11 | 0/2 | 70 | 1,811K | 38K | 14.0 |
| file-organizer | fail | 8/11 | 1/4 | 25 | 178K | 6K | 1.9 |
| csv-cleaner | fail | 7/13 | 3/5 | 30 | 381K | 17K | 5.7 |
| md-notes-search | fail | 6/12 | 0/3 | 44 | 600K | 16K | 5.0 |

Every run ended by submitting. There were 0 malformed tool calls in 274 turns.

## Findings

1. **Missing hidden preferences are the dominant failure mode.**
   - Four tasks (expense-tracker, json-to-sqlite, textual-todo, file-organizer) failed *only*
     intent tests.
   - The agent never asked a question.
   - So the spec workshop is likely the single largest lever.
2. **Genuine functional bugs are few, and they come from not checking against the spec.**
   - md-notes-search: YAML block-list tags weren't parsed, although the instruction names
     front-matter tags.
   - csv-cleaner: `30-Mar-2024` wasn't parsed, so a row was silently skipped. The instruction
     says "every format imaginable".
   - Five of eight runs never ran a test. Acceptance tests derived from the spec, plus the
     verify chain, target exactly this.
3. **Output format is not the problem for this model family.** There were zero malformed tool
   calls on either model, so tool-call repair moves down the priority list. Constrained
   decoding still matters for the harness's own small decisions.
4. **Context grows by accumulating the transcript.** Prompts peaked at 45–55K tokens on the
   longer tasks, and textual-todo used 1.8M prompt tokens over 70 calls. Prefix caching and the
   35B's fast prompt processing hide this. On the 27B it would cost hours. Rebuilding context
   each turn matters most for the slower model.
5. **The bare agent spends its tokens on whole-file rewrites.** md-notes-search rewrote files 10
   times and csv-cleaner 8 times. On the 27B, whole-file rewrites plus long thinking blocks were
   most of the 33 minutes. Symbol-level edits and per-action thinking budgets address this.

## Benchmark fixes made because of this run

- **file-organizer:**
  - Hidden-file handling had been checked by non-intent tests; it is now intent-only.
  - Added an unguessable `Screenshots/` intent, because the model guessed the conventional
    category names unaided.
- **csv-cleaner:**
  - Non-intent tests key rows on whitespace-normalised descriptions, so one interpretation
    choice can no longer cascade.
  - Internal whitespace collapsing and German dotted dates moved to intent tests.
  - One genuine bug can still cost about 4 tests: a skipped row changes counts and totals.
    Accepted for now.
- **Runner:** `verify()` now resolves relative run directories.
- **Sandbox:**
  - Reads under `$HOME` were open, so the agent could read hidden tests and solutions; reads
    there now trigger macOS privacy prompts no longer.
  - Fixed: only the run dir, the venv and `src/` are readable under `$HOME`.

## Next

- M1: the guarded loop core, with the minimal spec workshop moved early, since finding 1
  dominates.
- The paired comparison (bare vs harness, n≥3 per task) runs once M1 works.
- textual-todo's "input keeps focus" intent half is still weak, because Textual's default
  behaviour passes it.
