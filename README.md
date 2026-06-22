# headroom-poc

A standalone, config-driven **evaluation harness** for the
[Headroom](https://headroom-docs.vercel.app/docs) compression library. It measures
Headroom's central claim — *"100% Accuracy, 87% Token Reduction — same answers,
fraction of the tokens"* — against its documented, admittedly **lossy** mechanism,
over **JSON** and **plain-text** inputs.

This is an eval harness, not a product. Read [`CLAUDE.md`](CLAUDE.md) (operating
brief) and [`IMPLEMENTATION_LOG.md`](IMPLEMENTATION_LOG.md) (decisions, the
claims-under-test matrix, and the **verified `headroom-ai==0.26.0` API surface** —
which diverges from the published docs) before changing anything.

## Architecture

Compression and inference are **decoupled** (D3). Headroom only compresses; model
calls go through **boto3 Bedrock** directly, so the harness owns and compares both
legs.

```
input (JSON/prose) ──▶ Headroom compress()/simulate()/SmartCrusher/Universal
                          │  (token stats + waste signals + fidelity metrics)
                          ▼
        (bedrock mode)  boto3 Bedrock: original ctx  vs  compressed ctx
                          ▼
        LLM-as-judge (structured equivalence) + deterministic fact overlap
                          ▼
                   Rich report  +  results/<timestamp>/run.json
```

## Install

```powershell
python -m pip install -r requirements.txt
# Optional, only when testing LLMLingua (~2 GB weights):
#   python -m pip install "headroom-ai[llmlingua]"
```

Pinned to **`headroom-ai==0.26.0`** / Python 3.10.

## Run

Everything is driven by [`config/config.toml`](config/config.toml), which is
**re-read on every run** (D7) — edit it between runs to tune any tested parameter.

```powershell
# Simulation mode (default): local transforms only, no AWS, no cost, no latency.
python -m cli.main

# Point at a different config, or override the mode for one run:
python -m cli.main --config config/config.toml
python -m cli.main --mode bedrock

# Skip the Rich tables (still writes results/<timestamp>/run.json):
python -m cli.main --no-render
```

### Modes

- **simulation** — runs the compression leg only: `compress()`,
  `TransformPipeline.simulate()`, `SmartCrusher`, `UniversalCompressor`. Reports
  token reduction, waste signals, forward-pass diff classification, verbatim-quote
  survival, and SmartCrusher reversibility.
- **bedrock** — additionally runs the inference + judge legs. Requires
  `[bedrock].enabled=true` plus a `region` and `model_id` in the config, and AWS
  credentials in the environment/profile (**never committed** — Guardrail 5).
  Captures token usage from **both** Headroom and the Bedrock responses.

## Inputs

Test data is **both** synthetic defaults and your own files (D6):

```
data/json/*.json        # JSON-array inputs (SmartCrusher etc.)
data/text/*.{txt,md}    # prose inputs (compress / universal; accuracy & verbatim)
```

With `run.inputs = ["auto"]` the harness loads everything under `data/`, generating
seeded synthetic defaults there on first run (an event-log JSON array with
errors/anomalies/repetition, and a contract-summary prose doc with load-bearing
IDs, quoted clauses, and `$` amounts). List explicit paths instead of `"auto"` to
target specific files.

## Output

- **`results/<timestamp>/run.json`** — full, durable capture: meta (library
  version, tokenizer), the exact config used, per-feature compression results,
  fidelity metrics, and (in bedrock mode) accuracy answers + judge verdicts.
- **Rich tables** in the terminal: token reduction, fidelity, and accuracy.

## Layout

```
cli/        # config-driven entry point (re-reads config each run)
harness/    # config, tokens, compressors, metrics, bedrock, judge, datagen, report
config/     # config.toml — every tested Headroom param + Bedrock model/region
data/       # synthetic defaults + user-provided JSON/text samples
results/    # per-run JSON captures (git-ignored)
```

## Caveats surfaced by the harness

- **Token counts are estimates** for Claude/Bedrock models (no exact tokenizer is
  bundled; `get_tokenizer` returns an `EstimatingTokenCounter`).
- **The Kompress neural text rewriter fails on this CPU** (ONNX 4-bit-quant matmul
  unsupported); `compress()` falls back to `router:noop` for prose. This is
  captured, not hidden (D13). `UniversalCompressor` defaults to `use_kompress=false`.
- **Byte-exact `retrieve()` remains unverified** (Guardrail 2). SmartCrusher's
  `lossless:table` strategy is, however, checked for reversibility directly by
  reconstructing the array.
- The forward pass is **lossy by design** — the harness flags paraphrase/rewrite
  and any load-bearing string that does not survive verbatim.
```
