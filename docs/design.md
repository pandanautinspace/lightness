# lightness — design v0.2

A coding harness that makes small local models (~10–35B, quantized) useful for real work,
and makes large models faster and cheaper. Python-first. Biased toward scripts, small apps,
and small repos; supports both interactive use and vague "go build this" tasks.

Status: draft, 2026-11-02. Based on a research pass (sources at the bottom).
v0.2: replaced the fixed pipeline with a guarded agent loop + playbooks; added the
spec workshop (user-assisted design).

## Core thesis

**The model chooses; the harness owns state, context, and safety.**

Small models *can* pick tools. What they fail at is (1) emitting valid calls, (2) managing a long
growing transcript, (3) knowing things (APIs, patterns, what to build), and (4) recovering when
stuck. So lightness keeps an agent loop — the model picks the next action every turn — but:

- the action is chosen from a **grammar-constrained, state-dependent menu**, so it is always valid;
- actions are **macros** that run deterministic sub-pipelines (splice → lint → type-check →
  test) and return one compact observation;
- **context is rebuilt every turn** from harness state, not appended to a transcript;
- **knowledge comes from the harness** (spec, pattern catalog, scaffolds, API introspection),
  not the model's memory;
- **guards** (budgets, loop detection, forced replan/restart) wrap the loop;
- a **spec workshop** with the user fixes *what* to build and *which patterns* before code is
  written, and the spec stays the source of truth.

Fixed pipelines survive as **playbooks**: known-good action sequences ("new Flask app from spec")
that run deterministically when they fit; the model drops into free choice when they don't.

Evidence: little-coder's guard rails on a model-driven loop took Qwen3.5-9B from 19% → 46% on
Aider Polyglot (self-reported); Agentless-style fixed pipelines beat open agents of their time;
SWE-Gym's verifier + best-of-8 took a 32B model from 20.6% → 32.0%. Loop vs pipeline vs bare is
an ablation the benchmark will run.

## Decisions

| Decision | Choice | Why |
|---|---|---|
| Harness language | Python 3.12, uv | Same ecosystem as target code (libcst, ruff, pyright, `inspect`); direct control of request payloads |
| Build on pi? | No. Borrow ideas (minimal prompts, provider compat flags) and little-coder's guard-rail checklist | pi is TS; no grammar pass-through for local servers; we need to own context assembly |
| Target language | Python | Best small-model coverage, best deterministic tooling |
| Local server | llama-server (llama.cpp) | Only server with GBNF + json_schema + thinking budget + prefix/slot cache + MTP speculative decoding, at MLX-level speed on M5. oMLX as the MLX alternative |
| Primary model | Qwen3.8-27B, Q4_K_M/Q5, MTP on | Best fit for 48GB; cheap KV (~8GB @128K). Est. 25–30 tok/s on M5 Pro |
| Fast / alt model | Qwen3.6-35B-A3B (Q5/Q6) | ~2–3× faster; 4-bit reported noisy. Not co-resident with the 27B |
| Baseline | mini-swe-agent, same endpoint | Measures what the harness adds |

## Principles

1. **Never ask for diffs.** New/small files → whole-file output. Existing larger files →
   *symbol replacement* (model emits a complete function/class; libcst splices it in).
   Fuzzy search/replace only as fallback. (One report: qwen3-coder-30B 0/100 with diffs vs
   100/100 whole-file.)
2. **Never put code in JSON.** Actions are chosen with a grammar; code payloads come back in
   fenced blocks extracted deterministically.
3. **Reason, then constrain.** A grammar from token 1 kills thinking. When an action needs
   reasoning: bounded free text → constrained choice (CRANE-style, +up to 10pp).
4. **Thinking is a budget, not a default.** Per action type; off for routine writes.
5. **Context per turn, not per session.** Small models are hurt by extra context.
6. **Deterministic first, model last.** Auto-fix lint/format/imports/known errors before the
   model sees anything.
7. **Short repair, then restart.** Debugging effectiveness decays 60–80% within 2–3 attempts.
8. **Breadth + verifier over long loops** for hard steps (best-of-N, pick by tests).
9. **Ground every API** in the installed env; inject docs only for uncommon/failing APIs.
10. **Decide before coding.** Patterns, libraries, interfaces, and data model are settled in the
    spec workshop, from a curated catalog — the model customizes, it doesn't invent.
