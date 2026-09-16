# SPDX-License-Identifier: MIT

"""Incremental parsers and encoders for VCALENDAR and VCARD streams.

The batch codecs hold a whole document in memory on both sides. These
read one component — or one card — at a time from a line source, and
write one at a time to a sink, so a ledger larger than memory still
moves through.

Both parsers implement the iterator protocol. Exhaustion is
``StopIteration``, never an error: a stream that ends where it should
has not failed. A real parse failure raises a
:class:`~vstar.VstarError` subclass.

**The parsers unescape.** Each routes its content lines through its own
format's parser — :mod:`vstar.codec.rfc5545` for calendars,
:mod:`vstar.codec.rfc6350` for cards — so a streamed parse of a
document equals its batch parse, property for property. Splitting a
content line and unescaping its value are separate steps, and a stream
parser that performs only the first leaves ``FN:Last\\, Comma`` escaped
where the batch parser would not. The two parses would then disagree
about the same bytes.

Unfolding happens on **bytes**, before any decoding: a fold lands on an
octet boundary and may split a multi-byte UTF-8 sequence (spec rule 3),
so decoding physical lines first would replace both halves with U+FFFD
and lose the character before the fold was ever rejoined.

Input is pulled a chunk at a time rather than read whole — a streaming
parser that materializes its input first is streaming in name only.

Neither encoder closes its sink — the caller owns that lifecycle. No
type here is safe for concurrent use; give each thread its own.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Protocol

from ..._contentline import Input, escape_text, fold_line, unescape_text
from ...errors import (
    AlreadyClosed,
    HeaderLocked,
    Malformed,
    UnclosedBlock,
    UnsupportedVersion,
)
from ...types import Calendar, Card, Component, CompType, Kind, Property
from ..rfc5545._encoder import encode_component
from ..rfc5545._parser import parse_content_line as parse_calendar_line
from ..rfc5545._text import SUPPORTED_VERSION as CALENDAR_VERSION
from ..rfc5545._text import is_text_property
from ..rfc6350._encoder import encode as encode_card
from ..rfc6350._parser import SUPPORTED_VERSION as CARD_VERSION
from ..rfc6350._parser import parse_content_line as parse_card_line

__all__ = [
    "ByteSink",
    "CardStreamEncoder",
    "CardStreamParser",
    "StreamEncoder",
    "StreamParser",
    "VCalendarEncoder",
    "VCalendarParser",
    "VCardEncoder",
    "VCardParser",
]

#: The default PRODID, matching the batch encoder's so a streamed
#: calendar and a batch-encoded one agree byte for byte.
_DEFAULT_PROD_ID = "-//hop-top//vstar//EN"

_KW_BEGIN = "BEGIN"
_KW_END = "END"


class ByteSink(Protocol):
    """Anything an encoder can write bytes to.

    Narrower than :class:`io.BufferedWriter` on purpose: an encoder
    needs only ``write``, and demanding more would rule out the
    single-method sinks a caller writes to tee, count or checksum the
    stream on its way past.
    """

    def write(self, data: bytes, /) -> object: ...


class StreamParser(Protocol):
    """Yields one :class:`~vstar.Component` at a time."""

    def __iter__(self) -> Iterator[Component]: ...

    def __next__(self) -> Component: ...


class StreamEncoder(Protocol):
    """Accepts one :class:`~vstar.Component` at a time."""

    def encode(self, c: Component) -> None: ...

    def close(self) -> None: ...


class CardStreamParser(Protocol):
    """Yields one :class:`~vstar.Card` at a time."""

    def __iter__(self) -> Iterator[Card]: ...

    def __next__(self) -> Card: ...


class CardStreamEncoder(Protocol):
    """Accepts one :class:`~vstar.Card` at a time."""

    def encode(self, c: Card) -> None: ...

    def close(self) -> None: ...


class _LineSource:
    """Logical content lines, pulled from the input as they are asked for.

    The shared :class:`~vstar._contentline.Scanner` splits the whole
    input into physical lines at construction, which is right for a
    batch parse and wrong here: a streaming parser that materializes its
    input first is streaming in name only. This reads a chunk at a time
    instead, and holds no more than the logical line currently being
    assembled plus one unterminated tail.

    Unfolding runs on **bytes**, and each assembled logical line is
    decoded only once it is whole. RFC 5545 §3.1 folds at an *octet*
    boundary, which may land mid-rune; decoding physical lines first
    would replace both halves of a split sequence with U+FFFD before
    they could be rejoined, and the character would be gone. The shared
    scanner takes the same care, and this must not be the place the port
    quietly stops taking it.

    Input is read liberally: CRLF, bare LF and a mixture all terminate,
    blank lines outside a fold are skipped, and a WSP-prefixed line with
    nothing pending has its leading WSP stripped and starts fresh.
    """

    #: Bytes pulled per read. Large enough that a typical document costs
    #: few syscalls, small enough that "the parser read everything" and
    #: "the parser read a line" remain distinguishable.
    _CHUNK = 8192

    __slots__ = ("_buf", "_eof", "_has_pending", "_pending", "_read")

    def __init__(self, data: Input) -> None:
        self._read = _chunk_reader(data)
        self._buf = b""
        self._eof = False
        self._pending = b""
        self._has_pending = False

    def next(self) -> str | None:
        """The next logical line, terminator stripped, or ``None`` at end."""
        while True:
            raw = self._next_physical()
            if raw is None:
                if not self._has_pending:
                    return None
                out, self._pending = self._pending, b""
                self._has_pending = False
                return _decode(out) if out != b"" else None

            if raw[:1] in (b" ", b"\t"):
                # A fold continuation — or, with nothing pending, a fresh
                # logical line whose leading WSP is stripped.
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

    def _next_physical(self) -> bytes | None:
        """One physical line's bytes, reading more input only as needed."""
        while True:
            nl = self._buf.find(b"\n")
            if nl >= 0:
                line, self._buf = self._buf[:nl], self._buf[nl + 1 :]
                return line[:-1] if line.endswith(b"\r") else line
            if self._eof:
                if self._buf == b"":
                    return None
                # A trailing line with no terminator is still a line.
                line, self._buf = self._buf, b""
                return line[:-1] if line.endswith(b"\r") else line
            chunk = self._read(self._CHUNK)
            if not chunk:
                self._eof = True
                continue
            self._buf += chunk


