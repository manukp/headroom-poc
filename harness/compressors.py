"""Compression runners — one per Headroom feature under test.

Each runner takes a normalized Input plus the parsed Config and returns a plain
dict (JSON-serializable) capturing what the installed library actually did:
token deltas, transforms, waste signals, and fidelity metrics. Headroom only
compresses here — inference is a separate leg (D3).

Coded against the verified headroom-ai==0.26.0 API (IMPLEMENTATION_LOG §6).
"""

from __future__ import annotations

import json
import traceback
from typing import Any

import headroom
from headroom import CompressConfig, SmartCrusher, SmartCrusherConfig, TransformPipeline
from headroom import RelevanceScorerConfig
from headroom.compression import UniversalCompressor, UniversalCompressorConfig

from . import metrics, tokens
from .config import Config
from .datagen import Input


def _verbatim_targets(cfg: Config, text: str) -> list[str]:
    """Configured load-bearing strings + auto-extracted ones, de-duplicated."""
    targets = list(cfg.verbatim_strings)
    for s in metrics.extract_load_bearing(text):
        if s not in targets:
            targets.append(s)
    return targets


# --------------------------------------------------------------------------- #
# compress()  (whole-message optimization)
# --------------------------------------------------------------------------- #
def run_compress(inp: Input, cfg: Config) -> dict[str, Any]:
    text = inp.as_text()
    messages = inp.as_messages()
    c = cfg.compress
    conf = CompressConfig(
        compress_user_messages=c.compress_user_messages,
        compress_system_messages=c.compress_system_messages,
        protect_recent=c.protect_recent,
        protect_analysis_context=c.protect_analysis_context,
        target_ratio=c.target_ratio,
        min_tokens_to_compress=c.min_tokens_to_compress,
        kompress_model=c.kompress_model,
        savings_profile=c.savings_profile,
    )
    res = headroom.compress(
        messages,
        model=cfg.compress_model,
        model_limit=cfg.model_limit,
        optimize=c.optimize,
        config=conf,
    )
    compressed_text = _messages_text(res.messages)
    targets = _verbatim_targets(cfg, text)
    return {
        "feature": "compress",
        "ok": True,
        "tokens_before": res.tokens_before,
        "tokens_after": res.tokens_after,
        "tokens_saved": res.tokens_saved,
        "compression_ratio": round(res.compression_ratio, 4),
        "savings_percent": round(res.compression_ratio * 100, 2),
        "transforms_applied": list(res.transforms_applied),
        "diff": metrics.classify_diff(text, compressed_text),
        "verbatim": metrics.check_verbatim(targets, compressed_text).as_dict(),
        "tokenizer": tokens.counter_name(cfg.compress_model),
    }


# --------------------------------------------------------------------------- #
# simulation  (TransformPipeline.simulate -> TransformResult)
# --------------------------------------------------------------------------- #
def run_simulation(inp: Input, cfg: Config) -> dict[str, Any]:
    messages = inp.as_messages()
    pipeline = TransformPipeline()
    res = pipeline.simulate(messages, model=cfg.compress_model, model_limit=cfg.model_limit)
    before = getattr(res, "tokens_before", 0)
    after = getattr(res, "tokens_after", 0)
    waste = getattr(res, "waste_signals", {}) or {}
    if not isinstance(waste, dict):  # WasteSignals dataclass -> dict
        waste = {k: getattr(waste, k) for k in dir(waste)
                 if k.endswith("_tokens") and not k.startswith("_")}
    return {
        "feature": "simulation",
        "ok": True,
        "tokens_before": before,
        "tokens_after": after,
        "tokens_saved": before - after,
        "savings_percent": round(tokens.ratio(before, after) * 100, 2),
        "transforms_applied": list(getattr(res, "transforms_applied", []) or []),
        "transforms_summary": _stringify(getattr(res, "transforms_summary", None)),
        "waste_signals": {k: int(v) for k, v in waste.items() if isinstance(v, (int, float))},
        "warnings": list(getattr(res, "warnings", []) or []),
    }


