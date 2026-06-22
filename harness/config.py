"""Config loading. The config is the source of truth and is RE-READ every run (D7).

TOML has no null, so empty-string / 0 / 0.0 act as null sentinels on optional
fields (D10). This module exposes typed dataclasses plus the raw dict so report
output can echo exactly what was used.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:  # py311+
    import tomllib as _toml
except ModuleNotFoundError:  # py310
    import tomli as _toml  # type: ignore


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = REPO_ROOT / "config" / "config.toml"


def _opt_str(v: Any) -> str | None:
    """Map "" -> None for optional string fields."""
    s = (v or "").strip() if isinstance(v, str) else v
    return s or None


def _opt_float(v: Any) -> float | None:
    """Map 0 / 0.0 -> None for optional float fields."""
    return float(v) if v else None


@dataclass
class CompressCfg:
    optimize: bool = True
    compress_user_messages: bool = True
    compress_system_messages: bool = True
    protect_recent: int = 4
    protect_analysis_context: bool = True
    target_ratio: float | None = None
    min_tokens_to_compress: int = 250
    kompress_model: str | None = None
    savings_profile: str | None = None


@dataclass
class RelevanceCfg:
    tier: str = "hybrid"
    bm25_k1: float = 1.5
    bm25_b: float = 0.75
    hybrid_alpha: float = 0.5
    adaptive_alpha: bool = True
    relevance_threshold: float = 0.25


@dataclass
class SmartCrusherCfg:
    enabled: bool = True
    min_items_to_analyze: int = 5
    min_tokens_to_crush: int = 200
    variance_threshold: float = 2.0
    uniqueness_threshold: float = 0.1
    similarity_threshold: float = 0.8
    max_items_after_crush: int = 15
    preserve_change_points: bool = True
    factor_out_constants: bool = False
    include_summaries: bool = False
    use_feedback_hints: bool = True
    toin_confidence_threshold: float = 0.3
    dedup_identical_items: bool = True
    first_fraction: float = 0.3
    last_fraction: float = 0.15
    lossless_min_savings_ratio: float = 0.3
    query: str = ""
    bias: float = 1.0
    relevance: RelevanceCfg = field(default_factory=RelevanceCfg)


@dataclass
class UniversalCfg:
    enabled: bool = True
    use_magika: bool = True
    use_kompress: bool = False
    use_entropy_preservation: bool = True
    entropy_threshold: float = 0.85
    min_content_length: int = 100
    compression_ratio_target: float = 0.3
    ccr_enabled: bool = True


@dataclass
class LLMLinguaCfg:
    enabled: bool = False
    device: str = "auto"
    code_compression_rate: float = 0.4
    json_compression_rate: float = 0.35
    text_compression_rate: float = 0.25


@dataclass
class BedrockCfg:
    enabled: bool = False
    region: str | None = None
    model_id: str | None = None
    judge_model_id: str | None = None
    max_tokens: int = 1024
    temperature: float = 0.0
    anthropic_version: str = "bedrock-2023-05-31"


@dataclass
class RunCfg:
    mode: str = "simulation"
    features: list[str] = field(default_factory=lambda: ["compress", "simulation"])
    inputs: list[str] = field(default_factory=lambda: ["auto"])
    generate_synthetic_if_empty: bool = True
    results_dir: str = "results"


@dataclass
class Config:
    run: RunCfg
    compress_model: str
    model_limit: int
    compress: CompressCfg
    smart_crusher: SmartCrusherCfg
    universal: UniversalCfg
    llmlingua: LLMLinguaCfg
    bedrock: BedrockCfg
    verbatim_strings: list[str]
    raw: dict[str, Any]
    path: Path


def load_config(path: str | os.PathLike[str] | None = None) -> Config:
    """Read and parse the config fresh from disk. Call once per run (D7)."""
    cfg_path = Path(path) if path else DEFAULT_CONFIG_PATH
    with open(cfg_path, "rb") as fh:
        raw = _toml.load(fh)

    run = raw.get("run", {})
    model = raw.get("model", {})
    cmp = raw.get("compress", {})
    sc = raw.get("smart_crusher", {})
    rel = sc.get("relevance", {})
    uni = raw.get("universal", {})
    lll = raw.get("llmlingua", {})
    br = raw.get("bedrock", {})
    vb = raw.get("verbatim", {})

    return Config(
        run=RunCfg(
            mode=run.get("mode", "simulation"),
            features=list(run.get("features", ["compress", "simulation"])),
            inputs=list(run.get("inputs", ["auto"])),
            generate_synthetic_if_empty=bool(run.get("generate_synthetic_if_empty", True)),
            results_dir=run.get("results_dir", "results"),
        ),
        compress_model=model.get("compress_model", "claude-sonnet-4-5-20250929"),
        model_limit=int(model.get("model_limit", 200000)),
        compress=CompressCfg(
            optimize=bool(cmp.get("optimize", True)),
            compress_user_messages=bool(cmp.get("compress_user_messages", True)),
            compress_system_messages=bool(cmp.get("compress_system_messages", True)),
            protect_recent=int(cmp.get("protect_recent", 4)),
            protect_analysis_context=bool(cmp.get("protect_analysis_context", True)),
            target_ratio=_opt_float(cmp.get("target_ratio", 0.0)),
            min_tokens_to_compress=int(cmp.get("min_tokens_to_compress", 250)),
            kompress_model=_opt_str(cmp.get("kompress_model", "")),
            savings_profile=_opt_str(cmp.get("savings_profile", "")),
        ),
        smart_crusher=SmartCrusherCfg(
            enabled=bool(sc.get("enabled", True)),
            min_items_to_analyze=int(sc.get("min_items_to_analyze", 5)),
            min_tokens_to_crush=int(sc.get("min_tokens_to_crush", 200)),
            variance_threshold=float(sc.get("variance_threshold", 2.0)),
            uniqueness_threshold=float(sc.get("uniqueness_threshold", 0.1)),
            similarity_threshold=float(sc.get("similarity_threshold", 0.8)),
            max_items_after_crush=int(sc.get("max_items_after_crush", 15)),
            preserve_change_points=bool(sc.get("preserve_change_points", True)),
            factor_out_constants=bool(sc.get("factor_out_constants", False)),
            include_summaries=bool(sc.get("include_summaries", False)),
            use_feedback_hints=bool(sc.get("use_feedback_hints", True)),
            toin_confidence_threshold=float(sc.get("toin_confidence_threshold", 0.3)),
            dedup_identical_items=bool(sc.get("dedup_identical_items", True)),
            first_fraction=float(sc.get("first_fraction", 0.3)),
            last_fraction=float(sc.get("last_fraction", 0.15)),
            lossless_min_savings_ratio=float(sc.get("lossless_min_savings_ratio", 0.3)),
            query=sc.get("query", ""),
            bias=float(sc.get("bias", 1.0)),
            relevance=RelevanceCfg(
                tier=rel.get("tier", "hybrid"),
                bm25_k1=float(rel.get("bm25_k1", 1.5)),
                bm25_b=float(rel.get("bm25_b", 0.75)),
                hybrid_alpha=float(rel.get("hybrid_alpha", 0.5)),
                adaptive_alpha=bool(rel.get("adaptive_alpha", True)),
                relevance_threshold=float(rel.get("relevance_threshold", 0.25)),
            ),
        ),
        universal=UniversalCfg(
            enabled=bool(uni.get("enabled", True)),
            use_magika=bool(uni.get("use_magika", True)),
            use_kompress=bool(uni.get("use_kompress", False)),
            use_entropy_preservation=bool(uni.get("use_entropy_preservation", True)),
            entropy_threshold=float(uni.get("entropy_threshold", 0.85)),
            min_content_length=int(uni.get("min_content_length", 100)),
            compression_ratio_target=float(uni.get("compression_ratio_target", 0.3)),
            ccr_enabled=bool(uni.get("ccr_enabled", True)),
        ),
        llmlingua=LLMLinguaCfg(
            enabled=bool(lll.get("enabled", False)),
            device=lll.get("device", "auto"),
            code_compression_rate=float(lll.get("code_compression_rate", 0.4)),
            json_compression_rate=float(lll.get("json_compression_rate", 0.35)),
            text_compression_rate=float(lll.get("text_compression_rate", 0.25)),
        ),
        bedrock=BedrockCfg(
            enabled=bool(br.get("enabled", False)),
            region=_opt_str(br.get("region", "")),
            model_id=_opt_str(br.get("model_id", "")),
            judge_model_id=_opt_str(br.get("judge_model_id", "")),
            max_tokens=int(br.get("max_tokens", 1024)),
            temperature=float(br.get("temperature", 0.0)),
            anthropic_version=br.get("anthropic_version", "bedrock-2023-05-31"),
        ),
        verbatim_strings=list(vb.get("strings", [])),
        raw=raw,
        path=cfg_path,
    )
