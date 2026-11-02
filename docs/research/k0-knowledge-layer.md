# K0: Literature pass for the knowledge layer

Date: 2026-11-02. Evidence flags: **[S]** strong (peer-reviewed, replicated or large-scale), **[M]** moderate (single paper, reasonable setup), **[W]** weak (small sample, vendor blog, or preprint), **[U]** unverified (only secondary summaries seen; check before citing).

## 1. Code graphs for retrieval and localization

- **RepoGraph** (https://arxiv.org/abs/2410.14684). Nodes are *lines* of code tagged def/ref, with `contain` and `invoke` edges and builtins/third-party calls filtered out. Retrieval: k-hop ego-graph (k=1–2) around a search term, flattened or summarized. On SWE-bench Lite the gains are about +2–2.7 pp absolute: Agentless/GPT-4o went 27.3→29.7, SWE-agent/GPT-4o 18.3→20.3, RAG/GPT-4 2.7→5.3. The headline "32.8%" is a *relative* average. Open models were too weak to test on SWE-bench; on CrossCodeEval DeepSeek-Coder-V2-Lite went 10.2→19.7 EM. **[M]**
- **LocAgent** (https://arxiv.org/abs/2503.09089, ACL 2025). A heterogeneous graph of directories, files, classes and functions, with contain/import/invoke/inherit edges. Exposed as search/traverse/retrieve tools. A **fine-tuned Qwen2.5-Coder-32B** gets up to 92.7% file-level localization, near proprietary models, at about 86% lower cost, plus +12% Pass@10 on issue resolution. **[M]** This is the closest model-size match to Qwen3.8-27B, but it was fine-tuned.
- **CodexGraph** (https://arxiv.org/abs/2408.03910, NAACL 2025). Neo4j with LLM-written Cypher queries. It reports roughly 28% EM on CrossCodeEval Lite against about 21% for the best baseline, and about 23% on SWE-bench Lite, at 1.5–4× the tokens. **[U]**
- **GraphCoder** (https://ieeexplore.ieee.org/document/10765009): statement-level control/data-dependence graph, about +6 EM over sequence RAG for completion. **[U]**
- **CoSIL** (https://arxiv.org/abs/2503.22424). Iterative call-graph search with Qwen2.5-Coder-32B. Removing the graph search costs about 20% of performance. **[U]**
- **CodeCompass** (https://arxiv.org/abs/2602.20048). On hidden-dependency tasks, graph navigation reached 99.4%, against 76.2% for a vanilla agent and 78.2% for BM25. However, **58% of trials with graph access made zero graph calls.** **[W]**: one author, 30 tasks, one repo.

**Takeaway:** graphs help where dependencies lack **lexical overlap** (indirection, inheritance, route→handler). End-to-end gains are a few pp; optional graph tools often go unused.

## 2. Graph RAG for text

- **GraphRAG** (https://arxiv.org/abs/2404.16130): LLM-extracted entity graph plus community summaries; good for global sense-making, expensive to index. **[M]** **LightRAG** (https://arxiv.org/abs/2410.05779) is a cheaper variant evaluated mostly by LLM judges. **[W]**
- **HippoRAG / HippoRAG 2** (https://arxiv.org/abs/2502.14802, ICML 2025) seed **personalized PageRank** from query-matched nodes and passages. HippoRAG 2 is roughly +7 pts on associative multi-hop QA over strong embedding RAG and, unlike earlier graph RAGs, does not hurt simple factual QA. **[M]**, with the exact deltas **[U]**. This is the same algorithm as policy B.
- **Critiques.** RAG vs GraphRAG (https://arxiv.org/abs/2502.11371) finds the two complementary: graph wins on multi-hop, chunk RAG on detail. **[M]** GraphRAG-Bench (https://arxiv.org/abs/2506.05690, ICLR 2026) finds vanilla RAG equal or better on simple fact retrieval, with graphs helping on complex reasoning. Using graph context needs a reasoning threshold — relevant for small models. **[M]**

**Takeaway:** graphs for multi-hop/associative needs, plain retrieval for single facts.

## 3. Selective and gated retrieval; push vs pull

- **Repoformer** (https://arxiv.org/abs/2403.10059, ICML 2024). The code LM self-assesses whether retrieval will help. It makes the right decision more than 85% of the time, gives up to 70% online speedup, and is *more* accurate than always retrieving. **[M]**
- **CloudAPIBench** (https://arxiv.org/abs/2407.09726). Doc augmentation lifts low-frequency APIs from 38.6% to 47.9% for GPT-4o, but with weak retrievers it **costs 39 pts on high-frequency APIs**. Gating on an API-index check or on confidence recovers +8.2 pts overall. **[M]** This directly supports E's gating.
- **Self-RAG** (https://arxiv.org/abs/2310.11511) and **Adaptive-RAG** (https://arxiv.org/abs/2403.14403) gate retrieval with trained critics/classifiers. **[M]**
- **CodeRAG-Bench** (https://arxiv.org/abs/2406.14497). Good context helps, with the largest gains for weak models (StarCoder2-7B). Retrievers fail when lexical overlap is low, and generators often fail to *use* extra context. **[M]**
- **Push vs pull.** Cursor reports semantic search combined with grep beats grep alone by 12.5% on average, ranging 6.5–23.5% by model (https://cursor.com/blog/semsearch). **[W]** (vendor). Anthropic recommends just-in-time pull plus a light pushed index (https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents). **[W]** ContextBench (below) finds elaborate scaffolds barely beat mini-SWE-agent at retrieval. **[M]** CodeCompass's 58% non-use argues for **pushing** graph-derived context rather than hoping a small model pulls it. **[W]** No controlled push-vs-pull study at ~27B found.

## 4. Context-length degradation

- **Lost in the Middle** (https://arxiv.org/abs/2307.03172, TACL). Accuracy is U-shaped by position, and middle placement can fall below closed-book performance. **[S]**
- **RULER** (https://arxiv.org/abs/2404.06654). Only about half of the models that claim 32K+ context hold up at 32K. **[S]**
- **NoLiMa** (https://arxiv.org/abs/2502.05167, ICML 2025). When the needle has no literal overlap with the question, 11 of 13 models fall below 50% of their short-context score at 32K. GPT-4o drops from 99.3 to 69.7. **[S]** Code dependencies are often non-literal.
- **Context Rot** (Chroma, https://research.trychroma.com/context-rot). In 18 models including Qwen3, performance falls non-uniformly with length even on trivial tasks, and semantically similar distractors hurt. **[M]**; the per-distractor numbers are **[U]**.
- **Code-specific.** RepoExec (https://arxiv.org/abs/2406.11927) finds full *dependency* context helps. Stale or irrelevant snippets bias models (https://arxiv.org/abs/2507.14791). **[W]** I found no 27B-quantized stress curve. K1 must measure the knee itself.

**Implications:** 4–8K is sensible; once essentials are covered, precision beats recall. Stable reference first (prefix cache), anchor and ask **last**, nothing critical mid-context. Near-miss distractors (similarly named functions) are the dangerous kind.

## 5. Rendering and compression

- **Aider repo map** (https://aider.chat/docs/repomap.html). A tree-sitter def/ref graph ranked by PageRank and personalized to chat files, rendered as signatures within a token budget (1K by default). Baseline for policy B. **[W]**: no published ablation.
- **LLMLingua / LongLLMLingua** (https://arxiv.org/abs/2310.05736, https://arxiv.org/abs/2310.06839) prune tokens by perplexity, which is risky for code syntax. **LongCodeZip** (https://arxiv.org/abs/2510.00446, ASE 2025) instead keeps functions ranked by conditional perplexity and then selects blocks. It reports about 4–5.6× compression with no loss on Qwen2.5-Coder-7B. **[M]** Function-granular selection beats token-level pruning for code.
- Skeleton views (signatures plus docstrings, bodies elided) are used by Agentless (https://arxiv.org/abs/2407.01489) for localization, and full bodies only for edit targets. **[M]**

## 6. Agent memory and lessons

- **Reflexion** (https://arxiv.org/abs/2303.11366): within-task self-reflection, 91% HumanEval (GPT-4). **[M]** **ExpeL** (https://arxiv.org/abs/2308.10144): cross-task insights plus retrieved trajectories, modest transfer. **[M]**
- **Agent Workflow Memory** (https://arxiv.org/abs/2409.07429, ICML 2025). Induced reusable workflows give +51.1% relative on WebArena and hold up on cross-template splits. **[M]**
- **Coding.** SWE-Exp (https://arxiv.org/abs/2507.23361) reports 41.6% on SWE-bench Verified with an experience bank, and ReasoningBank (https://research.google/blog/reasoningbank-enabling-agents-to-learn-from-experience/) reports +4.6% on SWE-bench Verified. Both are **[W/U]**: there are no strong no-memory ablations at small scale.
- **Noise risk.** "Experience-following" (https://arxiv.org/abs/2505.16067, ACL 2026): agents copy retrieved records whose inputs look similar, so bad memories **propagate errors**, and noisy initial memory degrades performance quickly. Selective addition gated by evaluator or test outcomes gives about +10% over naive growth. **[M]**

**Takeaway:** store only test-verified lessons, promote on recurrence, key retrieval on error signature rather than task similarity.

## 7. Offline retrieval evaluation

- **SWE-bench gold patches → gold files and functions** is the standard source of localization labels (Agentless, LocAgent, CoSIL). LocAgent also releases **Loc-Bench**, built to avoid contamination. **[S]** as practice.
- **ContextBench** (https://arxiv.org/abs/2602.05892). 1,136 tasks with human-annotated gold context. It measures recall and precision at file, block and line level, plus AUC-coverage (how early gold context is found) and redundancy. Frontier models score below 0.45 block-F1. **[M]** Copy its metrics.
- **Caveat:** patches show what was *edited*, not what had to be *read* (callee signatures, API facts). Gold should combine edited symbols, 1-hop dependencies the patch uses, and APIs called in new code, tiered must/nice.

## Recommended first experiments for K1–K4

1. **K1:** Build gold context from 30–50 reference solutions in three tiers: edited symbols (must), used callees and types (should), external APIs called (API). Score recall@budget at 2K, 4K and 8K, plus precision and tokens.
2. **K1:** Run a context stress test on Qwen3.8-27B (Q4/Q8 KV). Keep the gold slice fixed and add 0, 2, 8 and 32K tokens of distractors, both random and **near-miss** (same-name or sibling functions). Vary the position (start, middle, end) to find the knee.
3. **K2:** Compare policies A, B (Aider-style PPR), C (typed walk, k≤2, per-edge budgets) and D (embedding top-k) offline on the same gold set. Report which edge types carry the recall.
4. **K2:** Rendering ablation at a fixed budget: skeleton for context with full body for the anchor, against full bodies everywhere. Measure how much more gold fits and the effect on pass rate.
5. **K3:** API-doc gating: no docs, always docs, or docs only when the import/attribute check fails or the API is rare. Reproduce CloudAPIBench's harm-on-common-APIs effect on our model.
6. **K4:** Push vs pull end to end: (a) push only the C slice, (b) a minimal push plus `read`/`search` tools, (c) both. Log how often tools are called to detect CodeCompass-style non-use.
7. **K4:** Ordering: stable catalog and repo-map first, then the working set, with the anchor and ask last. Compare against anchor-first for both accuracy and prefix-cache hit rate.
8. **K5 pilot:** compare a test-gated lesson store against an ungated one on repeated-error tasks, and measure regressions from wrong lessons.

## Things to avoid

- Building an LLM-extracted entity graph (GraphRAG-style) for code. AST, import and call extraction is cheaper and exact.
- Making the small model write graph queries (Cypher, as in CodexGraph), or relying on it to choose to call graph tools.
- k≥3 hops (RepoGraph found them noisy).
- Unconditional doc or memory injection; both hurt the common case.
- Judging policies by relative-percent headlines. Report absolute pp and tokens.
- Token-level compression (LLMLingua-style) of code that the model must edit.
- Trusting the large claimed context window: measure the 27B model's effective window.
- Storing unverified lessons or trajectories. They propagate errors.
