# SPDX-License-Identifier: MIT

"""RFC 5545 §3.3.5 DATE-TIME: form #2 on the wire, form #1 via VTIMEZONE.

An instant is a timezone-aware :class:`~datetime.datetime` with
``tzinfo=timezone.utc``, at second resolution, rendered as form #2
(``YYYYMMDDTHHMMSSZ``). A naive ``datetime`` is refused at every
boundary: Python raises only on a naive/aware *comparison*, so a naive
value travels a long way before it fails, and by then the failure names
the comparison rather than the boundary that let it in.

Absence is ``None``, never an in-band sentinel. A port that made the
epoch mean "no instant" would make 1970-01-01T00:00:00Z — a perfectly
ordinary timestamp — unrepresentable.

**There is no IANA timezone database here, and there must never be one.**
No :mod:`zoneinfo`, no ``pytz``, no ``dateutil``. A local time resolves
only against the VTIMEZONE definitions inside the calendar being
processed, using :class:`~datetime.timezone` with fixed offsets. That is
what makes a self-contained document hash identically on every machine,
in every year, whatever tzdata release is installed — and reaching for
the system database is exactly how two conformant implementations come
to disagree on canonical bytes.
"""

from __future__ import annotations

import re
from calendar import monthrange
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, timezone

from .types import Calendar, Component, CompType

__all__ = ["format_time", "parse_time", "parse_time_with_tzid"]

#: Form #2 is exactly 16 octets: 8 date + ``T`` + 6 time + ``Z``.
_FORM_TWO_OCTETS = 16

#: Form #1 is exactly 15 octets: 8 date + ``T`` + 6 time, no ``Z``.
_FORM_ONE_OCTETS = 15

_FORM_ONE_RE = re.compile(r"\A[0-9]{8}T[0-9]{6}\Z")

_OFFSET_RE = re.compile(r"\A([+-])([0-9]{2})([0-9]{2})([0-9]{2})?\Z")

_BYDAY_RE = re.compile(r"\A([+-]?[0-9]+)(SU|MO|TU|WE|TH|FR|SA)\Z", re.IGNORECASE)

#: Weekday codes per RFC 5545 §3.3.10, where ``SU = 0``.
#:
#: Deliberately NOT ISO-8601's ``MO = 1``, and deliberately not Python's
#: :meth:`datetime.date.weekday` (``MO = 0``) either. The conversion
#: happens once, here, at the boundary.
_WEEKDAYS = {"SU": 0, "MO": 1, "TU": 2, "WE": 3, "TH": 4, "FR": 5, "SA": 6}

_SECONDS_PER_HOUR = 3600
_SECONDS_PER_MINUTE = 60


def _require_aware(t: datetime, what: str) -> None:
    """Refuse a naive ``datetime`` at the API boundary.

    Raising here rather than coercing is the point: a silent
    ``replace(tzinfo=UTC)`` would read the caller's wall clock as UTC and
    shift the instant by the local offset, which is both wrong and
    invisible.
    """
    if t.tzinfo is None or t.tzinfo.utcoffset(t) is None:
        raise ValueError(f"{what} requires a timezone-aware datetime, got a naive one")


def format_time(t: datetime | None) -> str:
    """Render ``t`` as an RFC 5545 §3.3.5 form #2 string, in UTC.

    ``None`` renders as the empty string, which is how the property
    writers spell "clear the property".

    Any aware input is accepted and converted, so a value carrying a
    ``-05:00`` offset produces the same wire output as its UTC
    equivalent. Sub-second precision is truncated: form #2 has second
    resolution, and rounding would move an instant across a boundary.
    """
    if t is None:
        return ""
    _require_aware(t, "format_time")
    u = t.astimezone(UTC)
    return (
        f"{u.year:04d}{u.month:02d}{u.day:02d}"
        f"T{u.hour:02d}{u.minute:02d}{u.second:02d}Z"
    )