11. **Functional core, imperative shell.** Generated projects keep logic in pure, small,
    testable modules with thin I/O adapters. Small files + pure functions = small context and
    precise tests. Scaffolds enforce this.
12. **Stable prompt prefixes** so the server's prefix cache hits.

## The loop

```
 task ─► Spec workshop ──► spec.md (source of truth) ─► Plan (structured, revisable)
              ▲  ▲                                          │
              │  └──── propose_spec_change / ask_user ◄─────┤
              │                                             ▼
              │        ┌──────────── each turn ──────────────────────────────┐
              │        │ assemble context from state ─► model picks action   │
              │        │ (grammar: menu valid *now*)  ─► macro runs           │
              │        │ ─► compact observation ─► state update ─► guards     │
              │        └─────────────────────────────────────────────────────┘
              │                                             │ milestone reached
              └──────────── demo checkpoint (show running app, collect feedback) ◄┘
```

### Turn anatomy

Prompt layout (append-only within a turn, stable prefix across turns):

1. **Fixed prefix:** role, action menu docs, project conventions (cached).
2. **Spec digest:** goal, contract, chosen patterns (changes rarely → cached most turns).
3. **Plan:** steps with status; current step highlighted.
4. **Working set:** repo map slice + the 1–3 symbols/files relevant to the current step.
5. **Recent observations:** last 3–5 action results, compressed; older ones summarized into
   one "what's been tried" paragraph.
6. **Ask:** "choose the next action".

Output: optional bounded reasoning → constrained action JSON → (if the action carries code)
a fenced block.

### Action menu (initial)

| Action | Args (constrained to) | Macro does | Thinking |
|---|---|---|---|
| `read` | file / symbol (enum of real ones) | returns trimmed view, marks as read | off |
| `search` | query string, scope | ripgrep + symbol index, ranked hits | off |
| `api` | package.symbol (installed only) | real signature + docstring + example | off |
| `recipe` | tag (enum from catalog) | returns a pattern card | off |
| `write_file` | path (planned / new) + code block | write → ruff fix/format → import check → pyright → related tests | low |
| `edit_symbol` | existing symbol (read only) + code block | libcst splice → same verify chain | low |
| `run` | command (allow-listed shapes) / app smoke | runs with timeout, compressed output | off |
| `test` | target (enum) | pytest, first failure compressed | off |
| `diagnose` | — | bounded reasoning over last failure → {cause, symbol, fix_intent} | budgeted |
| `revise_plan` | step ops | edits plan object | budgeted |
| `ask_user` / `propose_spec_change` | question + options | interactive: ask; autonomous: take default, log assumption | low |
| `done_step` / `done` | — | harness verifies step check / acceptance before accepting | off |

The menu is **state-dependent**: `edit_symbol` only lists symbols already read; `done` only
appears when acceptance tests exist; after 2 failed repairs on a step only `diagnose`,
`revise_plan`, `ask_user` are offered; after 3, the harness restarts the step with fresh context
and a failure summary.

### Playbooks

Deterministic action sequences for common shapes, chosen by the spec's project type:
`scaffold → write core module → write tests → write shell (CLI/web/TUI) → acceptance`.
A playbook step can hand control to the free loop (e.g. "make tests pass") and resume after.
Ablation: playbook-guided vs free loop.

## Spec workshop (user-assisted design)

Goal: build the right thing with the right patterns before any code is written — and move
"what to build" and "how to structure it" decisions out of the small model's head into a
conversation backed by a curated catalog.

### Flow

1. **Intake.** User describes the task in any words.
2. **Classify** (constrained enum): CLI tool · data script · web app · TUI · GUI · library ·
   change to existing repo. For existing repos: run the indexer and summarize structure first.
3. **Load the decision checklist** for that type from the **decision catalog**. Example for a
   web app: storage, UI approach, auth (none/local), data model, key screens, import/export,
   port/config, test strategy.
