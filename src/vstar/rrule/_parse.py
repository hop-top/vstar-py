# SPDX-License-Identifier: MIT

"""RFC 5545 §3.3.10 RRULE value parsing, for the scope spec/03 fixes.

Two failure classes, and the ``rrule/rejected/`` fixtures distinguish
them:

- :class:`~vstar.Malformed` — syntactically wrong: unknown rule-part,
  missing FREQ, a zero ordinal, INTERVAL below 1, UNTIL and COUNT
  together, UNTIL outside form #2, a value out of its RFC range.
- :class:`~vstar.UnsupportedRrule` — syntactically fine but deferred by
  this scope: ``FREQ=SECONDLY``, ``RSCALE``.

Getting the two the wrong way round passes "it failed" and fails the
corpus, which asserts *which* failure.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import NoReturn

from ..errors import Malformed, UnsupportedRrule
from ..time import parse_time
from ._rule import Rule
from ._types import ByDay, Freq, Weekday

__all__ = ["parse_rrule", "validate_rrule"]

#: A base-10 integer, strictly spelled. Python's ``int()`` is
#: deliberately not trusted alone: it accepts ``"1_000"``, surrounding
#: whitespace and a unicode-digit spelling, each of which would turn a
#: malformed rule-part into a plausible value.
_INT_RE = re.compile(r"\A[+-]?[0-9]+\Z")

#: The RFC 5545 §3.3.10 ordinal bound shared by BYDAY prefixes.
_BYDAY_ORDINAL_MAX = 53

#: The largest BYSETPOS / BYYEARDAY magnitude: a leap year's day count.
_YEAR_DAYS_MAX = 366


def _malformed(message: str) -> NoReturn:
    """Raise :class:`~vstar.Malformed` with the given explanation."""
    raise Malformed(f"rrule: {message}")


def _unsupported(message: str) -> NoReturn:
    """Raise :class:`~vstar.UnsupportedRrule` with the given explanation."""
    raise UnsupportedRrule(f"rrule: {message}")


def parse_rrule(s: str) -> Rule:
    """Parse an RRULE property value — no ``RRULE:`` prefix — into a rule.

    The RFC defaults are applied (``INTERVAL=1``, ``WKST=MO``) and every
    cross-field invariant is enforced. Rule-part order is irrelevant.

    Keys and values are matched case-sensitively in their RFC wire
    spelling, matching the strict posture :func:`~vstar.parse_time`
    takes: a V* reader sees torn data rather than a silent coercion.

    Raises :class:`~vstar.Malformed` for a syntactic failure and
    :class:`~vstar.UnsupportedRrule` for a feature this scope defers —
    the two are different answers and the corpus asserts which.
    """
    if s == "":
        _malformed("empty input")

    fields: dict[str, object] = {}
    seen: set[str] = set()

    for part in s.split(";"):
        key, sep, value = part.partition("=")
        # An empty key (``=DAILY``) is as malformed as a missing separator.
        if not sep or key == "":
            _malformed(f"malformed rule-part {part!r}")
        if key in seen:
            _malformed(f"duplicate rule-part {key!r}")
        seen.add(key)
        name, parsed = _parse_rule_part(key, value)
        fields[name] = parsed

    rule = Rule(**fields)  # type: ignore[arg-type]
    _validate_after_parse(rule)
    return rule


def validate_rrule(s: str) -> None:
    """Check that ``s`` would parse cleanly, discarding the result.

    Returns nothing and raises exactly what :func:`parse_rrule` would.
    Deliberately not a boolean: the *identity* of the failure is the
    payload, and the ``rrule/rejected/`` fixtures assert it.
    """
    parse_rrule(s)


def _parse_rule_part(key: str, value: str) -> tuple[str, object]:
    """Decode one ``KEY=VALUE`` pair into a :class:`Rule` field entry."""
    match key:
        case "FREQ":
            return "freq", _parse_freq(value)
        case "INTERVAL":
            return "interval", _parse_bounded_int("INTERVAL", value, 1)
        case "UNTIL":
            return "until", _parse_until(value)
        case "COUNT":
            return "count", _parse_bounded_int("COUNT", value, 1)
        case "BYDAY":
            return "by_day", _parse_by_day_list(value)
        case "BYMONTH":
            return "by_month", _parse_int_list("BYMONTH", value, 1, 12)
        case "BYMONTHDAY":
            return "by_month_day", _parse_signed_int_list("BYMONTHDAY", value, 1, 31)
        case "BYHOUR":
            return "by_hour", _parse_int_list("BYHOUR", value, 0, 23)
        case "BYMINUTE":
            return "by_minute", _parse_int_list("BYMINUTE", value, 0, 59)
        case "BYSECOND":
            # 60 is retained for leap seconds per RFC 5545 §3.3.10.
            return "by_second", _parse_int_list("BYSECOND", value, 0, 60)
        case "BYYEARDAY":
            return "by_year_day", _parse_signed_int_list(
                "BYYEARDAY", value, 1, _YEAR_DAYS_MAX
            )
        case "BYWEEKNO":
            return "by_week_no", _parse_signed_int_list("BYWEEKNO", value, 1, 53)
        case "BYSETPOS":
            return "by_set_pos", _parse_signed_int_list(
                "BYSETPOS", value, 1, _YEAR_DAYS_MAX
            )
        case "WKST":
            return "week_start", _parse_weekday(value)
        case "RSCALE":
            # RFC 7529, non-Gregorian calendars — deferred indefinitely.
            _unsupported(f"rule-part {key}: outside the RRULE parsing scope")
        case _:
            _malformed(f"unknown rule-part {key!r}")


def _parse_freq(v: str) -> Freq:
    """The ``FREQ`` token, rejecting the one deferred frequency by name."""
    match v:
        case "MINUTELY" | "HOURLY" | "DAILY" | "WEEKLY" | "MONTHLY" | "YEARLY":
            return Freq(v)
        case "SECONDLY":
            # Syntactically valid, deliberately deferred: extreme expansion.
            _unsupported(f"FREQ={v}: outside the RRULE parsing scope")
        case _:
            _malformed(f"invalid FREQ value {v!r}")


def _parse_until(v: str) -> datetime:
    """The ``UNTIL`` instant, form #2 (UTC, ``Z``-suffixed) only.

    Form #1 (local) and form #3 (with TZID) are malformed: V*'s
    strict-UTC posture for RRULE bounds carries the VTIMEZONE subset's
    UTC-only stance forward.
    """
    t = parse_time(v)
    if t is None:
        _malformed(f"UNTIL must be RFC 5545 form #2 (UTC, Z-suffixed), got {v!r}")
    return t


def _strict_int(name: str, raw: str) -> int:
    """A base-10 integer, strictly spelled."""
    if _INT_RE.match(raw) is None:
        _malformed(f"{name} non-integer {raw!r}")
    return int(raw)


def _parse_bounded_int(name: str, v: str, lo: int) -> int:
    """A single integer of at least ``lo``."""
    n = _strict_int(name, v)
    if n < lo:
        _malformed(f"{name} must be >= {lo}, got {n}")
    return n


def _parse_int_list(name: str, v: str, lo: int, hi: int) -> list[int]:
    """A comma-separated list of integers, each in ``[lo, hi]``.

    Authored order is preserved: RFC 5545 gives BY-* lists no ordering
    semantics, so sorting here would rewrite the producer's content
    before the emitter ever sees it.
    """
    if v == "":
        _malformed(f"{name} empty")
    out: list[int] = []
    for raw in v.split(","):
        n = _strict_int(name, raw)
        if n < lo or n > hi:
            _malformed(f"{name} {n} out of range {lo}..{hi}")
        out.append(n)
    return out


def _parse_signed_int_list(name: str, v: str, lo: int, hi: int) -> list[int]:
    """A list of signed integers where each ``n`` has ``lo <= |n| <= hi``.

    The two-sided range is RFC 5545 §3.3.10's "from the start (positive)
    or from the end (negative)" pattern, shared by BYMONTHDAY,
    BYYEARDAY, BYWEEKNO and BYSETPOS. Zero is rejected for all four: it
    would name neither end. Authored order is preserved.
    """
    if v == "":
        _malformed(f"{name} empty")
    out: list[int] = []
    for raw in v.split(","):
        n = _strict_int(name, raw)
        if n == 0:
            _malformed(f"{name} 0 invalid (RFC 5545 §3.3.10)")
        if not lo <= abs(n) <= hi:
            _malformed(f"{name} {n} out of range -{hi}..-{lo} or {lo}..{hi}")
        out.append(n)
    return out


def _parse_by_day_list(v: str) -> list[ByDay]:
    """A ``BYDAY`` list, authored order kept."""
    if v == "":
        _malformed("BYDAY empty")
    return [_parse_by_day_entry(entry) for entry in v.split(",")]


def _parse_by_day_entry(s: str) -> ByDay:
    """One ``BYDAY`` entry. The weekday is the final two characters."""
    if len(s) < 2:
        _malformed(f"BYDAY entry {s!r} too short")
    weekday = _parse_weekday(s[-2:])
    prefix = s[:-2]
    if prefix == "":
        return ByDay(0, weekday)
    n = _strict_int("BYDAY ordinal", prefix)
    # The explicit "0" prefix is invalid per RFC 5545 §3.3.10 — "every
    # weekday of this kind" is spelled by omitting the ordinal.
    if n == 0:
        _malformed("BYDAY ordinal 0 invalid (RFC 5545 §3.3.10)")
    if not -_BYDAY_ORDINAL_MAX <= n <= _BYDAY_ORDINAL_MAX:
        _malformed(
            f"BYDAY ordinal {n} out of range "
            f"-{_BYDAY_ORDINAL_MAX}..{_BYDAY_ORDINAL_MAX}"
        )
    return ByDay(n, weekday)


def _parse_weekday(s: str) -> Weekday:
    """A two-letter weekday symbol, case-sensitively."""
    try:
        return Weekday[s]
    except KeyError:
        _malformed(f"invalid weekday {s!r}")


def _validate_after_parse(rule: Rule) -> None:
    """The cross-field invariants, run once every rule-part is consumed.

    Rule-part order is irrelevant per RFC, so none of these can be
    checked while parsing.
    """
    if rule.freq is Freq.INVALID:
        _malformed("FREQ is required")
    if rule.until is not None and rule.count > 0:
        _malformed("UNTIL and COUNT are mutually exclusive")
    if rule.by_year_day and rule.freq is not Freq.YEARLY:
        _malformed(
            f"BYYEARDAY requires FREQ=YEARLY (RFC 5545 §3.3.10), got FREQ={rule.freq}"
        )
    if rule.by_week_no and rule.freq is not Freq.YEARLY:
        _malformed(
            f"BYWEEKNO requires FREQ=YEARLY (RFC 5545 §3.3.10), got FREQ={rule.freq}"
        )
    if rule.by_set_pos and not _has_other_by(rule):
        _malformed(
            "BYSETPOS requires at least one other BY-* rule-part (RFC 5545 §3.3.10)"
        )


def _has_other_by(rule: Rule) -> bool:
    """Whether any BY-* clause other than BYSETPOS is present.

    The precondition RFC 5545 §3.3.10 puts on BYSETPOS: it "MUST only be
    used in conjunction with another BYxxx rule part".
    """
    return bool(
        rule.by_day
        or rule.by_month
        or rule.by_month_day
        or rule.by_hour
        or rule.by_minute
        or rule.by_second
        or rule.by_year_day
        or rule.by_week_no
    )
