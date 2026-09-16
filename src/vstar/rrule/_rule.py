# SPDX-License-Identifier: MIT

"""The :class:`Rule` value and the wire form spec §RRULE wire form fixes.

RFC 5545 §3.3.10 imposes no rule-part order — a producer may emit them
any way it likes and the value means the same thing. The spec fixes one
so identical logical content produces byte-identical output, and it is
the order the RFC's own ``recur`` ABNF lists: FREQ and its modifiers,
the termination bound, then the BY-* filters from coarsest to finest,
BYSETPOS last because it applies last, and WKST last of all because it
modifies the whole rule rather than filtering it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from ..time import format_time
from ..types import Property
from ._types import ByDay, Freq, Weekday

__all__ = ["Rule"]


@dataclass(frozen=True, slots=True)
class Rule:
    """A parsed RRULE.

    Absent list rule-parts are empty lists; an absent ``until`` is
    ``None`` and an absent ``count`` is ``0``. ``interval`` defaults to
    1 and ``week_start`` to ``MO``, both applied at parse.

    The value is frozen: a rule is a value, and mutating one after an
    evaluator has read it would make the ``complete`` flag and the
    iteration bound mean different things mid-expansion.

    Field order here is for reading; rule-part order on the wire is
    irrelevant on parse and fixed on emit — see :meth:`__str__`.
    """

    freq: Freq = Freq.INVALID
    interval: int = 1
    #: The ``UNTIL`` instant (form #2, UTC), or ``None`` when absent.
    until: datetime | None = None
    #: The ``COUNT`` value, or ``0`` when absent. Exclusive with ``until``.
    count: int = 0
    by_day: list[ByDay] = field(default_factory=list)
    by_month: list[int] = field(default_factory=list)
    by_month_day: list[int] = field(default_factory=list)
    by_hour: list[int] = field(default_factory=list)
    by_minute: list[int] = field(default_factory=list)
    by_second: list[int] = field(default_factory=list)
    by_year_day: list[int] = field(default_factory=list)
    by_week_no: list[int] = field(default_factory=list)
    by_set_pos: list[int] = field(default_factory=list)
    week_start: Weekday = Weekday.MO

    def __str__(self) -> str:
        """Render as an RRULE property value, with no ``RRULE:`` prefix.

        Three properties are contract, not implementation detail:

        - **Fixed rule-part order**, per spec §RRULE wire form.
        - **Defaults elided** — ``INTERVAL=1`` and ``WKST=MO`` are
          omitted, so two rules differing only in whether the producer
          spelled out a default render identically.
        - **List order preserved** — ``BYDAY=WE,MO`` stays
          ``BYDAY=WE,MO``. RFC 5545 gives BY-* lists no ordering
          semantics, so sorting them would rewrite the producer's
          content while looking tidier. Callers wanting order-insensitive
          equality compare parsed rules, not strings.

        Parsing the result and re-emitting it is idempotent.

        A rule with no ``FREQ`` renders as the empty string rather than
        a partial value that would fail to re-parse.
        """
        if self.freq is Freq.INVALID:
            return ""

        parts = [f"FREQ={self.freq}"]
        if self.interval > 1:
            parts.append(f"INTERVAL={self.interval}")
        # UNTIL and COUNT are mutually exclusive; emit whichever is set.
        if self.until is not None:
            parts.append(f"UNTIL={format_time(self.until)}")
        if self.count > 0:
            parts.append(f"COUNT={self.count}")

        for name, values in (
            ("BYMONTH", self.by_month),
            ("BYWEEKNO", self.by_week_no),
            ("BYYEARDAY", self.by_year_day),
            ("BYMONTHDAY", self.by_month_day),
            ("BYDAY", self.by_day),
            ("BYHOUR", self.by_hour),
            ("BYMINUTE", self.by_minute),
            ("BYSECOND", self.by_second),
            ("BYSETPOS", self.by_set_pos),
        ):
            if values:
                parts.append(f"{name}=" + ",".join(str(v) for v in values))

        if self.week_start is not Weekday.MO:
            parts.append(f"WKST={self.week_start}")
        return ";".join(parts)

    def to_property(self) -> Property:
        """Render as a complete :class:`~vstar.Property` ready to attach.

        A rule that cannot produce a valid value yields the empty
        property rather than a broken one.
        """
        value = str(self)
        if value == "":
            return Property(name="", params=[], value="")
        return Property(name="RRULE", params=[], value=value)
