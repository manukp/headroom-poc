"""LLM-as-judge over structured answers (D5).

"Same answers" is a downstream-equivalence claim, not byte-exactness. The judge
grades whether the compressed-context answer is task-equivalent to the
original-context answer. Per the judge-reliability risk in the log, we DON'T trust
the judge alone: we pair its verdict with a deterministic key-fact overlap check.
"""

from __future__ import annotations

import json
from typing import Any

from .bedrock import BedrockClient
from .config import Config

_JUDGE_PROMPT = (
    "You are a strict evaluator. Two assistants answered the SAME question using "
    "different versions of a source document (one full, one compressed). Decide "
    "whether their answers are TASK-EQUIVALENT: do they convey the same key facts, "
    "identifiers, amounts, and deadlines, such that a user would be equally well "
    "served? Minor wording differences are fine; a missing or wrong identifier/"
    "amount/deadline is NOT.\n\n"
    "Return ONLY JSON: {\"equivalent\": true|false, \"confidence\": 0..1, "
    "\"differences\": [short strings], \"reasoning\": \"one sentence\"}.\n\n"
    "ANSWER_A (original context):\n{a}\n\nANSWER_B (compressed context):\n{b}"
)


def _key_facts(answer_json: Any) -> set[str]:
    if isinstance(answer_json, dict):
        facts = answer_json.get("key_facts") or []
        if isinstance(facts, list):
            return {str(f).strip().lower() for f in facts if str(f).strip()}
    return set()


def deterministic_overlap(original_json: Any, compressed_json: Any) -> dict[str, Any]:
    """Jaccard-style overlap of the structured key_facts arrays."""
    a, b = _key_facts(original_json), _key_facts(compressed_json)
    if not a and not b:
        return {"available": False}
    inter = a & b
    union = a | b
    return {
        "available": True,
        "original_facts": sorted(a),
        "compressed_facts": sorted(b),
        "missing_in_compressed": sorted(a - b),
        "added_in_compressed": sorted(b - a),
        "overlap": round(len(inter) / len(union), 4) if union else 1.0,
    }


def judge(accuracy_result: dict[str, Any], cfg: Config,
          client: BedrockClient) -> dict[str, Any]:
    """Judge one accuracy result. Returns the judge verdict + deterministic check."""
    a_raw = accuracy_result["original"]["answer_raw"]
    b_raw = accuracy_result["compressed"]["answer_raw"]
    model_id = cfg.bedrock.judge_model_id or cfg.bedrock.model_id

    msgs = [{"role": "user", "content": _JUDGE_PROMPT.format(a=a_raw, b=b_raw)}]
    resp = client.invoke(msgs, model_id)
    verdict = _parse_verdict(resp["text"])

    overlap = deterministic_overlap(
        accuracy_result["original"].get("answer_json"),
        accuracy_result["compressed"].get("answer_json"),
    )
    return {
        "input_id": accuracy_result["input_id"],
        "judge_model_id": model_id,
        "verdict": verdict,
        "deterministic_overlap": overlap,
        "judge_input_tokens": resp["bedrock_input_tokens"],
        "judge_output_tokens": resp["bedrock_output_tokens"],
    }


def _parse_verdict(text: str) -> dict[str, Any]:
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end != -1:
        try:
            return json.loads(text[start:end + 1])
        except Exception:
            pass
    return {"equivalent": None, "raw": text[:500]}
