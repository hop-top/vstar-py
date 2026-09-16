# SPDX-License-Identifier: MIT

"""The forward evaluator: one FREQ period expanded, filtered, stepped.

Every calculation here is pure UTC :class:`~datetime.datetime`
arithmetic. **There is no IANA timezone database here and there must
never be one** — no :mod:`zoneinfo`, no ``dateutil``. A V*
implementation resolves local times only against the VTIMEZONE
definitions inside the document it is processing, which happens a layer
below this one; by the time a rule reaches the evaluator every instant
is absolute.

Weekday numbering is ``SU = 0`` per RFC 5545 §3.3.10, which is neither
ISO-8601's ``MO = 1`` nor Python's :meth:`datetime.date.weekday`
``MO = 0``. The conversion happens at :func:`_weekday_of` and nowhere
else.
"""

from __future__ import annotations

from calendar import isleap, monthrange
from datetime import UTC, datetime, timedelta

from ._rule import Rule
from ._types import ByDay, Freq

__all__ = ["MAX_ITERATIONS", "advance", "period_occurrences"]

#: The evaluator's iteration bound: the number of consecutive empty FREQ
#: periods walked before the search is abandoned.
#:
#: 100000 is large enough for every realistic recurrence — a yearly rule
#: steps once per year, so the bound covers ~100k years of those and
#: ~273 years of daily ones — and small enough to fail fast on a rule
#: that never yields, such as ``FREQ=YEARLY;BYMONTH=2;BYMONTHDAY=30``.
#:
#: The bound is a starvation guard, not a total-occurrence limit: the
#: counter resets whenever a period produces an occurrence, so a rule
#: that fires regularly runs as long as the caller wants.
#:
#: It counts FREQ periods, so under ``FREQ=MINUTELY`` at ``INTERVAL=1``
#: it spans about 69 days: a rule whose limits admit nothing for longer
#: — ``FREQ=MINUTELY;BYMONTH=1`` evaluated from February — reports
#: :class:`~vstar.IterationCap` rather than the eventual occurrence
#: (fixture ``rrule/evaluator/minutely_sparse_limit_caps``).
#:
#: Its value is implementation-defined per spec; what is not optional is
#: that the bound exists, is finite, and that reaching it produces
#: :class:`~vstar.IterationCap` rather than an empty or completed
#: result. It is published so a caller catching that failure can state
#: the bound that was hit, and deliberately not configurable: the only
#: inputs that reach it are unsatisfiable rules, for which a larger
#: budget merely costs more before failing identically.
MAX_ITERATIONS = 100000

_ONE_DAY = timedelta(days=1)

#: The largest year :class:`~datetime.datetime` can represent. Stepping
#: past it is termination, not an error: there are no further periods.
_MAX_YEAR = datetime.max.year


def _weekday_of(t: datetime) -> int:
    """``t``'s weekday in RFC 5545's numbering, where ``SU = 0``."""
    return (t.weekday() + 1) % 7


def _days_in_month(year: int, month: int) -> int:
    """Days in a 1-based ``month`` of ``year``, per the Gregorian leap rule."""
    return monthrange(year, month)[1]


def _days_in_year(year: int) -> int:
    """365 or 366, for the given Gregorian year."""
    return 366 if isleap(year) else 365


def _at(
    year: int, month: int, day: int, hour: int, minute: int, second: int
) -> datetime:
    """A UTC instant from wall-clock fields."""
    return datetime(year, month, day, hour, minute, second, tzinfo=UTC)


def _midnight(year: int, month: int, day: int) -> datetime:
    """Midnight UTC on the given date."""
    return _at(year, month, day, 0, 0, 0)


def _day_of_year(year: int, doy: int) -> datetime:
    """Midnight UTC on the 1-based ``doy``th day of ``year``."""
    return _midnight(year, 1, 1) + timedelta(days=doy - 1)


def _start_of_day(t: datetime) -> datetime:
    """Midnight UTC on the date ``t`` falls on."""
    return _midnight(t.year, t.month, t.day)


