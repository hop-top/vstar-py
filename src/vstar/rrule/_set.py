# SPDX-License-Identifier: MIT

"""Recurrence sets (RFC 5545 §3.8.5) and RECURRENCE-ID (§3.8.4.4).

The evaluation order in spec §Recurrence sets is load-bearing: DTSTART
first, the RRULE expands from it, RDATE merges in, and EXDATE removes
LAST — so an instant named by both an RDATE and an EXDATE stays
excluded. Applying EXDATE before RDATE would resurrect it, which is why
``set/exdate_after_rdate`` exists.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import NoReturn

from ..errors import Malformed, UnboundedExpansion, UnsupportedRrule
from ..time import format_time, parse_time
from ..types import Component, Param, Property
from ._expand import check_expandable, check_window, iteration_cap, walk
from ._parse import parse_rrule
from ._rule import Rule
from ._types import RecurrenceRange

__all__ = [
    "RecurrenceId",
    "RuleSet",
    "format_date_time_list",
    "parse_date_time_list",
    "parse_recurrence_id",
    "rule_set_from_component",
]


def _malformed(message: str) -> NoReturn:
    """Raise :class:`~vstar.Malformed` with the given explanation."""
    raise Malformed(f"rrule: {message}")


def _unsupported(message: str) -> NoReturn:
    """Raise :class:`~vstar.UnsupportedRrule` with the given explanation."""
    raise UnsupportedRrule(f"rrule: {message}")


def _sort_dedupe(times: list[datetime]) -> list[datetime]:
    """Sort ascending and drop duplicate instants, returning a new list.

    Comparison is by instant, not by wall-clock fields, so a UTC value
    correctly collapses with a zoned one naming the same moment.
    """
    out: list[datetime] = []
    for t in sorted(times):
        if not out or out[-1] != t:
            out.append(t)
    return out


@dataclass(slots=True)
class RuleSet:
    """A complete recurrence definition for one component.

    The DTSTART anchor, an optional RRULE, and the explicit RDATE
    additions and EXDATE removals RFC 5545 §3.8.5 layers on top.

    A set with RDATE and no RRULE is legal and finite. A set with
    neither is a single non-recurring occurrence at DTSTART.
    """

    #: The component's DTSTART: the anchor, and occurrence #1.
    dtstart: datetime
    #: The recurrence rule, or ``None`` for an RDATE-only set.
    rrule: Rule | None = None
    #: Explicit additional occurrences, sorted and de-duplicated.
    rdate: list[datetime] = field(default_factory=list)
    #: Explicit exclusions; one matching nothing is silently ignored.
    exdate: list[datetime] = field(default_factory=list)

    def __post_init__(self) -> None:
        """Normalize the explicit lists so order of authorship is irrelevant."""
        self.rdate = _sort_dedupe(self.rdate)
        self.exdate = _sort_dedupe(self.exdate)

    def _explicit(self) -> list[datetime]:
        """DTSTART plus every RDATE, sorted and de-duplicated.

        The occurrences that exist independently of any rule.
        """
        return _sort_dedupe([self.dtstart, *self.rdate])

    def occurrences(self, limit: int) -> tuple[list[datetime], bool]:
        """Up to ``limit`` occurrences of the set.

        Same ``complete`` contract as the module-level
        :func:`~vstar.rrule.occurrences`.

        EXDATE removals do not consume limit slots: the limit bounds
        *returned* occurrences, so a set whose first hundred rule
        occurrences are all excluded still yields the hundred-and-first.
        """
        if limit < 0:
            raise UnboundedExpansion(
                f"rrule: RuleSet.occurrences: limit must be >= 0, got {limit}"
            )
        if self.rrule is not None:
            check_expandable(self.rrule)
        if limit == 0:
            return [], False

        explicit = self._explicit()
        out: list[datetime] = []
        # The merge cursor into `explicit` and the truncation flag both
        # outlive the callback below, so they live here.
        index = 0
        truncated = False

        # EXDATE is consulted here, at emit — after the rule stream and
        # the explicit stream have been merged. That is what makes the
        # removal last, and an RDATE cannot undo it.
        def emit(t: datetime) -> bool:
            if t in self.exdate:
                return True
            if len(out) == limit:
                return False
            out.append(t)
            return True

        if self.rrule is not None:

            def collect(occ: datetime) -> bool:
                nonlocal index, truncated
                # Drain every explicit occurrence sorting before this
                # one, so the merged stream stays chronological.
                while index < len(explicit) and explicit[index] < occ:
                    if not emit(explicit[index]):
                        truncated = True
                        return False
                    index += 1
                # The same instant from both streams is one occurrence.
                if index < len(explicit) and explicit[index] == occ:
                    index += 1
                if not emit(occ):
                    truncated = True
                    return False
                return True

            result = walk(self.rrule, self.dtstart, collect)
            if result.capped:
                raise iteration_cap("RuleSet.occurrences", self.rrule)
            if truncated:
                return out, False

        while index < len(explicit):
            if not emit(explicit[index]):
                return out, False
            index += 1
        return out, True

    def between(self, start: datetime, end: datetime | None) -> list[datetime]:
        """Every occurrence of the set in the half-open window ``[start, end)``.

        RDATE merged and EXDATE removed last, then sorted and
        de-duplicated.
        """
        bound = check_window("RuleSet.between", start, end)

        merged: list[datetime] = []
        if self.rrule is not None:
            check_expandable(self.rrule)

            def collect(occ: datetime) -> bool:
                if occ >= bound:
                    return False
                merged.append(occ)
                return True

            result = walk(self.rrule, self.dtstart, collect)
            if result.capped:
                raise iteration_cap("RuleSet.between", self.rrule)
        merged.extend(self._explicit())

        windowed = [t for t in merged if start <= t < bound and t not in self.exdate]
        return _sort_dedupe(windowed)


def rule_set_from_component(c: Component) -> RuleSet:
    """Build a :class:`RuleSet` from a component's recurrence properties.

    DTSTART, RRULE, RDATE and EXDATE. EXDATE and RDATE may each appear
    several times and may each carry several comma-separated values;
    every value accumulates.

    v0.1 recurrence sets are UTC form #2 only, so a ``VALUE=DATE`` or
    ``TZID`` EXDATE/RDATE is :class:`~vstar.UnsupportedRrule`. Failing
    closed is deliberate: silently dropping an unparseable EXDATE would
    surface an occurrence the producer explicitly cancelled.
    """
    dtstart: datetime | None = None
    rrule: Rule | None = None
    rdate: list[datetime] = []
    exdate: list[datetime] = []

    start = c.get("DTSTART")
    if start is not None:
        t = parse_time(start.value)
        if t is None:
            _malformed(f"DTSTART {start.value!r} is not RFC 5545 form #2")
        dtstart = t

    for p in c.props:
        match p.name.upper():
            case "RRULE":
                rrule = parse_rrule(p.value)
            case "RDATE":
                rdate.extend(_parse_date_list_property(p))
            case "EXDATE":
                exdate.extend(_parse_date_list_property(p))
            case _:
                pass

    if dtstart is None:
        _malformed("recurrence set requires a DTSTART")
    return RuleSet(dtstart=dtstart, rrule=rrule, rdate=rdate, exdate=exdate)


def _parse_date_list_property(p: Property) -> list[datetime]:
    """Validate an EXDATE/RDATE property's parameters, then parse its list."""
    name = p.name.upper()
    for param in p.params:
        match param.name.upper():
            case "VALUE":
                if param.value.upper() != "DATE-TIME":
                    # A date-only value would need a time-of-day guessed.
                    _unsupported(
                        f"{name} VALUE={param.value} is outside the supported "
                        f"value types (DATE-TIME only)"
                    )
            case "TZID":
                # EXDATE and RDATE are not on the datetime-resolution
                # allow-list, so a zoned value arrives here unresolved
                # and would need the calendar's VTIMEZONE registry —
                # which a component-scoped constructor cannot reach.
                _unsupported(
                    f"{name} TZID={param.value} requires VTIMEZONE resolution "
                    f"unavailable at component scope"
                )
            case _:
                pass
    return parse_date_time_list(p.value)