4. **Model proposes defaults** for each decision, choosing among catalog options (each with
   when-to-use notes), with a one-line rationale tied to the user's words.
5. **Ask only what matters.** Questions are ranked by impact × ambiguity; ask the top few as
   multiple choice with a recommended option (user can override in free text). Everything else
   becomes a listed assumption the user can skim and change.
6. **Draft `spec.md`** (template-filled, model writes the prose bits):
   - goal, users, non-goals
   - features as short user stories, each with acceptance criteria in plain language
   - interface contract (CLI flags / routes / screens / public functions)
   - data model
   - chosen patterns + scaffold + libraries (verified installable, versions pinned)
   - assumptions (each marked confirmed / defaulted)
7. **Review.** User edits text or answers follow-ups; the spec is versioned.
8. **Acceptance tests.** Plain-language criteria → test skeletons (pytest / httpx / Playwright /
   Textual pilot), shown to the user as the "definition of done".

### During the build

- **Ambiguity hits** (`ask_user` / `propose_spec_change`) reopen a single spec item, not the
  whole workshop.
- **Demo checkpoints** at milestones (walking skeleton runs; first feature works): show how to
  run it, collect "this is right / change X" feedback → spec diff → plan revision.
- **Autonomous mode** runs the same workshop with a *defaults policy* instead of a user:
  catalog recommendations win, every choice is logged as an assumption, the final report lists
  them.

### Decision catalog (knowledge the model doesn't need to have)

Each entry: `id`, question, applies-to types, options with when-to-use / trade-offs, linked
scaffold + recipe cards. Starter set:

- storage: JSON file · SQLite (sqlite3) · SQLite (SQLAlchemy)
- web stack: Flask + Jinja · FastAPI + HTMX + Jinja · FastAPI JSON API + vanilla JS
- CLI: argparse · Typer · subcommands vs flags
- TUI: Textual; GUI: Tk (logic module separate)
- config: TOML file · env vars · CLI flags
- structure: single file (<300 LOC) · package with core/shell split
- safety: dry-run default, atomic writes, undo journal (file-mutating tools)
- testing: pytest + fixtures; injectable clock / filesystem roots

The spec workshop is high-leverage and low-volume — the first place to route to a big model
later.

## Knowledge layer (research track)

The harness's main job is deciding *what the model sees each turn*. With a ~4–8K-token working
set, the selection policy is probably the biggest single lever and the least settled part of
the design. Three questions:

1. **What knowledge exists** (stores / node types)
2. **How pieces relate** (typed edges, and who decides them)
3. **What goes into this turn, in what form** (selection + rendering under a token budget)

### One graph, four layers

| Layer | Nodes | Edges (examples) | Scope |
|---|---|---|---|
| Code | file, module, symbol, test, route, template, table | defines, calls, imports, tests, handles(route→fn), renders, reads/writes(table) | per project, rebuilt incrementally |
| Spec | feature, criterion, decision, assumption | feature→criterion→test, decision→option, feature→implemented_by→symbol | per project |
| Catalog | pattern, recipe card, scaffold, library API, error signature, decision option | uses, requires, alternative_to, conflicts_with, fixes(error→recipe), example_of | global, curated |
| Episodic | attempt, failure, fix, lesson | failed_with, fixed_by, generalizes_to | per project → promoted to global |

The **spec↔code traceability edges** connect the layers. When the current step is "feature F",
a walk gives F's criteria, their tests, the symbols implementing F, the decisions that constrain
F, recipe cards for the chosen patterns, and API facts for the libraries those symbols use.
This is a typed graph walk, not a similarity search.

### Who decides relationships (in order of trust)

1. **Extracted:** AST, imports, call graph, route tables, SQL table use, test→target (imports /
   coverage). Deterministic and preferred.
2. **Recorded:** the harness logs edges as things happen. A `write_file` during a step for
   feature F creates `F implemented_by symbol`. A failure fixed by a recipe creates
   `error fixes recipe`.
3. **Authored:** catalog content written by hand or by a big model, then reviewed.
4. **Inferred:** a small model proposes edges, constrained to existing node ids. Stored with
   low confidence and never trusted without corroboration.
5. **Similar:** embedding neighbours. Used only to generate candidates for vague queries.

