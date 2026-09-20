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

    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, FrozenDict):
        return value
    if isinstance(value, Mapping):
        frozen: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("semantic mapping keys must be strings")
            frozen[key] = freeze_value(item)
        return FrozenDict(frozen)
    if isinstance(value, (list, tuple)):
        return tuple(freeze_value(item) for item in value)
    raise TypeError("semantic value must be JSON-compatible")
