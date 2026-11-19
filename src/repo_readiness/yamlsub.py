"""A strict YAML subset parser (Python 3.9 standard library only).

Supported: block mappings and sequences (indented with spaces), flow
collections ``{}`` / ``[]`` on a single line, single- and double-quoted
strings, plain scalars, comments, and one optional leading ``---``.

Block scalars (``|`` literal, ``>`` folded, with ``-`` / ``+`` chomping) are
supported because real CI workflows use them; their content is taken raw.

Everything else is rejected with a YamlSubsetError carrying the line number:
anchors, aliases, tags, block-scalar indentation indicators, multiple documents,
tab indentation, complex keys, duplicate keys, multi-line plain or quoted
scalars and multi-line flow collections. Failing loudly is the point: a
readiness verdict must never rest on a file we only half understood.

Scalar resolution is deliberately conservative: null / ~ / empty -> None,
true/false -> bool, decimal integers -> int, decimal floats -> float,
everything else (dates, hex, versions) -> str. Mapping keys are always str.
"""

import re
from pathlib import Path
from typing import Any, Dict, List, NamedTuple, Optional, Tuple, Union

__all__ = ["YamlSubsetError", "load", "loads"]


class YamlSubsetError(ValueError):
    def __init__(self, line: int, message: str):
        super().__init__("line %d: %s" % (line, message))
        self.line = line


class _Tok(NamedTuple):
    line: int
    indent: int
    text: str


_QUOTE_OPENERS = set(":-,[{?")
_NULLS = {"", "~", "null", "Null", "NULL"}
_TRUES = {"true", "True", "TRUE"}
_FALSES = {"false", "False", "FALSE"}
_INT = re.compile(r"[-+]?[0-9]+\Z")
_FLOAT = re.compile(r"[-+]?([0-9]+\.[0-9]*|\.[0-9]+)([eE][-+]?[0-9]+)?\Z")
_SIMPLE_ESCAPES = {'"': '"', "\\": "\\", "/": "/", "n": "\n", "t": "\t", "r": "\r", "0": "\0"}


def load(path: Union[str, Path]) -> Any:
    return loads(Path(path).read_text(encoding="utf-8"))


def loads(text: str) -> Any:
    toks, blocks = _tokenize(text)
    if not toks:
        return None
    parser = _Parser(toks, blocks)
    value, i = parser.block(0, toks[0].indent)
    if i < len(toks):
        raise YamlSubsetError(toks[i].line, "unexpected indentation or trailing content")
    return value


# --------------------------------------------------------------------------- lines

def _strip_comment(raw: str, line: int) -> str:
    """Drop a trailing comment, honouring quotes. Quotes must close on the same line."""
    quote = None
    prev_sig = None  # previous non-space character outside quotes
    i = 0
    while i < len(raw):
        c = raw[i]
        if quote == '"':
            if c == "\\":
                i += 2
                continue
            if c == '"':
                quote = None
        elif quote == "'":
            if c == "'":
                if i + 1 < len(raw) and raw[i + 1] == "'":
                    i += 2
                    continue
                quote = None
        else:
            if c == "#" and (i == 0 or raw[i - 1] in " \t"):
                return raw[:i]
            if c in "\"'" and (prev_sig is None or prev_sig in _QUOTE_OPENERS):
                quote = c
            if c not in " \t":
                prev_sig = c
        i += 1
    if quote is not None:
        raise YamlSubsetError(line, "unterminated quoted string (quoted scalars must fit on one line)")
    return raw


_BLOCK = "\x00block\x00"  # stands in for a block scalar's value in token text
_BLOCK_HEADER = re.compile(r"(?:^|(?<=\s))([|>])([0-9]?)([-+]?)([0-9]?)\Z")


def _block_header(content: str, indent: int, line: int) -> Optional[Tuple[str, str, str, int]]:
    """If content ends in a block scalar indicator after 'key:' or '-', return
    (text with the indicator replaced by _BLOCK, style, chomp, parent column)."""
    m = _BLOCK_HEADER.search(content)
    if not m:
        return None
    before = content[: m.start()].rstrip()
    if not (before.endswith(":") or before == "-" or before.endswith(" -")):
        return None
    if before.endswith(":") and before != ":" and _split_key(before, line) is None:
        return None  # the ':' is inside quotes or brackets, so this is a plain value
    if m.group(2) or m.group(4):
        raise YamlSubsetError(line, "block scalar indentation indicator is not supported")
    if before == "-" or before.endswith(" -"):
        parent = indent  # "- |": the sequence item itself
    elif content.startswith("- "):
        parent = indent + (len(content) - len(content[1:].lstrip(" ")))  # "- key: |": the key's column
    else:
        parent = indent
    return before + " " + _BLOCK, m.group(1), m.group(3), parent