def parse_time(s: str) -> datetime | None:
    """Parse an RFC 5545 §3.3.5 form #2 string into an aware UTC datetime.

    ``None`` for any other input shape — strict by design, so a V* reader
    sees torn data rather than a silent coercion. Specifically rejected:

    - form #1 (``YYYYMMDDTHHMMSS``), which has no zone and is resolved
      only through :func:`parse_time_with_tzid`;
    - RFC 3339 / ISO 8601 extended layouts (``2026-05-04T18:30:45Z``);
    - date-only values, which are the DATE value type (see
      :mod:`vstar.date`);
    - a lowercase ``z`` suffix — RFC 5545 mandates upper case;
    - leading or trailing whitespace, extra octets, and any length other
      than sixteen;
    - impossible calendar dates. February 30th does not roll into March.
    """
    if len(s) != _FORM_TWO_OCTETS or s[15] != "Z":
        return None
    wall = _parse_wall(s[:_FORM_ONE_OCTETS])
    if wall is None:
        return None
    return wall.replace(tzinfo=UTC)


def _parse_wall(s: str) -> datetime | None:
    """Decode a form #1 wire string into a **naive** wall-clock datetime.

    Naive on purpose: the value carries no zone yet, and attaching one
    before the offset is known would be a lie. Every caller either
    stamps UTC (:func:`parse_time`) or attaches the resolved fixed
    offset (:func:`parse_time_with_tzid`).
    """
    if _FORM_ONE_RE.match(s) is None:
        return None
    try:
        return datetime(
            int(s[0:4]),
            int(s[4:6]),
            int(s[6:8]),
            int(s[9:11]),
            int(s[11:13]),
            int(s[13:15]),
        )
    except ValueError:
        # An impossible date (Feb 30, month 13) or an out-of-range clock
        # field. datetime validates both and never rolls over.
        return None


def _parse_form_one(s: str) -> datetime | None:
    """Decode ``s`` as form #1, rejecting a ``Z`` suffix explicitly.

    A form #2 value is already absolute; resolving it against a zone
    would apply an offset twice. Rule 5 falls back to verbatim emit
    there, which is why this refuses rather than coerces.
    """
    if len(s) != _FORM_ONE_OCTETS:
        return None
    if s[-1] in ("Z", "z"):
        return None
    return _parse_wall(s)


@dataclass(frozen=True, slots=True)
class _TzRule:
    """The subset of a STANDARD/DAYLIGHT child needed to place a transition."""

    #: ``TZOFFSETTO`` in seconds east of UTC.
    offset_to: int
    #: Whether the child carried an accepted ``FREQ=YEARLY`` RRULE.
    yearly: bool
    #: ``BYMONTH`` (1-12); zero when the child carried no RRULE.
    month: int
    #: ``BYDAY`` weekday, ``SU = 0`` per RFC 5545.
    weekday: int
    #: ``BYDAY`` ordinal: positive counts from the start, negative from the end.
    week: int
    #: The transition's wall-clock time of day, from the child's ``DTSTART``.
    hour: int
    minute: int
    second: int


@dataclass(frozen=True, slots=True)
class _TzRuleSet:
    """The STANDARD plus optional DAYLIGHT pair extracted from a VTIMEZONE."""

    std: _TzRule
    dst: _TzRule | None


def parse_time_with_tzid(s: str, tzid: str, cal: Calendar) -> datetime | None:
    """Resolve an RFC 5545 form #1 wall-clock value in the zone ``tzid`` names.

    The zone is reconstructed from a VTIMEZONE component inside ``cal``
    and nowhere else. The returned datetime carries a fixed
    :class:`~datetime.timezone` reflecting the offset active for that
    wall-clock instant; call :meth:`~datetime.datetime.astimezone` with
    :data:`~datetime.timezone.utc`, or :func:`format_time`, for the
    canonical UTC instant.

    ``None`` — not an exception — when:

    - ``tzid`` is empty;
    - ``cal`` carries no VTIMEZONE whose ``TZID`` matches (comparison is
      case-sensitive: TZIDs are opaque identifiers per RFC 5545 §3.2.19);
    - the matching VTIMEZONE falls outside the spec's v0.1 subset —
      multiple STANDARD or DAYLIGHT children, a missing or malformed
      offset or ``DTSTART``, or an RRULE the subset does not accept;
    - ``s`` is not form #1.

    Resolution failure is a normal outcome. Rule 5 passes the value and
    its ``TZID`` parameter through verbatim in that branch, so the
    canonical layer treats ``None`` as "emit as authored", never as an
    error.
    """
    if tzid == "":
        return None
    wall = _parse_form_one(s)
    if wall is None:
        return None
    tz = _find_vtimezone(tzid, cal)
    if tz is None:
        return None
    rules = _load_tz_rules(tz)
    if rules is None:
        return None
    offset = _active_offset(wall, rules)
    return wall.replace(tzinfo=timezone(timedelta(seconds=offset)))


