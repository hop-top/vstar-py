# SPDX-License-Identifier: MIT

"""The RFC 5545 §3.3.4 DATE value type.

The component-level accessors that read and write it live on
:class:`vstar.Component`; this module holds the value type and the
free functions, so it depends on nothing else in the package.

DATE and DATE-TIME are semantically different, not two spellings of one
thing. ``DUE;VALUE=DATE:20260515`` means "due on the 15th, as reckoned
by whoever reads it"; ``DUE:20260515T000000Z`` means "due at one
specific instant, the stroke of midnight UTC". A task due on the 15th is
not late at 00:00:01Z; a task due at midnight UTC is.

A ``datetime`` cannot carry that distinction — every one has clock
fields and a ``tzinfo``, so a date-only value stored in one is
indistinguishable from a midnight instant, and forgetting the
out-of-band flag is silent data corruption rather than a type error.
:class:`VDate` has no clock fields at all, so the distinction is
structural.
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import UTC, datetime

__all__ = [
    "VALUE_DATE",
    "VALUE_PARAM",
    "VDate",
    "date_of",
    "format_date",
    "parse_date",
]

#: The exact wire width of an RFC 5545 §3.3.4 DATE.
_DATE_OCTETS = 8

_DATE_RE = re.compile(r"\A[0-9]{8}\Z")

#: The RFC 5545 §3.2.20 parameter name declaring a value type explicitly.
VALUE_PARAM = "VALUE"

#: The §3.2.20 ``VALUE`` argument selecting the DATE value type (§3.3.4).
#:
#: The parameter is REQUIRED on any date-only DTSTART/DTEND/DUE/
#: COMPLETED: the default value type for those properties is DATE-TIME,
#: so an untagged eight-octet value is a malformed DATE-TIME, not a DATE.
VALUE_DATE = "DATE"


@dataclass(frozen=True, slots=True)
class VDate:
    """A calendar date with no time and no time zone.

    Named ``VDate`` rather than ``Date`` because ``date`` is a built-in
    type name in Python. ``month`` is **1-based**.

    The zero ``VDate`` (all fields 0) is the "no date" sentinel: it
    formats as the empty string, and the date-typed setters treat it as
    "clear the property".
    """

    year: int
    month: int
    day: int

    def is_zero(self) -> bool:
        """Whether this is the zero ``VDate`` — the "no date" sentinel."""
        return self.year == 0 and self.month == 0 and self.day == 0

    def to_datetime(self) -> datetime:
        """This date as midnight UTC.

        Lossy by design and one-way: the result no longer records that
        its source was date-only. Do not round-trip a ``VDate`` through
        a ``datetime`` to store it — use the date-typed accessors, which
        preserve the DATE value type on the wire.
        """
        if self.is_zero():
            return datetime.min.replace(tzinfo=UTC)
        return datetime(self.year, self.month, self.day, tzinfo=UTC)

    def __str__(self) -> str:
        """The RFC 5545 §3.3.4 wire form, or ``""`` for the zero date."""
        return format_date(self)


def date_of(t: datetime) -> VDate:
    """The calendar date of ``t``, as observed in ``t``'s own zone.

    The conversion is deliberately zone-sensitive: 2026-05-15 20:00 in a
    UTC-05:00 zone is 2026-05-16 01:00 UTC, and this reports May 15 —
    the date a person standing in that zone would name. Callers wanting
    the UTC date should convert first.
    """
    return VDate(t.year, t.month, t.day)


def format_date(d: VDate) -> str:
    """Render ``d`` as ``YYYYMMDD``, zero-padded to eight octets.

    The zero date renders as the empty string, which is how the
    date-typed writers spell "clear the property".

    Out-of-range field values (month 13, day 32, a year outside
    0000-9999) render as the empty string rather than an impossible wire
    form: the DATE production is a fixed-width four-digit year, and
    emitting torn data would defeat the strictness the reader enforces.
    """
    if d.is_zero():
        return ""
    if not (0 <= d.year <= 9999 and 1 <= d.month <= 12 and 1 <= d.day <= 31):
        return ""
    return f"{d.year:04d}{d.month:02d}{d.day:02d}"


def parse_date(s: str) -> VDate | None:
    """Parse an RFC 5545 §3.3.4 DATE string. ``None`` for anything else.

    Strict by design. Rejected: DATE-TIME forms
    (``YYYYMMDDTHHMMSS``, ``YYYYMMDDTHHMMSSZ``), ISO 8601 extended
    layouts (``2026-05-15``), impossible calendar dates (Feb 30, month
    13, day 0, Feb 29 in a non-leap year) with no silent roll-over,
    leading or trailing whitespace, and any input that is not exactly
    eight ASCII digits.
    """
    if len(s) != _DATE_OCTETS or _DATE_RE.match(s) is None:
        return None
    year, month, day = int(s[0:4]), int(s[4:6]), int(s[6:8])
    if not 1 <= month <= 12:
        return None
    if not 1 <= day <= calendar.monthrange(year, month)[1]:
        return None
    return VDate(year, month, day)