def _finish_block(lines: List[str], style: str, chomp: str, trailing_blank: int = 0) -> str:
    """Join de-indented block content lines, then apply chomping.

    Folding (>) joins adjacent plain lines with a space; an empty line becomes a
    newline; more-indented lines are kept on their own lines.
    """
    if not lines:
        return "\n" * trailing_blank if chomp == "+" else ""
    if style == "|":
        body = "\n".join(lines)
    else:
        out = []  # type: List[str]
        for k, ln in enumerate(lines):
            if k == 0:
                out.append(ln)
                continue
            prev = lines[k - 1]
            if ln == "":
                out.append("\n")
            elif prev == "" or ln.startswith(" ") or prev.startswith(" "):
                out.append(("\n" if prev != "" else "") + ln)
            else:
                out.append(" " + ln)
        body = "".join(out)
    if chomp == "-":
        return body
    if chomp == "+":
        return body + "\n" + "\n" * trailing_blank
    return body + "\n"


def _tokenize(text: str) -> Tuple[List[_Tok], Dict[int, str]]:
    toks = []  # type: List[_Tok]
    blocks = {}  # type: Dict[int, str]
    raws = text.splitlines()
    i = 0
    while i < len(raws):
        n, raw = i + 1, raws[i]
        i += 1
        lead = raw[: len(raw) - len(raw.lstrip(" \t"))]
        if "\t" in lead and raw.strip():
            raise YamlSubsetError(n, "tab in indentation is not supported")
        body = _strip_comment(raw, n).rstrip()
        if not body.strip():
            continue
        content = body.lstrip(" ")
        indent = len(body) - len(content)
        if content == "---" or content.startswith("--- "):
            if toks or content != "---":
                raise YamlSubsetError(n, "multiple documents are not supported")
            continue
        if content == "..." or content.startswith("%"):
            raise YamlSubsetError(n, "multiple documents and directives are not supported")
        header = _block_header(content, indent, n)
        if header:
            content, style, chomp, parent = header
            lines = []  # type: List[str]
            content_indent = None
            while i < len(raws):
                r = raws[i]
                if not r.strip():
                    lines.append("")
                    i += 1
                    continue
                lead = len(r) - len(r.lstrip(" "))
                if r[lead:lead + 1] == "\t" and lead <= (content_indent or parent):
                    raise YamlSubsetError(i + 1, "tab in indentation is not supported")
                if lead <= parent:
                    break
                if content_indent is None:
                    content_indent = lead
                elif lead < content_indent:
                    raise YamlSubsetError(i + 1, "line is less indented than the block scalar's content")
                lines.append(r[content_indent:])
                i += 1
            trailing = 0
            while lines and lines[-1] == "":
                lines.pop()
                trailing += 1
            blocks[n] = _finish_block(lines, style, chomp, trailing)
        toks.append(_Tok(n, indent, content))
    return toks, blocks


def _is_item(text: str) -> bool:
    return text == "-" or text.startswith("- ")


# --------------------------------------------------------------------------- block

