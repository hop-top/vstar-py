# SPDX-License-Identifier: MIT

"""The typed vocabulary of an RFC 5545 §3.3.10 RRULE value.

The scope is the one ``spec/v0.1/03-canonicalization.md`` §RRULE
parsing scope fixes. Wire spellings are normative: a port that changes
one is broken.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum, StrEnum

__all__ = ["ByDay", "Freq", "RecurrenceRange", "Weekday"]


class Freq(StrEnum):
    """The RRULE ``FREQ`` value.

    ``INVALID`` is the unset marker: a :class:`~vstar.rrule.Rule` built
    without an explicit ``freq`` carries it, and a successful parse
    never produces it, because a missing ``FREQ`` is
    :class:`~vstar.Malformed`.

    ``SECONDLY`` is deliberately absent. It is a syntactically valid
    RFC value this scope defers, so it is rejected at parse with
    :class:`~vstar.UnsupportedRrule` rather than modelled — a member
    would invite an evaluator branch the spec says must not exist.
    """

    INVALID = ""
    MINUTELY = "MINUTELY"
    HOURLY = "HOURLY"
    DAILY = "DAILY"
    WEEKLY = "WEEKLY"
    MONTHLY = "MONTHLY"
    YEARLY = "YEARLY"

    def __str__(self) -> str:
        """The wire spelling, e.g. ``"DAILY"``."""
        return self.value


class Weekday(IntEnum):
    """An RFC 5545 §3.3.10 weekday symbol, numbered ``SU = 0``.

    That numbering is normative. It is **not** ISO-8601's ``MO = 1``
    and **not** Python's :meth:`datetime.date.weekday` ``MO = 0``;
    reusing a platform weekday number without converting is a one-off
    bug the ``rrule/by-clauses/byday`` fixtures catch.
    :meth:`to_weekday` is the explicit conversion to Python's numbering
    and is the only place that conversion should live.
    """

    SU = 0
    MO = 1
    TU = 2
    WE = 3
    TH = 4
    FR = 5
    SA = 6

    def __str__(self) -> str:
        """The two-letter wire spelling, e.g. ``"MO"``."""
        return self.name

    def to_weekday(self) -> int:
        """This weekday in Python's numbering, where ``MO = 0``.

        The counterpart to the RFC's own ``SU = 0``, exposed so callers
        needing the platform spelling convert at one named boundary.
        """
        return (int(self) - 1) % 7


#: The weekday symbols in RFC order, indexed by their RFC number.
WEEKDAYS: tuple[Weekday, ...] = tuple(Weekday)


@dataclass(frozen=True, slots=True)
class ByDay:
    """One entry in a ``BYDAY`` list: an optional ordinal plus a weekday.

    ``ordinal == 0`` means "every weekday of this kind in the containing
    FREQ period" — ``BYDAY=MO`` under ``FREQ=MONTHLY`` is every Monday
    of the month. A non-zero ordinal in -53..-1 or 1..53 picks the nth,
    counting from the start when positive and from the end when
    negative. The explicit ``0`` prefix is invalid per RFC 5545 §3.3.10
    and is rejected at parse: "every one" is spelled by omitting the
    ordinal, not by writing zero.
    """

    ordinal: int
    weekday: Weekday

    def __str__(self) -> str:
        """The wire spelling: ``MO``, ``2MO``, ``-1FR``."""
        return (
            str(self.weekday) if self.ordinal == 0 else f"{self.ordinal}{self.weekday}"
        )


class RecurrenceRange(StrEnum):
    """The ``RECURRENCE-ID`` ``RANGE`` parameter (RFC 5545 §3.2.13).

    The empty member is the default: the RFC expresses "this instance
    only" by omitting the parameter entirely, so the default has no wire
    token of its own and emitting one would change the bytes.
    """

    THIS_INSTANCE = ""
    THIS_AND_FUTURE = "THISANDFUTURE"

    def __str__(self) -> str:
        """The wire spelling; the empty string for the default."""
        return self.value
