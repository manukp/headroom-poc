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

## 5. Changelog

- **2026-06-20** — Decisions D1–D7 recorded. Headroom docs reviewed (api-reference,
  simulation, text-and-logs, smart-crusher) and the API cheat-sheet captured in
  [`CLAUDE.md`](CLAUDE.md).
- **2026-06-21** — Authored `CLAUDE.md` and this `IMPLEMENTATION_LOG.md`. No harness code yet.
