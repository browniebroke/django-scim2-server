"""
Apply SCIM PATCH operations to a resource's JSON representation.

This is the engine behind :meth:`BaseUserAdapter.patch` and
:meth:`BaseGroupAdapter.patch`: an adapter dumps its resource to JSON,
the operations are applied to that document, and the result is handed
back to the adapter's ``from_scim`` as a full replacement (RFC 7644 §3.5.2).

It also absorbs the known deviations of the main identity providers:

* Microsoft Entra ID capitalises ``op`` (``"Replace"``), sends booleans as
  strings (``"False"``) and puts dotted or URN-prefixed paths as keys of a
  path-less ``value`` object.
* Entra sends the enterprise ``manager`` as a bare id string.
* Entra and Okta both target ``emails[type eq "work"].value`` on users whose
  stored e-mail carries no ``type``; the value is appended with the filter's
  attribute set rather than rejected.
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from typing import Any

from django_scim2_server.exceptions import BadRequestError, SCIMError

_BOOLEAN_ATTRIBUTES = frozenset({"active", "primary"})
_STRING_BOOLEANS = {"true": True, "false": False}

_PATH_RE = re.compile(
    r"""
    ^(?P<attr>[A-Za-z][\w$-]*)
    (?:\[(?P<filter>[^\]]+)\])?
    (?:\.(?P<sub>[A-Za-z][\w$-]*))?$
    """,
    re.VERBOSE,
)
_VALUE_FILTER_RE = re.compile(
    r'^\s*(?P<attr>[A-Za-z][\w$-]*)\s+eq\s+"(?P<value>(?:[^"\\]|\\.)*)"\s*$',
    re.IGNORECASE,
)


class NoTargetError(SCIMError):
    """The path did not match any attribute or value (RFC 7644 §3.12)."""

    def __init__(self, detail: str) -> None:
        super().__init__(detail=detail, status=400, scim_type="noTarget")


class InvalidPathError(SCIMError):
    """The path is malformed or unsupported (RFC 7644 §3.12)."""

    def __init__(self, detail: str) -> None:
        super().__init__(detail=detail, status=400, scim_type="invalidPath")


@dataclass(frozen=True)
class _ValueFilter:
    attr: str
    value: str

    def matches(self, item: Any) -> bool:
        if not isinstance(item, dict):
            return False
        current = _get_ci(item, self.attr)
        return isinstance(current, str) and current.lower() == self.value.lower()


@dataclass(frozen=True)
class _Path:
    container: tuple[str, ...]
    """Keys leading to the dict holding ``attr`` (empty, or one extension URN)."""
    attr: str
    value_filter: _ValueFilter | None
    sub_attr: str | None


def apply_patch_to_resource(
    resource: dict[str, Any],
    operations: list[dict[str, Any]],
) -> dict[str, Any]:
    """Return a copy of ``resource`` with the PATCH ``operations`` applied."""
    document = copy.deepcopy(resource)
    if not isinstance(operations, list):
        raise BadRequestError("Operations must be a list")
    for operation in operations:
        if not isinstance(operation, dict):
            raise BadRequestError("Each operation must be an object")
        op = str(operation.get("op", "")).lower()
        if op not in ("add", "remove", "replace"):
            raise BadRequestError(f"Unsupported PATCH op: {operation.get('op')}")
        path = operation.get("path")
        value = operation.get("value")

        if not path:
            if op == "remove":
                raise NoTargetError("path is required for remove operations")
            if not isinstance(value, dict):
                raise BadRequestError("value must be an object when path is omitted")
            for key, sub_value in value.items():
                if key == "schemas":
                    continue
                _apply(document, op, _parse_path(document, key), sub_value)
            continue

        _apply(document, op, _parse_path(document, path), value)
    return document


def _parse_path(document: dict[str, Any], raw_path: str) -> _Path:
    path = raw_path.strip()
    container: tuple[str, ...] = ()
    if path.lower().startswith("urn:"):
        if path.lower() in _known_schemas(document):
            return _Path((), path, None, None)
        urn, _, path = path.rpartition(":")
        if not urn or not path:
            raise InvalidPathError(f"Invalid path: {raw_path}")
        if urn.lower() not in _core_schemas(document):
            container = (urn,)

    match = _PATH_RE.match(path)
    if not match:
        raise InvalidPathError(f"Invalid path: {raw_path}")
    attr, raw_filter, sub_attr = match.group("attr", "filter", "sub")
    value_filter = _parse_value_filter(raw_filter) if raw_filter else None
    return _Path(container, attr, value_filter, sub_attr)


def _known_schemas(document: dict[str, Any]) -> set[str]:
    return _extension_keys(document) | {
        s.lower() for s in document.get("schemas") or []
    }


def _core_schemas(document: dict[str, Any]) -> set[str]:
    """The resource's base schema is listed first; the others are extensions."""
    schemas = [s.lower() for s in document.get("schemas") or []]
    return {s for s in schemas[:1] if s not in _extension_keys(document)} | {
        s for s in schemas if ":core:" in s
    }


def _extension_keys(document: dict[str, Any]) -> set[str]:
    return {k.lower() for k in document if k.lower().startswith("urn:")}


def _parse_value_filter(raw_filter: str) -> _ValueFilter:
    """Parse ``attr eq "value"``, the only filter form Entra ID and Okta send."""
    match = _VALUE_FILTER_RE.match(raw_filter)
    if not match:
        raise InvalidPathError(f"Unsupported value filter: [{raw_filter}]")
    value = match.group("value").replace('\\"', '"').replace("\\\\", "\\")
    return _ValueFilter(match.group("attr"), value)


