# SPDX-License-Identifier: MIT

"""The vCard 4.0 (RFC 6350) wire format.

Line unfolding (§3.2 -> RFC 5545 §3.1), content-line parsing including
group prefixes (§3.3), TEXT escaping (§3.4), ``BEGIN:VCARD...END:VCARD``
framing, and the symmetric encoder with 75-octet folding and CRLF
terminators. ``VERSION:4.0`` is the only version accepted.

The two halves are deliberately asymmetric: :func:`parse` returns a
**list** of cards, :func:`encode` takes exactly one.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..._contentline import Input
from ...types import Card
from ._encoder import encode, format_property
from ._parser import SUPPORTED_VERSION, parse, parse_content_line

__all__ = [
    "DEFAULT",
    "SUPPORTED_VERSION",
    "Codec",
    "Encoder",
    "Parser",
    "encode",
    "format_property",
    "new_codec",
    "new_encoder",
    "new_parser",
    "parse",
    "parse_content_line",
]


@runtime_checkable
class Parser(Protocol):
    """Reads zero or more vCards from a document.

    vCards have a different top-level shape from calendars, so this
    codec defines its own protocols rather than reusing the root ones:
    ``parse`` returns a **list**.
    """

    def parse(self, data: Input) -> list[Card]:
        """Parse every VCARD block in ``data``."""
        ...


@runtime_checkable
class Encoder(Protocol):
    """Writes a single vCard."""

    def encode(self, card: Card) -> bytes:
        """Render one card as wire-format bytes."""
        ...


@runtime_checkable
class Codec(Parser, Encoder, Protocol):
    """:class:`Parser` and :class:`Encoder` composed."""


class _Rfc6350Codec:
    """A stateless codec over the RFC 6350 functions."""

    __slots__ = ()

    def parse(self, data: Input) -> list[Card]:
        """Parse every VCARD block in ``data``."""
        return parse(data)

    def encode(self, card: Card) -> bytes:
        """Render one card as RFC 6350 wire-format bytes."""
        return encode(card)


def new_codec() -> Codec:
    """A fresh, stateless :class:`Codec`."""
    return _Rfc6350Codec()


def new_parser() -> Parser:
    """A fresh :class:`Parser`, for callers needing only the read side."""
    return _Rfc6350Codec()


def new_encoder() -> Encoder:
    """A fresh :class:`Encoder`, for callers needing only the write side."""
    return _Rfc6350Codec()


#: A shared, stateless codec.
DEFAULT: Codec = new_codec()