# --------------------------------------------------------------------------- #
# SmartCrusher  (JSON arrays)
# --------------------------------------------------------------------------- #
def run_smart_crusher(inp: Input, cfg: Config) -> dict[str, Any]:
    data = inp.as_json()
    if not isinstance(data, list):
        return {"feature": "smart_crusher", "ok": False,
                "skipped": "input is not a JSON array"}

    sc = cfg.smart_crusher
    rel = RelevanceScorerConfig(
        tier=sc.relevance.tier,
        bm25_k1=sc.relevance.bm25_k1,
        bm25_b=sc.relevance.bm25_b,
        hybrid_alpha=sc.relevance.hybrid_alpha,
        adaptive_alpha=sc.relevance.adaptive_alpha,
        relevance_threshold=sc.relevance.relevance_threshold,
    )
    conf = SmartCrusherConfig(
        enabled=sc.enabled,
        min_items_to_analyze=sc.min_items_to_analyze,
        min_tokens_to_crush=sc.min_tokens_to_crush,
        variance_threshold=sc.variance_threshold,
        uniqueness_threshold=sc.uniqueness_threshold,
        similarity_threshold=sc.similarity_threshold,
        max_items_after_crush=sc.max_items_after_crush,
        preserve_change_points=sc.preserve_change_points,
        factor_out_constants=sc.factor_out_constants,
        include_summaries=sc.include_summaries,
        use_feedback_hints=sc.use_feedback_hints,
        toin_confidence_threshold=sc.toin_confidence_threshold,
        dedup_identical_items=sc.dedup_identical_items,
        first_fraction=sc.first_fraction,
        last_fraction=sc.last_fraction,
        lossless_min_savings_ratio=sc.lossless_min_savings_ratio,
        relevance=rel,
    )
    crusher = SmartCrusher(config=conf)
    original_json = json.dumps(data)
    result = crusher.crush(original_json, query=sc.query, bias=sc.bias)

    compressed = result.compressed
    before = tokens.count_text(original_json, cfg.compress_model)
    after = tokens.count_text(compressed, cfg.compress_model)
    targets = _verbatim_targets(cfg, original_json)
    return {
        "feature": "smart_crusher",
        "ok": True,
        "items": len(data),
        "query": sc.query,
        "strategy": result.strategy,
        "was_modified": bool(result.was_modified),
        "tokens_before": before,
        "tokens_after": after,
        "tokens_saved": before - after,
        "savings_percent": round(tokens.ratio(before, after) * 100, 2),
        "verbatim": metrics.check_verbatim(targets, compressed).as_dict(),
        "reversibility": metrics.reversibility_from_crush(
            original_json, compressed, result.strategy),
        "compressed_preview": compressed[:280],
    }


# --------------------------------------------------------------------------- #
# UniversalCompressor  (structure-aware text/JSON/code/log)
# --------------------------------------------------------------------------- #
def run_universal(inp: Input, cfg: Config) -> dict[str, Any]:
    u = cfg.universal
    conf = UniversalCompressorConfig(
        use_magika=u.use_magika,
        use_kompress=u.use_kompress,
        use_entropy_preservation=u.use_entropy_preservation,
        entropy_threshold=u.entropy_threshold,
        min_content_length=u.min_content_length,
        compression_ratio_target=u.compression_ratio_target,
        ccr_enabled=u.ccr_enabled,
    )
    uc = UniversalCompressor(conf)
    text = inp.as_text()
    res = uc.compress(text)
    targets = _verbatim_targets(cfg, text)
    return {
        "feature": "universal",
        "ok": True,
        "content_type": str(res.content_type),
        "detection_confidence": round(float(res.detection_confidence), 4),
        "handler_used": res.handler_used,
        "tokens_before": res.tokens_before,
        "tokens_after": res.tokens_after,
        "tokens_saved": res.tokens_before - res.tokens_after,
        "compression_ratio": round(float(res.compression_ratio), 4),
        "savings_percent": round((1 - res.compression_ratio) * 100, 2),
        "preservation_ratio": round(float(res.preservation_ratio), 4),
        "ccr_key": res.ccr_key,
        "diff": metrics.classify_diff(text, res.compressed),
        "verbatim": metrics.check_verbatim(targets, res.compressed).as_dict(),
    }