def _start_of_week(t: datetime, wkst: int) -> datetime:
    """The start of the week containing ``t``, anchored on ``wkst``.

    WKST-awareness lives here and nowhere else: every week boundary the
    evaluator draws — weekly expansion, BYWEEKNO numbering — comes
    through this function, so a rule's week start is honoured uniformly.
    """
    delta = (_weekday_of(t) - wkst) % 7
    return _start_of_day(t) - timedelta(days=delta)


def _start_of_week_n(year: int, n: int, wkst: int) -> datetime:
    """The WKST-anchored start of week ``n`` of ``year``.

    Week 1 is the week containing January 4th — the ISO 8601 rule,
    generalized to an arbitrary week start.
    """
    return _start_of_week(_midnight(year, 1, 4), wkst) + timedelta(days=7 * (n - 1))


def _weeks_in_year(year: int, wkst: int) -> int:
    """The number of WKST-anchored weeks in ``year``.

    Under the same "week 1 contains January 4th" rule. Most years have
    52; a 53rd exists when the trailing days of December still belong to
    a week of the current year rather than to week 1 of the next.
    """
    first = _start_of_week(_midnight(year, 1, 4), wkst)
    nxt = _start_of_week(_midnight(year + 1, 1, 4), wkst)
    return round((nxt - first).days / 7)


# ── Period stepping ───────────────────────────────────────────────


def advance(rule: Rule, current: datetime) -> datetime | None:
    """Step ``current`` forward by one ``FREQ x INTERVAL`` period.

    ``None`` when there is no next period — an unsteppable frequency, or
    a step past the end of the representable calendar. That ``None`` is
    a *termination* signal and is deliberately distinct from exhausting
    :data:`MAX_ITERATIONS`, which means periods remained but the budget
    did not and reports :class:`~vstar.IterationCap`.
    """
    try:
        match rule.freq:
            case Freq.MINUTELY:
                return current + timedelta(minutes=rule.interval)
            case Freq.HOURLY:
                return current + timedelta(hours=rule.interval)
            case Freq.DAILY:
                return current + timedelta(days=rule.interval)
            case Freq.WEEKLY:
                return current + timedelta(weeks=rule.interval)
            case Freq.MONTHLY:
                # Land on day 1 of the target month rather than adding
                # months to the current day: adding a month to January
                # 31st would overflow into March, and the expansion below
                # reconstructs the real day from BYMONTHDAY or dtstart.
                total = (current.year * 12) + (current.month - 1) + rule.interval
                year, month = divmod(total, 12)
                if year > _MAX_YEAR:
                    return None
                return current.replace(year=year, month=month + 1, day=1)
            case Freq.YEARLY:
                # Same reasoning as MONTHLY, one level up: landing on
                # January 1st stops a February 29th rule sliding into
                # March on a non-leap year, because _expand_yearly takes
                # the month from dtstart.
                year = current.year + rule.interval
                if year > _MAX_YEAR:
                    return None
                return current.replace(year=year, month=1, day=1)
            case Freq.INVALID:
                return None
    except (OverflowError, ValueError):
        # The calendar ran out. No further periods exist, which is
        # termination rather than a failure.
        return None


# ── BY-* matching ─────────────────────────────────────────────────


def _matches_by_month(rule: Rule, t: datetime) -> bool:
    """Whether ``t``'s month satisfies BYMONTH (vacuously true when unset)."""
    return not rule.by_month or t.month in rule.by_month


def _matches_by_hour(rule: Rule, t: datetime) -> bool:
    """Whether ``t``'s hour satisfies BYHOUR (vacuously true when unset).

    The :func:`_matches_by_month` shape, for the FREQs where the
    RFC 5545 §3.3.10 table says BYHOUR limits: HOURLY and finer.
    """
    return not rule.by_hour or t.hour in rule.by_hour


def _matches_by_minute(rule: Rule, t: datetime) -> bool:
    """Whether ``t``'s minute satisfies BYMINUTE (vacuously true when unset).

    The BYMINUTE twin of :func:`_matches_by_hour`, for the FREQ where
    the table says BYMINUTE limits: MINUTELY.
    """
    return not rule.by_minute or t.minute in rule.by_minute


