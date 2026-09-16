# SPDX-License-Identifier: MIT

"""spec/05 §5 — type-specific required properties."""

from __future__ import annotations

from collections.abc import Callable
from typing import Final

from .._generated.codes import (
    VCARD_MISSING_REQUIRED,
    VEVENT_MISSING_DTSTART,
    VFREEBUSY_MISSING_TIMES,
    VTODO_MISSING_DUE,
)
from ..types import COMP_EVENT, COMP_FREE_BUSY, COMP_TODO, TODO_COMPLETED, Component
from ._internal import Diagnostic, diagnostic, equal_fold, has, wire_type

__all__ = ["check_type_specific"]

#: The ``VCARD`` wire type, as it appears on a :class:`Component`.
#:
#: A top-level vCard is a :class:`~vstar.types.Card`, not a Component.
#: A ``VCARD`` block nested inside a ``VCALENDAR`` still parses into a
#: Component carrying the wire string, and the rule below exists so a
#: caller hand-building one still gets the check.
_VCARD: Final[str] = "VCARD"


def check_type_specific(c: Component, path: str) -> list[Diagnostic]:
    """Dispatch the per-type rule for ``c``.

    Component types with no extra MUST in spec/05 §5 — VJOURNAL,
    VTIMEZONE, VALARM, VCALENDAR — yield nothing.
    """
    rule = _RULES.get(wire_type(c))
    if rule is None:
        return []
    return rule(c, path)


def _check_vtodo(c: Component, path: str) -> list[Diagnostic]:
    """A VTODO must be reachable as "scheduled".

    Either DUE is present, or STATUS=COMPLETED is paired with a
    COMPLETED timestamp. RFC 5545 §3.6.2 lets a finished VTODO drop DUE
    so long as COMPLETED records when it finished; that route is
    honoured rather than demanding a due date the task no longer has.
    """
    if has(c, "DUE"):
        return []
    status = c.get("STATUS")
    if (
        status is not None
        and equal_fold(status.value, str(TODO_COMPLETED))
        and has(c, "COMPLETED")
    ):
        return []
    return [
        diagnostic(
            VTODO_MISSING_DUE,
            "VTODO requires DUE, or STATUS=COMPLETED paired with COMPLETED "
            "(spec/05 §5; RFC 5545 §3.6.2)",
            path,
        )
    ]


def _check_vevent(c: Component, path: str) -> list[Diagnostic]:
    """A VEVENT must carry DTSTART.

    RFC 5545 §3.6.1 allows its absence outside a PUBLISH METHOD
    context; V* is strict, because an agentic playthrough always
    anchors to a start time.
    """
    if has(c, "DTSTART"):
        return []
    return [
        diagnostic(
            VEVENT_MISSING_DTSTART,
            "VEVENT requires DTSTART (spec/05 §5; RFC 5545 §3.6.1)",
            f"{path}.DTSTART",
        )
    ]


def _check_vfreebusy(c: Component, path: str) -> list[Diagnostic]:
    """A VFREEBUSY must carry both DTSTART and DTEND."""
    missing = _required_missing(c, ("DTSTART", "DTEND"))
    if not missing:
        return []
    return [
        diagnostic(
            VFREEBUSY_MISSING_TIMES,
            "VFREEBUSY requires DTSTART and DTEND; missing: "
            f"{', '.join(missing)} (spec/05 §5; RFC 5545 §3.6.4)",
            path,
        )
    ]


def _check_vcard_component(c: Component, path: str) -> list[Diagnostic]:
    """A VCARD-as-Component must carry both VERSION and UID."""
    missing = _required_missing(c, ("VERSION", "UID"))
    if not missing:
        return []
    return [
        diagnostic(
            VCARD_MISSING_REQUIRED,
            "VCARD requires VERSION and UID; missing: "
            f"{', '.join(missing)} (spec/05 §5; RFC 6350 §6.7.6, §6.7.9)",
            path,
        )
    ]


def _required_missing(c: Component, names: tuple[str, ...]) -> list[str]:
    """Which of ``names`` ``c`` lacks, in the order given."""
    return [name for name in names if not has(c, name)]


#: Wire type to its spec/05 §5 rule. A type absent from this table
#: carries no extra MUST and is skipped.
_RULES: Final[dict[str, Callable[[Component, str], list[Diagnostic]]]] = {
    str(COMP_TODO): _check_vtodo,
    str(COMP_EVENT): _check_vevent,
    str(COMP_FREE_BUSY): _check_vfreebusy,
    _VCARD: _check_vcard_component,
}