# --------------------------------------------------------------------------- #
# LLMLingua  (optional; probed against the *installed* library, not the docs)
# --------------------------------------------------------------------------- #
def _find_llmlingua_compressor() -> tuple[Any, Any] | None:
    """Locate a headroom LLMLingua compressor class + its config, if present.

    The published docs show ``from headroom.transforms import LLMLinguaCompressor,
    LLMLinguaConfig`` (and a ``headroom-ai[llmlingua]`` extra), but none of that
    exists in the pinned 0.26.0 install: no extra is declared, and the string
    "LLMLingua" appears nowhere in the package. We probe the documented import
    path plus a couple of plausible fallbacks so this runner lights up
    automatically if a future version ships it, and otherwise reports the truth
    (D9: trust the installed library over the docs).
    """
    for mod_name in ("headroom.transforms", "headroom.compression", "headroom"):
        try:
            mod = importlib.import_module(mod_name)
        except Exception:
            continue
        cls = getattr(mod, "LLMLinguaCompressor", None)
        if cls is not None:
            conf_cls = getattr(mod, "LLMLinguaConfig", None)
            return cls, conf_cls
    return None


def run_llmlingua(inp: Input, cfg: Config) -> dict[str, Any]:
    if not cfg.llmlingua.enabled:
        return {"feature": "llmlingua", "ok": False,
                "skipped": "disabled in config ([llmlingua].enabled=false)"}

    found = _find_llmlingua_compressor()
    if found is None:
        # Accurate, version-specific diagnosis — not a generic "not installed".
        ver = getattr(headroom, "__version__", "?")
        return {
            "feature": "llmlingua",
            "ok": False,
            "skipped": (
                f"no LLMLingua compressor in installed headroom-ai=={ver}: the "
                "library declares no 'llmlingua' extra and ships no "
                "LLMLinguaCompressor/LLMLinguaConfig (docs cheat-sheet diverges "
                "from this version — see IMPLEMENTATION_LOG D12)."
            ),
        }

    cls, conf_cls = found
    lc = cfg.llmlingua
    compressor = cls(conf_cls(
        device=lc.device,
        code_compression_rate=lc.code_compression_rate,
        json_compression_rate=lc.json_compression_rate,
        text_compression_rate=lc.text_compression_rate,
    )) if conf_cls is not None else cls()

    text = inp.as_text()
    res = compressor.compress(text)
    # Normalize whatever shape the (future) API returns into our common dict.
    compressed = (getattr(res, "compressed", None)
                  or getattr(res, "compressed_prompt", None)
                  or getattr(res, "compressed_text", None)
                  or (res if isinstance(res, str) else ""))
    # Docs sample uses original_tokens/compressed_tokens; tolerate both spellings.
    before = getattr(res, "tokens_before", None) or getattr(res, "original_tokens", None)
    after = getattr(res, "tokens_after", None) or getattr(res, "compressed_tokens", None)
    if before is None:
        before = tokens.count_text(text, cfg.compress_model)
    if after is None:
        after = tokens.count_text(compressed, cfg.compress_model)
    targets = _verbatim_targets(cfg, text)
    return {
        "feature": "llmlingua",
        "ok": True,
        "device": lc.device,
        "tokens_before": before,
        "tokens_after": after,
        "tokens_saved": before - after,
        "savings_percent": round(tokens.ratio(before, after) * 100, 2),
        "diff": metrics.classify_diff(text, compressed),
        "verbatim": metrics.check_verbatim(targets, compressed).as_dict(),
        "note": "LLMLingua is lossy/paraphrase-ish by design (BERT token dropping).",
    }


RUNNERS = {
    "compress": run_compress,
    "simulation": run_simulation,
    "smart_crusher": run_smart_crusher,
    "universal": run_universal,
    "llmlingua": run_llmlingua,
}


def run_feature(feature: str, inp: Input, cfg: Config) -> dict[str, Any]:
    """Dispatch one feature against one input, catching failures as data."""
    runner = RUNNERS.get(feature)
    if runner is None:
        return {"feature": feature, "ok": False, "error": "unknown feature"}
    try:
        out = runner(inp, cfg)
    except Exception as exc:  # capture, never crash the whole run (Guardrail 4)
        return {
            "feature": feature,
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(limit=4),
        }
    out["input_id"] = inp.id
    out["input_kind"] = inp.kind
    return out


# --------------------------------------------------------------------------- #
def _messages_text(messages: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for m in messages:
        content = m.get("content", "")
        if isinstance(content, list):  # content blocks
            for block in content:
                if isinstance(block, dict):
                    parts.append(str(block.get("text", "")))
                else:
                    parts.append(str(block))
        else:
            parts.append(str(content))
    return "\n".join(parts)


def _stringify(v: Any) -> Any:
    if v is None or isinstance(v, (str, int, float, bool, list, dict)):
        return v
    return str(v)
