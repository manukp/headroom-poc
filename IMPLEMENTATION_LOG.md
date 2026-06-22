# IMPLEMENTATION_LOG.md — Headroom PoC

> Decision & risk ledger for the Headroom PoC. Companion to [`CLAUDE.md`](CLAUDE.md)
> (the operating brief). This file is the durable record of *why* things are the way they
> are, what we're testing, and what we don't yet trust.

## How to use this log

- **Append-only.** Add new dated entries; do not rewrite or delete history. If a decision is
  reversed, add a new entry that supersedes the old one and reference it.
- Date every entry `YYYY-MM-DD`. Convert relative dates to absolute.
- Decisions, the claims matrix, known issues, and the changelog all live here so they survive
  across sessions.

---

## 1. Decision log

| # | Date | Decision | Rationale |
|---|------|----------|-----------|
| D1 | 2026-06-20 | **Standalone PoC, library/`compress()` path only.** Proxy mode, MCP mode, and the TS SDK are out of scope. | The goal is to evaluate the compression library on its own terms, not to ship an integration. A live `headroom` MCP is a convenience wrapper, not the thing under test. |
| D2 | 2026-06-20 | **Tech stack: Python CLI + AWS Bedrock (boto3) + Rich.** Web UI / exporter for visualization deferred. | Matches the team's environment and keeps the harness simple; the final visualization surface can be chosen once eval scope is locked. |
| D3 | 2026-06-20 | **Decouple compression from inference.** Headroom only compresses (`compress`/`simulate`/transforms); model calls go through boto3 Bedrock directly. | Lets the harness own and measure both legs and compare them cleanly. Avoids coupling to Headroom's client-wrap/LiteLLM Bedrock path. |
| D4 | 2026-06-20 | **Bedrock model id + region are config-only.** | Keeps environment-specific choices out of source/docs; lets runs target different models without code changes. |
| D5 | 2026-06-20 | **Accuracy metric = LLM-as-judge over structured responses.** Tasks emit structured output; a Bedrock judge grades semantic/field equivalence of original-context vs compressed-context answers. Verbatim-quote survival tracked as a secondary signal. | "Same answers" is a downstream-equivalence claim; structured output + a judge makes equivalence objective, while verbatim tracking catches the load-bearing-text failure mode. |
| D6 | 2026-06-20 | **Test data = both** — ship synthetic JSON + prose defaults *and* load user-provided files from `data/`. | Synthetic gives reproducibility; user files let us stress real-world inputs. |
| D7 | 2026-06-20 | **Config-driven CLI; config re-read every run.** Every config param of every Headroom feature under test must be exposed. | Requirement from the project description; enables trial-and-error tuning between runs without restarts. |
| D8 | 2026-06-21 | **Pin `headroom-ai==0.26.0`** (installed locally, Python 3.10). | Claims/defaults are version-specific; this is the version actually under test. |
| D9 | 2026-06-21 | **Trust the installed library over the docs cheat-sheet.** §10 records the real 0.26.0 API surface; the CLAUDE.md cheat-sheet is treated as approximate. | Empirical introspection found large divergences (see §6 entry 2026-06-21). Guardrail 6 / §8 "verify against installed version" mandate this. |
| D10 | 2026-06-21 | **Config format = TOML**, loaded via `tomllib`/`tomli`; `""`/`0`/`0.0` are null-sentinels mapped to `None`. | `tomli` is already a transitive dep; TOML is hand-editable and has clear sections per feature. TOML lacks null, hence sentinels. |
| D11 | 2026-06-21 | **Simulation uses `TransformPipeline.simulate(...)` returning `TransformResult`**, not a top-level `simulate()` / `SimulationResult`. | No top-level `simulate` exists in 0.26.0; `TransformResult` carries the `waste_signals`/`transforms`/token fields we need. |
| D12 | 2026-06-21 | **Text compression path = `compress()` + `compression.UniversalCompressor`.** No `TextCompressor`/`LLMLinguaCompressor` classes exist; LLMLingua extra is **not installed**, runner is guarded/optional. | The doc-named classes are absent in 0.26.0; UniversalCompressor is the real structure-aware text/JSON/code compressor. |
| D13 | 2026-06-21 | **Default `use_kompress = false`** for UniversalCompressor; `compress()`'s kompress leg is allowed to run but its failure is captured, not fatal. | The Kompress ONNX model crashes on this CPU (4-bit-quant matmul unsupported); it would otherwise no-op silently. We record the failure as data rather than hiding it (Guardrail 4). |
| D14 | 2026-06-22 | **LLMLingua is unavailable in 0.26.0 — runner probes-and-reports, never silently skips.** `pip install "headroom-ai[llmlingua]"` is a **no-op**: 0.26.0 declares no `llmlingua` extra (pip warns `does not provide the extra 'llmlingua'`), ships no `LLMLinguaCompressor`/`LLMLinguaConfig` (the string "LLMLingua" appears nowhere in the package — incl. `headroom.transforms`, the docs' import path), and standalone `llmlingua` is not installed. `run_llmlingua` introspects `headroom.transforms`/`compression`/top-level for the class and, when absent, returns an accurate version-specific `skipped` reason; it auto-wires (config params → `LLMLinguaConfig`, result fields incl. `original_tokens`/`compressed_tokens`) if a future version ships it. | The docs sample (`from headroom.transforms import LLMLinguaCompressor, LLMLinguaConfig`) describes an API not present in the pinned version. Probing the installed library (D9) keeps the harness honest (Guardrail 4) and forward-compatible without claiming a feature we can't run. |

---

## 2. Claims-under-test matrix

> Each requirement from `Project Description.md` maps to a measurable check. Status starts at
> **todo**; update as the harness lands.

| Claim / requirement | Input | How measured | Pass criterion | Status |
|---|---|---|---|---|
| **87% token reduction** | JSON + prose | `compress()`/`simulate()` `tokens_before/after/saved`, `compression_ratio` | Reduction reported per input; compare to the 87% claim | todo |
| **100% accuracy / "same answers"** | ~300–500-word complex prompts | Bedrock answer on original ctx vs compressed ctx, **LLM-as-judge over structured output** | Judge marks structured answers equivalent | todo |
| **Forward-pass fidelity** | prose | Diff compressed vs original; classify delete-only vs paraphrase | Characterize aggressiveness; flag any rewriting | todo |
| **Verbatim-quote survival** | JSON + prose with load-bearing strings (IDs, quoted clauses) | Check exact strings survive compression and/or retrieval | Exact strings present, or restored exactly by `retrieve()` | todo |
| **Retrieval fidelity** | compressed outputs w/ `ccr_hashes` | `retrieve(hash)` returns vs original | **Byte-identical?** (undocumented — must test) | todo |
| **SmartCrusher (JSON)** | large JSON arrays | `crush(data, query=...)` keep/drop behavior vs `SmartCrusherConfig` | Preservation rules behave as documented | todo |
| **TextCompressor / LLMLingua (prose)** | prose/docs | run each; measure reduction + fidelity | Reduction vs fidelity trade-off recorded | todo |
| **Simulation waste signals** | mixed | `WasteSignals` (`json_bloat`, `html_noise`, `whitespace`, `dynamic_date`, `repetition`) | Signals populated and plausible vs input | todo |
| **Dual token capture on LLM runs** | any Bedrock run | Capture token stats from **both** Headroom result and Bedrock response | Both recorded per run | todo |

---

## 3. Guardrails

1. **The forward pass is lossy by design** — never assume compressed output preserves the
   input verbatim.
2. **Byte-exact `retrieve()` is unproven** — verify empirically; never assume.
3. **Keep compression separate from inference** — Headroom compresses; boto3 Bedrock runs the
   model; the harness owns the comparison.
4. **Never silently drop divergence** — record every original-vs-compressed difference and
   surface verbatim-quote loss explicitly.
5. **No credentials in the repo** — AWS creds via environment/profile only; nothing committed.
6. **Pin & record the `headroom-ai` version**; re-check claims if it changes.
7. **Config is the source of truth** — expose every tested feature's params; re-read config
   each run.

---

## 4. Known issues / risks / open questions

- **Marketing-vs-mechanism tension.** "100% / same answers" is a claim about *downstream
  answer equivalence*, **not** byte-exact preservation. The forward pass drops/rewrites
  "low-information" content by design. This gap is the entire point of the PoC.
- **`retrieve()` / CCR is under-documented.** `compress()` exposes `ccr_hashes` and the docs
  mention a `headroom_retrieve` agent tool, but there is **no documented guarantee of
  byte-identical return**, and the SmartCrusher page omits reversibility entirely. Byte-exact
  retrieval is **unverified — must be tested** against the installed version.
- **Bedrock integration mismatch.** Headroom's native Bedrock support is via
  client-wrapping / LiteLLM; we deliberately call Bedrock via boto3 ourselves (D3). Watch for
  **tokenizer / model-mapping caveats** when counting tokens for Bedrock models — Headroom's
  token counters are built around OpenAI/Anthropic/Google providers.
- **LLMLingua is lossy and heavy.** BERT-based token classification removes tokens by
  estimated importance (paraphrase-ish, not verbatim); adds ~2 GB weights and 50–200 ms
  latency. Optional extra (`headroom-ai[llmlingua]`) — install only when testing it.
- **Version sensitivity.** Documented claims/defaults may be version-specific. Pin the
  installed `headroom-ai` version and re-validate if it changes.
- **Judge reliability.** LLM-as-judge can mask real divergence (it may call genuinely
  different answers "equivalent"). Pair it with structured field comparison and verbatim-quote
  checks rather than trusting the judge alone.
- **Package name / install command unconfirmed.** Docs show `from headroom import compress`
  but don't state the exact PyPI name/command on the intro page (likely `headroom-ai`).
  Confirm on install and record here.
- **Visualization shape (web UI vs exporter script)** — open, deferred until eval scope is
  locked (D2).
- **Sample-data definition** — the synthetic-generator spec and the expected `data/` file
  format/layout for user-provided inputs still need to be designed.

---

## 6. Installed API reality (`headroom-ai==0.26.0`) — verified by introspection

> Captured 2026-06-21 by importing the installed package, **not** from the docs. Where this
> contradicts the CLAUDE.md §8 cheat-sheet, **this section wins** (D9). The harness is coded
> against these shapes.

**`compress(messages, model="claude-sonnet-4-5-20250929", model_limit=200000, optimize=True,
hooks=None, config=CompressConfig|None, **kwargs)` → `CompressResult`.**
- `CompressResult` fields: `messages`, `tokens_before`, `tokens_after`, `tokens_saved`,
  `compression_ratio`, `transforms_applied`. **No `ccr_hashes`, no `compressed` field** (the
  cheat-sheet lists these; they do not exist on the result here).
- `CompressConfig`: `compress_user_messages=False`, `compress_system_messages=True`,
  `protect_recent=4`, `protect_analysis_context=True`, `target_ratio=None`,
  `min_tokens_to_compress=250`, `kompress_model=None`, `savings_profile=None`.
- **Gotcha:** user messages are *protected by default* — a user-only prompt comes back as
  `transforms=['router:protected:user_message']` with 0 savings. Set
  `compress_user_messages=true` to compress prose carried in a user turn.

**Simulation:** no top-level `simulate()`. Use `TransformPipeline().simulate(messages, model,
model_limit=...)` → `TransformResult` with `tokens_before`, `tokens_after`,
`transforms_applied`, `transforms_summary`, `waste_signals` (a `dict`), `diff_artifact`,
`cache_metrics`, `timing`, `warnings`, `markers_inserted`. **`model_limit` is required.**
`HeadroomClient.simulate(...)` also exists but requires constructing a wrapped client.
- `WasteSignals` dataclass fields: `json_bloat_tokens`, `html_noise_tokens`, `base64_tokens`,
  `whitespace_tokens`, `dynamic_date_tokens`, `repetition_tokens`, `reread_tokens`,
  `reread_compressed_tokens` (cheat-sheet missed `base64`/`reread*`).

**SmartCrusher (JSON):** `SmartCrusher(config, relevance_config, scorer, ccr_config,
with_compaction, observer, compaction_format)`. `crush(content: str, query="", bias=1.0)`
takes a **JSON string** (not a list) → `CrushResult(compressed, original, strategy,
was_modified)`. `strategy` reports e.g. `lossless:table(60->len=1184)` — directly tells us
whether the transform was lossless. Also `crush_array_json`, `compact_document_json`,
`ccr_get(hash_key)`, `ccr_len()`.
- `SmartCrusherConfig` (real): `enabled`, `min_items_to_analyze=5`, `min_tokens_to_crush=200`,
  `variance_threshold=2.0`, `uniqueness_threshold=0.1`, `similarity_threshold=0.8`,
  `max_items_after_crush=15`, `preserve_change_points=True`, `factor_out_constants=False`,
  `include_summaries=False`, `use_feedback_hints=True`, `toin_confidence_threshold=0.3`,
  `relevance: RelevanceScorerConfig`, `anchor: AnchorConfig`, `dedup_identical_items=True`,
  `first_fraction=0.3`, `last_fraction=0.15`, `lossless_min_savings_ratio=0.3`. **None of the
  cheat-sheet names** (`keep_first/keep_last/relevance_threshold/anomaly_std_threshold/
  preserve_errors/relevance_tier/min_tokens_to_crush=200`-only) match except `min_tokens_to_crush`.
- `RelevanceScorerConfig`: `tier="hybrid"` (`bm25|embedding|hybrid`), `bm25_k1=1.5`,
  `bm25_b=0.75`, `embedding_model=<factory>`, `hybrid_alpha=0.5`, `adaptive_alpha=True`,
  `relevance_threshold=0.25`.

**Text compressors:** `TextCompressor` / `LLMLinguaCompressor` classes **do not exist** in
0.26.0. Real path: `compress()` (whole-message) and `compression.UniversalCompressor`
(`UniversalCompressorConfig`: `use_magika=True`, `use_kompress=True`,
`use_entropy_preservation=True`, `entropy_threshold=0.85`, `min_content_length=100`,
`compression_ratio_target=0.3`, `ccr_enabled=True`). Handles `ContentType`
{CODE,DIFF,JSON,LOG,MARKDOWN,TEXT,UNKNOWN}. **LLMLingua is absent from 0.26.0 entirely**
(see D14): no `llmlingua` extra is declared, the string "LLMLingua" appears nowhere in the
package (incl. `headroom.transforms`, the docs' import path), and standalone `llmlingua` is
not installed. The runner introspects for it and reports an accurate skip when missing.

**Tokenization:** `count_tokens_text(text, token_counter)` / `count_tokens_messages(messages,
token_counter)` need a concrete counter from `headroom.tokenizers.get_tokenizer(model)`.
`TokenCounter` is a Protocol (not instantiable). For Claude models `get_tokenizer` returns an
**`EstimatingTokenCounter`** (no exact Claude tokenizer bundled) — token counts for Claude/
Bedrock models are **estimates**, reinforcing the §4 tokenizer caveat.

**CCR / retrieval:** rich `headroom.ccr` module (MCP server, tool injection, context tracker)
but a plain `SmartCrusher.crush` leaves `ccr_len()==0` — CCR is **not auto-populated** in the
simple path. Byte-exact retrieval remains unverified (Guardrail 2); SmartCrusher's
`strategy=lossless:table` is, however, reversible by parsing the table back, which the harness
checks directly.

**Environment issue:** `compress()`/Kompress emits an ONNXRuntime error on this CPU —
`MatMulNBits ... Only 4b quantization is supported for unpacked compute` — and silently falls
back to `router:noop` for text. UniversalCompressor defaults `use_kompress=false` here (D13).

---

## 5. Changelog

- **2026-06-20** — Decisions D1–D7 recorded. Headroom docs reviewed (api-reference,
  simulation, text-and-logs, smart-crusher) and the API cheat-sheet captured in
  [`CLAUDE.md`](CLAUDE.md).
- **2026-06-21** — Authored `CLAUDE.md` and this `IMPLEMENTATION_LOG.md`. No harness code yet.
- **2026-06-21** — Introspected installed `headroom-ai==0.26.0`; recorded the real API surface
  (§6) and decisions D8–D13. Pinned the version in `requirements.txt`.
- **2026-06-21** — Scaffolded the harness: `config/config.toml` (every tested param exposed),
  `harness/` (config, tokens, compressors, metrics, bedrock, judge, datagen, report), `cli/`
  entry point, synthetic `data/` defaults, `results/`. Simulation mode runs end-to-end with no
  AWS creds; Bedrock + judge legs are wired but gated behind `[bedrock].enabled`.