class VCalendarParser:
    """Reads a VCALENDAR one top-level component at a time.

    The header — ``VERSION`` and ``PRODID`` — is consumed lazily, on the
    first :meth:`header` call or the first iteration step, whichever
    comes first. Each subsequent step returns the next component,
    sub-components nested inside it, and ``StopIteration`` once
    ``END:VCALENDAR`` is consumed.

    Calendar-level properties are accepted only in the header section.
    One appearing among the components is :class:`~vstar.Malformed`:
    the shape a producer emits is a header followed by a component run,
    and accepting an interleaved property would make ``header()``'s
    answer depend on how far iteration had progressed.
    """

    def __init__(self, data: Input) -> None:
        """Wrap ``data`` — bytes, text or a readable stream."""
        self._scanner = _LineSource(data)
        self._header = Calendar(prod_id="")
        self._header_read = False
        self._pending: str | None = None
        self._done = False

    def header(self) -> Calendar:
        """The calendar's ``PRODID``, with no components attached.

        Callable before the first iteration step: it consumes the header
        section on demand. A malformed header raises here, and raises
        again from the next iteration step — the parse does not silently
        continue past it.
        """
        self._ensure_header()
        return self._header

    def __iter__(self) -> Iterator[Component]:
        """Iterate the calendar's top-level components."""
        return self

    def __next__(self) -> Component:
        """The next top-level component.

        :raises StopIteration: once ``END:VCALENDAR`` is consumed.
        :raises Malformed: on a structural violation.
        :raises UnclosedBlock: at end of input inside an open block.
        """
        if self._done:
            raise StopIteration
        self._ensure_header()

        line = self._next_line()
        if line is None:
            raise UnclosedBlock("BEGIN:VCALENDAR never closed")

        prop = parse_calendar_line(line)
        upper = prop.name.upper()

        if upper == _KW_END:
            if prop.value.upper() != "VCALENDAR":
                raise Malformed(f"END:{prop.value} does not match BEGIN:VCALENDAR")
            self._done = True
            raise StopIteration
        if upper == _KW_BEGIN:
            return self._read_block(prop.value)
        raise Malformed(
            f"unexpected calendar-level property {prop.name!r} after components"
        )

    def _ensure_header(self) -> None:
        """Consume ``BEGIN:VCALENDAR`` and the calendar-level properties.

        The boundary line — the first ``BEGIN:`` or ``END:VCALENDAR`` —
        is stashed for the next read rather than pushed back into the
        scanner, which keeps the lookahead to exactly one line.
        """
        if self._header_read:
            return
        # Latched before the work so a raising call does not re-run the
        # header scan and consume a second document's worth of lines.
        self._header_read = True

        first = self._scanner.next()
        if first is None:
            raise Malformed("empty input")
        if first.upper() != "BEGIN:VCALENDAR":
            raise Malformed(f"expected BEGIN:VCALENDAR, got {first!r}")

        while True:
            line = self._scanner.next()
            if line is None:
                raise UnclosedBlock("BEGIN:VCALENDAR never closed")

            prop = parse_calendar_line(line)
            upper = prop.name.upper()
            if upper in (_KW_BEGIN, _KW_END):
                self._pending = line
                return

            if upper == "VERSION":
                if prop.value != CALENDAR_VERSION:
                    raise UnsupportedVersion(
                        f"VERSION={prop.value!r} (only {CALENDAR_VERSION!r} supported)"
                    )
            elif upper == "PRODID":
                # PRODID is TEXT-typed, and the batch parser unescapes it
                # on the way through its block parser before lifting it
                # onto the Calendar. Doing the same here is what keeps a
                # streamed header equal to a batch-parsed one.
                self._header.prod_id = _unescape_calendar_value(prop)

    def _next_line(self) -> str | None:
        """The stashed boundary line, else the scanner's next."""
        if self._pending is not None:
            line, self._pending = self._pending, None
            return line
        return self._scanner.next()

    def _read_block(self, type_name: str) -> Component:
        """Assemble one component, recursing into nested blocks."""
        tname = type_name.upper()
        out = Component(type=CompType(tname), props=[], sub=[])

        while True:
            line = self._scanner.next()
            if line is None:
                raise UnclosedBlock(f"BEGIN:{tname} never closed")

            prop = parse_calendar_line(line)
            upper = prop.name.upper()

            if upper == _KW_BEGIN:
                try:
                    out.sub.append(self._read_block(prop.value))
                except RecursionError as exc:
                    raise Malformed("component nesting too deep") from exc
                continue
            if upper == _KW_END:
                if prop.value.upper() != tname:
                    raise Malformed(f"END:{prop.value} does not match BEGIN:{tname}")
                return out

            # Unescape TEXT-typed values exactly as the batch block
            # parser does, so a streamed parse equals a batch parse.
            # Splitting the content line does not do this on its own:
            # the escape rules are property-typed, and the type table
            # lives a layer above the splitter.
            prop.value = _unescape_calendar_value(prop)
            out.props.append(prop)