def _apply(document: dict[str, Any], op: str, path: _Path, value: Any) -> None:
    target = document
    for key in path.container:
        existing_key = _find_key(target, key)
        if existing_key is None:
            if op == "remove":
                return
            target[key] = {}
            existing_key = key
            _register_extension(document, key)
        target = target[existing_key]

    if path.attr.lower().startswith("urn:"):
        _register_extension(document, path.attr)

    value = _normalise(path.sub_attr or path.attr, value)

    if path.value_filter is not None:
        _apply_filtered(target, op, path, value)
    elif path.sub_attr is not None:
        _apply_sub_attr(target, op, path.attr, path.sub_attr, value)
    else:
        _apply_attr(target, op, path.attr, value)


def _apply_attr(target: dict[str, Any], op: str, attr: str, value: Any) -> None:
    key = _find_key(target, attr) or attr
    current = target.get(key)
    if op == "remove":
        if isinstance(current, list) and isinstance(value, list):
            # Entra removes members with ``value: [{"value": id}]`` and no filter.
            to_remove = [v for v in value if isinstance(v, dict)]
            target[key] = [
                item
                for item in current
                if not any(_same_item(item, r) for r in to_remove)
            ]
        else:
            target.pop(key, None)
        return

    if isinstance(current, list) or isinstance(value, list):
        values = value if isinstance(value, list) else [value]
        if op == "add" and isinstance(current, list):
            merged = list(current)
            for item in values:
                if not any(_same_item(item, existing) for existing in merged):
                    merged.append(item)
            target[key] = merged
        else:
            target[key] = values
        return

    if isinstance(current, dict) and isinstance(value, dict):
        merged_dict = dict(current)
        for sub_key, sub_value in value.items():
            existing = _find_key(merged_dict, sub_key) or sub_key
            merged_dict[existing] = _normalise(sub_key, sub_value)
        target[key] = merged_dict
        return

    target[key] = value


def _apply_sub_attr(
    target: dict[str, Any], op: str, attr: str, sub_attr: str, value: Any
) -> None:
    key = _find_key(target, attr) or attr
    current = target.get(key)
    if isinstance(current, list):
        # ``emails.value`` without a filter addresses every value (RFC 7644 §3.5.2.3);
        # in practice clients mean the primary one.
        if not current:
            if op != "remove":
                target[key] = [{sub_attr: value}]
            return
        items = [
            i for i in current if isinstance(i, dict) and i.get("primary")
        ] or current[:1]
        for item in items:
            _set_or_remove(item, op, sub_attr, value)
        return

    if current is None:
        if op == "remove":
            return
        target[key] = {}
        current = target[key]
    if not isinstance(current, dict):
        raise InvalidPathError(f"'{attr}' is not a complex attribute")
    _set_or_remove(current, op, sub_attr, value)


def _apply_filtered(target: dict[str, Any], op: str, path: _Path, value: Any) -> None:
    assert path.value_filter is not None  # noqa: S101
    key = _find_key(target, path.attr) or path.attr
    current = target.get(key)
    if current is None:
        current = []
    if not isinstance(current, list):
        raise InvalidPathError(f"'{path.attr}' is not multi-valued")

    matches = [item for item in current if path.value_filter.matches(item)]

    if op == "remove":
        if path.sub_attr is None:
            target[key] = [item for item in current if item not in matches]
        else:
            for item in matches:
                item.pop(_find_key(item, path.sub_attr) or path.sub_attr, None)
        return

    if not matches:
        new_item: dict[str, Any] = {path.value_filter.attr: path.value_filter.value}
        if path.sub_attr is None:
            if not isinstance(value, dict):
                raise InvalidPathError("value must be an object for a filtered path")
            new_item.update(value)
        else:
            new_item[path.sub_attr] = value
        target[key] = [*current, new_item]
        return

    for item in matches:
        if path.sub_attr is None:
            if not isinstance(value, dict):
                raise InvalidPathError("value must be an object for a filtered path")
            for sub_key, sub_value in value.items():
                item[_find_key(item, sub_key) or sub_key] = _normalise(
                    sub_key, sub_value
                )
        else:
            _set_or_remove(item, op, path.sub_attr, value)
    target[key] = current


def _set_or_remove(item: dict[str, Any], op: str, attr: str, value: Any) -> None:
    key = _find_key(item, attr) or attr
    if op == "remove":
        item.pop(key, None)
    else:
        item[key] = value


def _normalise(attr: str, value: Any) -> Any:
    name = attr.rsplit(".", 1)[-1].lower()
    if name in _BOOLEAN_ATTRIBUTES and isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in _STRING_BOOLEANS:
            return _STRING_BOOLEANS[lowered]
    if name == "manager" and isinstance(value, str):
        # Entra sends the enterprise manager as a bare id.
        return {"value": value}
    return value


def _same_item(left: Any, right: Any) -> bool:
    if isinstance(left, dict) and isinstance(right, dict):
        left_value, right_value = _get_ci(left, "value"), _get_ci(right, "value")
        if left_value is not None or right_value is not None:
            return bool(left_value == right_value)
    return bool(left == right)


def _find_key(mapping: dict[str, Any], name: str) -> str | None:
    """SCIM attribute names are case-insensitive (RFC 7643 §2.1)."""
    if name in mapping:
        return name
    lowered = name.lower()
    for key in mapping:
        if key.lower() == lowered:
            return key
    return None


def _get_ci(mapping: dict[str, Any], name: str) -> Any:
    key = _find_key(mapping, name)
    return mapping.get(key) if key is not None else None


def _register_extension(document: dict[str, Any], urn: str) -> None:
    schemas = document.setdefault("schemas", [])
    if urn.lower() not in {s.lower() for s in schemas}:
        schemas.append(urn)