def parse_date_time_list(s: str) -> list[datetime]:
    """Parse a comma-separated list of RFC 5545 form #2 (UTC) datetimes.

    The value form of a DATE-TIME-valued EXDATE or RDATE. The result is
    sorted and de-duplicated, so callers get a canonical set whatever
    order the producer wrote.
    """
    if s == "":
        _malformed("empty date-time list")
    out: list[datetime] = []
    for raw in s.split(","):
        t = parse_time(raw)
        if t is None:
            _malformed(f"{raw!r} is not an RFC 5545 form #2 date-time")
        out.append(t)
    return _sort_dedupe(out)


def format_date_time_list(times: list[datetime]) -> str:
    """Render instants as an EXDATE/RDATE property value.

    Comma-separated UTC form #2, sorted and de-duplicated so identical
    logical content yields identical bytes. An empty input renders as
    the empty string.
    """
    return ",".join(format_time(t) for t in _sort_dedupe(times))


@dataclass(frozen=True, slots=True)
class RecurrenceId:
    """The typed form of a RECURRENCE-ID property.

    The instant identifying which instance of a series a component
    overrides, plus RANGE.

    This is parsing and typed access only. Applying overrides — taking a
    base component plus its RECURRENCE-ID siblings and producing the
    effective series — needs component-level semantics that sit above
    this layer and are outside v0.1 scope.
    """

    #: The identified instance's original start instant — what the base
    #: series expands to for it, not the overriding component's own
    #: (possibly moved) DTSTART.
    time: datetime
    #: The RANGE parameter; the default when absent.
    range: RecurrenceRange = RecurrenceRange.THIS_INSTANCE

    def to_property(self) -> Property:
        """Render back to wire form.

        RANGE is emitted only for ``THISANDFUTURE`` — the default is
        expressed by omitting it, so emitting a token for it would
        change the bytes.
        """
        params: list[Param] = []
        if self.range is not RecurrenceRange.THIS_INSTANCE:
            params.append(Param("RANGE", str(self.range)))
        return Property(
            name="RECURRENCE-ID", params=params, value=format_time(self.time)
        )