class VCardParser:
    """Reads a vCard stream one card at a time.

    A vCard stream is a run of self-contained ``BEGIN:VCARD`` …
    ``END:VCARD`` blocks with no enclosing wrapper, so there is no
    header to read and no :meth:`header` method. Blank lines between
    blocks are skipped; empty input yields no cards, which is not an
    error.

    A card with no ``UID`` parses fine and leaves ``uid`` empty — the
    encoder is where that becomes a refusal. The asymmetry is
    deliberate: reading stays permissive so a non-conforming document
    can be recovered rather than lost.
    """

    def __init__(self, data: Input) -> None:
        """Wrap ``data`` — bytes, text or a readable stream."""
        self._scanner = _LineSource(data)
        self._done = False

    def __iter__(self) -> Iterator[Card]:
        """Iterate the stream's cards."""
        return self

    def __next__(self) -> Card:
        """The next card.

        :raises StopIteration: at end of input between blocks.
        :raises Malformed: on a structural violation.
        :raises UnsupportedVersion: on a ``VERSION`` other than 4.0.
        :raises UnclosedBlock: at end of input inside an open block.
        """
        if self._done:
            raise StopIteration

        while True:
            line = self._scanner.next()
            if line is None:
                self._done = True
                raise StopIteration
            if line == "":
                continue
            if line.upper() != "BEGIN:VCARD":
                raise Malformed(f"expected BEGIN:VCARD, got {line!r}")
            break

        card = Card()
        version = ""

        while True:
            line = self._scanner.next()
            if line is None:
                raise UnclosedBlock("BEGIN:VCARD never closed")
            if line == "":
                continue

            upper_line = line.upper()
            if upper_line == "END:VCARD":
                if version == "":
                    raise Malformed("VCARD missing VERSION")
                if version != CARD_VERSION:
                    raise UnsupportedVersion(f"VERSION:{version}")
                return card
            if upper_line == "BEGIN:VCARD":
                raise Malformed("nested BEGIN:VCARD")

            # The vCard content-line parser, not the iCalendar one.
            # RFC 6350 §3.3's grammar is close enough that the latter
            # would read the line, but §3.4 TEXT unescaping differs
            # between the formats and lives inside each parser. Reaching
            # for the iCalendar parser here would leave
            # "FN:Last\, Comma" escaped, and the streamed parse would
            # disagree with the batch parse of the same document.
            prop = parse_card_line(line)
            name = prop.name.upper()

            if name == "VERSION":
                if version != "":
                    raise Malformed("duplicate VERSION")
                version = prop.value
                continue
            if name == "UID":
                card.uid = prop.value
                continue
            if name == "KIND":
                card.kind = Kind(prop.value.lower())
                continue
            card.props.append(prop)