def _find_vtimezone(tzid: str, cal: Calendar) -> Component | None:
    """The VTIMEZONE in ``cal`` whose ``TZID`` property equals ``tzid``."""
    for c in cal.filter(CompType.TIMEZONE):
        p = c.get("TZID")
        if p is not None and p.value == tzid:
            return c
    return None


def _subs_by_type(c: Component, name: str) -> list[Component]:
    """Sub-components of ``c`` whose type is exactly ``name``.

    Case-sensitive: RFC 5545 component identifiers are uppercase, and a
    lowercase ``standard`` is not one.
    """
    return [s for s in c.sub if str(s.type) == name]


def _load_tz_rules(tz: Component) -> _TzRuleSet | None:
    """Extract the rule pair from a VTIMEZONE, or ``None`` outside the subset.

    Accepted shapes, per the spec's VTIMEZONE subset:

    1. a single STANDARD alone — a fixed-offset zone, RRULE optional;
    2. a single STANDARD plus a single DAYLIGHT, where **both** carry an
       accepted ``FREQ=YEARLY`` rule;
    3. a DAYLIGHT alone, treated as a fixed offset since there is no
       transition to compute.

    Everything else — split-zone histories, RDATE-only zones, a child
    missing an offset — is a resolution failure.
    """
    standards = _subs_by_type(tz, "STANDARD")
    daylights = _subs_by_type(tz, "DAYLIGHT")

    if not standards and not daylights:
        return None
    # Split-zone histories (multiple STANDARD or DAYLIGHT entries) are
    # outside v0.1.
    if len(standards) > 1 or len(daylights) > 1:
        return None

    if not standards:
        only = _parse_tz_rule(daylights[0])
        return None if only is None else _TzRuleSet(std=only, dst=None)

    std = _parse_tz_rule(standards[0])
    if std is None:
        return None
    if not daylights:
        return _TzRuleSet(std=std, dst=None)

    dst = _parse_tz_rule(daylights[0])
    if dst is None:
        return None
    # With both children present the subset requires a yearly rule on
    # each: without one there is no transition date to compute.
    if not std.yearly or not dst.yearly:
        return None
    return _TzRuleSet(std=std, dst=dst)


def _active_offset(wall: datetime, rs: _TzRuleSet) -> int:
    """The offset in seconds east of UTC that applies to ``wall``.

    With no DAYLIGHT child the STANDARD offset applies unconditionally.
    Otherwise both transitions are placed in ``wall``'s own year and
    compared on the same naive timeline — which orders two wall events
    within one year correctly, and is all the comparison needs. The
    absolute values are meaningless; only their ordering is used.
    """
    if rs.dst is None:
        return rs.std.offset_to
    dst_start = _transition_at(wall.year, rs.dst)
    std_start = _transition_at(wall.year, rs.std)
    if dst_start <= wall < std_start:
        return rs.dst.offset_to
    return rs.std.offset_to


def _transition_at(year: int, r: _TzRule) -> datetime:
    """The naive wall-clock instant at which ``r`` becomes active in ``year``.

    Naive because it is a wall-clock value, never an instant: attaching a
    zone here would beg the question the caller is asking. Only the
    ordering of two such values from the same year is ever used.
    """
    day = _nth_weekday_of_month(year, r.month, r.weekday, r.week)
    return datetime(year, r.month, day, r.hour, r.minute, r.second)


def _rfc_weekday(d: date) -> int:
    """``d``'s weekday in RFC 5545's numbering, where ``SU = 0``.

    Python's :meth:`~datetime.date.weekday` is ``MO = 0`` and ISO-8601 is
    ``MO = 1``; RFC 5545 §3.3.10 is neither. The conversion happens here
    and nowhere else.
    """
    return (d.weekday() + 1) % 7


def _nth_weekday_of_month(year: int, month: int, weekday: int, n: int) -> int:
    """The day-of-month of the ``n``th ``weekday`` in ``(year, month)``.

    Positive ``n`` counts from the start (1 = first); negative counts
    from the end (-1 = last). ``n = 0`` is rejected at parse time, so it
    never reaches here.

    ``weekday`` is RFC 5545's ``SU = 0``, per :func:`_rfc_weekday`.
    """
    if n > 0:
        offset = (weekday - _rfc_weekday(date(year, month, 1))) % 7
        return 1 + offset + (n - 1) * 7
    last_day = monthrange(year, month)[1]
    offset = (_rfc_weekday(date(year, month, last_day)) - weekday) % 7
    return last_day - offset + (n + 1) * 7


