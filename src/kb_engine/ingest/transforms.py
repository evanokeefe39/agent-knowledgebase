"""Registered pure parametric transforms (plan §6.1, §12).

The registry is CLOSED: exactly the primitives the expert panel locked —
``identity``, ``coerce_str``, ``coerce_int``, ``coerce_bool``, ``list``,
``template``, ``path_join``. Bespoke derivation (e.g. presence -> status)
lives in the per-source adapter, NEVER accretes here. No IO, no network,
no clock: every transform is pure and deterministic.
"""

from __future__ import annotations

from typing import Any, Callable, Mapping

__all__ = [
    "TransformError",
    "TRANSFORMS",
    "apply_transform",
    "registered_transforms",
]


class TransformError(ValueError):
    """A transform id is unknown, or the value cannot be transformed."""


def _identity(value: Any, params: Mapping[str, Any]) -> Any:
    return value


def _coerce_str(value: Any, params: Mapping[str, Any]) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    raise TransformError(f"coerce_str: cannot coerce {type(value).__name__} to str")


def _coerce_int(value: Any, params: Mapping[str, Any]) -> int:
    if isinstance(value, bool):
        raise TransformError("coerce_int: bool is not an int")
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if value.is_integer():
            return int(value)
        raise TransformError(f"coerce_int: {value!r} is not integral")
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            raise TransformError(f"coerce_int: {value!r} is not an int") from None
    raise TransformError(f"coerce_int: cannot coerce {type(value).__name__} to int")


_BOOL_TRUE = frozenset({"true", "1", "yes", "y"})
_BOOL_FALSE = frozenset({"false", "0", "no", "n"})


def _coerce_bool(value: Any, params: Mapping[str, Any]) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in _BOOL_TRUE:
            return True
        if lowered in _BOOL_FALSE:
            return False
    raise TransformError(f"coerce_bool: {value!r} is not a bool")


def _to_list(value: Any, params: Mapping[str, Any]) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return list(value)
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _template(value: Any, params: Mapping[str, Any]) -> str:
    pattern = params.get("pattern")
    if not isinstance(pattern, str):
        raise TransformError("template: 'pattern' param is required")
    return pattern.format(value=value)


def _path_join(value: Any, params: Mapping[str, Any]) -> str:
    parts = value if isinstance(value, (list, tuple)) else [value]
    joined = "/".join(str(p) for p in parts if p not in (None, ""))
    return joined


TRANSFORMS: dict[str, Callable[[Any, Mapping[str, Any]], Any]] = {
    "identity": _identity,
    "coerce_str": _coerce_str,
    "coerce_int": _coerce_int,
    "coerce_bool": _coerce_bool,
    "list": _to_list,
    "template": _template,
    "path_join": _path_join,
}


def apply_transform(name: str, value: Any, params: Mapping[str, Any]) -> Any:
    """Apply the registered transform ``name``; unknown id -> clear error."""
    transform = TRANSFORMS.get(name)
    if transform is None:
        known = ", ".join(sorted(TRANSFORMS))
        raise TransformError(
            f"unknown transform {name!r} (registered: {known})"
        )
    return transform(value, params)


def registered_transforms() -> frozenset[str]:
    """The closed registry ids (for diagnostics / fail-fast loaders)."""
    return frozenset(TRANSFORMS)