class VCalendarEncoder:
    """Writes a VCALENDAR incrementally to a byte sink.

    The header is flushed at the first :meth:`encode`, or at
    :meth:`close` when nothing was encoded at all — so closing an empty
    encoder still produces a legal, empty calendar. Locking the header
    at first encode is what keeps the ``BEGIN:VCALENDAR`` / ``VERSION``
    / ``PRODID`` ordering on the wire deterministic.
    """

    def __init__(self, sink: ByteSink) -> None:
        """Wrap ``sink``, anything with a ``write`` taking bytes."""
        self._sink = sink
        self._header = Calendar(prod_id="")
        self._header_written = False
        self._closed = False

    def set_header(self, h: Calendar) -> None:
        """Set the calendar whose ``PRODID`` the header carries.

        Only ``prod_id`` is read; ``VERSION`` is fixed at 2.0 and the
        components are ignored, since this encoder emits them one at a
        time through :meth:`encode`.

        :raises HeaderLocked: once the first :meth:`encode` has flushed
            the header. There is nothing left to change by then, and
            silently dropping the new value would hide the mistake.
        """
        if self._header_written:
            raise HeaderLocked("set_header after first encode")
        self._header = h

    def encode(self, c: Component) -> None:
        """Append one component, flushing the header if it is pending.

        :raises AlreadyClosed: after :meth:`close`.
        """
        if self._closed:
            raise AlreadyClosed("encode after close")
        self._write_header_once()
        self._sink.write(encode_component(c))

    def close(self) -> None:
        """Write ``END:VCALENDAR`` and finish the stream.

        The sink itself is left open — the caller owns it.

        :raises AlreadyClosed: on a second call. A silently ignored
            double close hides a lifecycle bug that would otherwise
            surface at the first test.
        """
        if self._closed:
            raise AlreadyClosed("close after close")
        self._write_header_once()
        self._sink.write(fold_line("END:VCALENDAR"))
        self._closed = True

    def _write_header_once(self) -> None:
        """Emit the header on first demand and latch it."""
        if self._header_written:
            return
        self._header_written = True
        prod_id = self._header.prod_id or _DEFAULT_PROD_ID
        self._sink.write(fold_line("BEGIN:VCALENDAR"))
        self._sink.write(fold_line(f"VERSION:{CALENDAR_VERSION}"))
        # PRODID is TEXT-typed, so it goes through the shared escaping
        # rather than onto the wire raw — the batch encoder does the
        # same, and the two must agree byte for byte.
        self._sink.write(fold_line(f"PRODID:{escape_text(prod_id)}"))


