# M1 plan: spec workshop + guarded loop core

Status: draft for review, 2026-11-02. Builds on [design.md](design.md) v0.2 and the
[M0 diagnostic](research/m0-bare-diagnostic.md).

## Goal

A first working lightness harness that beats the bare agent on the same model. It wins
mainly by asking the right questions up front and by checking its work against the spec,
while spending fewer tokens and finishing within time on the 27B.

M0 told us where to aim:

| M0 finding | M1 response |
|---|---|
| 4/8 tasks failed **only** on unstated preferences; the agent never asked | Spec workshop with task-specific questions, before any code |
| Real bugs went unnoticed; 5/8 runs never ran a test | Acceptance criteria → tests; verify chain after every write |
| 0 malformed tool calls in 274 turns | Keep constrained decoding for harness decisions; don't build call repair yet |
| Transcript grew to 45–55K tokens; 1.8M prompt tokens on one task | Context rebuilt per turn under a hard budget |
| Whole-file rewrites and long thinking ate the 27B's time | `edit_symbol` for existing code; thinking off by default, budgeted per action |

## Scope

**In M1:**
- Provider client for llama-server, with call logging
- User channel: terminal, defaults policy, simulated user
- Spec workshop: classify, task-specific questions, `spec.md`, acceptance criteria
- Loop core: turn assembly, state-dependent action menu, guards, persisted state
- Actions: `read`, `search`, `write_file`, `edit_symbol`, `write_tests`, `run`, `test`,
  `ask_user`, `revise_plan`, `done_step`, `done`
- Verify chain: parse → ruff → pyright (high-precision rules only) → related tests →
  compressed error
- Bench integration: `lightness` and `bare-ask` agents; held-out tasks; evaluation
- Minimal interactive CLI

**Not in M1** (later milestones):
- Graph and knowledge layer (K-track)
- Recipes and scaffolds
- API introspection
- Best-of-N
- Playbooks beyond one default plan shape
- TUI
- Hosted providers (the client is designed for them but not tested against them)
- Docker isolation

## Package layout

```
src/lightness/
  provider.py        # Client, Reply, capability flags, call log
  user.py            # UserChannel protocol + TerminalUser, DefaultsUser, SimulatedUser
  state.py           # RunState (spec, plan, files read, observations, attempts) ↔ .lightness/state.json
  spec/
    workshop.py      # classify → questions → answers → spec + criteria
    catalog/*.yaml   # per project type: decision dimensions + pattern options
    render.py        # spec.md
  loop/
    context.py       # turn prompt assembly under a token budget
    menu.py          # allowed actions + JSON schema for the current state
    guards.py        # budgets, repetition, step attempts, restart
    driver.py        # main loop
  actions/           # one module per action (macro)
  edit/
    fences.py        # extract code blocks from model output
    symbols.py       # libcst: outline, find, replace/insert symbol
  verify/
    chain.py         # parse → ruff → pyright → tests
    compress.py      # error → short observation
  cli.py             # `lightness "task"` / `lightness --auto "task"`
```

New dependencies: `libcst`, `ruff`, `basedpyright` (pip-installable, bundles node).

## Work items, in order

Each item ends with a check we can run.

### 1. Provider and call log

- `Client.chat(messages, *, schema=None, thinking="off" | int, max_tokens, stop) -> Reply`
  - `Reply` holds `text`, `reasoning`, `parsed`, `usage` and `timings`.
- `Client.decide(messages, schema, reason_budget)`: optional bounded free reasoning, then a
  schema-constrained answer. This is the two-phase "reason, then constrain" call.
- If parsing fails, validate and retry once with the error message, then raise.
- Every call is appended to `calls.jsonl` with: purpose (call type), prompt tokens, completion
  tokens, latency, thinking tokens, and whether it was retried.
- **Capability probe:** a script that checks against the live server:
  - per-request thinking on/off (`chat_template_kwargs.enable_thinking`);
  - per-request reasoning budget, if supported;
  - `response_format` json_schema with `anyOf` + `const` + `enum`.

  Record the findings in `models.toml`.
- *Check:* unit tests against a fake server, plus a probe run on both local models.

### 2. User channel, simulated user, and a `bare-ask` baseline

- `UserChannel.ask(question, options: list[str] | None, default) -> Answer`, with three
  implementations:
  - `TerminalUser`: interactive.
  - `DefaultsUser`: autonomous mode; always returns the default and logs an assumption.
  - `SimulatedUser`: bench only. A local-model call that answers *only the question asked*,
    from `intent.md`. It returns "no preference" when the intent file doesn't cover the
    question, and never volunteers other intent items.
- `bare-ask` bench agent: mini-swe-agent plus an `ask_user "question"` shell command. The
  harness intercepts the command before it reaches the sandbox and replies via
  `SimulatedUser`. The prompt tells the agent it may ask.
- *Check:*
  - Leakage test: ask unrelated or broad questions ("anything else I should know?"); the
    answers must not dump the intent file.
  - Then run `bare-ask` once on the 8 tasks with the 35B. This tells us how much of the intent
    gap asking alone closes, before we credit the workshop.

