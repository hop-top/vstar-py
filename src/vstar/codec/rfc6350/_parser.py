# SPDX-License-Identifier: MIT

"""The RFC 6350 reader: group prefixes, framing, a LIST of cards."""

from __future__ import annotations

from ..._contentline import (
    Input,
    find_first_unquoted,
    scan_all,
    unescape_text,
    unquote_param_value,
)
from ...errors import Malformed, UnclosedBlock, UnsupportedVersion
from ...types import Card, Kind, Param, Property

__all__ = ["SUPPORTED_VERSION", "parse", "parse_content_line"]

#: The only vCard ``VERSION`` value accepted.
SUPPORTED_VERSION = "4.0"


def parse(data: Input) -> list[Card]:
    """Parse every ``BEGIN:VCARD...END:VCARD`` block into a **list**.

    A vCard stream is a sequence of self-contained blocks with no
    enclosing wrapper, so a file with three cards parses to three
    :class:`~vstar.Card` values. Empty input returns an empty list —
    "no cards" is not an error.

    ``UID`` handling is asymmetric across this codec. The parser
    **accepts** a VCARD with no ``UID`` property, leaving ``card.uid``
    as ``""``; the encoder **refuses** such a card with
    :class:`~vstar.MissingUid`, and the validation layer reports it as
    a diagnostic. That asymmetry is deliberate: the parser is permissive
    so adopters can recover a non-conforming document rather than lose
    it, and strictness lives where it can be opted into.

    Failures raise :class:`~vstar.Malformed`,
    :class:`~vstar.UnsupportedVersion` or
    :class:`~vstar.UnclosedBlock`.
    """
    cards: list[Card] = []
    current = Card()
    version = ""
    is_open = False

    for index, line in enumerate(scan_all(data), start=1):
        if line == "":
            continue

        upper = line.upper()

        if upper == "BEGIN:VCARD":
            if is_open:
                raise Malformed("nested BEGIN:VCARD", line=index)
            is_open = True
            current = Card()
            version = ""
            continue

        if upper == "END:VCARD":
            if not is_open:
                raise Malformed("stray END:VCARD", line=index)
            if version == "":
                raise Malformed("VCARD missing VERSION", line=index)
            if version != SUPPORTED_VERSION:
                raise UnsupportedVersion(f"VERSION:{version}", line=index)
            cards.append(current)
            is_open = False
            current = Card()
            version = ""
            continue

        if not is_open:
            # Real vCards never carry content outside BEGIN/END.
            raise Malformed("content outside VCARD", line=index)

        prop = parse_content_line(line, index)
        name = prop.name.upper()

        if name == "VERSION":
            if version != "":
                raise Malformed("duplicate VERSION", line=index)
            version = prop.value
            continue
        if name == "UID":
            current.uid = prop.value
            continue
        if name == "KIND":
            # RFC 6350 §6.1.4 registry values are lowercase; the wire is
            # case-insensitive on read.
            current.kind = Kind(prop.value.lower())
            continue
        current.props.append(prop)

    if is_open:
        raise UnclosedBlock("BEGIN:VCARD never closed")
    return cards


def parse_content_line(line: str, at: int | None = None) -> Property:
    """Decompose one unfolded vCard content line per RFC 6350 §3.3 / §3.4.

    The grammar::

        [group "."] name *(";" param) ":" value

    A group prefix, when present, is preserved verbatim on the property
    name (e.g. ``home.TEL``). TEXT escaping is reversed on the value.
    """
    if line == "":
        raise Malformed("empty line", line=at)

    colon = find_first_unquoted(line, ":")
    if colon is None:
        raise Malformed("unterminated quoted value", line=at)
    if colon < 0:
        raise Malformed("missing value separator", line=at)

    head = line[:colon]
    raw_value = line[colon + 1 :]

    name_end = find_first_unquoted(head, ";")
    if name_end is None:
        raise Malformed("unterminated quoted value", line=at)

    name = head if name_end < 0 else head[:name_end]
    param_tok = "" if name_end < 0 else head[name_end + 1 :]

    if name == "":
        raise Malformed("empty property name", line=at)

    return Property(
        name=name,
        params=_parse_params(param_tok, at),
        value=unescape_text(raw_value, "keep-both"),
    )


def _parse_params(s: str, at: int | None) -> list[Param]:
    """Parse the parameter portion of a content-line head.

    Each parameter is ``NAME=VALUE``; ``VALUE`` may be DQUOTE-wrapped to
    embed ``,`` ``:`` or ``;``.
    """
    if s == "":
        return []
    params: list[Param] = []
    rest = s
    while rest:
        end = find_first_unquoted(rest, ";")
        if end is None:
            raise Malformed("unterminated quoted value", line=at)
        tok = rest if end < 0 else rest[:end]
        rest = "" if end < 0 else rest[end + 1 :]

        eq = find_first_unquoted(tok, "=")
        if eq is None:
            raise Malformed("unterminated quoted value", line=at)
        if eq < 0:
            raise Malformed(f"param {tok!r} missing '='", line=at)
        name = tok[:eq]
        if name == "":
            raise Malformed("empty param name", line=at)
        params.append(Param(name, unquote_param_value(tok[eq + 1 :])))
    return params
