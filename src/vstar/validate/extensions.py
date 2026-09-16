# SPDX-License-Identifier: MIT

"""spec/05 §3, spec/04 — extension namespace compliance."""

from __future__ import annotations

from typing import Final

from .._generated.codes import STANDARD_PROPERTIES, UNKNOWN_PROPERTY
from ..ext import is_extension
from ..types import Component
from ._internal import Diagnostic, diagnostic

__all__ = ["check_extension_namespace", "standard_property_count"]

#: The RFC 5545 §3.7-§3.8 / RFC 6350 §6 allow-list, uppercased for
#: case-insensitive lookup. The list itself is generated from
#: ``spec/registry/standard-properties.json`` — this is only the index.
_STANDARD: Final[frozenset[str]] = frozenset(
    name.upper() for name in STANDARD_PROPERTIES
)


def check_extension_namespace(c: Component, path: str) -> list[Diagnostic]:
    """One warning per property neither on the allow-list nor ``X-``-prefixed.

    The ``X-`` classification is delegated to
    :func:`vstar.ext.is_extension` so there is one answer to "what
    counts as an extension"; the allow-list stays here because it
    answers the orthogonal question "is this a known RFC property?",
    which :mod:`vstar.ext` has no business knowing.
    """
    out: list[Diagnostic] = []
    for p in c.props:
        if p.name.upper() in _STANDARD:
            continue
        if is_extension(p.name):
            continue
        out.append(
            diagnostic(
                UNKNOWN_PROPERTY,
                f"property {p.name} is not a known RFC 5545/6350 property and "
                "does not use the X- extension prefix (spec/05 §3, spec/04)",
                f"{path}.{p.name}",
            )
        )
    return out


def standard_property_count() -> int:
    """How many properties the generated RFC allow-list carries."""
    return len(STANDARD_PROPERTIES)
