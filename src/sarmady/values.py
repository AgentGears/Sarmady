from __future__ import annotations

from collections.abc import Mapping
from typing import Any


class FrozenDict(dict):
    """JSON-serializable immutable mapping used at semantic boundaries."""

    def _immutable(self, *args: Any, **kwargs: Any) -> None:
        raise TypeError("frozen semantic value is immutable")

    __setitem__ = _immutable
    __delitem__ = _immutable
    clear = _immutable
    pop = _immutable
    popitem = _immutable
    setdefault = _immutable
    update = _immutable
    __ior__ = _immutable


def freeze_value(value: Any) -> Any:
    """Recursively detach mutable JSON-like values from caller-owned objects."""

    if isinstance(value, FrozenDict):
        return value
    if isinstance(value, Mapping):
        return FrozenDict({key: freeze_value(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(freeze_value(item) for item in value)
    if isinstance(value, tuple):
        return tuple(freeze_value(item) for item in value)
    if isinstance(value, set):
        return frozenset(freeze_value(item) for item in value)
    if isinstance(value, frozenset):
        return frozenset(freeze_value(item) for item in value)
    return value
