"""Headroom PoC CLI.

Config-driven (D7): the config file is RE-READ on every invocation, so editing
config/config.toml between runs takes effect with no restart/state. Two modes:

    simulation  (default) — local transform pipeline only; no AWS, no cost.
    bedrock                — additionally runs the inference + judge legs.

Usage (PowerShell-first):
    python -m cli.main
    python -m cli.main --config config/config.toml
    python -m cli.main --mode bedrock
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

# Allow running as `python cli/main.py` as well as `python -m cli.main`.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import headroom

from harness import compressors, report
from harness.config import load_config
from harness.datagen import load_inputs


def _parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="headroom-poc", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--config", default=None,
                   help="Path to config.toml (default: config/config.toml).")
    p.add_argument("--mode", choices=["simulation", "bedrock"], default=None,
                   help="Override run.mode for this invocation only.")
    p.add_argument("--no-render", action="store_true",
                   help="Skip Rich output; still writes results JSON.")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])

    # Re-read config fresh every run (D7).
    cfg = load_config(args.config)
    if args.mode:
        cfg.run.mode = args.mode

    notes: list[str] = []
    from harness import tokens
    meta: dict[str, Any] = {
        "headroom_version": getattr(headroom, "__version__", "?"),
        "tokenizer": tokens.counter_name(cfg.compress_model),
        "mode": cfg.run.mode,
        "features": cfg.run.features,
        "notes": notes,
    }
    if "Estimating" in meta["tokenizer"]:
        notes.append("Token counts are ESTIMATES (no exact Claude tokenizer bundled).")

    inputs = load_inputs(cfg.run.inputs, cfg.run.generate_synthetic_if_empty)
    if not inputs:
        print("No inputs resolved. Add files under data/ or set run.inputs.",
              file=sys.stderr)
        return 2

    # --- compression leg (always) ---------------------------------------- #
    results: list[dict[str, Any]] = []
    for inp in inputs:
        for feature in cfg.run.features:
            # SmartCrusher only applies to JSON arrays; skip prose cleanly.
            if feature == "smart_crusher" and inp.kind != "json":
                continue
            results.append(compressors.run_feature(feature, inp, cfg))

    # --- inference + judge leg (bedrock mode only) ----------------------- #
    accuracy: list[dict[str, Any]] = []
    judgements: list[dict[str, Any]] = []
    if cfg.run.mode == "bedrock":
        accuracy, judgements = _run_bedrock(cfg, inputs, notes)

    run_dir = report.write_run(cfg, results, accuracy, judgements, meta)
    if not args.no_render:
        report.render(cfg, results, accuracy, judgements, meta, run_dir)
    else:
        print(f"results written: {run_dir}")
    return 0


def _run_bedrock(cfg, inputs, notes) -> tuple[list[dict], list[dict]]:
    from harness import judge as judge_mod
    from harness.bedrock import BedrockClient, BedrockUnavailable, run_accuracy

    if not cfg.bedrock.enabled:
        notes.append("mode=bedrock but [bedrock].enabled=false — inference leg skipped.")
        return [], []
    try:
        client = BedrockClient(cfg)
    except BedrockUnavailable as exc:
        notes.append(f"Bedrock unavailable: {exc} — inference leg skipped.")
        return [], []

    accuracy: list[dict] = []
    judgements: list[dict] = []
    for inp in inputs:
        if inp.kind != "text":  # accuracy task targets prose prompts
            continue
        try:
            acc = run_accuracy(inp, cfg, client)
        except Exception as exc:  # capture, never crash (Guardrail 4)
            accuracy.append({"feature": "accuracy", "ok": False,
                             "input_id": inp.id, "error": f"{type(exc).__name__}: {exc}"})
            continue
        accuracy.append(acc)
        try:
            judgements.append(judge_mod.judge(acc, cfg, client))
        except Exception as exc:
            judgements.append({"input_id": inp.id, "verdict": {"equivalent": None},
                               "error": f"{type(exc).__name__}: {exc}"})
    return accuracy, judgements


if __name__ == "__main__":
    raise SystemExit(main())
