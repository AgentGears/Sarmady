from __future__ import annotations

from collections.abc import Iterator, Mapping
from types import MappingProxyType
from typing import Any


class FrozenMapping(Mapping[str, Any]):
    """Deeply immutable mapping for canonical JSON-like semantic values.

    This is deliberately not a ``dict`` subclass: unbound built-in dict
    mutators therefore cannot bypass the immutability boundary.
    """

    __slots__ = ("_items", "_index")

    def __init__(self, source: Mapping[str, Any]) -> None:
        normalized: dict[str, Any] = {}
        for key, item in source.items():
            if not isinstance(key, str):
                raise TypeError("semantic mapping keys must be strings")
            normalized[key] = freeze_value(item)
        items = tuple(normalized.items())
        object.__setattr__(self, "_items", items)
        object.__setattr__(self, "_index", MappingProxyType(dict(items)))

    def __getitem__(self, key: str) -> Any:
        return self._index[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._index)

    def __len__(self) -> int:
        return len(self._index)

    def __setattr__(self, name: str, value: Any) -> None:
        raise TypeError("frozen semantic value is immutable")

    def __repr__(self) -> str:
        return f"FrozenMapping({dict(self._items)!r})"

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Mapping):
            return dict(self.items()) == dict(other.items())
        return NotImplemented


def freeze_value(value: Any) -> Any:
    """Recursively detach and freeze JSON-compatible semantic values."""

    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        # Always reconstruct, including FrozenMapping inputs, so callers cannot
        # smuggle mutable descendants through a trusted-looking wrapper.
        return FrozenMapping(value)
    if isinstance(value, (list, tuple)):
        return tuple(freeze_value(item) for item in value)
    raise TypeError("semantic value must be JSON-compatible")


def thaw_value(value: Any) -> Any:
    """Convert frozen semantic values into plain JSON-serializable containers."""

    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return {key: thaw_value(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [thaw_value(item) for item in value]
    raise TypeError("semantic value is not JSON-compatible")