### 3. Spec workshop

1. **Classify**: enum over cli, data-script, webapp, tui, gui, library, repo-change.
   - For repo-change, a cheap repo summary goes into the prompt first: file tree, README
     head, test names.
2. **Generate questions** in one `decide` call:
   - The prompt gets the task text plus the catalog's *dimensions* for that type.
   - Examples of dimensions: naming and labels, ordering, formats and units, edge cases,
     error behaviour, persistence format, what counts as a duplicate, defaults.
   - The output is a list of `{question, options[], default, impact 1–3, ambiguity 1–3}`.
3. **Rank** by impact × ambiguity and ask the top K via `UserChannel`. Start with K=5 and tune
   it. Unasked questions keep their defaults and become listed assumptions.
4. **Write the spec** in one call:
   - goal, non-goals;
   - features, each with acceptance criteria in plain language;
   - interface contract (copied from the task's Contract section when one exists);
   - data model;
   - assumptions, each marked confirmed or defaulted.
5. **Render** `spec.md`. In interactive mode the user can approve it, edit it, or answer a
   follow-up.
- Catalog files for M1: `cli`, `data-script`, `webapp`, `tui`, `repo-change`. These hold
  dimensions plus a small set of pattern decisions, e.g. storage (JSON/SQLite) and web stack
  (Flask + Jinja). No scaffolds yet.
- *Check:* **intent coverage**, measured offline without writing any code.
  - Run the workshop alone on the 8 tasks with `SimulatedUser`.
  - Score how many `intent.md` bullets appear correctly in the resulting spec. A local judge
    call scores each bullet, with spot checks by hand.
  - Target: ≥70% coverage at K≤5.
  - This is the cheapest feedback loop in M1, so iterate here first.

### 4. Edit and verify, deterministic and model-free

- `fences.py`: extract the single code block for a target file. Tolerate chatter, missing
  language tags and nested fences; reject output containing several conflicting blocks.
- `symbols.py` (libcst):
  - outline a file (signatures + docstrings);
  - get a symbol's source;
  - replace a top-level function or class, or a method, preserving surrounding formatting;
  - insert a new symbol after a given one.
- `chain.py`:
  1. `ast.parse`;
  2. `ruff check --fix` and `ruff format`;
  3. basedpyright, limited to unresolved import/attribute and undefined-name rules;
  4. tests related to the touched module (test files that import it), then the full suite
     at `done`.

  All subprocesses run inside the bench sandbox.
- `compress.py`: reduce output to the first failing check, the relevant traceback frames in
  workspace files, the assertion diff, and at most about 40 lines, mapped back to the symbol
  the model wrote when possible.
- *Check:* unit tests on fixtures, covering the M0 failure shapes (missing date format,
  unparsed YAML block list, server not starting).

### 5. Loop core

- **State.** Spec, plan (steps `{id, goal, files, check, status, attempts}`), files read,
  observation log, assumptions and budgets. Persisted after every turn, so a run can resume.
- **Plan.** One `decide` call after the spec.
  - The prompt asks for small steps ordered as: core logic → tests from acceptance criteria →
    I/O shell (CLI / web / TUI) → acceptance.
  - The harness checks every file path and every criterion reference against the spec.
- **Turn prompt**, under a hard budget (start at 12K tokens):
  1. fixed prefix
  2. spec digest
  3. plan with statuses
  4. working set: file tree with sizes, then for the current step an outline of the target
     files plus full bodies of the symbols in play
  5. last 3 observations
  6. a one-paragraph "tried so far" summary
  7. the ask
- **Menu.** The set of allowed actions and targets depends on state. It is compiled into a
  JSON schema of `anyOf` branches, one per action, with `const` action names and `enum`
  targets. Rules:
  - `edit_symbol` only lists symbols in files already read.
  - `done` appears only once acceptance tests exist.
  - After 2 failed repairs on a step, only `read`, `ask_user` and `revise_plan` are offered.
  - A sandboxed `bash` action is always available as an escape hatch, so a capable model is
    never boxed in. Its use is logged; if a model leans on it heavily, the menu is missing
    something.
- **Code-carrying actions** (`write_file`, `edit_symbol`, `write_tests`) make a second,
  unconstrained call that asks for exactly one fenced block. Its context is the step, the spec
  slice and the target outline or body. Thinking is off.
- **Guards:**
  - At most 3 attempts per step, then restart the step with fresh context and a one-paragraph
    failure summary.
  - The same action and target three times with no state change triggers a forced
    `revise_plan`.
  - Turn and token caps, and a wall-clock limit.
  - Assert the prompt fits the server's context.
- **Thinking policy:** off for routine actions. A budgeted reasoning phase for `plan`,
  `revise_plan`, and action choice after a failure. Budgets start at 1–2K tokens.
- **`done`:** requires the full test suite and acceptance tests to pass, or an exhausted
  budget. The run then ends with a report listing assumptions, failing checks, and
  questions asked.
- *Check:* end-to-end on 2 tasks (`file-organizer`, `bugfix`) on the 35B; the call logs are
  read by hand.

### 6. Bench integration and held-out tasks

- `LightnessAgent` in `bench/agents.py`.
  - Runs in-process. Writes go through the harness, which refuses any path outside the
    workspace.
  - Every subprocess (run, test, verify) goes through the sandbox.
  - User channel: `SimulatedUser` (the `lightness` condition) or `DefaultsUser` (the
    `lightness-auto` condition).
- **Held-out tasks.**
  - Before the M1 evaluation, an agent with no knowledge of the harness writes 6 new tasks
    in the same format: 2 scripts/data, 2 webapp/tui, 2 repo-edit.
  - M0 suggests the dev tasks are easy for the 35B on functionality, so half of the held-out
    tasks are a **harder tier**, each with at least one of:
    - several files;
    - two or more interacting features;
    - a 1,500–3,000 LOC seed repo;
    - a follow-up change request applied to the agent's own first result.
  - Each is checked with oracle and null, and with one `bare` run looked at for fairness
    (the M0 lesson).
  - We don't tune on them.
- Runner additions:
  - per-call-type token and time breakdown, read from `calls.jsonl`;
  - questions asked;
  - intent coverage;
  - a `report` command that aggregates the n runs per task and condition (pass rate with CI,
    pass^k).

### 7. Evaluation

| Condition | What it isolates |
|---|---|
| `bare` | baseline |
| `bare-ask` | asking alone |
| `lightness-auto` | loop + verify, no user |
| `lightness` | the full harness |

- 35B-A3B: all 4 conditions × 14 tasks (8 dev + 6 held-out) × n=3.
- 27B: `bare` and `lightness` on the 6 held-out tasks × n=2.
- **Qwen3.5-9B** (≈6GB at Q5): `bare` and `lightness` on all 14 tasks × n=2. This is where
  the harness should matter most, and the case that matters for "light" models.
- **Layer ablation** on the 35B, held-out tasks: `lightness-loose` keeps only the workshop and
  the verify chain, with a free sandboxed `bash` action instead of the strict menu. It tests
  whether the strict loop helps a capable model or gets in its way.
- Paired per-task comparison.

### 8. Interactive CLI (minimal)

- `lightness "make me a ..."` runs in the current directory: workshop Q&A in the terminal,
  show `spec.md` for approval, then one status line per step.
- `--auto` uses the defaults policy.
- Resume from `.lightness/state.json`.

## Exit criteria

M1 is done when, on the **held-out** tasks:

1. `lightness` passes more tasks than `bare-ask` on the 35B, with ≥15 points more mean pass@1,
   and doesn't lose on any task category.
2. `lightness-auto` is at least as good as `bare` (the loop and verify chain alone don't hurt).
3. Intent coverage of the workshop is ≥70%, using ≤5 questions per task.
4. On the 27B, `lightness` finishes every task within the time limit, with median wall-clock
   ≤ 50% of `bare`'s.
5. 0 unparseable harness decisions after the single retry, and 0 writes outside the
   workspace.

If 1 fails but 3 passes, the problem is the build loop, not the questions, and the next work
goes there.

## Risks

- **Simulated user leaks or over-answers.**
  - Mitigation: answer-only-what-was-asked prompt, a leakage test, logs reviewed for the
    first runs.
  - Alternative: a stronger judge model later (M6).
- **Model-written acceptance tests encode wrong behaviour,** so the loop "passes" its own bad
  tests.
  - Mitigation: tests derive from spec criteria; the hidden tests are the real judge; check
    the gap between "own tests pass" and "hidden tests pass" in reports.
- **Per-request thinking control may not work as documented on llama-server.**
  - Mitigation: the probe in item 1; fall back to separate server launches or prompt-level
    `/no_think`.
- **Overfitting to the 8 dev tasks.** Mitigation: held-out tasks, written blind.
- **The harness makes a capable model worse.** M0 showed the 35B writes working code well on
  its own; strict menus and forced steps add overhead and may cut off good strategies.
  - Mitigation: the `lightness-auto` vs `bare` exit criterion, the `bash` escape hatch, and
    the `lightness-loose` ablation.
  - Every layer can be switched off, so we can keep only the ones that pay for themselves on
    each model size.
- **A fixed step order is too rigid for repo-change tasks.** Mitigation: the default plan
  shape is only a suggestion to the plan call; `revise_plan` is always available.
- **Prompt cache misses from rebuilding context every turn.** Mitigation: keep the prefix,
  spec digest and plan stable and first; measure the cache hit rate from server timings.

## Decisions to confirm

- Question budget K=5 by default, with `ask_user` during the build counting against it.
- The local model plays the simulated user; no hosted judge in M1.
- 6 held-out tasks written blind, by a separate agent.
- 35B-A3B for development, 27B for confirmation runs.
