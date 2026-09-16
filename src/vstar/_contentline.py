# SPDX-License-Identifier: MIT

"""The shared RFC 5545 §3.1 content-line scanner and folder.

RFC 6350 §3.2 references RFC 5545 §3.1 for line folding, so the
iCalendar and vCard codecs need byte-identical scanning behavior; both
consume this module.

Private to the package: callers outside ``vstar.codec`` reach the
scanner through ``vstar.codec.rfc5545.Scanner``.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import IO, Literal

__all__ = [
    "CRLF",
    "MAX_LINE_OCTETS",
    "Scanner",
    "decode_input",
    "encode_param_value",
    "escape_text",
    "find_first_unquoted",
    "fold_line",
    "new_scanner",
    "scan_all",
    "split_unquoted",
    "unescape_text",
    "unquote_param_value",
]

#: The RFC 5545 §3.1 fold limit, in OCTETS, excluding the terminator.
MAX_LINE_OCTETS = 75

#: The wire-format physical-line terminator.
CRLF = "\r\n"

#: What an unrecognised two-character escape becomes on unescape.
UnknownEscape = Literal["drop-backslash", "keep-both"]

#: Anything a codec accepts as input: text, raw bytes, or a stream.
Input = str | bytes | bytearray | IO[bytes] | IO[str]


def decode_input(data: Input) -> str:
    """Decode codec input, which arrives as text, bytes, or a stream.

    Undecodable bytes are replaced rather than raising: a
    ``UnicodeDecodeError`` escaping the codec is not one of the twelve
    documented failure classes, and the fuzz-seed corpus asserts that
    nothing but a ``VstarError`` ever leaves.
    """
    return _read_bytes(data).decode("utf-8", errors="replace")


def _read_bytes(data: Input) -> bytes:
    """Normalize any accepted input to raw bytes.

    Scanning happens on bytes, not text. RFC 5545 §3.1 folds at an
    *octet* boundary, which may land mid-rune; unfolding the decoded
    text would have already replaced each half of the split sequence
    with U+FFFD and lost the character. Rejoining the octets first and
    decoding the assembled logical line is what makes the round-trip
    lossless — and is what the Go reference gets for free, since its
    strings are byte sequences.
    """
    if isinstance(data, str):
        return data.encode("utf-8")
    if isinstance(data, bytes | bytearray):
        return bytes(data)
    read = data.read()
    return read.encode("utf-8") if isinstance(read, str) else read


class Scanner:
    """A stream of logical content lines, with §3.1 unfolding applied.

    The wire format permits a logical line to be split across physical
    lines by inserting CRLF + (SP | HTAB); on read both the terminator
    and the leading WSP octet are consumed and the continuation is
    appended to the previous logical line.

    The scanner is **liberal on input**: CRLF, bare LF and a mixture are
    all accepted as terminators, blank physical lines outside a fold
    sequence are skipped, and a WSP-prefixed line with no pending
    logical line has its leading WSP stripped and starts a fresh line —
    which is what real-world vCard parsers do, and what keeps a
    malformed blank-then-continuation input from either growing a
    leading space or being silently dropped.

    Unfolding runs on **bytes**, and each assembled logical line is
    decoded only once it is whole. A fold lands on an octet boundary,
    which may sit mid-rune; unfolding decoded text would have replaced
    both halves of the split sequence with U+FFFD before they could be
    rejoined.
    """

    __slots__ = ("_at", "_has_pending", "_pending", "_physical")

    def __init__(self, data: Input) -> None:
        self._physical = _split_physical(_read_bytes(data))
        self._at = 0
        self._pending = b""
        self._has_pending = False

    def next(self) -> str | None:
        """The next logical line, or ``None`` when the input is exhausted.

        The returned string does not include the terminator.
        """
        while True:
            if self._at >= len(self._physical):
                if not self._has_pending:
                    return None
                out = self._pending
                self._pending = b""
                self._has_pending = False
                return _decode(out) if out != b"" else None

            raw = self._physical[self._at]
            self._at += 1

            if raw[:1] in (b" ", b"\t"):
                # A fold continuation — or, with nothing pending, a
                # fresh logical line whose leading WSP is stripped.
                if self._has_pending:
                    self._pending += raw[1:]
                else:
                    self._pending = raw[1:]
                    self._has_pending = True
                continue

            # A new logical line starts here; flush any pending one.
            if self._has_pending:
                out = self._pending
                self._pending = raw
                if raw == b"":
                    self._has_pending = False
                if out == b"":
                    continue
                return _decode(out)

            if raw == b"":
                continue
            self._pending = raw
            self._has_pending = True

    def __iter__(self) -> Iterator[str]:
        """Iterate every remaining logical line."""
        while True:
            line = self.next()
            if line is None:
                return
            yield line


def new_scanner(data: Input) -> Scanner:
    """A :class:`Scanner` over ``data``."""
    return Scanner(data)


def scan_all(data: Input) -> list[str]:
    """Every logical content line of ``data``, in input order."""
    return list(Scanner(data))


def _decode(data: bytes) -> str:
    """Decode one assembled logical line.

    Undecodable bytes are replaced rather than raising: a
    ``UnicodeDecodeError`` escaping the codec is not one of the twelve
    documented failure classes.
    """
    return data.decode("utf-8", errors="replace")


def _split_physical(data: bytes) -> list[bytes]:
    """Split on CRLF or bare LF, dropping the terminators.

    A trailing partial line (no final terminator) is surfaced as a final
    element; a trailing terminator does not produce an empty one.
    """
    if data == b"":
        return []
    out = [line[:-1] if line.endswith(b"\r") else line for line in data.split(b"\n")]
    if out and out[-1] == b"":
        out.pop()
    return out


def fold_line(line: str) -> bytes:
    """Fold one assembled logical line into CRLF-terminated physical lines.

    None exceeds :data:`MAX_LINE_OCTETS` octets. Two rules the whole
    canonical form rests on:

    - **Octets, measured in UTF-8 bytes.** ``len(str)`` counts code
      points: ``"é"`` is 1 there and 2 bytes on the wire. Folding on the
      code-point count puts the fold at the wrong octet, and the damage
      surfaces as a canonical-byte mismatch several layers away.
    - **Applied AFTER property assembly** (spec rule 3). The caller
      hands over the complete logical line — name, every parameter,
      value, with escaping already applied — and this folds that.
      Folding a value before appending parameters puts the fold points
      in the wrong place and still unfolds to the same logical line, so
      only a byte comparison catches it.

    Continuation lines are prefixed with a single SP, which costs one of
    the 75 octets, leaving 74 of payload.
    """
    data = line.encode("utf-8")
    terminator = CRLF.encode("ascii")
    if len(data) <= MAX_LINE_OCTETS:
        return data + terminator

    chunks = [data[:MAX_LINE_OCTETS], terminator]
    rest = data[MAX_LINE_OCTETS:]
    cont_payload = MAX_LINE_OCTETS - 1
    while rest:
        chunks.append(b" ")
        chunks.append(rest[:cont_payload])
        chunks.append(terminator)
        rest = rest[cont_payload:]
    return b"".join(chunks)


def find_first_unquoted(s: str, target: str) -> int | None:
    """The index of the first ``target`` outside any DQUOTE-delimited span.

    ``-1`` when there is none; ``None`` when the string ends inside an
    open quote — the caller decides which sentinel that maps to.
    """
    in_quote = False
    for i, c in enumerate(s):
        if c == '"':
            in_quote = not in_quote
            continue
        if not in_quote and c == target:
            return i
    return None if in_quote else -1


def split_unquoted(s: str, sep: str) -> list[str] | None:
    """Split ``s`` on every ``sep`` outside a DQUOTE-delimited span.

    ``None`` when the string ends inside an open quote.
    """
    out: list[str] = []
    in_quote = False
    start = 0
    for i, c in enumerate(s):
        if c == '"':
            in_quote = not in_quote
            continue
        if c == sep and not in_quote:
            out.append(s[start:i])
            start = i + 1
    if in_quote:
        return None
    out.append(s[start:])
    return out


def unquote_param_value(v: str) -> str:
    """Strip a surrounding DQUOTE pair from a parameter value, if present."""
    if len(v) >= 2 and v.startswith('"') and v.endswith('"'):
        return v[1:-1]
    return v


def encode_param_value(v: str) -> str:
    """Wrap ``v`` in DQUOTEs when it carries a boundary-ambiguous character.

    ``,`` ``;`` or ``:`` per RFC 5545 §3.2. Inner DQUOTEs are dropped —
    the grammar does not permit DQUOTE inside a quoted-string.
    """
    stripped = v.replace('"', "")
    if any(c in stripped for c in ",;:"):
        return f'"{stripped}"'
    return stripped


_ESCAPES = {"\\": "\\\\", ",": "\\,", ";": "\\;", "\n": "\\n"}


def escape_text(s: str) -> str:
    """Apply RFC 5545 §3.3.11 / RFC 6350 §3.4 TEXT escaping.

    ``\\`` becomes ``\\\\`` (first, so a literal backslash is not
    mis-paired), ``,`` becomes ``\\,``, ``;`` becomes ``\\;``, LF
    becomes ``\\n``. CR is dropped: canonical TEXT uses bare LF for
    embedded newlines, so a literal CRLF collapses to a single escaped
    ``\\n``.

    Not idempotent — a string containing a literal backslash gets
    re-escaped on a second pass. The encoder calls it exactly once per
    emit, paired with :func:`unescape_text` on the parse side, which is
    what makes the model hold raw values and the round-trip byte-stable.
    """
    if not any(c in s for c in "\\,;\n\r"):
        return s
    out: list[str] = []
    for c in s:
        if c == "\r":
            continue
        out.append(_ESCAPES.get(c, c))
    return "".join(out)


def unescape_text(s: str, unknown: UnknownEscape) -> str:
    """Reverse RFC 5545 §3.3.11 / RFC 6350 §3.4 TEXT escaping.

    ``\\\\`` becomes ``\\``, ``\\,`` becomes ``,``, ``\\;`` becomes
    ``;``, ``\\n`` and ``\\N`` become LF. A trailing solitary backslash
    is preserved verbatim, which keeps the function total and mirrors
    real-world parser leniency.

    ``unknown`` selects what happens to an unrecognised two-character
    escape such as ``\\x``: ``"drop-backslash"`` keeps only the second
    character (RFC 5545 common practice), ``"keep-both"`` keeps the
    backslash too (the lenient vCard shape). The two codecs differ here,
    so the choice is the caller's.
    """
    if "\\" not in s:
        return s
    out: list[str] = []
    i = 0
    n = len(s)
    while i < n:
        c = s[i]
        if c != "\\" or i + 1 >= n:
            out.append(c)
            i += 1
            continue
        nxt = s[i + 1]
        if nxt == "\\":
            out.append("\\")
        elif nxt == ",":
            out.append(",")
        elif nxt == ";":
            out.append(";")
        elif nxt in ("n", "N"):
            out.append("\n")
        else:
            out.append("\\" + nxt if unknown == "keep-both" else nxt)
        i += 2
    return "".join(out)
