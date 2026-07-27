"""A deliberately small YAML reader.

Why this exists: this repository has **zero third-party dependencies**. A
workshop that opens with `pip install` spends its first fifteen minutes on
corporate proxies and Python versions instead of on analytics. But the files
humans edit in this repo — launch contracts, review rubrics, eval cases — should
be YAML, because that is what analytics teams already read and write.

So this module supports the subset of YAML actually used here:

- mappings, nested by indentation
- sequences (`- item`), including sequences of mappings
- inline sequences (`[a, b, c]`)
- scalars: quoted strings, ints, floats, booleans, null
- block scalars (`|` literal, `>` folded)
- `#` comments

It does NOT support anchors, aliases, tags, multiple documents, complex keys,
or flow mappings. If you hand it something outside the subset it raises
`YamlError` rather than guessing — a config file that parses into the wrong
shape is worse than one that fails loudly.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

__all__ = ["YamlError", "loads", "load_path"]


class YamlError(ValueError):
    """Raised when input falls outside the supported YAML subset."""


def load_path(path: str | Path) -> Any:
    return loads(Path(path).read_text(encoding="utf-8"))


def loads(text: str) -> Any:
    lines = text.splitlines()
    value, index = _parse_node(lines, 0, 0)
    index = _next_content(lines, index)
    if index < len(lines):
        raise YamlError(f"unexpected content at line {index + 1}: {lines[index]!r}")
    return {} if value is None else value


# ---------------------------------------------------------------------------
# Line helpers
# ---------------------------------------------------------------------------


def _strip_comment(line: str) -> str:
    """Remove a trailing `#` comment, respecting quotes. Preserves indentation."""
    out: list[str] = []
    quote: str | None = None
    i = 0
    while i < len(line):
        char = line[i]
        if quote:
            out.append(char)
            if char == "\\" and i + 1 < len(line):
                out.append(line[i + 1])
                i += 2
                continue
            if char == quote:
                quote = None
        elif char in "\"'":
            quote = char
            out.append(char)
        elif char == "#" and (not out or out[-1] in " \t"):
            break
        else:
            out.append(char)
        i += 1
    return "".join(out).rstrip()


def _next_content(lines: list[str], i: int) -> int:
    """Index of the next line with something on it."""
    while i < len(lines) and not _strip_comment(lines[i]).strip():
        i += 1
    return i


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def _parse_node(lines: list[str], i: int, min_indent: int) -> tuple[Any, int]:
    i = _next_content(lines, i)
    if i >= len(lines):
        return None, i
    line = _strip_comment(lines[i])
    indent = _indent(line)
    if indent < min_indent:
        return None, i
    if line.lstrip().startswith("- ") or line.strip() == "-":
        return _parse_sequence(lines, i, indent)
    return _parse_mapping(lines, i, indent)


def _parse_sequence(lines: list[str], i: int, indent: int) -> tuple[list, int]:
    items: list[Any] = []
    while True:
        i = _next_content(lines, i)
        if i >= len(lines):
            break
        line = _strip_comment(lines[i])
        if _indent(line) != indent:
            if _indent(line) < indent:
                break
            raise YamlError(f"unexpected indent at line {i + 1}: {lines[i]!r}")
        stripped = line.strip()
        if not (stripped.startswith("- ") or stripped == "-"):
            break

        rest = stripped[1:].lstrip()
        if not rest:
            # `-` alone: the item is the indented block beneath it.
            value, i = _parse_node(lines, i + 1, indent + 1)
            items.append(value)
            continue

        # `- key: value` starts a mapping whose other keys are indented to line
        # up with `key`. Splice the remainder in as a synthetic first line.
        if _is_mapping_start(rest):
            synthetic_indent = indent + (len(line) - len(line.lstrip()) - indent) + 2
            patched = list(lines)
            patched[i] = " " * synthetic_indent + rest
            value, i = _parse_mapping(patched, i, synthetic_indent)
            items.append(value)
            continue

        items.append(_scalar(rest))
        i += 1
    return items, i


def _is_mapping_start(text: str) -> bool:
    """True for `key: ...`, false for a plain scalar containing a colon."""
    quote: str | None = None
    for idx, char in enumerate(text):
        if quote:
            if char == quote:
                quote = None
            continue
        if char in "\"'":
            quote = char
        elif char == ":":
            return idx + 1 == len(text) or text[idx + 1] in " \t"
    return False


def _parse_mapping(lines: list[str], i: int, indent: int) -> tuple[dict, int]:
    result: dict[str, Any] = {}
    while True:
        i = _next_content(lines, i)
        if i >= len(lines):
            break
        line = _strip_comment(lines[i])
        if _indent(line) != indent:
            if _indent(line) < indent:
                break
            raise YamlError(f"unexpected indent at line {i + 1}: {lines[i]!r}")
        stripped = line.strip()
        if stripped.startswith("- "):
            break
        if not _is_mapping_start(stripped):
            raise YamlError(f"expected 'key: value' at line {i + 1}: {lines[i]!r}")

        key, _, rest = stripped.partition(":")
        key = _scalar(key.strip())
        rest = rest.strip()

        if rest in ("|", "|-", ">", ">-"):
            value, i = _parse_block_scalar(lines, i + 1, indent, rest)
        elif rest == "":
            value, i = _parse_node(lines, i + 1, indent + 1)
        else:
            value = _scalar(rest)
            i += 1
        result[key] = value
    return result, i


def _parse_block_scalar(lines: list[str], i: int, indent: int, style: str) -> tuple[str, int]:
    collected: list[str] = []
    body_indent: int | None = None
    while i < len(lines):
        raw = lines[i]
        if not raw.strip():
            collected.append("")
            i += 1
            continue
        if _indent(raw) <= indent:
            break
        if body_indent is None:
            body_indent = _indent(raw)
        collected.append(raw[body_indent:])
        i += 1

    while collected and not collected[-1]:
        collected.pop()

    if style.startswith("|"):
        text = "\n".join(collected)
    else:
        # Folded: single newlines become spaces, blank lines become newlines.
        paragraphs: list[list[str]] = [[]]
        for entry in collected:
            if entry:
                paragraphs[-1].append(entry.strip())
            else:
                paragraphs.append([])
        text = "\n".join(" ".join(p) for p in paragraphs if p)

    if not style.endswith("-") and style.startswith("|"):
        text += "\n"
    return text, i


def _scalar(token: str) -> Any:
    token = token.strip()
    if len(token) >= 2 and token[0] == token[-1] and token[0] in "\"'":
        return token[1:-1]
    if token.startswith("[") and token.endswith("]"):
        inner = token[1:-1].strip()
        if not inner:
            return []
        return [_scalar(part) for part in _split_inline(inner)]
    lowered = token.lower()
    if lowered in ("true", "yes", "on"):
        return True
    if lowered in ("false", "no", "off"):
        return False
    if lowered in ("null", "~", ""):
        return None
    try:
        return int(token)
    except ValueError:
        pass
    try:
        return float(token)
    except ValueError:
        pass
    return token


def _split_inline(inner: str) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    quote: str | None = None
    for char in inner:
        if quote:
            current.append(char)
            if char == quote:
                quote = None
            continue
        if char in "\"'":
            quote = char
            current.append(char)
        elif char == ",":
            parts.append("".join(current))
            current = []
        else:
            current.append(char)
    if current:
        parts.append("".join(current))
    return [p.strip() for p in parts if p.strip()]
