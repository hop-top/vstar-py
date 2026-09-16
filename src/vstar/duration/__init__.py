# SPDX-License-Identifier: MIT

"""The RFC 5545 §3.3.6 DURATION value type and the §3.8.6.3 TRIGGER property.

**Why a class and not a timedelta.** :class:`VDuration` preserves the
units the producer authored — weeks, days, hours, minutes, seconds —
rather than collapsing them to a second count. A
:class:`~datetime.timedelta` cannot represent "one day" distinctly from
"24 hours", but RFC 5545 draws that distinction deliberately: a calendar
day is 23, 24 or 25 hours across a UTC-offset transition. Re-serializing
a second count would silently rewrite ``P1D`` as ``PT24H`` and shift
every alarm that crosses a transition by an hour — and spec rule 12
preserves DURATION values verbatim precisely so that cannot happen.

Both views are available:

- :meth:`VDuration.signed` reports the **nominal** length (days = 24h,
  weeks = 7 days), exact for time-only values and for any anchor in a
  fixed-offset zone such as UTC. Use it for display, sorting and
  comparison.
- :meth:`VDuration.add_to` anchors the value against a real instant,
  advancing calendar days and weeks by date rather than by elapsed time.
  Use it whenever a real anchor is available.

The type is named ``VDuration``, not ``Duration``, because
:class:`~datetime.timedelta` already occupies that conceptual slot in
Python and the two are not interchangeable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum

from ..errors import Malformed, NoAnchor, NoTrigger
from ..time import format_time, parse_time
from ..types import Calendar, Component, CompType, Param, Property

__all__ = [
    "Related",
    "Trigger",
    "VDuration",
    "alarm_repeat_cycle",
    "alarm_trigger",
    "event_end",
    "from_signed",
    "parse",
    "parse_trigger",
    "valid",
]

# Property names this module reads off components.
_PROP_TRIGGER = "TRIGGER"
_PROP_DURATION = "DURATION"
_PROP_REPEAT = "REPEAT"

# Parameter names and values from RFC 5545 §3.2.
_PARAM_RELATED = "RELATED"
_PARAM_VALUE = "VALUE"
_VALUE_DURATION = "DURATION"
_VALUE_DATE_TIME = "DATE-TIME"

_HOURS_PER_DAY = 24
_DAYS_PER_WEEK = 7


@dataclass(frozen=True, slots=True)
class VDuration:
    """An RFC 5545 §3.3.6 DURATION value in the units its producer authored.

    The grammar admits either a week form (``weeks`` alone) or a
    day-and-time form (``days`` plus an optional hour/minute/second time
    part); the two never mix.

    ``negative`` applies to the **whole** duration, not to any single
    field — it is what makes ``-PT15M`` mean "fifteen minutes before" on
    a VALARM TRIGGER.

    The default ``VDuration()`` is a valid, positive, zero-length value
    and formats as ``PT0S``.
    """

    #: Whether the whole duration is subtractive.
    negative: bool = False
    #: The ``nW`` count. When non-zero every other unit field is zero —
    #: RFC 5545 forbids mixing weeks with other units.
    weeks: int = 0
    #: The ``nD`` count.
    days: int = 0
    #: The ``nH`` count from the time part.
    hours: int = 0
    #: The ``nM`` count from the time part.
    minutes: int = 0
    #: The ``nS`` count from the time part.
    seconds: int = 0
    #: Whether the value was authored in the day form with a zero day
    #: count (``P0D``).
    #:
    #: Every unit field is then zero, which is indistinguishable from the
    #: default ``VDuration``, so this flag is what lets :meth:`__str__`
    #: reproduce ``P0D`` rather than the canonical zero spelling
    #: ``PT0S``. It affects **formatting only** — :meth:`signed`,
    #: :meth:`is_negative` and :meth:`add_to` ignore it, and the two
    #: values are numerically identical.
    #:
    #: A port that drops this field fails the ``behavior/duration`` gate.
    day_form: bool = False

    def _is_zero(self) -> bool:
        """Whether every unit field is zero."""
        return (
            self.weeks == 0
            and self.days == 0
            and self.hours == 0
            and self.minutes == 0
            and self.seconds == 0
        )

    def __str__(self) -> str:
        """Render as an RFC 5545 §3.3.6 DURATION value.

        :func:`parse` and this round-trip byte for byte, with one
        intentional normalization: an explicit ``+`` is dropped, since a
        positive duration is the default.

        A wholly zero value renders as ``PT0S`` — never the empty string
        and never a bare ``P``, both of which :func:`parse` rejects — or
        as ``P0D`` when :attr:`day_form` records that spelling.
        """
        out = []
        if self.negative and not self._is_zero():
            out.append("-")
        out.append("P")

        if self.weeks != 0:
            out.append(f"{self.weeks}W")
            return "".join(out)

        has_time = self.hours != 0 or self.minutes != 0 or self.seconds != 0

        if self._is_zero() and not self.day_form:
            out.append("T0S")
            return "".join(out)

        if self.days != 0 or self.day_form:
            out.append(f"{self.days}D")
        if not has_time:
            return "".join(out)

        out.append("T")
        if self.hours != 0:
            out.append(f"{self.hours}H")
        if self.minutes != 0:
            out.append(f"{self.minutes}M")
        if self.seconds != 0:
            out.append(f"{self.seconds}S")
        return "".join(out)

    def signed(self) -> timedelta:
        """The **nominal** signed length, with days at 24h and weeks at 7 days.

        Exact for time-only values and for any anchor in a fixed-offset
        zone, UTC included. NOT exact for day or week values crossing a
        UTC-offset transition — use :meth:`add_to` when a real anchor is
        available.
        """
        total = timedelta(
            weeks=self.weeks,
            days=self.days,
            hours=self.hours,
            minutes=self.minutes,
            seconds=self.seconds,
        )
        return -total if self.negative else total

    def is_negative(self) -> bool:
        """Whether this duration is subtractive.

        A zero-length duration is never negative, however it was
        authored: ``-PT0S`` carries the sign flag and reports ``False``
        here. This normalized predicate is what the
        ``behavior/duration/parse.json`` ``negative`` column records —
        not :attr:`negative`, the raw flag.
        """
        return self.negative and not self._is_zero()

    def add_to(self, t: datetime) -> datetime:
        """Advance ``t`` by this duration, honouring calendar semantics.

        Weeks and days move by calendar date so a value crossing a
        UTC-offset transition lands on the same wall-clock time; the
        hour/minute/second part is added as elapsed time. A negative
        duration subtracts, moving both parts backwards.

        This is the difference the authored-unit design exists to
        preserve. Against a zone with DST, ``P1D`` from 12:00 the day
        before a spring-forward yields 12:00 (23 elapsed hours) while
        ``PT24H`` yields 13:00.
        """
        from ..time import _require_aware

        _require_aware(t, "VDuration.add_to")
        sign = -1 if self.negative else 1
        days = sign * (self.weeks * _DAYS_PER_WEEK + self.days)
        clock = timedelta(hours=self.hours, minutes=self.minutes, seconds=self.seconds)
        return t + timedelta(days=days) + sign * clock


def parse(s: str) -> VDuration:
    """Decode an RFC 5545 §3.3.6 DURATION value, e.g. ``-PT15M``.

    The grammar accepted is exactly::

        dur-value  = ["+" / "-"] "P" (dur-date / dur-time / dur-week)
        dur-date   = dur-day [dur-time]
        dur-time   = "T" (dur-hour / dur-minute / dur-second)
        dur-week   = 1*DIGIT "W"
        dur-hour   = 1*DIGIT "H" [dur-minute]
        dur-minute = 1*DIGIT "M" [dur-second]
        dur-second = 1*DIGIT "S"
        dur-day    = 1*DIGIT "D"

    Parsing is strict, matching :func:`vstar.parse_time`'s posture.
    Rejected with :class:`~vstar.Malformed`: empty input, a missing
    ``P``, lowercase designators, weeks mixed with any other unit, time
    units outside the ``T`` part, units out of RFC order, repeated units,
    digits with no unit, an empty ``T`` part, ISO 8601 years or months
    (``P1Y``, ``P1M`` — not in RFC 5545), fractional values, per-component
    signs, and any leading, trailing or internal whitespace.
    """
    rest, negative = _parse_sign(s)
    d = _parse_body(rest, s)
    return VDuration(
        negative=negative,
        weeks=d.weeks,
        days=d.days,
        hours=d.hours,
        minutes=d.minutes,
        seconds=d.seconds,
        day_form=d.day_form,
    )


def valid(s: str) -> bool:
    """Whether ``s`` is a well-formed DURATION value.

    Equivalent to discarding :func:`parse`'s result, offered so a caller
    testing a wire string need not name one it will not use.
    """
    try:
        parse(s)
    except Malformed:
        return False
    return True


def from_signed(td: timedelta) -> VDuration:
    """Convert a :class:`~datetime.timedelta` into hours, minutes and seconds.

    Sub-second precision is truncated toward zero: RFC 5545 durations
    have second resolution.

    The result never uses the week or day units. A ``timedelta`` carries
    no calendar information, so emitting ``P1D`` from 24 hours would
    invent a distinction the input never made. A caller who means
    calendar days constructs :class:`VDuration` directly.
    """
    total = int(td.total_seconds())
    negative = total < 0
    total = abs(total)
    hours, total = divmod(total, 3600)
    minutes, seconds = divmod(total, 60)
    return VDuration(negative=negative, hours=hours, minutes=minutes, seconds=seconds)


@dataclass(slots=True)
class _Body:
    """The unit fields decoded from the portion after ``P``."""

    weeks: int = 0
    days: int = 0
    hours: int = 0
    minutes: int = 0
    seconds: int = 0
    day_form: bool = False


def _parse_sign(s: str) -> tuple[str, bool]:
    """Strip the optional sign and the mandatory ``P``, returning the rest."""
    if s == "":
        raise Malformed("duration: empty input")
    negative = False
    if s[0] == "+":
        s = s[1:]
    elif s[0] == "-":
        negative = True
        s = s[1:]
    if s == "" or s[0] != "P":
        raise Malformed('duration: missing "P" designator')
    return s[1:], negative


def _parse_body(body: str, orig: str) -> _Body:
    """Decode the portion after ``P``: a week value, or days with a time part."""
    if body == "":
        raise Malformed(f'duration: {orig!r} has no value after "P"')

    d = _Body()

    # A bare time part: "PT...".
    if body[0] == "T":
        _parse_time_part(body[1:], d, orig)
        return d

    # Otherwise a date part: weeks, or days with an optional time part.
    date_part, sep, time_part = body.partition("T")
    has_time = bool(sep)

    n, unit, remainder = _next_field(date_part, orig)
    if unit == "W":
        if remainder != "":
            raise Malformed(f"duration: {orig!r} mixes weeks with other units")
        if has_time:
            raise Malformed(f"duration: {orig!r} mixes weeks with a time part")
        d.weeks = n
    elif unit == "D":
        if remainder != "":
            raise Malformed(
                f"duration: {orig!r} has trailing input {remainder!r} "
                f"after the day value"
            )
        d.days = n
        d.day_form = True
    else:
        raise Malformed(
            f"duration: {orig!r} uses unit {unit!r} outside a time part "
            f"(RFC 5545 has no years or months)"
        )

    if has_time:
        _parse_time_part(time_part, d, orig)
    return d


def _parse_time_part(s: str, d: _Body, orig: str) -> None:
    """Decode the segment after ``T`` into ``d``'s hours, minutes and seconds.

    Units appear at most once and in RFC order (H, then M, then S). The
    rank counter is what rejects both a repeat and a misorder with one
    comparison.
    """
    if s == "":
        raise Malformed(f"duration: {orig!r} has an empty time part")
    order = 0
    while s != "":
        n, unit, remainder = _next_field(s, orig)
        if unit == "H":
            rank, d.hours = 1, n
        elif unit == "M":
            rank, d.minutes = 2, n
        elif unit == "S":
            rank, d.seconds = 3, n
        else:
            raise Malformed(f"duration: {orig!r} uses unknown time unit {unit!r}")
        if rank <= order:
            raise Malformed(
                f"duration: {orig!r} repeats or misorders time unit {unit!r}"
            )
        order = rank
        s = remainder


def _next_field(s: str, orig: str) -> tuple[int, str, str]:
    """Consume one ``1*DIGIT UNIT`` field, returning value, unit and remainder."""
    i = 0
    while i < len(s) and s[i].isascii() and s[i].isdigit():
        i += 1
    if i == 0:
        raise Malformed(f"duration: {orig!r} has a unit with no digits")
    if i == len(s):
        raise Malformed(f"duration: {orig!r} has digits with no unit")
    return int(s[:i]), s[i], s[i + 1 :]


class Related(Enum):
    """Which end of the parent component a relative TRIGGER is measured from.

    The RFC 5545 §3.2.14 ``RELATED`` parameter. :attr:`START` is listed
    first because it is also the RFC default when the parameter is
    absent.
    """

    #: Anchored to the parent's start (``DTSTART``). The default.
    START = "START"
    #: Anchored to the parent's end (``DTEND``, ``DTSTART``+``DURATION``,
    #: or a VTODO's ``DUE``).
    END = "END"

    def __str__(self) -> str:
        """The RFC wire spelling, ``START`` or ``END``."""
        return self.value


@dataclass(slots=True)
class Trigger:
    """A parsed RFC 5545 §3.8.6.3 TRIGGER: a relative offset or an instant.

    Exactly one of the two forms is populated. When :attr:`relative` is
    ``True``, :attr:`duration` and :attr:`related` carry the offset and
    its anchor and :attr:`absolute` is ``None``; when it is ``False``,
    :attr:`absolute` carries the instant and :attr:`duration` is the
    zero duration.
    """

    #: Which of the two forms this is.
    relative: bool = False
    #: The offset, valid only when :attr:`relative`. A negative duration
    #: fires before the anchor — the common case.
    duration: VDuration = field(default_factory=VDuration)
    #: The anchor, valid only when :attr:`relative`.
    related: Related = Related.START
    #: The firing instant, valid only when :attr:`relative` is ``False``.
    #:
    #: ``None`` rather than an epoch sentinel: an in-band "no instant"
    #: value makes 1970-01-01T00:00:00Z unrepresentable.
    absolute: datetime | None = None

    def to_property(self) -> Property:
        """Render back to the wire property.

        A relative trigger emits its duration as the value, adding
        ``RELATED=END`` only when the anchor is the end — ``RELATED=START``
        is the RFC default and is left implicit. An absolute trigger emits
        the UTC form #2 instant and carries ``VALUE=DATE-TIME``
        explicitly, so a consumer never has to infer the form.
        """
        if not self.relative:
            return Property(
                name=_PROP_TRIGGER,
                params=[Param(_PARAM_VALUE, _VALUE_DATE_TIME)],
                value=format_time(self.absolute),
            )
        params = (
            [Param(_PARAM_RELATED, Related.END.value)]
            if self.related is Related.END
            else []
        )
        return Property(name=_PROP_TRIGGER, params=params, value=str(self.duration))

    def resolve(self, parent: Component, cal: Calendar) -> datetime:
        """The instant at which this trigger fires.

        An absolute trigger returns its instant and ignores ``parent``
        and ``cal``. A relative trigger resolves its anchor from
        ``parent`` — ``DTSTART`` for :attr:`Related.START`, and for
        :attr:`Related.END` the end as computed by :func:`event_end`
        (``DTEND``, else ``DTSTART``+``DURATION``) or a VTODO's ``DUE`` —
        then offsets it with :meth:`VDuration.add_to`, so calendar days
        and weeks honour zone transitions.

        ``cal`` supplies the VTIMEZONE registry used to resolve a
        ``TZID``-bearing anchor; pass the parent's calendar, or an empty
        one when the anchors are plain UTC.

        Raises :class:`~vstar.NoAnchor` when the required anchor is
        absent or unparseable — reported rather than silently resolved
        against a zero time, which would place every such alarm in year 1.
        """
        if not self.relative:
            # An absolute trigger without an instant cannot be built by
            # parse_trigger; a hand-constructed one is the caller's bug.
            if self.absolute is None:
                raise NoAnchor("duration: absolute trigger carries no instant")
            return self.absolute
        anchor = self._anchor(parent, cal)
        if anchor is None:
            raise NoAnchor(
                f"duration: {parent.type} has no {self.related} anchor "
                f"for a relative trigger"
            )
        return self.duration.add_to(anchor)

    def _anchor(self, parent: Component, cal: Calendar) -> datetime | None:
        """The parent instant this trigger is measured from."""
        if self.related is Related.START:
            return parent.dtstart(cal)
        # RelatedEnd: a VTODO ends at DUE; everything else at DTEND or
        # DTSTART+DURATION.
        if parent.type == CompType.TODO:
            due = parent.due(cal)
            if due is not None:
                return due
        return event_end(parent, cal)


def parse_trigger(p: Property) -> Trigger:
    """Decode a TRIGGER property.

    The value form is chosen as follows:

    - ``VALUE=DURATION``, or no ``VALUE`` parameter with a value that
      parses as a duration, gives a relative trigger.
    - ``VALUE=DATE-TIME``, or no ``VALUE`` parameter with a value that
      parses as an RFC 5545 form #2 UTC instant, gives an absolute one.

    An explicit ``VALUE`` parameter is **authoritative**: a value that
    contradicts it is :class:`~vstar.Malformed`, never silently re-read
    as the other form. With no ``VALUE`` parameter the two value shapes
    are unambiguous, so the value itself decides — producers in the wild
    routinely omit the parameter.

    ``RELATED`` is honoured on relative triggers only; RFC 5545 §3.2.14
    scopes the parameter to DURATION-valued triggers, so ``RELATED`` on
    an absolute trigger is rejected. Both the parameter name and its
    value are matched case-insensitively per RFC 5545 §3.2.
    """
    declared = _param_value(p, _PARAM_VALUE)

    if declared is not None and declared.upper() == _VALUE_DURATION:
        try:
            d = parse(p.value)
        except Malformed as exc:
            raise Malformed(
                "trigger: VALUE=DURATION but value is not a duration"
            ) from exc
        t = Trigger(relative=True, duration=d)
    elif declared is not None and declared.upper() == _VALUE_DATE_TIME:
        at = parse_time(p.value)
        if at is None:
            raise Malformed(
                f"trigger: VALUE=DATE-TIME but value {p.value!r} is not an "
                f"RFC 5545 form #2 instant"
            )
        t = Trigger(absolute=at)
    elif declared is not None:
        raise Malformed(
            f"trigger: unsupported VALUE={declared} (want DURATION or DATE-TIME)"
        )
    else:
        # No VALUE parameter — infer from the value's shape.
        t = _infer_trigger(p.value)

    related = _param_value(p, _PARAM_RELATED)
    if related is None:
        return t
    if not t.relative:
        raise Malformed(
            "trigger: RELATED is meaningful only on a relative trigger "
            "(RFC 5545 §3.2.14)"
        )
    upper = related.upper()
    if upper == Related.START.value:
        t.related = Related.START
    elif upper == Related.END.value:
        t.related = Related.END
    else:
        raise Malformed(f"trigger: unknown RELATED={related} (want START or END)")
    return t


def _infer_trigger(value: str) -> Trigger:
    """Choose the trigger form from the value's own shape.

    A duration and a form #2 instant cannot be confused for one another,
    so this is unambiguous — which is why the RFC lets producers omit the
    ``VALUE`` parameter at all.
    """
    try:
        return Trigger(relative=True, duration=parse(value))
    except Malformed:
        pass
    at = parse_time(value)
    if at is None:
        raise Malformed(
            f"trigger: value {value!r} is neither a DURATION nor a DATE-TIME"
        )
    return Trigger(absolute=at)


def alarm_trigger(alarm: Component) -> Trigger:
    """Read and parse the TRIGGER property of a VALARM.

    Raises :class:`~vstar.NoTrigger` when the property is absent:
    RFC 5545 §3.6.6 makes it mandatory, so its absence is a producer bug
    rather than an absent optional, and the alarm cannot be scheduled.
    """
    p = alarm.get(_PROP_TRIGGER)
    if p is None:
        raise NoTrigger("duration: VALARM has no TRIGGER")
    return parse_trigger(p)


def event_end(c: Component, cal: Calendar) -> datetime | None:
    """The end instant of a component expressing it as ``DTEND`` or ``DURATION``.

    RFC 5545 §3.6.1 allows exactly one of the two on a VEVENT.
    ``DTEND`` wins when both are present — it is the explicit statement.
    Falling back, ``DURATION`` is applied to ``DTSTART`` with
    :meth:`VDuration.add_to`, so a ``P1D`` event keeps its wall-clock end
    across a transition.

    ``None`` when neither form is available, when ``DTSTART`` is missing
    for the ``DURATION`` form, or when the ``DURATION`` value is
    malformed — torn data does not become a plausible end instant.
    """
    end = c.dtend(cal)
    if end is not None:
        return end
    p = c.get(_PROP_DURATION)
    if p is None:
        return None
    try:
        d = parse(p.value)
    except Malformed:
        return None
    start = c.dtstart(cal)
    if start is None:
        return None
    return d.add_to(start)


def alarm_repeat_cycle(alarm: Component) -> tuple[VDuration, int]:
    """The VALARM ``DURATION``/``REPEAT`` pair: interval and repeat count.

    RFC 5545 §3.8.6.2 and §3.8.6.3: the two properties travel together —
    if one is present the other must be too.

    Returns the zero duration and ``0`` when neither is present, which is
    a legal alarm rather than an error. Raises :class:`~vstar.Malformed`
    when only one is, when the ``DURATION`` value is invalid, or when
    ``REPEAT`` is not a non-negative integer.
    """
    dur = alarm.get(_PROP_DURATION)
    rep = alarm.get(_PROP_REPEAT)

    if dur is None:
        if rep is None:
            return VDuration(), 0
        raise Malformed(
            "duration: VALARM has REPEAT without DURATION (RFC 5545 §3.8.6.2)"
        )
    if rep is None:
        raise Malformed(
            "duration: VALARM has DURATION without REPEAT (RFC 5545 §3.8.6.2)"
        )

    d = parse(dur.value)
    value = rep.value
    if not (value.isascii() and value.isdigit()):
        raise Malformed(
            f"duration: VALARM REPEAT {value!r} is not a non-negative integer"
        )
    return d, int(value)


def _param_value(p: Property, name: str) -> str | None:
    """The value of the first parameter named ``name``, case-insensitively."""
    wanted = name.upper()
    for par in p.params:
        if par.name.upper() == wanted:
            return par.value
    return None
