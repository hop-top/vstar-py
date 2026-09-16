# SPDX-License-Identifier: MIT

"""spec/05 §8 — the CLASS and TRANSP value domains."""

from __future__ import annotations

from typing import Final

from .._generated.codes import CLASS_NOT_IN_VOCABULARY, TRANSP_NOT_IN_VOCABULARY
from ..types import Component, Transp, VClass
from ._internal import Diagnostic, diagnostic, equal_fold

__all__ = ["check_classification"]

_CLASS: Final[str] = "CLASS"
_TRANSP: Final[str] = "TRANSP"

#: The wire values RFC 5545 §3.8.1.3 and §3.8.2.7 allow.
#:
#: Built from the port's own wire enums rather than read out of the
#: generated ``CLASS_VOCABULARY`` / ``TRANSP_VOCABULARY``, for the reason
#: :mod:`.status` gives: these are the values the codec encodes against,
#: so a table built from them cannot disagree with what this library
#: actually writes. The registry's cross-language copy is reconciled
#: against the enums in ``tests/test_registry_vocabulary.py``.
_CLASS_VOCABULARY: Final[tuple[str, ...]] = tuple(str(v) for v in VClass)
_TRANSP_VOCABULARY: Final[tuple[str, ...]] = tuple(str(v) for v in Transp)


def check_classification(c: Component, path: str) -> list[Diagnostic]:
    """Flag a CLASS outside §3.8.1.3's vocabulary, a TRANSP outside §3.8.2.7's.

    Comparison is case-insensitive (spec/05 §8, RFC 5545 §3.1). The
    value is checked on any component carrying the property — there is
    no type gating, because V* diagnoses no scope rule for any property.
    An ``X-`` or IANA token on CLASS, which the RFC's ABNF admits, is
    still flagged: spec/05 §8 binds the value to the three registered
    names.
    """
    return [
        *_vocabulary_diagnostic(
            c, path, _CLASS, _CLASS_VOCABULARY, CLASS_NOT_IN_VOCABULARY, "§3.8.1.3"
        ),
        *_vocabulary_diagnostic(
            c, path, _TRANSP, _TRANSP_VOCABULARY, TRANSP_NOT_IN_VOCABULARY, "§3.8.2.7"
        ),
    ]


def _vocabulary_diagnostic(
    c: Component,
    path: str,
    name: str,
    allowed: tuple[str, ...],
    code: str,
    section: str,
) -> list[Diagnostic]:
    """The STATUS-shaped diagnostic for ``name`` when its value is outside ``allowed``.

    Empty when the property is absent or its value is allowed.
    """
    p = c.get(name)
    if p is None:
        return []
    if any(equal_fold(p.value, want) for want in allowed):
        return []
    return [
        diagnostic(
            code,
            f"{name} value {p.value} is not valid; allowed: {', '.join(allowed)} "
            f"(RFC 5545 {section})",
            f"{path}.{name}",
        )
    ]
