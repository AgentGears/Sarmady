from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from typing import Any


class FrozenMapping(Mapping[str, Any], tuple):
    """Deeply immutable mapping for canonical JSON-like semantic values.

    The backing representation is the tuple object itself, so admitted values
    expose no mutable instance attributes that can be rewritten through
    ``object.__setattr__`` or by calling ``__init__`` again. This is also
    deliberately not a ``dict`` subclass: unbound built-in dict mutators cannot
    bypass the immutability boundary.

    Construction accepts either a mapping or an iterable of key/value pairs so
    Python's tuple reconstruction protocol used by ``copy``/``deepcopy`` and
    ``dataclasses.asdict`` remains compatible with this immutable tuple-backed
    representation.
    """

    __slots__ = ()

    def __new__(
        cls,
        source: Mapping[str, Any] | Iterable[tuple[str, Any]],
    ) -> FrozenMapping:
        pairs = source.items() if isinstance(source, Mapping) else source
        normalized: dict[str, Any] = {}
        for pair in pairs:
            try:
                key, item = pair
            except (TypeError, ValueError):
                raise TypeError(
                    "semantic mapping source must yield key/value pairs"
                ) from None
            if not isinstance(key, str):
                raise TypeError("semantic mapping keys must be strings")
            normalized[key] = freeze_value(item)
        return tuple.__new__(cls, tuple(normalized.items()))

    def __init__(
        self,
        source: Mapping[str, Any] | Iterable[tuple[str, Any]],
    ) -> None:
        # All state is constructed immutably in __new__. Re-entering __init__
        # on an admitted value is therefore harmless and cannot replace state.
        del source

    def __getitem__(self, key: str) -> Any:
        for candidate, value in tuple.__iter__(self):
            if candidate == key:
                return value
        raise KeyError(key)

    def __iter__(self) -> Iterator[str]:
        return (key for key, _ in tuple.__iter__(self))

    def __len__(self) -> int:
        return tuple.__len__(self)

    @staticmethod
    def _immutable(*args: Any, **kwargs: Any) -> None:
        raise TypeError("frozen semantic value is immutable")

    __setitem__ = _immutable
    __delitem__ = _immutable

    def __setattr__(self, name: str, value: Any) -> None:
        raise TypeError("frozen semantic value is immutable")

    def __repr__(self) -> str:
        return f"FrozenMapping({dict(self.items())!r})"

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
