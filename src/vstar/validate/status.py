# SPDX-License-Identifier: MIT

"""spec/05 §8 — the STATUS value domain."""

from __future__ import annotations

from typing import Final

from .._generated.codes import STATUS_NOT_IN_VOCABULARY
from ..types import (
    COMP_EVENT,
    COMP_JOURNAL,
    COMP_TODO,
    EVENT_CANCELLED,
    EVENT_CONFIRMED,
    EVENT_TENTATIVE,
    JOURNAL_CANCELLED,
    JOURNAL_DRAFT,
    JOURNAL_FINAL,
    TODO_CANCELLED,
    TODO_COMPLETED,
    TODO_IN_PROCESS,
    TODO_NEEDS_ACTION,
    Component,
)
from ._internal import Diagnostic, diagnostic, equal_fold, wire_type

__all__ = ["check_status_vocabulary"]

#: The STATUS values RFC 5545 §3.8.1.11 scopes to each component type.
#:
#: The vocabularies are per-type, not global: ``CANCELLED`` is the only
#: value all three share, and ``DRAFT`` — legal iCalendar text, and
#: legal on a VJOURNAL — is a conformance violation on a VEVENT. A type
#: absent from this table admits no STATUS vocabulary at all
#: (VFREEBUSY, VTIMEZONE, VALARM, VCALENDAR) and is skipped.
#:
#: Built from the port's own wire constants rather than read out of the
#: generated ``STATUS_VOCABULARY``, deliberately. These are the values
#: the codec encodes against, so a table built from them cannot
#: disagree with what this library actually writes — a guarantee a
#: lookup into a generated table would give up. The registry's
#: cross-language copy is reconciled against this one in
#: ``tests/test_registry_vocabulary.py``, which is what keeps the five
#: ports agreeing without any of them losing the codec linkage.
_STATUS_VOCABULARIES: Final[dict[str, tuple[str, ...]]] = {
    str(COMP_EVENT): (
        str(EVENT_TENTATIVE),
        str(EVENT_CONFIRMED),
        str(EVENT_CANCELLED),
    ),
    str(COMP_TODO): (
        str(TODO_NEEDS_ACTION),
        str(TODO_IN_PROCESS),
        str(TODO_COMPLETED),
        str(TODO_CANCELLED),
    ),
    str(COMP_JOURNAL): (
        str(JOURNAL_DRAFT),
        str(JOURNAL_FINAL),
        str(JOURNAL_CANCELLED),
    ),
}


def check_status_vocabulary(c: Component, path: str) -> list[Diagnostic]:
    """Flag a STATUS outside its own component type's vocabulary.

    Comparison is case-insensitive per RFC 5545 §3.1. An absent STATUS
    is clean — the property is optional on every type that admits it.
    """
    allowed = _STATUS_VOCABULARIES.get(wire_type(c))
    if allowed is None:
        return []
    p = c.get("STATUS")
    if p is None:
        return []
    if any(equal_fold(p.value, want) for want in allowed):
        return []
    return [
        diagnostic(
            STATUS_NOT_IN_VOCABULARY,
            f"STATUS value {p.value} is not valid for {wire_type(c)}; "
            f"allowed: {', '.join(allowed)} (RFC 5545 §3.8.1.11)",
            f"{path}.STATUS",
        )
    ]
