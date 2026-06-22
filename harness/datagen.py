"""Inputs: the `Input` model, synthetic default generators, and the data/ loader.

Test data is BOTH synthetic defaults and user-provided files (D6). Layout under
data/ (created on demand):
    data/json/*.json   -> JSON-array inputs (SmartCrusher etc.)
    data/text/*.txt|.md -> prose inputs (compress/universal; accuracy/verbatim)

Synthetic inputs are deliberately seeded with the failure modes the claims matrix
cares about: repetition, JSON bloat, whitespace, anomalies/errors, and
load-bearing literals (IDs, quoted clauses, $amounts).
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import REPO_ROOT

DATA_DIR = REPO_ROOT / "data"
JSON_DIR = DATA_DIR / "json"
TEXT_DIR = DATA_DIR / "text"

_TEXT_EXTS = {".txt", ".md", ".markdown", ".log"}


@dataclass
class Input:
    id: str
    kind: str  # "json" | "text"
    path: Path | None
    _raw: str

    # --- views the runners consume ---------------------------------------- #
    def as_text(self) -> str:
        return self._raw

    def as_json(self) -> Any:
        return json.loads(self._raw)

    def as_messages(self) -> list[dict[str, Any]]:
        return [{"role": "user", "content": self._raw}]


# --------------------------------------------------------------------------- #
# Synthetic generators
# --------------------------------------------------------------------------- #
def _synthetic_json_logs(n: int = 80, seed: int = 7) -> list[dict[str, Any]]:
    """Mostly-uniform event log with a few errors + numeric anomalies + repetition."""
    rng = random.Random(seed)
    rows: list[dict[str, Any]] = []
    for i in range(n):
        is_error = i in (12, 37, 61)
        is_anomaly = i in (5, 50)
        rows.append({
            "id": f"EVT-2026-{i:04d}",
            "ts": f"2026-06-21T10:{i % 60:02d}:00Z",
            "service": "billing",                      # constant -> factor-out-able
            "region": "us-east-1",                     # constant
            "level": "ERROR" if is_error else "INFO",
            "latency_ms": (9000 if is_anomaly else rng.randint(20, 80)),
            "message": ("payment declined: card AUTH-FAIL-7781" if is_error
                        else "processed payment ok"),  # repetitive
            "amount_usd": 50000 if is_anomaly else rng.randint(10, 200),
        })
    return rows


_PROSE = """\
# Master Services Agreement — Summary for Review

This Agreement (ID: ACME-2024-001) is entered into between Acme Corp ("Provider")
and Globex LLC ("Client") and governs the provision of cloud services described
herein. The parties acknowledge that the terms below are material and that the
defined monetary thresholds are load-bearing for any downstream interpretation.

Section 4 (Penalties). The penalty clause states: 'Party A shall pay $50,000
within 30 days of a confirmed breach.' This figure is not subject to proration.
A separate late-fee of $1,200 per week accrues thereafter until cured.

Section 7 (Termination). Either party may terminate for convenience on 60 days
written notice. For cause, the cure period is 15 days. Upon termination the
Client must settle all outstanding invoices, including the reference invoice
INV-2026-0042 dated 2026-05-01, before any data export is released.

Section 9 (Liability). Aggregate liability is capped at the fees paid in the
trailing 12 months, except for the indemnities in Section 10, which are uncapped.
The cap explicitly excludes the penalty in Section 4.

Filler context (intentionally low-information): The companies have a long and
storied history of collaboration spanning many quarters and many handshakes and
many slide decks, and everyone involved is very excited about the synergies and
the alignment and the strategic value-add of this wonderful partnership, etc.
Repeated boilerplate: All rights reserved. All rights reserved. All rights
reserved. All rights reserved. All rights reserved.

Question this document must still answer after compression: What is the penalty
in Section 4, what is its deadline, and which contract ID and invoice number are
referenced?
"""


def write_synthetic_defaults() -> list[Input]:
    """Create synthetic default files under data/ and return them as Inputs."""
    JSON_DIR.mkdir(parents=True, exist_ok=True)
    TEXT_DIR.mkdir(parents=True, exist_ok=True)

    json_path = JSON_DIR / "synthetic_event_logs.json"
    if not json_path.exists():
        json_path.write_text(
            json.dumps(_synthetic_json_logs(), indent=2), encoding="utf-8")

    text_path = TEXT_DIR / "synthetic_contract.md"
    if not text_path.exists():
        text_path.write_text(_PROSE, encoding="utf-8")

    return [
        _load_file(json_path),
        _load_file(text_path),
    ]


# --------------------------------------------------------------------------- #
# Loading
# --------------------------------------------------------------------------- #
def _classify(path: Path) -> str:
    if path.suffix.lower() == ".json":
        return "json"
    if path.suffix.lower() in _TEXT_EXTS:
        return "text"
    return "text"


def _load_file(path: Path) -> Input:
    raw = path.read_text(encoding="utf-8")
    rel = path.relative_to(REPO_ROOT) if REPO_ROOT in path.parents else path
    return Input(id=str(rel).replace("\\", "/"), kind=_classify(path), path=path, _raw=raw)


def _iter_data_files() -> list[Path]:
    files: list[Path] = []
    for d in (JSON_DIR, TEXT_DIR, DATA_DIR):
        if d.exists():
            for p in sorted(d.glob("*")):
                if p.is_file() and (p.suffix.lower() == ".json"
                                    or p.suffix.lower() in _TEXT_EXTS):
                    files.append(p)
    # de-dup (DATA_DIR glob may also catch files in subdirs on some platforms)
    seen: set[Path] = set()
    uniq: list[Path] = []
    for p in files:
        rp = p.resolve()
        if rp not in seen:
            seen.add(rp)
            uniq.append(p)
    return uniq


def load_inputs(selectors: list[str], generate_if_empty: bool = True) -> list[Input]:
    """Resolve the `run.inputs` selectors into concrete Inputs.

    "auto" -> everything under data/ (generating synthetic defaults first if the
    directory is empty). Any other entry is treated as a file path.
    """
    inputs: list[Input] = []
    auto = any(s == "auto" for s in selectors)
    explicit = [s for s in selectors if s != "auto"]

    if auto:
        existing = _iter_data_files()
        if not existing and generate_if_empty:
            inputs.extend(write_synthetic_defaults())
        else:
            if not existing:
                # generation disabled and nothing on disk: still seed defaults
                inputs.extend(write_synthetic_defaults())
            else:
                inputs.extend(_load_file(p) for p in existing)

    for s in explicit:
        p = Path(s)
        if not p.is_absolute():
            p = REPO_ROOT / s
        if p.exists():
            inputs.append(_load_file(p))

    return inputs