class _Parser:
    def __init__(self, toks: List[_Tok], blocks: Dict[int, str]):
        self.toks = toks
        self.blocks = blocks

    def _value(self, text: str, line: int) -> Any:
        if text == _BLOCK:
            return self.blocks[line]
        return _inline(text, line)

    def block(self, i: int, indent: int) -> Tuple[Any, int]:
        if _is_item(self.toks[i].text):
            return self.sequence(i, indent)
        return self.mapping(i, indent)

    def mapping(self, i: int, indent: int) -> Tuple[dict, int]:
        out = {}  # type: dict
        toks = self.toks
        while i < len(toks):
            t = toks[i]
            if t.indent < indent:
                break
            if t.indent > indent:
                raise YamlSubsetError(t.line, "unexpected indentation")
            if _is_item(t.text):
                raise YamlSubsetError(t.line, "sequence item where a mapping key was expected")
            if t.text == "?" or t.text.startswith("? "):
                raise YamlSubsetError(t.line, "complex key ('? ') is not supported")
            split = _split_key(t.text, t.line)
            if split is None:
                raise YamlSubsetError(t.line, "expected 'key: value'")
            key, rest = split
            if key in out:
                raise YamlSubsetError(t.line, "duplicate key %r" % key)
            i += 1
            if rest:
                out[key] = self._value(rest, t.line)
                if i < len(toks) and toks[i].indent > indent:
                    raise YamlSubsetError(toks[i].line, "unexpected indentation (multi-line values are not supported)")
            elif i < len(toks) and toks[i].indent > indent:
                out[key], i = self.block(i, toks[i].indent)
            elif i < len(toks) and toks[i].indent == indent and _is_item(toks[i].text):
                out[key], i = self.sequence(i, indent)
            else:
                out[key] = None
        return out, i

    def sequence(self, i: int, indent: int) -> Tuple[list, int]:
        out = []  # type: list
        toks = self.toks
        while i < len(toks):
            t = toks[i]
            if t.indent < indent or not _is_item(t.text):
                if t.indent > indent:
                    raise YamlSubsetError(t.line, "unexpected indentation")
                break
            if t.indent > indent:
                raise YamlSubsetError(t.line, "unexpected indentation")
            rest = t.text[1:].lstrip(" ")
            if not rest:
                i += 1
                if i < len(toks) and toks[i].indent > indent:
                    value, i = self.block(i, toks[i].indent)
                    out.append(value)
                else:
                    out.append(None)
                continue
            if _is_item(rest) or (_split_key(rest, t.line) is not None and rest[0] not in "{["):
                # "- key: v" or "- - x": the rest opens a nested block at its own column.
                vindent = t.indent + (len(t.text) - len(rest))
                toks[i] = _Tok(t.line, vindent, rest)
                value, i = self.block(i, vindent)
                out.append(value)
                continue
            out.append(self._value(rest, t.line))
            i += 1
            if i < len(toks) and toks[i].indent > indent:
                raise YamlSubsetError(toks[i].line, "unexpected indentation (multi-line values are not supported)")
        return out, i


def _split_key(text: str, line: int) -> Optional[Tuple[str, str]]:
    """Find the first ': ' (or trailing ':') outside quotes and flow brackets."""
    depth = 0
    quote = None
    i = 0
    while i < len(text):
        c = text[i]
        if quote == '"':
            if c == "\\":
                i += 2
                continue
            if c == '"':
                quote = None
        elif quote == "'":
            if c == "'":
                if i + 1 < len(text) and text[i + 1] == "'":
                    i += 2
                    continue
                quote = None
        elif c in "\"'" and (i == 0 or text[i - 1] in " ,[{:"):
            quote = c
        elif c in "[{":
            depth += 1
        elif c in "]}":
            depth -= 1
        elif c == ":" and depth == 0 and (i + 1 == len(text) or text[i + 1] == " "):
            key = text[:i].strip()
            if not key:
                raise YamlSubsetError(line, "empty mapping key")
            return _key(key, line), text[i + 1:].strip()
        i += 1
    return None


def _key(raw: str, line: int) -> str:
    if raw[0] in "\"'":
        value, end = _quoted(raw, 0, line)
        if raw[end:].strip():
            raise YamlSubsetError(line, "unexpected text after quoted key")
        return value
    _reject_indicator(raw, line)
    return raw


# --------------------------------------------------------------------------- scalars and flow

def _reject_indicator(text: str, line: int) -> None:
    c = text[0]
    if c == "&":
        raise YamlSubsetError(line, "anchor ('&') is not supported")
    if c == "*":
        raise YamlSubsetError(line, "alias ('*') is not supported")
    if c == "!":
        raise YamlSubsetError(line, "tag ('!') is not supported")
    if c in "|>":
        raise YamlSubsetError(line, "block scalar ('|' / '>') is not supported")
    if c in "@`%":
        raise YamlSubsetError(line, "reserved indicator %r" % c)


