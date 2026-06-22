"""Bedrock inference leg (boto3, D3) — original-context vs compressed-context.

This is the right half of the architecture diagram and runs ONLY in bedrock mode.
Headroom compresses the context; boto3 calls Bedrock directly for both legs; the
harness captures token usage from BOTH Headroom and the Bedrock response
(requirement 2 / "dual token capture"). The judge (judge.py) then grades
equivalence. No credentials live here — boto3 resolves them from env/profile
(Guardrail 5).
"""

from __future__ import annotations

import json
from typing import Any

import headroom
from headroom import CompressConfig

from . import tokens
from .config import Config
from .datagen import Input

# Structured task: force JSON so equivalence is checkable field-by-field (D5).
_TASK_INSTRUCTION = (
    "You are answering strictly from the CONTEXT below. Return ONLY a JSON object "
    "with keys: \"answer\" (string, a direct answer to the question), and "
    "\"key_facts\" (array of short strings: the load-bearing IDs, amounts, "
    "deadlines, and names you relied on). Do not invent facts not in the context.\n\n"
    "QUESTION: {question}\n\nCONTEXT:\n{context}"
)

_DEFAULT_QUESTION = (
    "Summarize the key obligations, and list every identifier, monetary amount, "
    "and deadline mentioned."
)


class BedrockUnavailable(RuntimeError):
    pass


class BedrockClient:
    """Thin boto3 Bedrock Runtime wrapper for the Anthropic Messages API."""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        b = cfg.bedrock
        if not b.enabled:
            raise BedrockUnavailable("bedrock.enabled is false")
        if not b.region or not b.model_id:
            raise BedrockUnavailable("bedrock.region and bedrock.model_id are required")
        try:
            import boto3
        except Exception as exc:  # pragma: no cover
            raise BedrockUnavailable(f"boto3 not importable: {exc}") from exc
        self._client = boto3.client("bedrock-runtime", region_name=b.region)

    def invoke(self, messages: list[dict[str, Any]], model_id: str) -> dict[str, Any]:
        b = self.cfg.bedrock
        body = {
            "anthropic_version": b.anthropic_version,
            "max_tokens": b.max_tokens,
            "temperature": b.temperature,
            "messages": messages,
        }
        resp = self._client.invoke_model(modelId=model_id, body=json.dumps(body))
        payload = json.loads(resp["body"].read())
        text = "".join(
            blk.get("text", "") for blk in payload.get("content", [])
            if blk.get("type") == "text"
        )
        usage = payload.get("usage", {})
        return {
            "text": text,
            "bedrock_input_tokens": usage.get("input_tokens"),
            "bedrock_output_tokens": usage.get("output_tokens"),
        }


def _compressed_context(context: str, cfg: Config) -> tuple[str, dict[str, Any]]:
    """Compress the context message via Headroom; return (text, headroom stats)."""
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
    # Carry context in a system message so it is eligible for compression.
    messages = [{"role": "system", "content": context}]
    res = headroom.compress(messages, model=cfg.compress_model,
                            model_limit=cfg.model_limit, optimize=c.optimize, config=conf)
    compressed = "\n".join(
        str(m.get("content", "")) for m in res.messages if m.get("role") == "system")
    stats = {
        "headroom_tokens_before": res.tokens_before,
        "headroom_tokens_after": res.tokens_after,
        "headroom_tokens_saved": res.tokens_saved,
        "headroom_compression_ratio": round(res.compression_ratio, 4),
        "transforms_applied": list(res.transforms_applied),
    }
    return compressed, stats


def run_accuracy(inp: Input, cfg: Config, client: BedrockClient,
                 question: str | None = None) -> dict[str, Any]:
    """Run the same structured task on original vs compressed context."""
    question = question or _DEFAULT_QUESTION
    context = inp.as_text()
    compressed_ctx, hr_stats = _compressed_context(context, cfg)

    model_id = cfg.bedrock.model_id
    orig_msgs = [{"role": "user", "content":
                  _TASK_INSTRUCTION.format(question=question, context=context)}]
    comp_msgs = [{"role": "user", "content":
                  _TASK_INSTRUCTION.format(question=question, context=compressed_ctx)}]

    orig = client.invoke(orig_msgs, model_id)
    comp = client.invoke(comp_msgs, model_id)

    return {
        "feature": "accuracy",
        "ok": True,
        "input_id": inp.id,
        "input_kind": inp.kind,
        "question": question,
        "headroom": hr_stats,
        "original": {
            "answer_raw": orig["text"],
            "answer_json": _safe_json(orig["text"]),
            "bedrock_input_tokens": orig["bedrock_input_tokens"],
            "bedrock_output_tokens": orig["bedrock_output_tokens"],
            "context_tokens_est": tokens.count_text(context, cfg.compress_model),
        },
        "compressed": {
            "answer_raw": comp["text"],
            "answer_json": _safe_json(comp["text"]),
            "bedrock_input_tokens": comp["bedrock_input_tokens"],
            "bedrock_output_tokens": comp["bedrock_output_tokens"],
            "context_tokens_est": tokens.count_text(compressed_ctx, cfg.compress_model),
        },
    }


def _safe_json(text: str) -> Any:
    """Best-effort extraction of a JSON object from model output."""
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text[text.find("{"):] if "{" in text else text
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except Exception:
            return None
    return None