### Selection policies to compare

- **A. Local only:** current file/symbol and nothing else (floor)
- **B. Repo map:** Aider-style PageRank, personalized on the step's anchor symbols
- **C. Typed walk:** from step anchors, with per-edge-type budgets and decay by hop
- **D. Embedding top-k** over code chunks and cards
- **E. Hybrid:** C for code and spec, D for catalog cards, plus gating (API docs only when the
  import/attribute check fails or the API is rare, per CloudAPIBench)
- **Push vs pull:** push a minimal slice and let the model pull more via `read`/`search`/`api`/
  `recipe`, versus pushing a richer slice. Measure both.

### Rendering

Form matters as much as selection:
- signature-only vs skeleton (bodies elided) vs full body
- ordering (anchor last, next to the ask?)
- dedupe and stable ordering for prefix caching
- card format, and how much of the token budget goes to each layer

### Measuring context without running the model

**Gold context:** for each benchmark task, derive the symbols, files, cards and APIs the
reference solution touched or depended on. Retrieval quality is then measured offline:
- recall@budget, precision and tokens per policy
- cheap and fast, with no model in the loop

End-to-end pass rate is the confirmation. Also run **context stress tests** on our models: how
pass rate degrades with distractors and with working-set size (find the knee for Qwen3.8-27B).

### Implementation stance

- Start with in-memory `networkx` plus JSON/SQLite persistence. No graph database.
- Embeddings from a small local model via `llama-server --embedding`.
- One node/edge schema shared by all four layers, so walks can cross layers.

## Components

- **`provider/`** — OpenAI-compatible client + capability flags (`grammar`, `strict_schema`,
  `thinking_budget`, `logprobs`, `prefix_cache`). `Constraint` with three levels: JSON Schema in
  the cross-provider common subset → regex/GBNF when local → validate-and-retry fallback.
- **`loop/`** — turn assembly, action menu generation, action dispatch, guards, state store
  (`.lightness/state.json`, resumable).
- **`spec/`** — workshop flow, decision catalog, spec template, acceptance-test generation.
- **`actions/`** — the macros above.
- **`graph/`** — shared node/edge schema across code, spec, catalog and episodic layers;
  extractors; recorded edges; selection policies; renderers.
- **`index/`** — symbol index (`ast`/tree-sitter), call/import graph extractors, ranked repo map.
- **`edit/`** — whole-file write, libcst symbol replace/insert, fuzzy anchor fallback, write guard.
- **`verify/`** — parse → ruff fix/format → import/API check → pyright → targeted tests → app
  smoke; error compressor.
- **`knowledge/`** — API introspection cache, scaffolds, recipe cards, error playbook,
  decision catalog data.
- **`ui/`** — CLI first (interactive prompts for the workshop, step status); TUI later.

## Guard-rail checklist (from little-coder + field reports)

- Repair tool calls / code emitted as prose; strip chatter around fences
- Read-before-edit; write guard; trim oversized reads
- Explicit `n_ctx`; assert prompt fits; never rely on server defaults (Ollama 2048 trap)
- KV cache at ≥ Q8
- Model-recommended sampling (Qwen: T 0.6 / top-p 0.95 / top-k 20; presence penalty when
  quantized); never greedy in thinking mode
- Repetition detection on streamed tokens and on repeated actions
- Per-model chat-template tests

## Milestones

- **M0 — measure.** Install llama-server + models; benchmark runner; 8 starter tasks with
  simulated users; mini-swe-agent baseline. Edit-format micro-benchmark on our models.
- **M1 — loop core.** provider + constraints, turn assembly, action menu, `read/search/
  write_file/run/test/done`, verify chain, guards. Whole-file edits only.
- **M2 — spec workshop.** classify, decision catalog (starter set), spec template, acceptance
  test generation, CLI Q&A, defaults policy; scaffolds for CLI, Flask, Textual.
- **M3 — existing code.** symbol index, repo map, `edit_symbol`, working-set selection.
- **M4 — knowledge.** `api` introspection + import check, recipe cards, error playbook.
- **M5 — playbooks + robustness.** playbooks per project type, best-of-N, demo checkpoints,
  tuning thinking budgets; ablation loop vs playbook.
