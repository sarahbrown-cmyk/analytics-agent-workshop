"""A small JSON Schema validator.

Same reasoning as src/tools/_yaml.py: zero dependencies, so no `pip install
jsonschema` in the first ten minutes of the workshop. Supports the keywords the
schemas in this directory actually use:

    type, required, properties, additionalProperties (false only), items,
    enum, minLength, minItems, pattern, $ref (local $defs only)

Anything else in a schema is ignored rather than silently treated as satisfied —
`unsupported_keywords()` lists what was skipped, so a schema author can tell the
difference between "validated and passed" and "not checked".
"""

from __future__ import annotations

import re
from typing import Any

SUPPORTED = {
    "type",
    "required",
    "properties",
    "additionalProperties",
    "items",
    "enum",
    "minLength",
    "minItems",
    "pattern",
    "$ref",
    # Annotations, not constraints.
    "$schema",
    "$id",
    "title",
    "description",
    "$defs",
}

_TYPE_MAP = {
    "object": dict,
    "array": list,
    "string": str,
    "number": (int, float),
    "integer": int,
    "boolean": bool,
    "null": type(None),
}


def validate(instance: Any, schema: dict) -> list[str]:
    """Return a list of human-readable errors. Empty means valid."""
    errors: list[str] = []
    _check(instance, schema, schema, "$", errors)
    return errors


def unsupported_keywords(schema: dict) -> set[str]:
    found: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key in ("properties", "$defs"):
                    for child in value.values():
                        walk(child)
                    continue
                if key not in SUPPORTED:
                    found.add(key)
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(schema)
    return found


def _resolve(schema: dict, root: dict) -> dict:
    ref = schema.get("$ref")
    if not ref:
        return schema
    if not ref.startswith("#/$defs/"):
        return schema
    target = root.get("$defs", {}).get(ref.split("/")[-1])
    if target is None:
        return schema
    merged = dict(target)
    for key, value in schema.items():
        if key != "$ref":
            merged[key] = value
    return merged


def _check(value: Any, schema: dict, root: dict, path: str, errors: list[str]) -> None:
    schema = _resolve(schema, root)

    expected = schema.get("type")
    if expected is not None:
        allowed = expected if isinstance(expected, list) else [expected]
        python_types = tuple(
            t for name in allowed for t in _as_tuple(_TYPE_MAP.get(name, object))
        )
        # bool is a subclass of int; a boolean is not a number here.
        if isinstance(value, bool) and "boolean" not in allowed:
            errors.append(f"{path}: expected {'/'.join(allowed)}, got boolean")
            return
        if not isinstance(value, python_types):
            errors.append(
                f"{path}: expected {'/'.join(allowed)}, got {type(value).__name__}"
            )
            return

    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: {value!r} is not one of {schema['enum']}")

    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            errors.append(
                f"{path}: string shorter than minLength {schema['minLength']} "
                f"(got {len(value)})"
            )
        pattern = schema.get("pattern")
        if pattern and not re.search(pattern, value):
            errors.append(f"{path}: {value!r} does not match pattern {pattern}")

    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            errors.append(
                f"{path}: expected at least {schema['minItems']} item(s), got {len(value)}"
            )
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(value):
                _check(item, item_schema, root, f"{path}[{index}]", errors)

    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                errors.append(f"{path}: missing required property {key!r}")
        properties = schema.get("properties", {})
        for key, sub_schema in properties.items():
            if key in value:
                _check(value[key], sub_schema, root, f"{path}.{key}", errors)
        if schema.get("additionalProperties") is False:
            for key in value:
                if key not in properties:
                    errors.append(f"{path}: unexpected property {key!r}")


def _as_tuple(value) -> tuple:
    return value if isinstance(value, tuple) else (value,)