class VCardEncoder:
    """Writes a vCard stream incrementally to a byte sink.

    There is deliberately **no** ``set_header``. A vCard stream has no
    enclosing wrapper — each :meth:`encode` writes a complete,
    self-contained ``BEGIN:VCARD`` … ``END:VCARD`` block — so there is
    no header to set and no trailer to emit. An encoder that grew one
    for symmetry with :class:`VCalendarEncoder` would have nothing for
    it to do, and its existence would invite a caller to emit a wrapper
    that every parser rejects.

    :meth:`close` therefore exists only to mark the stream finished and
    to make a use-after-close detectable.
    """

    def __init__(self, sink: ByteSink) -> None:
        """Wrap ``sink``, anything with a ``write`` taking bytes."""
        self._sink = sink
        self._closed = False

    def encode(self, c: Card) -> None:
        """Append one complete VCARD block.

        :raises AlreadyClosed: after :meth:`close`.
        :raises MissingUid: when ``c`` has no UID — the encoder is
            where a UID-less card is refused.
        """
        if self._closed:
            raise AlreadyClosed("encode after close")
        self._sink.write(encode_card(c))

    def close(self) -> None:
        """Finish the stream, leaving the sink open.

        :raises AlreadyClosed: on a second call.
        """
        if self._closed:
            raise AlreadyClosed("close after close")
        self._closed = True


def _chunk_reader(data: Input) -> Callable[[int], bytes]:
    """A ``read(n) -> bytes`` over ``data``, whatever shape it arrived in.

    Text and bytes are already whole, so they are served from memory a
    slice at a time — there is nothing to stream. A readable stream is
    read incrementally, which is the case the whole class exists for; a
    text stream's chunks are re-encoded so unfolding still sees octets.
    """
    if isinstance(data, str):
        return _memory_reader(data.encode("utf-8"))
    if isinstance(data, bytes | bytearray):
        return _memory_reader(bytes(data))

    def read(n: int) -> bytes:
        chunk = data.read(n)
        if not chunk:
            return b""
        return chunk.encode("utf-8") if isinstance(chunk, str) else chunk

    return read


def _memory_reader(data: bytes) -> Callable[[int], bytes]:
    """Serve ``data`` in slices, so in-memory input takes the same path."""
    pos = 0

    def read(n: int) -> bytes:
        nonlocal pos
        chunk = data[pos : pos + n]
        pos += len(chunk)
        return chunk

    return read


def _decode(data: bytes) -> str:
    """Decode one assembled logical line.

    Undecodable bytes are replaced rather than raising: a
    ``UnicodeDecodeError`` escaping the codec is not one of the twelve
    documented failure classes.
    """
    return data.decode("utf-8", errors="replace")


def _unescape_calendar_value(p: Property) -> str:
    """``p``'s value, unescaped when the property is TEXT-typed.

    Delegates the type test and the unescape policy to the RFC 5545
    codec so there is exactly one answer to "is this TEXT?" in the port.
    """
    if not is_text_property(p.name):
        return p.value
    return unescape_text(p.value, "drop-backslash")