def _matches_by_month_day(rule: Rule, t: datetime) -> bool:
    """Whether ``t``'s day satisfies BYMONTHDAY.

    Negative entries resolve against the real length of ``t``'s own
    month, so ``-1`` is the last day of whichever month this is, 28 or
    31.
    """
    if not rule.by_month_day:
        return True
    dim = _days_in_month(t.year, t.month)
    return any(
        md == t.day if md > 0 else dim + md + 1 == t.day for md in rule.by_month_day
    )


def _matches_by_day(rule: Rule, t: datetime) -> bool:
    """Whether ``t``'s weekday appears in BYDAY, ignoring ordinals.

    Ordinals are meaningful only inside a MONTHLY or YEARLY period,
    where :func:`_matches_by_day_ordinal` honours them.
    """
    if not rule.by_day:
        return True
    wd = _weekday_of(t)
    return any(int(bd.weekday) == wd for bd in rule.by_day)


def _matches_by_day_ordinal(rule: Rule, t: datetime) -> bool:
    """The BYDAY check for MONTHLY and YEARLY periods.

    Here ``2MO`` means "the second Monday of this month" and ``-1FR``
    "the last Friday".
    """
    if not rule.by_day:
        return True
    wd = _weekday_of(t)
    dim = _days_in_month(t.year, t.month)
    return any(
        _matches_one_by_day(bd, wd, t.day, t.year, t.month, dim) for bd in rule.by_day
    )


