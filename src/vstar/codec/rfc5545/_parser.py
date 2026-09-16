# SPDX-License-Identifier: MIT

"""The RFC 5545 reader: content lines, BEGIN/END blocks, VCALENDAR."""

from __future__ import annotations

from ..._contentline import (
    Input,
    Scanner,
    find_first_unquoted,
    new_scanner,
    split_unquoted,
    unescape_text,
    unquote_param_value,
)
from ...errors import Malformed, UnclosedBlock, UnsupportedVersion
from ...types import Calendar, Component, CompType, Param, Property
from ._text import SUPPORTED_VERSION, is_text_property

__all__ = ["parse", "parse_content_line"]


def parse(data: Input) -> Calendar:
    """Parse a single VCALENDAR from ``data``.

    Property order, parameter order and component order are preserved
    verbatim. No canonicalization happens here — that is the canonical
    layer's business.

    The parser is liberal about line endings (CRLF, LF, or a mixture)
    and strict about structure. Failures raise :class:`Malformed`,
    :class:`UnclosedBlock` or :class:`UnsupportedVersion`.
    """
    scanner = new_scanner(data)

    first = scanner.next()
    if first is None:
        raise Malformed("empty input")
    if first.upper() != "BEGIN:VCALENDAR":
        raise Malformed(f"expected BEGIN:VCALENDAR, got {first!r}")

    root = _parse_block(scanner, "VCALENDAR")

    cal = Calendar(prod_id="", components=root.sub)
    for p in root.props:
        upper = p.name.upper()
        if upper == "VERSION":
            if p.value != SUPPORTED_VERSION:
                raise UnsupportedVersion(
                    f"VERSION={p.value!r} (only {SUPPORTED_VERSION!r} supported)"
                )
        elif upper == "PRODID":
            cal.prod_id = p.value

    # Trailing content after END:VCALENDAR is ignored on purpose:
    # producers concatenate streams and scanners round up trailing
    # whitespace. The stance is strict-but-not-pedantic — we got a valid
    # calendar, stop reading.
    return cal


def _parse_block(scanner: Scanner, type_name: str) -> Component:
    """Consume content lines until ``END:<type_name>``, assembling one component.

    Nested ``BEGIN:`` blocks recurse onto ``sub``; a mismatched ``END``
    is :class:`Malformed`; end of input before ``END`` is
    :class:`UnclosedBlock`.

    The recursion is bounded by the input's own nesting depth; a
    pathologically deep document raises :class:`Malformed` rather than
    letting a ``RecursionError`` escape the codec.
    """
    out = Component(type=_comp_type(type_name), props=[], sub=[])

    while True:
        line = scanner.next()
        if line is None:
            raise UnclosedBlock(f"BEGIN:{type_name} never closed")

        prop = parse_content_line(line)
        upper = prop.name.upper()

        if upper == "BEGIN":
            try:
                out.sub.append(_parse_block(scanner, prop.value))
            except RecursionError as exc:
                raise Malformed("component nesting too deep") from exc
            continue
        if upper == "END":
            if prop.value.upper() != type_name.upper():
                raise Malformed(f"END:{prop.value} does not match BEGIN:{type_name}")
            return out

        # Unescape TEXT-typed values so the in-memory model holds raw
        # values; the encoder re-applies escaping symmetrically, which
        # is what makes a parse -> encode round-trip byte-stable.
        if is_text_property(prop.name):
            prop.value = unescape_text(prop.value, "drop-backslash")
        out.props.append(prop)


def _comp_type(name: str) -> CompType:
    """The wire name as a :class:`CompType`, uppercased.

    An unregistered identifier is kept verbatim rather than rejected:
    the parser is strict about structure and lossless about content, and
    the validation layer is where an unknown component type is reported.
    ``STANDARD`` and ``DAYLIGHT`` inside a ``VTIMEZONE`` take this path.
    """
    return CompType(name.upper())


def parse_content_line(line: str) -> Property:
    """Parse a single, already-unfolded RFC 5545 content line.

    The grammar (RFC 5545 §3.1)::

        contentline = name *(";" param) ":" value
        param       = param-name "=" param-value *("," param-value)
        param-value = paramtext / quoted-string

    A DQUOTE-wrapped parameter value may contain commas, semicolons and
    colons; an unquoted one may not. The wire case of names and
    parameter names is preserved verbatim — case-insensitive matching is
    the consumer's job.

    Raises :class:`Malformed` for a missing colon, an empty name, a
    parameter without ``=``, or an unbalanced DQUOTE.
    """
    colon = find_first_unquoted(line, ":")
    if colon is None:
        raise Malformed(f"unbalanced quote in {line!r}")
    if colon < 0:
        raise Malformed(f"missing colon in content line {line!r}")

    head = line[:colon]
    value = line[colon + 1 :]

    segs = split_unquoted(head, ";")
    if segs is None:
        raise Malformed(f"unbalanced quote in {line!r}")
    name = segs[0]
    if name == "":
        raise Malformed(f"empty property name in {line!r}")

    params: list[Param] = []
    for seg in segs[1:]:
        eq = seg.find("=")
        if eq <= 0:
            raise Malformed(f"malformed parameter {seg!r} in {line!r}")
        params.append(Param(seg[:eq], unquote_param_value(seg[eq + 1 :])))

    return Property(name=name, params=params, value=value)
