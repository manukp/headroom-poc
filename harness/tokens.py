"""Token counting via the installed headroom tokenizer.

`headroom.count_tokens_*` need a concrete `TokenCounter` from
`headroom.tokenizers.get_tokenizer(model)`. For Claude models this is an
`EstimatingTokenCounter` (no exact Claude tokenizer is bundled) — so counts are
ESTIMATES. We capture the counter class name in reports so that caveat is visible
(IMPLEMENTATION_LOG §4/§6).
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

import headroom
from headroom.tokenizers import get_tokenizer


@lru_cache(maxsize=None)
def _counter(model: str):
    return get_tokenizer(model)


def counter_for(model: str):
    return _counter(model)


def counter_name(model: str) -> str:
    return type(_counter(model)).__name__


def count_text(text: str, model: str) -> int:
    return int(headroom.count_tokens_text(text, _counter(model)))


def count_messages(messages: list[dict[str, Any]], model: str) -> int:
    return int(headroom.count_tokens_messages(messages, _counter(model)))


def ratio(before: int, after: int) -> float:
    """Fraction of tokens removed (0..1). Positive = reduction."""
    return 0.0 if before <= 0 else round((before - after) / before, 4)
