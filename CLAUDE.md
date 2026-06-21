# CLAUDE.md — Headroom PoC Operating Brief

> Always-loaded brief for any agent working in this repo. Read this before touching code.
> Companion file: [`IMPLEMENTATION_LOG.md`](IMPLEMENTATION_LOG.md) holds dated decisions,
> the claims-under-test matrix, and known issues.

## 1. Project overview

This is a **standalone proof-of-concept that evaluates the [Headroom](https://headroom-docs.vercel.app/docs)
compression library's central claim** — *"100% Accuracy, 87% Token Reduction — same answers,
fraction of the tokens"* — against its documented, admittedly **lossy** mechanism. The forward
compression pass drops/rewrites content it judges "low-information"; "nothing is lost" in the
docs means *recoverable via retrieval*, not *byte-exact*. The PoC's job is to turn that
tension into measured numbers over **JSON** and **plain-text** inputs. This is an evaluation
harness, not a product — no app, no integration into any other codebase.

## 2. Scope

**In scope** — the Python library path only:
- `compress()` and `retrieve()` APIs.
- `SmartCrusher` (JSON), `TextCompressor` and `LLMLinguaCompressor` (plain text).
- Simulation mode (local, no LLM call) + waste signals.
- Bedrock-driven task-equivalence ("100% accuracy") checks via boto3.

**Out of scope** — proxy mode, MCP mode, the TypeScript SDK, and any integration into the
ClauseLens app. A live `headroom` MCP server may be connected in-session; it is a convenience
wrapper and is **not** the object of evaluation.

## 3. Tech stack & key dependencies

- **Python CLI**, config-driven.
- **`headroom-ai`** — the library under test. **Pin the exact installed version** in
  `requirements.txt` and record it in [`IMPLEMENTATION_LOG.md`](IMPLEMENTATION_LOG.md);
  claims may be version-specific.
- **boto3** — AWS Bedrock calls for the inference leg.
- **Rich** — result visualization in the terminal. A web UI or exporter script may be added
  later (deferred — see log).
- **LLMLingua is an optional extra** — `pip install "headroom-ai[llmlingua]"`, ~2 GB model
  weights + 50–200 ms latency. Install only when that compressor is actually under test.

## 4. Architecture — compression and inference are decoupled

Headroom is used **only to compress**. The actual model calls go through **boto3 Bedrock
directly**, so the harness owns and measures both legs and can compare them. Headroom's own
Bedrock support (client-wrapping / LiteLLM) is deliberately **not** used for inference.

```
            ┌─────────────┐
 input ───▶ │  Headroom   │ ──▶ compressed messages + Headroom token stats
 (JSON/     │ compress()/ │       (compression_ratio, transforms_applied, waste signals)
  prose)    │ simulate()  │
            └─────────────┘
                  │
       ┌──────────┴───────────┐  (only in Bedrock mode)
       ▼                      ▼
  boto3 Bedrock          boto3 Bedrock
  (original ctx)         (compressed ctx)
       │                      │
       └────────┬─────────────┘
                ▼
        LLM-as-judge (structured equivalence)  ──▶  Rich report
```

In **simulation mode** the right half is skipped entirely (no cost, no creds, no latency).

## 5. Repo layout (planned — not yet created)

```
cli/        # config-driven entry point; re-reads config each run
harness/    # compression runners, Bedrock client, judge, diff/metrics
config/     # run configuration (all tested Headroom params + Bedrock model/region)
data/       # synthetic defaults + user-provided JSON/text samples
results/    # captured run output / reports
```

## 6. Configuration model

- The CLI is **config-driven**, and the config is **re-read on every run** so changes take
  effect without restarting.
- **Every configuration parameter of every Headroom feature under test must be exposed** in
  the config (see the cheat-sheet in §8 for the full parameter set and defaults).
- **Bedrock model id + region are config-only** — never hard-coded in source or docs; set per
  environment.

## 7. How to run

Two modes:

- **Simulation mode** — runs the full transform pipeline locally. No AWS credentials, no cost,
  no provider latency. Use this for token-reduction and waste-signal measurement.
- **Bedrock mode** — additionally makes boto3 Bedrock calls for the original-vs-compressed
  task-equivalence check. Requires AWS credentials (env/profile) and a configured model +
  region.

Examples are **PowerShell-first** (this is a Windows 11 environment); the Bash tool is also
available for POSIX scripts. Concrete commands will be added when the CLI is scaffolded.

## 8. Headroom API cheat-sheet

> Sourced from the Headroom docs (api-reference, simulation, text-and-logs, smart-crusher).
> Anything the docs leave ambiguous is marked **verify against installed version** — confirm
> empirically, do not state as fact.

**`compress(messages, model=...)`** → result with:
`messages` (compressed, same shape), `tokens_before`, `tokens_after`, `tokens_saved`,
`compression_ratio`, `transforms_applied`, `ccr_hashes`, `compressed`.

**Simulation** → `SimulationResult`: `tokens_before`, `tokens_after`, `tokens_saved`,
`savings_percent`, `transforms_applied`, `waste_signals`.
`WasteSignals`: `json_bloat_tokens`, `html_noise_tokens`, `whitespace_tokens`,
`dynamic_date_tokens`, `repetition_tokens`.

**`SmartCrusher().crush(data, query=...)`** (JSON arrays) — `SmartCrusherConfig` defaults:

| Param | Default | Purpose |
|---|---|---|
| `min_tokens_to_crush` | `200` | Compression threshold |
| `max_items_after_crush` | `50` | Max retained items |
| `keep_first` | `3` | Always keep first N |
| `keep_last` | `2` | Always keep last N |
| `relevance_threshold` | `0.3` | Query-match cutoff |
| `anomaly_std_threshold` | `2.0` | Outlier detection (std devs) |
| `preserve_errors` | `True` | Always keep error items |
| `relevance_tier` | `"bm25"` | `bm25` \| `embedding` \| `hybrid` |

**`TextCompressor().compress(text, context=...)`** — keeps context-relevant paragraphs,
headers, and document structure; drops filler. No documented config class.

**`LLMLinguaCompressor(LLMLinguaConfig(...))`** — `LLMLinguaConfig` defaults:
`device="auto"` (`cuda`|`cpu`|`mps`), `code_compression_rate=0.4`,
`json_compression_rate=0.35`, `text_compression_rate=0.25`. BERT-based token dropping —
**lossy / paraphrase-ish, not verbatim.**

**`retrieve()` / CCR** — **under-documented.** `compress()` returns `ccr_hashes`; the docs
describe a `headroom_retrieve` agent tool but make **no guarantee of byte-identical return**,
and the SmartCrusher page omits reversibility entirely. **Treat byte-exact retrieval as
unverified — must be tested.**

## 9. Guardrails (must-follow)

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

## 10. Working conventions

- Windows 11 / PowerShell primary; Bash tool available for POSIX scripts.
- Do not commit AWS credentials or any secret.
- Record the installed `headroom-ai` version anywhere claims are evaluated.
- Keep the compression leg and the inference leg as separate, independently testable code.
- Log decisions and newly discovered issues in [`IMPLEMENTATION_LOG.md`](IMPLEMENTATION_LOG.md)
  rather than letting them live only in chat.