def _parse_tz_rule(c: Component) -> _TzRule | None:
    """Read one STANDARD/DAYLIGHT child, or ``None`` outside the subset."""
    offset_to = _read_offset(c, "TZOFFSETTO")
    if offset_to is None:
        return None
    # TZOFFSETFROM takes no part in the arithmetic, but the subset
    # requires it present and well-formed: a child missing it is a
    # producer shape this implementation declines to guess at.
    if _read_offset(c, "TZOFFSETFROM") is None:
        return None

    dtstart = c.get("DTSTART")
    if dtstart is None:
        return None
    wall = _parse_form_one(dtstart.value)
    if wall is None:
        return None

    rrule = c.get("RRULE")
    if rrule is None:
        return _TzRule(
            offset_to=offset_to,
            yearly=False,
            month=0,
            weekday=0,
            week=0,
            hour=wall.hour,
            minute=wall.minute,
            second=wall.second,
        )
    yearly = _parse_yearly_rrule(rrule.value)
    if yearly is None:
        return None
    month, weekday, week = yearly
    return _TzRule(
        offset_to=offset_to,
        yearly=True,
        month=month,
        weekday=weekday,
        week=week,
        hour=wall.hour,
        minute=wall.minute,
        second=wall.second,
    )


def _read_offset(c: Component, name: str) -> int | None:
    """Read a ``±HHMM`` / ``±HHMMSS`` offset property as seconds east of UTC."""
    p = c.get(name)
    if p is None:
        return None
    m = _OFFSET_RE.match(p.value)
    if m is None:
        return None
    sign = -1 if m.group(1) == "-" else 1
    hh, mm = int(m.group(2)), int(m.group(3))
    ss = int(m.group(4)) if m.group(4) is not None else 0
    return sign * (hh * _SECONDS_PER_HOUR + mm * _SECONDS_PER_MINUTE + ss)


def _parse_yearly_rrule(s: str) -> tuple[int, int, int] | None:
    """Accept only the VTIMEZONE RRULE subset; return ``(month, weekday, week)``.

    ``FREQ=YEARLY`` with an optional ``BYMONTH``, an ordinal ``BYDAY``,
    and a no-op ``INTERVAL=1``. Everything else fails closed — ``UNTIL``,
    ``COUNT``, ``BYWEEKNO``, ``BYSETPOS``, ``WKST``, an unknown key, a
    ``BYDAY`` without an ordinal — because applying a partial rule
    produces a plausible instant that is wrong, which is worse than no
    instant at all.

    This is deliberately narrow and unrelated to the generic RRULE
    parsing scope, which lands with the recurrence layer.
    """
    freq_seen = False
    month = 0
    weekday = 0
    week = 0

    for part in s.split(";"):
        key, sep, val = part.partition("=")
        if not sep:
            return None
        match key.upper():
            case "FREQ":
                if val.upper() != "YEARLY":
                    return None
                freq_seen = True
            case "BYMONTH":
                if not val.isdigit():
                    return None
                m = int(val)
                if not 1 <= m <= 12:
                    return None
                month = m
            case "BYDAY":
                byday = _parse_byday(val)
                if byday is None:
                    return None
                week, weekday = byday
            case "INTERVAL":
                # A no-op INTERVAL=1 is accepted; any other value is not.
                if val != "1":
                    return None
            case _:
                return None
    return (month, weekday, week) if freq_seen else None


def _parse_byday(s: str) -> tuple[int, int] | None:
    """Parse one BYDAY entry such as ``2SU`` or ``-1SU`` into ``(week, weekday)``.

    The ordinal-less forms (``SU``, ``0SU``) are rejected: a VTIMEZONE
    transition needs an explicit nth, and guessing "every Sunday" would
    place the transition somewhere the producer never said.
    """
    m = _BYDAY_RE.match(s)
    if m is None:
        return None
    week = int(m.group(1))
    if week == 0:
        return None
    return week, _WEEKDAYS[m.group(2).upper()]
