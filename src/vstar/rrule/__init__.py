# SPDX-License-Identifier: MIT

"""RFC 5545 §3.3.10 recurrence: parsing, formatting, expansion, sets.

Validation, the fixed wire form, forward evaluation, bounded and lazy
expansion, recurrence sets, and RECURRENCE-ID.

The accepted scope is fixed by ``spec/v0.1/03-canonicalization.md``
§RRULE parsing scope: ``FREQ`` of ``MINUTELY``, ``HOURLY``, ``DAILY``,
``WEEKLY``, ``MONTHLY`` or ``YEARLY``, with ``INTERVAL``, ``UNTIL``
(UTC form #2 only), ``COUNT``, every ``BY-*`` clause, and ``WKST``.
``FREQ=SECONDLY`` and ``RSCALE`` parse as recognizable and are
reported :class:`~vstar.UnsupportedRrule`.

Parser scope equals evaluator scope: everything the parser accepts, the
evaluator evaluates.

All arithmetic is pure UTC :class:`~datetime.datetime` arithmetic.
**There is no IANA timezone database here and there must never be one**
— zone resolution against a document's own VTIMEZONE happens a layer
below, so every instant reaching this module is already absolute.

Usage::

    from vstar.rrule import occurrences, parse_rrule

    rule = parse_rrule("FREQ=WEEKLY;BYDAY=MO,WE;COUNT=4")
    times, complete = occurrences(rule, dtstart, 10)
"""

from __future__ import annotations

from ._evaluate import MAX_ITERATIONS

# `all` shadows the builtin by design: docs/dev/api-mapping.md fixes the
# name across all five ports (Go's `rrule.All`), and callers reach it as
# `rrule.all`, where the package qualifier disambiguates it exactly as
# the Go qualifier does. Renaming it here would diverge the Python port
# from the other four for a shadowing that never reaches a caller's
# namespace.
from ._expand import (
    all,  # noqa: A004
    between,
    next_occurrence,
    occurrences,
)
from ._parse import parse_rrule, validate_rrule
from ._rule import Rule
from ._set import (
    RecurrenceId,
    RuleSet,
    format_date_time_list,
    parse_date_time_list,
    parse_recurrence_id,
    rule_set_from_component,
)
from ._types import WEEKDAYS, ByDay, Freq, RecurrenceRange, Weekday

__all__ = [
    "MAX_ITERATIONS",
    "WEEKDAYS",
    "ByDay",
    "Freq",
    "RecurrenceId",
    "RecurrenceRange",
    "Rule",
    "RuleSet",
    "Weekday",
    "all",
    "between",
    "format_date_time_list",
    "next_occurrence",
    "occurrences",
    "parse_date_time_list",
    "parse_recurrence_id",
    "parse_rrule",
    "rule_set_from_component",
    "validate_rrule",
]
