# SPDX-License-Identifier: MIT

"""spec/03 §RRULE parsing scope — RRULE conformance."""

from __future__ import annotations

from typing import Final

from .._generated.codes import R_RULE_MALFORMED, R_RULE_UNSUPPORTED
from ..errors import UnsupportedRrule
from ..rrule import validate_rrule
from ..types import Component
from ._internal import Diagnostic, diagnostic, equal_fold

__all__ = ["check_rrule"]

#: RFC 5545 §3.8.5.3.
_RRULE: Final[str] = "RRULE"


def check_rrule(c: Component, path: str) -> list[Diagnostic]:
    """One diagnostic per RRULE property whose value fails validation.

    The split is by failure class, not by guesswork: an unsupported
    feature is a warning because the property still round-trips through
    the codec — only its recurrence semantics are out of reach — while a
    malformed value is an error because no consumer, V* or otherwise,
    can evaluate it.

    A failure that classifies as neither is reported as malformed rather
    than swallowed: a finding the consumer can see beats silence.
    """
    out: list[Diagnostic] = []
    for p in c.props:
        if not equal_fold(p.name, _RRULE):
            continue
        err = _validation_error(p.value)
        if err is None:
            continue
        if isinstance(err, UnsupportedRrule):
            out.append(
                diagnostic(
                    R_RULE_UNSUPPORTED,
                    "RRULE uses a feature outside the RRULE parsing scope "
                    f"(spec/03 §RRULE parsing scope): {err}",
                    f"{path}.{_RRULE}",
                )
            )
            continue
        out.append(
            diagnostic(
                R_RULE_MALFORMED,
                f"RRULE is malformed (RFC 5545 §3.3.10): {err}",
                f"{path}.{_RRULE}",
            )
        )
    return out


def _validation_error(value: str) -> Exception | None:
    """The failure :func:`vstar.rrule.validate_rrule` raises, or ``None``."""
    try:
        validate_rrule(value)
    except Exception as e:
        return e
    return None
