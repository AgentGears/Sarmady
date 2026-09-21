from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any


_TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)


def lexical_tokens(text: str) -> set[str]:
    """Return deterministic case-folded Unicode word tokens."""

    return {match.group(0).casefold() for match in _TOKEN_RE.finditer(text)}


def semantic_tokens(value: Any) -> set[str]:
    """Tokenize a strict canonical JSON-like semantic value recursively."""

    if value is None:
        return set()
    if isinstance(value, str):
        return lexical_tokens(value)
    if isinstance(value, bool):
        return {"true" if value else "false"}
    if isinstance(value, (int, float)):
        return lexical_tokens(str(value))
    if isinstance(value, Mapping):
        tokens: set[str] = set()
        for key, item in value.items():
            tokens.update(lexical_tokens(key))
            tokens.update(semantic_tokens(item))
        return tokens
    if isinstance(value, tuple):
        tokens: set[str] = set()
        for item in value:
            tokens.update(semantic_tokens(item))
        return tokens
    raise TypeError("lexical normalization received non-canonical semantic value")