- **M6 — big models.** hosted providers through the same constraint layer; route spec/plan/
  diagnose to a big model; cost comparison.

### Knowledge track (runs alongside; K1 needs M0's tasks)

- **K0: literature pass.** *Done:* see [research/k0-knowledge-layer.md](research/k0-knowledge-layer.md).
  Main findings:
  - code graphs give small absolute gains and help mainly where links aren't lexical;
  - gating doc retrieval beats always retrieving;
  - small models often ignore optional graph tools, which argues for pushing context;
  - keep walks to ≤2 hops;
  - store episodic lessons only once a test has verified them.

  The pass covered graph and hybrid RAG for code and docs:
  - code graphs: RepoGraph, CodexGraph, LocAgent
  - graph RAG: GraphRAG, HippoRAG
  - selective retrieval (e.g. Repoformer); CodeRAG-Bench
  - context-length degradation ("context rot") studies
  - agent memory and lesson-learning work

  Output: a note on which policies to test first.
- **K1: gold context and offline evaluation.** *Tiered* gold context from benchmark reference
  solutions: symbols edited, dependencies the solution uses, and APIs it calls. A patch alone
  under-counts what had to be read (ContextBench). Offline scorer for recall at 2K/4K/8K budgets,
  precision and tokens. Context stress tests on Qwen3.8-27B and 35B-A3B: 0/2/8/32K of random and
  near-miss distractors, placed at the start, middle and end.
- **K2: code and spec graph.** Extractors, traceability edges recorded by the loop, typed-walk
  policy (C); compare against A, B and D offline.
- **K3: catalog graph.** Schema plus starter content: decision options → scaffolds → recipes →
  APIs → error fixes. Gated API retrieval.
- **K4: policy ablations end to end.** A–E and push vs pull, run through the benchmark.
  Rendering variants.
- **K5: episodic memory.** Failure→fix lessons within a project; promotion to the global catalog
  once a fix recurs across projects.
- **K6: model-assisted linking.** Small model proposes edges, constrained to existing nodes;
  measure precision before trusting any.

## Open questions

- How many workshop questions before users get annoyed? Target ≤5 for a small app.
- Whole-file vs symbol edits for 300–1500 LOC files on Qwen3.8 — decide from M0 data.
- 27B for everything vs 35B-A3B for writes + 27B for spec/plan/diagnose? Model swaps cost load
  time on 48GB.
- Which context selection policy wins, and does it differ per action type? See *Knowledge layer*
  and K0–K6.
- How compressed can observations be before the model loses the thread? (A rendering question;
  test it in K4.)
- Do episodic lessons generalize across projects, or just add noise?

## Sources (selected)

- Edit formats: Diff-XYZ arxiv.org/abs/2510.12487 · aider.chat/docs/more/edit-formats.html ·
  geometricagi.github.io/2026/04/02/ast-edits.html
- Code in JSON / constrained decoding: aider.chat/2024/08/14/code-in-json.html ·
  arxiv.org/abs/2408.02442 · CRANE arxiv.org/abs/2502.09061
- Context: RepoGraph arxiv.org/abs/2410.14684 · LocAgent arxiv.org/abs/2503.09089 ·
  CodeRAG-Bench arxiv.org/abs/2406.14497
- API knowledge: arxiv.org/abs/2406.10279 · CloudAPIBench arxiv.org/abs/2407.09726
- Repair decay: arxiv.org/abs/2506.18403 · SWE-agent ACI arxiv.org/abs/2405.15793
- Reasoning: overthinking arxiv.org/abs/2502.08235 · small-agent orchestration arxiv.org/abs/2601.11327
- Pipelines: Agentless arxiv.org/abs/2407.01489 · SWE-Gym arxiv.org/abs/2412.21139
- Harnesses: github.com/earendil-works/pi · github.com/itayinbarr/little-coder ·
  github.com/SWE-agent/mini-swe-agent
- Inference: github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md ·
  github.com/jundot/omlx · github.com/QwenLM/Qwen3.8

Caveat: many numbers above are vendor- or self-reported; M0 exists to check what matters on our
own hardware and models.
