"""Fidelity metrics: verbatim-quote survival, forward-pass diff classification,
and SmartCrusher reversibility. Guardrail 4 — never silently drop divergence.
"""

from __future__ import annotations

import difflib
import json
import re
from dataclasses import dataclass, field
from typing import Any


# Heuristics for "load-bearing" strings whose exact survival matters:
#   - quoted clauses '...' / "..."     - dollar amounts $50,000
#   - IDs like ACME-2024-001, ISO dates, UUID-ish, long digit runs
_PATTERNS = [
    re.compile(r"'([^']{6,})'"),
    re.compile(r'"([^"]{6,})"'),
    re.compile(r"\$\s?[\d,]+(?:\.\d+)?"),
    re.compile(r"\b[A-Z]{2,}[A-Z0-9]*-[A-Z0-9-]{2,}\b"),
    re.compile(r"\b\d{4}-\d{2}-\d{2}\b"),
    re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}\b"),
]


def extract_load_bearing(text: str, limit: int = 25) -> list[str]:
    """Auto-detect likely load-bearing literal strings in `text`."""
    found: list[str] = []
    seen: set[str] = set()
    for pat in _PATTERNS:
        for m in pat.finditer(text):
            s = (m.group(1) if m.groups() else m.group(0)).strip()
            if len(s) >= 3 and s not in seen:
                seen.add(s)
                found.append(s)
    return found[:limit]


@dataclass
class VerbatimReport:
    checked: int = 0
    survived: int = 0
    lost: list[str] = field(default_factory=list)

    @property
    def survival_rate(self) -> float:
        return 1.0 if self.checked == 0 else round(self.survived / self.checked, 4)

    def as_dict(self) -> dict[str, Any]:
        return {
            "checked": self.checked,
            "survived": self.survived,
            "survival_rate": self.survival_rate,
            "lost": self.lost,
        }


def check_verbatim(strings: list[str], compressed_text: str) -> VerbatimReport:
    """Did each load-bearing string survive byte-for-byte in the compressed text?"""
    rep = VerbatimReport()
    for s in strings:
        if not s:
            continue
        rep.checked += 1
        if s in compressed_text:
            rep.survived += 1
        else:
            rep.lost.append(s)
    return rep


def classify_diff(original: str, compressed: str) -> dict[str, Any]:
    """Characterize the forward pass: deletion-only vs paraphrase/rewrite.

    Deletion-only means every token in the compressed output also appears, in
    order, in the original (the compressor only dropped spans). If the compressed
    output introduces text not present in the original, it rewrote/paraphrased —
    a stronger fidelity risk worth flagging (claims-matrix "forward-pass fidelity").
    """
    sm = difflib.SequenceMatcher(a=original, b=compressed, autojunk=False)
    inserted = 0
    deleted = 0
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag in ("replace", "insert"):
            inserted += j2 - j1
        if tag in ("replace", "delete"):
            deleted += i2 - i1
    # Insertions that are pure whitespace don't count as rewriting.
    rewrite_chars = _nonspace_insertions(sm)
    return {
        "chars_before": len(original),
        "chars_after": len(compressed),
        "chars_deleted": deleted,
        "chars_inserted": inserted,
        "nonspace_inserted": rewrite_chars,
        "deletion_only": rewrite_chars == 0,
        "classification": "deletion-only" if rewrite_chars == 0 else "paraphrase/rewrite",
        "similarity": round(sm.ratio(), 4),
    }


def _nonspace_insertions(sm: difflib.SequenceMatcher) -> int:
    b = sm.b
    n = 0
    for tag, _i1, _i2, j1, j2 in sm.get_opcodes():
        if tag in ("replace", "insert"):
            n += sum(1 for ch in b[j1:j2] if not ch.isspace())
    return n


def reversibility_from_crush(original_json: str, compressed: str, strategy: str) -> dict[str, Any]:
    """Best-effort byte-exact reversibility check for SmartCrusher output.

    SmartCrusher reports a `strategy` (e.g. `lossless:table(...)`). When it claims
    lossless we try to reconstruct the original array from the compact table form
    and compare structurally. Byte-exact retrieve() is unproven (Guardrail 2), so
    this is reported as evidence, never assumed.
    """
    claims_lossless = strategy.startswith("lossless")
    result: dict[str, Any] = {
        "strategy": strategy,
        "claims_lossless": claims_lossless,
        "reconstructed": False,
        "structural_match": None,
    }
    try:
        orig = json.loads(original_json)
    except Exception:
        return result

    recon = _try_parse_table(compressed)
    if recon is None:
        return result
    result["reconstructed"] = True
    result["structural_match"] = _structural_equal(orig, recon)
    return result


def _try_parse_table(compressed: str) -> list[dict[str, Any]] | None:
    """Parse the SmartCrusher compact table form:
        "[N]{col:type,col:type}\nv,v\nv,v..."  (outer quotes optional)
    Returns a list of row dicts, or None if it doesn't look like a table.
    """
    s = compressed.strip()
    if s.startswith('"') and s.endswith('"'):
        try:
            s = json.loads(s)
        except Exception:
            s = s[1:-1]
    lines = [ln for ln in s.splitlines() if ln != ""]
    if not lines:
        return None
    header = lines[0]
    m = re.match(r"^\[\d+\]\{(.+)\}$", header)
    if not m:
        return None
    cols = [c.split(":", 1)[0] for c in m.group(1).split(",")]
    rows: list[dict[str, Any]] = []
    for ln in lines[1:]:
        vals = ln.split(",")
        if len(vals) != len(cols):
            # ragged row -> give up on structural reconstruction
            return rows or None
        rows.append({c: _coerce(v) for c, v in zip(cols, vals)})
    return rows


def _coerce(v: str) -> Any:
    try:
        return int(v)
    except ValueError:
        try:
            return float(v)
        except ValueError:
            return v


def _structural_equal(a: Any, b: Any) -> bool:
    """Compare two record lists ignoring key order and numeric int/float jitter."""
    if not isinstance(a, list) or not isinstance(b, list) or len(a) != len(b):
        return False
    for ra, rb in zip(a, b):
        if not isinstance(ra, dict) or not isinstance(rb, dict):
            if str(ra) != str(rb):
                return False
            continue
        if set(ra.keys()) != set(rb.keys()):
            return False
        for k in ra:
            if str(ra[k]) != str(rb[k]):
                return False
    return True