def _matches_one_by_day(
    bd: ByDay, weekday: int, day: int, year: int, month: int, dim: int
) -> bool:
    """Whether one BYDAY entry matches a day of the month."""
    if int(bd.weekday) != weekday:
        return False
    if bd.ordinal == 0:
        return True
    if bd.ordinal > 0:
        # Days 1-7 hold the first of each weekday, 8-14 the second, ...
        return bd.ordinal == (day - 1) // 7 + 1
    last = _last_weekday_of_month(year, month, dim, weekday)
    return bd.ordinal == -((last - day) // 7 + 1)


def _last_weekday_of_month(year: int, month: int, dim: int, weekday: int) -> int:
    """The day-of-month of the last ``weekday`` in the given month."""
    last_wd = _weekday_of(_midnight(year, month, dim))
    return dim - (last_wd - weekday) % 7


# ── Period expansion ──────────────────────────────────────────────


def _by_or_default(values: list[int], fallback: int) -> list[int]:
    """A BY-* list if non-empty, else a single-element list of the default."""
    return values if values else [fallback]


def _cross_time_of_day(rule: Rule, day: datetime, dtstart: datetime) -> list[datetime]:
    """The cartesian product of BYHOUR x BYMINUTE x BYSECOND on ``day``.

    A time field with no BY-* clause is taken from ``dtstart``, which is
    the RFC's anchor for everything a rule does not constrain.
    """
    return [
        _at(day.year, day.month, day.day, hour, minute, second)
        for hour in _by_or_default(rule.by_hour, dtstart.hour)
        for minute in _by_or_default(rule.by_minute, dtstart.minute)
        for second in _by_or_default(rule.by_second, dtstart.second)
    ]


def _month_day_candidates(rule: Rule, dim: int, dtstart_day: int) -> list[int]:
    """The days-of-month to consider in a month of ``dim`` days.

    With BYMONTHDAY, each entry resolved (negative from the end). With
    BYDAY but no BYMONTHDAY, every day — the BYDAY filter narrows them.
    Otherwise the single day dtstart falls on, which is how an
    unqualified monthly rule fires. A dtstart day past the end of a
    shorter month yields nothing, which is RFC 5545's explicit
    skip-don't-clamp behaviour: a January 31st monthly rule has no
    February occurrence rather than a February 28th one.
    """
    if rule.by_month_day:
        return [md if md > 0 else dim + md + 1 for md in rule.by_month_day]
    if rule.by_day:
        return list(range(1, dim + 1))
    return [] if dtstart_day > dim else [dtstart_day]


def _expand_month_days(
    rule: Rule, year: int, month: int, dtstart: datetime
) -> list[datetime]:
    """Every occurrence in the days of one month that pass the filters."""
    dim = _days_in_month(year, month)
    out: list[datetime] = []
    for d in _month_day_candidates(rule, dim, dtstart.day):
        # An out-of-range candidate is dropped, not clamped: BYMONTHDAY=29
        # simply has no occurrence in a non-leap February.
        if d < 1 or d > dim:
            continue
        day = _midnight(year, month, d)
        if not _matches_by_day_ordinal(rule, day):
            continue
        out.extend(_cross_time_of_day(rule, day, dtstart))
    return out


def _expand_minutely(rule: Rule, base: datetime, dtstart: datetime) -> list[datetime]:
    """One base minute, at BYSECOND of it, if the limits admit it.

    BYMONTH/BYMONTHDAY/BYDAY/BYHOUR/BYMINUTE limit; BYSECOND expand
    (RFC 5545 §3.3.10 table, MINUTELY column). A base that fails any
    limit yields nothing; one that passes emits one occurrence per
    BYSECOND entry — the base's own second when unset — on the base's
    date, hour and minute: the :func:`_expand_hourly` shape, one level
    finer.
    """
    if not (
        _matches_by_month(rule, base)
        and _matches_by_month_day(rule, base)
        and _matches_by_day(rule, base)
        and _matches_by_hour(rule, base)
        and _matches_by_minute(rule, base)
    ):
        return []
    return [
        _at(base.year, base.month, base.day, base.hour, base.minute, second)
        for second in _by_or_default(rule.by_second, base.second)
    ]


def _expand_hourly(rule: Rule, base: datetime, dtstart: datetime) -> list[datetime]:
    """One base hour, at BYMINUTE x BYSECOND of it, if the limits admit it.

    BYMONTH/BYMONTHDAY/BYDAY/BYHOUR limit; BYMINUTE x BYSECOND expand
    (RFC 5545 §3.3.10 table, HOURLY column). A base whose hour is not
    in BYHOUR yields nothing.
    """
    if not (
        _matches_by_month(rule, base)
        and _matches_by_month_day(rule, base)
        and _matches_by_day(rule, base)
        and _matches_by_hour(rule, base)
    ):
        return []
    return [
        _at(base.year, base.month, base.day, base.hour, minute, second)
        for minute in _by_or_default(rule.by_minute, base.minute)
        for second in _by_or_default(rule.by_second, dtstart.second)
    ]


def _expand_daily(rule: Rule, base: datetime, dtstart: datetime) -> list[datetime]:
    """One base day, with the time-of-day clauses crossed over it."""
    if not (
        _matches_by_month(rule, base)
        and _matches_by_month_day(rule, base)
        and _matches_by_day(rule, base)
    ):
        return []
    return _cross_time_of_day(rule, base, dtstart)


def _expand_weekly(rule: Rule, base: datetime, dtstart: datetime) -> list[datetime]:
    """One WKST-anchored week.

    With BYDAY, its seven days, filtered. Without it, only dtstart's own
    weekday — which is the base itself, since the weekly step preserves
    the weekday.
    """
    if not rule.by_day:
        if not (_matches_by_month(rule, base) and _matches_by_month_day(rule, base)):
            return []
        return _cross_time_of_day(rule, base, dtstart)

    week_start = _start_of_week(base, int(rule.week_start))
    out: list[datetime] = []
    for i in range(7):
        day = week_start + timedelta(days=i)
        if not (
            _matches_by_day(rule, day)
            and _matches_by_month(rule, day)
            and _matches_by_month_day(rule, day)
        ):
            continue
        out.extend(_cross_time_of_day(rule, day, dtstart))
    return out


def _expand_monthly(rule: Rule, base: datetime, dtstart: datetime) -> list[datetime]:
    """Every matching day of the base month."""
    if not _matches_by_month(rule, base):
        return []
    return _expand_month_days(rule, base.year, base.month, dtstart)


def _expand_yearly(rule: Rule, base: datetime, dtstart: datetime) -> list[datetime]:
    """A year, expanded by whichever clause governs it.

    BYYEARDAY picks days of the year, BYWEEKNO picks whole weeks, and
    otherwise the BYMONTH months — or dtstart's own month — expand as
    monthly ones.
    """
    year = base.year
    if rule.by_year_day:
        return _expand_by_year_day(rule, year, dtstart)
    if rule.by_week_no:
        return _expand_by_week_no(rule, year, dtstart)

    # The yearly step resets the base to January to dodge day overflow,
    # so the anchor month has to come from dtstart, not from the base.
    months = rule.by_month if rule.by_month else [dtstart.month]
    out: list[datetime] = []
    for month in months:
        if month < 1 or month > 12:
            continue
        out.extend(_expand_month_days(rule, year, month, dtstart))
    return out


def _expand_by_year_day(rule: Rule, year: int, dtstart: datetime) -> list[datetime]:
    """The BYYEARDAY days of a year, with BYMONTH and BYDAY narrowing them.

    Negative entries count back from year-end, and an entry the year does
    not have — day 366 of a non-leap year — is silently dropped per
    RFC 5545 §3.3.10.
    """
    total = _days_in_year(year)
    out: list[datetime] = []
    for yd in rule.by_year_day:
        doy = yd if yd > 0 else total + yd + 1
        if doy < 1 or doy > total:
            continue
        day = _day_of_year(year, doy)
        if not (_matches_by_month(rule, day) and _matches_by_day(rule, day)):
            continue
        out.extend(_cross_time_of_day(rule, day, dtstart))
    return out


def _expand_by_week_no(rule: Rule, year: int, dtstart: datetime) -> list[datetime]:
    """All seven days of each BYWEEKNO week, with BYMONTH and BYDAY narrowing.

    Negative entries count weeks from year-end, and a week the year does
    not have — 53 in a 52-week year — is dropped.
    """
    wkst = int(rule.week_start)
    total = _weeks_in_year(year, wkst)
    out: list[datetime] = []
    for wn in rule.by_week_no:
        n = wn if wn > 0 else total + wn + 1
        if n < 1 or n > total:
            continue
        week_start = _start_of_week_n(year, n, wkst)
        for i in range(7):
            day = week_start + timedelta(days=i)
            if not (_matches_by_month(rule, day) and _matches_by_day(rule, day)):
                continue
            out.extend(_cross_time_of_day(rule, day, dtstart))
    return out


def _expand(rule: Rule, base: datetime, dtstart: datetime) -> list[datetime]:
    """Expand one FREQ period into its concrete occurrences, unsorted."""
    match rule.freq:
        case Freq.MINUTELY:
            return _expand_minutely(rule, base, dtstart)
        case Freq.HOURLY:
            return _expand_hourly(rule, base, dtstart)
        case Freq.DAILY:
            return _expand_daily(rule, base, dtstart)
        case Freq.WEEKLY:
            return _expand_weekly(rule, base, dtstart)
        case Freq.MONTHLY:
            return _expand_monthly(rule, base, dtstart)
        case Freq.YEARLY:
            return _expand_yearly(rule, base, dtstart)
        case Freq.INVALID:
            return []


def _apply_by_set_pos(occs: list[datetime], set_pos: list[int]) -> list[datetime]:
    """Filter a sorted occurrence list to the 1-based positions BYSETPOS names.

    Positive entries index from the start, negative from the end (``-1``
    is the last). Out-of-range entries are dropped per RFC 5545
    §3.3.10, and the result is de-duplicated — two entries may resolve to
    the same occurrence — and left in chronological order.
    """
    if not occs:
        return []
    picked: set[int] = set()
    for p in set_pos:
        idx = p - 1 if p > 0 else len(occs) + p
        if 0 <= idx < len(occs):
            picked.add(idx)
    return [t for i, t in enumerate(occs) if i in picked]


def period_occurrences(rule: Rule, base: datetime, dtstart: datetime) -> list[datetime]:
    """One FREQ period, expanded, sorted, and positionally filtered.

    BYSETPOS is applied here, after every other BY-* clause and after the
    sort, because RFC 5545 §3.3.10 defines it as a filter over the fully
    expanded set of the period — ``-1`` means "the last of whatever the
    other clauses produced", so the ordering of these three steps is the
    semantics.
    """
    occs = sorted(_expand(rule, base, dtstart))
    return _apply_by_set_pos(occs, rule.by_set_pos) if rule.by_set_pos else occs
