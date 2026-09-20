from __future__ import annotations

import math
import weakref
from collections.abc import Iterator, Mapping
from typing import Any


_FROZEN_MAPPING_STATE: dict[
    int,
    tuple[weakref.ReferenceType["FrozenMapping"], tuple[tuple[str, Any], ...]],
] = {}


def _drop_frozen_mapping_state(
    object_id: int,
    reference: weakref.ReferenceType["FrozenMapping"],
) -> None:
    current = _FROZEN_MAPPING_STATE.get(object_id)
    if current is not None and current[0] is reference:
        _FROZEN_MAPPING_STATE.pop(object_id, None)


class FrozenMapping(Mapping[str, Any]):
    """Deeply immutable mapping for canonical JSON-like semantic values.

    Admitted values expose no writable semantic backing state on the instance:
    the object has only a weak-reference slot, while its recursively frozen
    contents live in a private identity-checked side table. Consequently,
    ``object.__setattr__`` and repeated ``__init__`` calls cannot replace an
    admitted mapping's contents. The type is also deliberately not a ``dict``
    subclass, so unbound built-in dict mutators cannot bypass the boundary.

    Because this is a normal ``Mapping`` rather than a tuple subclass,
    ``copy``/``deepcopy`` and ``dataclasses.asdict`` follow the standard custom
    object path instead of misinterpreting mapping keys as sequence elements.
    """

    __slots__ = ("__weakref__",)

    def __new__(cls, source: Mapping[str, Any]) -> FrozenMapping:
        self = object.__new__(cls)
        normalized: dict[str, Any] = {}
        for key, item in source.items():
            if not isinstance(key, str):
                raise TypeError("semantic mapping keys must be strings")
            normalized[key] = freeze_value(item)

        object_id = id(self)
        reference = weakref.ref(
            self,
            lambda ref, object_id=object_id: _drop_frozen_mapping_state(
                object_id,
                ref,
            ),
        )
        _FROZEN_MAPPING_STATE[object_id] = (
            reference,
            tuple(normalized.items()),
        )
        return self

    def __init__(self, source: Mapping[str, Any]) -> None:
        # All semantic state is fixed in __new__. Re-entering __init__ on an
        # admitted value is intentionally a no-op.
        del source

    def _state_items(self) -> tuple[tuple[str, Any], ...]:
        current = _FROZEN_MAPPING_STATE.get(id(self))
        if current is None or current[0]() is not self:
            raise RuntimeError("frozen semantic value backing state is unavailable")
        return current[1]

    def __getitem__(self, key: str) -> Any:
        for candidate, value in self._state_items():
            if candidate == key:
                return value
        raise KeyError(key)

    def __iter__(self) -> Iterator[str]:
        return (key for key, _ in self._state_items())

    def __len__(self) -> int:
        return len(self._state_items())

    @staticmethod
    def _immutable(*args: Any, **kwargs: Any) -> None:
        raise TypeError("frozen semantic value is immutable")

    __setitem__ = _immutable
    __delitem__ = _immutable

    def __setattr__(self, name: str, value: Any) -> None:
        raise TypeError("frozen semantic value is immutable")

    def __copy__(self) -> FrozenMapping:
        return self

    def __deepcopy__(self, memo: dict[int, Any]) -> FrozenMapping:
        memo[id(self)] = self
        return self

    def __reduce__(self):
        return (FrozenMapping, (dict(self.items()),))

    def __repr__(self) -> str:
        return f"FrozenMapping({dict(self.items())!r})"

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Mapping):
            return dict(self.items()) == dict(other.items())
        return NotImplemented


def freeze_value(value: Any) -> Any:
    """Recursively detach and freeze strict-JSON-compatible semantic values."""

    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("semantic float values must be finite")
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
