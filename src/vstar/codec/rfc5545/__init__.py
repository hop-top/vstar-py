# SPDX-License-Identifier: MIT

"""The iCalendar (VCALENDAR) wire format per RFC 5545.

A content-line scanner with §3.1 line unfolding, a content-line parser
(§3.2), a recursive BEGIN/END block parser (§3.4-§3.6), and an encoder
emitting CRLF-terminated, 75-octet-folded output.

The scanner is re-exported here because RFC 6350 inherits the same
line-folding mechanism; sister codecs consume it directly.
"""

from __future__ import annotations

from ..._codec import Codec
from ..._contentline import Input, Scanner, new_scanner
from ...types import Calendar
from ._encoder import encode, encode_component, encode_content_line
from ._parser import parse, parse_content_line
from ._text import SUPPORTED_VERSION

__all__ = [
    "DEFAULT",
    "SUPPORTED_VERSION",
    "Scanner",
    "encode",
    "encode_component",
    "encode_content_line",
    "new_codec",
    "new_scanner",
    "parse",
    "parse_content_line",
]


class _Rfc5545Codec:
    """A stateless :class:`~vstar.Codec` over the RFC 5545 functions."""

    __slots__ = ()

    def parse(self, data: Input) -> Calendar:
        """Parse one calendar from ``data``."""
        return parse(data)

    def encode(self, cal: Calendar) -> bytes:
        """Render ``cal`` as RFC 5545 wire-format bytes."""
        return encode(cal)


def new_codec() -> Codec:
    """A fresh :class:`~vstar.Codec` backed by this parser and encoder.

    The returned value is stateless — share it or reconstruct it freely.
    """
    return _Rfc5545Codec()


#: A shared, stateless codec for callers not needing their own.
DEFAULT: Codec = new_codec()