def parse_recurrence_id(p: Property) -> RecurrenceId:
    """Extract a :class:`RecurrenceId` from a RECURRENCE-ID property.

    :class:`~vstar.Malformed` for a property that is not RECURRENCE-ID,
    a value outside form #2, or a RANGE other than ``THISANDFUTURE`` —
    RFC 5545 §3.2.13 defines exactly the one token.
    :class:`~vstar.UnsupportedRrule` for ``VALUE=DATE`` or ``TZID``, for
    the same reasons as EXDATE and RDATE.
    """
    if p.name.upper() != "RECURRENCE-ID":
        _malformed(f"property {p.name!r} is not RECURRENCE-ID")

    rng = RecurrenceRange.THIS_INSTANCE
    for param in p.params:
        match param.name.upper():
            case "RANGE":
                if param.value.upper() != "THISANDFUTURE":
                    _malformed(
                        f"RECURRENCE-ID RANGE={param.value!r} invalid "
                        f"(RFC 5545 §3.2.13 defines THISANDFUTURE only)"
                    )
                rng = RecurrenceRange.THIS_AND_FUTURE
            case "VALUE":
                if param.value.upper() != "DATE-TIME":
                    _unsupported(
                        f"RECURRENCE-ID VALUE={param.value} is outside the "
                        f"supported value types (DATE-TIME only)"
                    )
            case "TZID":
                _unsupported(
                    f"RECURRENCE-ID TZID={param.value} requires VTIMEZONE "
                    f"resolution unavailable at property scope"
                )
            case _:
                pass

    t = parse_time(p.value)
    if t is None:
        _malformed(f"RECURRENCE-ID {p.value!r} is not an RFC 5545 form #2 date-time")
    return RecurrenceId(time=t, range=rng)
