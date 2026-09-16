# SPDX-License-Identifier: MIT

"""The four expansion entry points, plus the shared walk behind them.

``next_occurrence``, ``all``, ``occurrences`` and ``between``. Spec
§Expansion names three bounding strategies and this module offers all
three: a count (:func:`occurrences`), a window (:func:`between`), and
laziness (:func:`all`, which the consumer stops). An unbounded request
through either of the bounded two is
:class:`~vstar.UnboundedExpansion`, not an empty result.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import datetime

from ..errors import IterationCap, UnboundedExpansion, UnsupportedRrule
from ._evaluate import MAX_ITERATIONS, advance, period_occurrences
from ._rule import Rule
from ._types import Freq

__all__ = ["all", "between", "next_occurrence", "occurrences"]


def check_expandable(rule: Rule) -> None:
    """Reject a rule the evaluator cannot walk.

    :func:`~vstar.rrule.parse_rrule` guarantees both conditions, so this
    fires only for a rule assembled by hand — which is exactly why it
    reports :class:`~vstar.UnsupportedRrule` rather than trusting the
    value.
    """
    if rule.freq is Freq.INVALID:
        raise UnsupportedRrule("rrule: FREQ is required")
    if rule.interval < 1:
        raise UnsupportedRrule(f"rrule: INTERVAL must be >= 1, got {rule.interval}")


def iteration_cap(op: str, rule: Rule) -> IterationCap:
    """The :class:`~vstar.IterationCap` failure, naming the bound that was hit."""
    return IterationCap(
        f"rrule: {op}: no occurrence within {MAX_ITERATIONS} "
        f"consecutive {rule.freq} periods"
    )


@dataclass(frozen=True, slots=True)
class WalkResult:
    """How a :func:`walk` ended."""

    #: ``True`` when :data:`~vstar.rrule.MAX_ITERATIONS` consecutive
    #: periods produced nothing and the search was abandoned. This is
    #: NOT termination — the rule may well have occurrences beyond the
    #: budget.
    capped: bool


def walk(
    rule: Rule, dtstart: datetime, on_occurrence: Callable[[datetime], bool]
) -> WalkResult:
    """Feed every occurrence of ``rule`` from ``dtstart`` to ``on_occurrence``.

    Chronological, stopping when the callback returns ``False``.

    The iteration bound is a starvation guard: the empty-period counter
    resets whenever a period yields, so a regularly-firing rule runs as
    long as the caller wants while one whose BY-* clauses can never
    match still stops.

    Two things end the walk without either the rule terminating or the
    callback asking it to stop, and both are cap hits: exhausting the
    bound, and stepping past the end of the representable calendar
    (:class:`~datetime.datetime` stops at year 9999, well inside the
    bound for a yearly rule). Both mean the evaluator gave up while
    empty periods remained, which spec §Expansion requires be reported
    as :class:`~vstar.IterationCap` rather than as an empty or completed
    result. The distinction is not academic:
    ``FREQ=YEARLY;BYMONTH=2;BYMONTHDAY=30`` runs out of calendar long
    before it runs out of budget.

    An unwalkable rule yields nothing and is not a cap hit; callers
    needing that reported run :func:`check_expandable` first.
    """
    try:
        check_expandable(rule)
    except UnsupportedRrule:
        return WalkResult(capped=False)

    emitted = 0
    empty = 0
    current: datetime | None = dtstart

    while empty < MAX_ITERATIONS:
        if current is None:
            # The calendar ran out with empty periods still pending.
            return WalkResult(capped=empty > 0)
        produced = False
        for occ in period_occurrences(rule, current, dtstart):
            # A period can reach back before dtstart — a weekly expansion
            # covers the whole week dtstart falls in — and the series
            # starts at dtstart, never earlier.
            if occ < dtstart:
                continue
            # UNTIL is inclusive per RFC 5545 §3.3.10.
            if rule.until is not None and occ > rule.until:
                return WalkResult(capped=False)
            produced = True
            emitted += 1
            if not on_occurrence(occ):
                return WalkResult(capped=False)
            if rule.count > 0 and emitted >= rule.count:
                return WalkResult(capped=False)
        empty = 0 if produced else empty + 1
        current = advance(rule, current)

    # The budget ran out with periods still to walk.
    return WalkResult(capped=True)


def next_occurrence(rule: Rule, dtstart: datetime, after: datetime) -> datetime | None:
    """The next occurrence strictly after ``after``, or ``None`` when ended.

    Termination — UNTIL passed, COUNT exhausted, no further period — is
    ``None`` and is normal completion. Reaching the iteration bound is
    :class:`~vstar.IterationCap` and is not: the rule has not
    necessarily ended, the evaluator stopped looking. A caller treating
    the two alike silently drops occurrences, which is why they are
    different answers.

    The first occurrence of a rule is ``dtstart`` itself whenever it
    satisfies the BY-* filters, per RFC 5545 — pass ``after = dtstart``
    to step past it.

    Raises :class:`~vstar.UnsupportedRrule` for a rule outside the
    parsing scope.
    """
    check_expandable(rule)

    found: datetime | None = None

    def collect(occ: datetime) -> bool:
        nonlocal found
        if occ > after:
            found = occ
            return False
        return True

    result = walk(rule, dtstart, collect)
    if found is not None:
        return found
    if result.capped:
        raise iteration_cap("next_occurrence", rule)
    return None


def all(rule: Rule, dtstart: datetime) -> Iterator[datetime]:  # noqa: A001
    """Every occurrence of ``rule`` from ``dtstart``, lazily.

    A rule with neither UNTIL nor COUNT is infinite, and iterating this
    without breaking will not return — that is the documented behaviour
    of a lazy sequence and the reason it exists. Use
    :func:`occurrences` or :func:`between` when a bounded result is what
    you want.

    The sequence also ends at the iteration bound. A generator has
    nowhere to put an error, so ``all`` cannot tell that apart from
    termination; the bounded entry points report it as
    :class:`~vstar.IterationCap`.

    The name shadows the builtin :func:`all` inside this module only —
    the API mapping fixes it, mirroring Go's ``rrule.All``, and callers
    reach it as ``rrule.all`` where the package qualifier disambiguates.
    """
    try:
        check_expandable(rule)
    except UnsupportedRrule:
        return

    emitted = 0
    empty = 0
    current: datetime | None = dtstart

    while empty < MAX_ITERATIONS and current is not None:
        produced = False
        for occ in period_occurrences(rule, current, dtstart):
            if occ < dtstart:
                continue
            if rule.until is not None and occ > rule.until:
                return
            produced = True
            emitted += 1
            yield occ
            if rule.count > 0 and emitted >= rule.count:
                return
        empty = 0 if produced else empty + 1
        current = advance(rule, current)


def occurrences(
    rule: Rule, dtstart: datetime, limit: int
) -> tuple[list[datetime], bool]:
    """Up to ``limit`` occurrences, with the flag saying how it stopped.

    ``complete`` is ``True`` when the rule itself terminated within the
    limit — the returned list is the entire series — and ``False`` when
    the limit truncated it. Reporting that distinction is required by
    spec §Expansion: a caller that stops after N steps otherwise never
    learns whether N was the whole series or merely the first N.

    A limit of ``0`` returns no occurrences and ``complete=False`` — no
    occurrences, and no claim that the series ended. A negative limit is
    :class:`~vstar.UnboundedExpansion`.
    """
    if limit < 0:
        raise UnboundedExpansion(f"rrule: occurrences: limit must be >= 0, got {limit}")
    check_expandable(rule)
    if limit == 0:
        return [], False

    out: list[datetime] = []
    truncated = False

    def collect(occ: datetime) -> bool:
        nonlocal truncated
        if len(out) == limit:
            # The walk produced one more than asked for, so the series
            # definitively continues past the limit.
            truncated = True
            return False
        out.append(occ)
        return True

    result = walk(rule, dtstart, collect)
    if result.capped:
        raise iteration_cap("occurrences", rule)
    return out, not truncated


def between(
    rule: Rule, dtstart: datetime, start: datetime, end: datetime | None
) -> list[datetime]:
    """Every occurrence in the half-open window ``[start, end)``.

    ``start`` inclusive, ``end`` exclusive.

    The window bounds the result, so this terminates even for a rule
    with neither UNTIL nor COUNT. It does not bound the *search*: a rule
    that never yields never reaches ``end``, so the iteration bound
    stops it and the failure is :class:`~vstar.IterationCap`.

    A missing ``end``, or an ``end`` not strictly after ``start``, is
    :class:`~vstar.UnboundedExpansion` rather than a silent empty result
    — an unbounded window is an infinite expansion request.
    """
    bound = check_window("between", start, end)
    check_expandable(rule)

    out: list[datetime] = []

    def collect(occ: datetime) -> bool:
        if occ >= bound:
            return False
        if occ >= start:
            out.append(occ)
        return True

    result = walk(rule, dtstart, collect)
    if result.capped:
        raise iteration_cap("between", rule)
    return out


def check_window(op: str, start: datetime, end: datetime | None) -> datetime:
    """Refuse an unbounded window; return the validated exclusive bound.

    Shared by the rule-level and set-level window forms so the two
    cannot drift. Returning the bound rather than only validating it
    gives the caller a non-optional value to compare against.
    """
    if end is None:
        raise UnboundedExpansion(
            f"rrule: {op}: end must be present "
            f"(an open-ended window is an infinite expansion; use all)"
        )
    if end <= start:
        raise UnboundedExpansion(f"rrule: {op}: end {end} must be after start {start}")
    return end
