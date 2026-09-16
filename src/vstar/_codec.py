# SPDX-License-Identifier: MIT

"""The codec protocols every wire format satisfies.

Go's encode functions write to an ``io.Writer`` and return an error.
Python has no idiomatic writer in the same position, so the byte-
returning form is the contract, and it is the one the conformance gates
exercise. A port MAY additionally offer a writer-taking overload.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ._contentline import Input
from .types import Calendar

__all__ = ["Codec", "Encoder", "Parser"]


@runtime_checkable
class Parser(Protocol):
    """Reads a single :class:`~vstar.Calendar` from a document.

    Implementations are stateless and safe to share. A failure raises a
    :class:`~vstar.VstarError` carrying one of the sentinel identifiers
    — dispatch on its ``sentinel``.
    """

    def parse(self, data: Input) -> Calendar:
        """Parse one calendar from ``data``."""
        ...


@runtime_checkable
class Encoder(Protocol):
    """Writes a :class:`~vstar.Calendar` in the codec's wire format."""

    def encode(self, cal: Calendar) -> bytes:
        """Render ``cal`` as wire-format bytes."""
        ...


@runtime_checkable
class Codec(Parser, Encoder, Protocol):
    """:class:`Parser` and :class:`Encoder` composed."""
