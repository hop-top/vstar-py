# SPDX-License-Identifier: MIT

"""spec/05 §8 — the bounded integer value domains, and the shared decimal form."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

from .._generated.codes import INTEGER_OUT_OF_DOMAIN
from ..types import Component
from ._internal import Diagnostic, diagnostic, equal_fold

__all__ = ["check_integer_domains", "is_canonical_decimal"]

#: A canonical non-negative decimal per spec/05 §8, anchored: digits
#: only, no sign, no whitespace, and no leading zero unless the value is
#: exactly ``0``.
#:
#: Deliberately a pattern rather than :func:`int`, which accepts
#: surrounding whitespace, a leading ``+``, leading zeros and underscore
#: separators — none of which the wire form admits. The check is
#: textual on purpose: the value is never converted to decide
#: well-formedness, so a SEQUENCE past any machine range is well-formed.
#: The spec bounds SEQUENCE below, never above.
_CANONICAL_DECIMAL: Final[re.Pattern[str]] = re.compile(r"\A(0|[1-9][0-9]*)\Z")


def is_canonical_decimal(s: str) -> bool:
    """Whether ``s`` is a canonical non-negative decimal (spec/05 §8)."""
    return _CANONICAL_DECIMAL.match(s) is not None


@dataclass(frozen=True, slots=True)
class _IntegerDomain:
    """One bounded integer property.

    ``max`` is the upper bound as a digit string, ``None`` when the
    property is unbounded. The lower bound is always 0, which the
    canonical form already enforces — there is no sign to admit.
    """

    name: str
    section: str
    max: str | None


#: The table the integer-domain rule checks, in the order the codes
#: catalog lists the properties.
_INTEGER_DOMAINS: Final[tuple[_IntegerDomain, ...]] = (
    _IntegerDomain("PRIORITY", "§3.8.1.9", "9"),
    _IntegerDomain("PERCENT-COMPLETE", "§3.8.1.8", "100"),
    _IntegerDomain("SEQUENCE", "§3.8.7.4", None),
)


def _exceeds_digit_string(v: str, max_: str) -> bool:
    """Whether canonical decimal ``v`` is numerically greater than ``max_``.

    Both must already satisfy :func:`is_canonical_decimal`: with no
    leading zeros, a longer string is a larger number and equal lengths
    compare lexically. No conversion, so no range to fall out of.
    """
    if len(v) != len(max_):
        return len(v) > len(max_)
    return v > max_


def check_integer_domains(c: Component, path: str) -> list[Diagnostic]:
    """One diagnostic per bounded integer property outside its RFC 5545 domain.

    The form is decided first and textually; only a value the form has
    admitted is compared against its bound, and only where the RFC sets
    one (PRIORITY ≤ 9, PERCENT-COMPLETE ≤ 100; SEQUENCE is unbounded).
    The value is checked wherever the property appears; the rule does
    not gate on component type — PERCENT-COMPLETE on a VEVENT is
    bounded, not flagged for scope. One diagnostic per offending
    property, at the property's path, like the STATUS and DURATION rules.
    """
    out: list[Diagnostic] = []
    for p in c.props:
        dom = _domain_of(p.name)
        if dom is None:
            continue
        if not is_canonical_decimal(p.value):
            out.append(
                diagnostic(
                    INTEGER_OUT_OF_DOMAIN,
                    f"{dom.name} is not a canonical non-negative decimal "
                    f"(RFC 5545 {dom.section}, spec/05 §8): {p.value}",
                    f"{path}.{dom.name}",
                )
            )
        elif dom.max is not None and _exceeds_digit_string(p.value, dom.max):
            out.append(
                diagnostic(
                    INTEGER_OUT_OF_DOMAIN,
                    f"{dom.name} value {p.value} is outside 0-{dom.max} "
                    f"(RFC 5545 {dom.section})",
                    f"{path}.{dom.name}",
                )
            )
    return out


def _domain_of(name: str) -> _IntegerDomain | None:
    """The bounded domain for property ``name``, matched case-insensitively."""
    for dom in _INTEGER_DOMAINS:
        if equal_fold(name, dom.name):
            return dom
    return None