def _inline(text: str, line: int) -> Any:
    if text[0] in "{[":
        value, end = _flow(text, 0, line)
        if text[end:].strip():
            raise YamlSubsetError(line, "unexpected text after flow collection")
        return value
    if text[0] in "\"'":
        value, end = _quoted(text, 0, line)
        if text[end:].strip():
            raise YamlSubsetError(line, "unexpected text after quoted string")
        return value
    _reject_indicator(text, line)
    if ": " in text or text.endswith(":"):
        raise YamlSubsetError(line, "plain value contains ': ' (quote it)")
    return _resolve(text)


def _resolve(plain: str) -> Any:
    if plain in _NULLS:
        return None
    if plain in _TRUES:
        return True
    if plain in _FALSES:
        return False
    if _INT.match(plain):
        return int(plain)
    if _FLOAT.match(plain):
        return float(plain)
    return plain


def _quoted(text: str, i: int, line: int) -> Tuple[str, int]:
    q = text[i]
    i += 1
    buf = []
    while i < len(text):
        c = text[i]
        if q == "'":
            if c == "'":
                if i + 1 < len(text) and text[i + 1] == "'":
                    buf.append("'")
                    i += 2
                    continue
                return "".join(buf), i + 1
            buf.append(c)
            i += 1
            continue
        if c == '"':
            return "".join(buf), i + 1
        if c == "\\":
            if i + 1 >= len(text):
                break
            e = text[i + 1]
            if e in _SIMPLE_ESCAPES:
                buf.append(_SIMPLE_ESCAPES[e])
                i += 2
            elif e in "xu":
                width = 2 if e == "x" else 4
                hexdigits = text[i + 2:i + 2 + width]
                if len(hexdigits) != width or not re.match(r"[0-9a-fA-F]+\Z", hexdigits):
                    raise YamlSubsetError(line, "bad \\%s escape" % e)
                buf.append(chr(int(hexdigits, 16)))
                i += 2 + width
            else:
                raise YamlSubsetError(line, "unsupported escape \\%s" % e)
            continue
        buf.append(c)
        i += 1
    raise YamlSubsetError(line, "unterminated quoted string")


def _skip_ws(text: str, i: int) -> int:
    while i < len(text) and text[i] == " ":
        i += 1
    return i


def _flow(text: str, i: int, line: int) -> Tuple[Any, int]:
    """Parse a flow collection starting at text[i] ('{' or '[')."""
    opener = text[i]
    closer = "}" if opener == "{" else "]"
    out = {} if opener == "{" else []  # type: Any
    i = _skip_ws(text, i + 1)
    if i < len(text) and text[i] == closer:
        return out, i + 1
    while True:
        if i >= len(text):
            raise YamlSubsetError(line, "unterminated flow collection (must fit on one line)")
        if opener == "{":
            key, i = _flow_scalar(text, i, line, ":")
            if not isinstance(key, str):
                key = "" if key is None else str(key)
            i = _skip_ws(text, i)
            if i >= len(text) or text[i] != ":":
                raise YamlSubsetError(line, "expected ':' in flow mapping")
            i = _skip_ws(text, i + 1)
            value, i = _flow_value(text, i, line)
            if key in out:
                raise YamlSubsetError(line, "duplicate key %r" % key)
            out[key] = value
        else:
            value, i = _flow_value(text, i, line)
            out.append(value)
        i = _skip_ws(text, i)
        if i >= len(text):
            raise YamlSubsetError(line, "unterminated flow collection (must fit on one line)")
        if text[i] == ",":
            i = _skip_ws(text, i + 1)
            continue
        if text[i] == closer:
            return out, i + 1
        raise YamlSubsetError(line, "expected ',' or %r in flow collection" % closer)


def _flow_value(text: str, i: int, line: int) -> Tuple[Any, int]:
    if i < len(text) and text[i] in "{[":
        return _flow(text, i, line)
    return _flow_scalar(text, i, line, "")


def _flow_scalar(text: str, i: int, line: int, extra_stop: str) -> Tuple[Any, int]:
    if i >= len(text):
        raise YamlSubsetError(line, "unterminated flow collection (must fit on one line)")
    if text[i] in "\"'":
        return _quoted(text, i, line)
    start = i
    while i < len(text) and text[i] not in ",]}":
        if extra_stop and text[i] == ":" and (i + 1 == len(text) or text[i + 1] in " ,}"):
            break
        i += 1
    plain = text[start:i].strip()
    if not plain:
        raise YamlSubsetError(line, "empty entry in flow collection")
    _reject_indicator(plain, line)
    return _resolve(plain), i
