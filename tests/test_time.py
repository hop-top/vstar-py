# SPDX-License-Identifier: MIT

"""RFC 5545 §3.3.5 DATE-TIME: form #2 on the wire, form #1 via VTIMEZONE.

``spec/behavior/time/tzid.json`` is the gate. A ``null`` ``utc`` column
means the Go reference returned not-ok — which is an absence, not a
failure class, so this port returns ``None`` and never raises.

No ``zoneinfo``, no ``pytz``, no ``dateutil.tz``, no IANA database of any
kind. A local time resolves only against the VTIMEZONE definitions inside
the document being processed, which is what makes a self-contained
calendar hash the same on every machine in every year. The fixtures name
a real IANA zone, and that is the trap: a port resolving it from the
system database passes those and fails every other zone.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import TypedDict

import pytest

from _fixtures import CONFORMANCE_DIR
from vstar import (
    Calendar,
    Component,
    CompType,
    Param,
    Property,
    format_time,
    parse_time,
    parse_time_with_tzid,
)
from vstar.codec import rfc5545

BEHAVIOR_DIR = Path(__file__).resolve().parents[2] / "spec" / "behavior"


class TzidCase(TypedDict):
    """One row of ``behavior/time/tzid.json``.

    Unlike the other behavior families this one carries no ``error``
    column: the reference reports a boolean, not a failure class, so a
    rejection is spelled ``utc: null`` and there is nothing to name.
    """

    #: The ``conformance/time/<name>.ics`` fixture supplying the registry.
    calendar: str
    #: The zone to resolve against. The empty string is a rejection case.
    tzid: str
    #: RFC 5545 form #1: local wall time, no ``Z``. The one family whose
    #: input is not form #2.
    value: str
    #: The resolved instant in form #2, or ``None`` for a rejection.
    utc: str | None


with (BEHAVIOR_DIR / "time" / "tzid.json").open(encoding="utf-8") as fh:
    TZID_CASES: list[TzidCase] = json.load(fh)

TZID_IDS = [f"{c['calendar']}/{c['tzid'] or 'empty'}/{c['value']}" for c in TZID_CASES]

_CALENDARS: dict[str, Calendar] = {}


def _calendar(name: str) -> Calendar:
    """The named ``conformance/time/<name>.ics`` fixture, parsed once."""
    if name not in _CALENDARS:
        _CALENDARS[name] = rfc5545.parse(
            (CONFORMANCE_DIR / "time" / f"{name}.ics").read_bytes()
        )
    return _CALENDARS[name]


def test_the_behavior_table_has_cases_to_walk() -> None:
    """An empty table would make every parametrized test below vacuous."""
    assert len(TZID_CASES) >= 10
    assert any(c["utc"] is None for c in TZID_CASES)
    assert any(c["utc"] is not None for c in TZID_CASES)


@pytest.mark.parametrize("case", TZID_CASES, ids=TZID_IDS)
def test_tzid_resolution_matches_the_behavior_table(case: TzidCase) -> None:
    """Each row of ``behavior/time/tzid.json``, resolved and compared."""
    cal = _calendar(case["calendar"])
    got = parse_time_with_tzid(case["value"], case["tzid"], cal)
    want = case["utc"]
    if want is None:
        assert got is None
        return
    assert got is not None
    assert format_time(got) == want


@pytest.mark.parametrize("case", TZID_CASES, ids=TZID_IDS)
def test_a_resolved_instant_is_timezone_aware(case: TzidCase) -> None:
    """Every datetime crossing the API boundary is aware.

    A naive value compares and arithmetics differently and Python will
    not stop you mixing them — it raises only on a naive/aware
    comparison, so a naive value travels a long way before it fails.
    """
    got = parse_time_with_tzid(case["value"], case["tzid"], _calendar(case["calendar"]))
    if got is not None:
        assert got.tzinfo is not None
        assert got.utcoffset() is not None


def test_resolution_uses_no_iana_database() -> None:
    """A zone the document does not define is unresolvable, name or not.

    ``America/New_York`` is a real IANA zone. A port reaching for the
    system database resolves it; this one must not, because the document
    carries no such VTIMEZONE.
    """
    cal = _calendar("america_montreal")
    assert parse_time_with_tzid("20260104T133045", "America/New_York", cal) is None


#: Timezone-database modules no V* implementation may reach for.
FORBIDDEN_TZ_MODULES = frozenset({"zoneinfo", "pytz", "dateutil"})


def _imported_modules(source: str) -> set[str]:
    """Every top-level module name ``source`` imports, from its AST.

    Parsing rather than substring-matching is the point: the module
    docstrings *name* the forbidden modules in order to say they are not
    used, and a text scan cannot tell a prohibition from a dependency.
    """
    import ast

    out: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            out.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            out.add(node.module.split(".")[0])
    return out


def test_no_module_imports_a_timezone_database() -> None:
    """The forbidden modules are absent from the package's import graph.

    A stricter statement than "the fixtures pass": a port can consult
    tzdata for one zone and the document for another, and the corpus
    would not notice. Every ``vstar`` module's imports are read from its
    own AST, so a lazy import inside a function is caught too.
    """
    import sys

    checked = 0
    for module in list(sys.modules.values()):
        name = getattr(module, "__name__", "")
        source_path = getattr(module, "__file__", None)
        if not name.startswith("vstar") or source_path is None:
            continue
        checked += 1
        imported = _imported_modules(Path(source_path).read_text(encoding="utf-8"))
        offending = imported & FORBIDDEN_TZ_MODULES
        assert not offending, f"{name} imports {sorted(offending)}"
    assert checked >= 5, "no vstar modules were inspected"


# --- format_time / parse_time ----------------------------------------


def test_format_time_emits_form_two() -> None:
    """``YYYYMMDDTHHMMSSZ``, always UTC, always second resolution."""
    t = datetime(2026, 5, 4, 18, 30, 45, tzinfo=UTC)
    assert format_time(t) == "20260504T183045Z"


def test_format_time_converts_a_non_utc_aware_value() -> None:
    """An offset-bearing input produces the same wire output as its UTC form."""
    east = timezone(timedelta(hours=-5))
    t = datetime(2026, 5, 4, 13, 30, 45, tzinfo=east)
    assert format_time(t) == "20260504T183045Z"


def test_format_time_truncates_sub_second_precision() -> None:
    """Form #2 has second resolution; microseconds have no wire form."""
    t = datetime(2026, 5, 4, 18, 30, 45, 999999, tzinfo=UTC)
    assert format_time(t) == "20260504T183045Z"


def test_format_time_of_none_is_the_empty_string() -> None:
    """Absence is ``None``, and it renders as "clear the property"."""
    assert format_time(None) == ""


def test_format_time_rejects_a_naive_datetime() -> None:
    """Reject naive input at the boundary, per the port's time contract."""
    with pytest.raises(ValueError, match="aware"):
        format_time(datetime(2026, 5, 4, 18, 30, 45))


def test_parse_time_accepts_form_two() -> None:
    """The one accepted wire shape, returned as an aware UTC datetime."""
    got = parse_time("20260504T183045Z")
    assert got == datetime(2026, 5, 4, 18, 30, 45, tzinfo=UTC)
    assert got is not None
    assert got.tzinfo is UTC


def test_parse_time_round_trips_the_epoch() -> None:
    """1970-01-01T00:00:00Z is a representable instant, not "absent".

    An in-band sentinel — epoch zero meaning "no instant" — makes this
    value unrepresentable. Absence is ``None``.
    """
    got = parse_time("19700101T000000Z")
    assert got is not None
    assert format_time(got) == "19700101T000000Z"


@pytest.mark.parametrize(
    "value",
    [
        "20260504T183045",  # form #1: no zone
        "2026-05-04T18:30:45Z",  # RFC 3339 extended
        "20260504",  # date-only
        "20260504T183045z",  # lowercase suffix
        "",
        " 20260504T183045Z",
        "20260504T183045Z ",
        "20260504T183045ZZ",
        "20260230T000000Z",  # February 30th does not roll into March
        "20261301T000000Z",  # month 13
        "20260504T253045Z",  # hour 25
    ],
)
def test_parse_time_rejects_everything_else(value: str) -> None:
    """Strict by design: a V* reader sees torn data, never a coercion."""
    assert parse_time(value) is None


# --- parse_time_with_tzid: the VTIMEZONE subset -----------------------


def _tz(*children: Component, tzid: str = "Test/Zone") -> Calendar:
    """A calendar carrying one VTIMEZONE built from ``children``."""
    return Calendar(
        prod_id="x",
        components=[
            Component(
                type=CompType.TIMEZONE,
                props=[Property("TZID", [], tzid)],
                sub=list(children),
            )
        ],
    )


def _child(
    kind: str,
    *,
    offset_to: str,
    offset_from: str,
    dtstart: str = "19700101T000000",
    rrule: str | None = None,
    tzname: str | None = None,
) -> Component:
    """One STANDARD or DAYLIGHT child with the named fields."""
    props = [
        Property("DTSTART", [], dtstart),
        Property("TZOFFSETFROM", [], offset_from),
        Property("TZOFFSETTO", [], offset_to),
    ]
    if tzname is not None:
        props.append(Property("TZNAME", [], tzname))
    if rrule is not None:
        props.append(Property("RRULE", [], rrule))
    return Component(type=CompType(kind), props=props)


def test_subset_accepts_a_single_standard_fixed_offset() -> None:
    """Accepted shape 1: a STANDARD alone, with no RRULE."""
    cal = _tz(_child("STANDARD", offset_to="-0500", offset_from="-0500"))
    got = parse_time_with_tzid("20260104T133045", "Test/Zone", cal)
    assert got is not None
    assert format_time(got) == "20260104T183045Z"


def test_subset_accepts_a_daylight_only_zone_as_a_fixed_offset() -> None:
    """Accepted shape 3: a DAYLIGHT alone; there is no transition to compute."""
    cal = _tz(_child("DAYLIGHT", offset_to="-0400", offset_from="-0400"))
    got = parse_time_with_tzid("20260104T133045", "Test/Zone", cal)
    assert got is not None
    assert format_time(got) == "20260104T173045Z"


def test_subset_accepts_a_seconds_bearing_offset() -> None:
    """``±HHMMSS`` is a legal offset shape, not only ``±HHMM``."""
    cal = _tz(_child("STANDARD", offset_to="+000030", offset_from="+000030"))
    got = parse_time_with_tzid("20260104T000100", "Test/Zone", cal)
    assert got is not None
    assert format_time(got) == "20260104T000030Z"


def test_subset_rejects_multiple_standard_children() -> None:
    """Split-zone histories are outside the spec's VTIMEZONE subset."""
    cal = _tz(
        _child("STANDARD", offset_to="-0500", offset_from="-0500"),
        _child("STANDARD", offset_to="-0600", offset_from="-0600"),
    )
    assert parse_time_with_tzid("20260104T133045", "Test/Zone", cal) is None


def test_subset_rejects_a_vtimezone_with_no_children() -> None:
    """There is nothing to reconstruct an offset from."""
    assert parse_time_with_tzid("20260104T133045", "Test/Zone", _tz()) is None


def test_subset_rejects_a_child_missing_tzoffsetto() -> None:
    """The offset the resolution applies has no substitute."""
    child = Component(
        type=CompType("STANDARD"),
        props=[
            Property("DTSTART", [], "19700101T000000"),
            Property("TZOFFSETFROM", [], "-0500"),
        ],
    )
    assert parse_time_with_tzid("20260104T133045", "Test/Zone", _tz(child)) is None


def test_subset_rejects_a_child_missing_tzoffsetfrom() -> None:
    """The subset requires it present and well-formed, unused or not."""
    child = Component(
        type=CompType("STANDARD"),
        props=[
            Property("DTSTART", [], "19700101T000000"),
            Property("TZOFFSETTO", [], "-0500"),
        ],
    )
    assert parse_time_with_tzid("20260104T133045", "Test/Zone", _tz(child)) is None


def test_subset_rejects_a_child_missing_dtstart() -> None:
    """DTSTART carries the transition's wall-clock time of day."""
    child = Component(
        type=CompType("STANDARD"),
        props=[
            Property("TZOFFSETFROM", [], "-0500"),
            Property("TZOFFSETTO", [], "-0500"),
        ],
    )
    assert parse_time_with_tzid("20260104T133045", "Test/Zone", _tz(child)) is None


def test_subset_rejects_a_malformed_offset() -> None:
    """``-05:00`` is not the wire shape; guessing would be silent corruption."""
    cal = _tz(_child("STANDARD", offset_to="-05:00", offset_from="-0500"))
    assert parse_time_with_tzid("20260104T133045", "Test/Zone", cal) is None


def _dst_pair(std_rrule: str, dst_rrule: str) -> Calendar:
    """A STANDARD + DAYLIGHT pair carrying the named rules."""
    return _tz(
        _child(
            "STANDARD",
            offset_to="-0500",
            offset_from="-0400",
            dtstart="20071104T020000",
            rrule=std_rrule,
        ),
        _child(
            "DAYLIGHT",
            offset_to="-0400",
            offset_from="-0500",
            dtstart="20070311T020000",
            rrule=dst_rrule,
        ),
    )


def test_subset_accepts_a_yearly_pair_with_bymonth_and_ordinal_byday() -> None:
    """Accepted shape 2, which covers every IANA zone with active DST."""
    cal = _dst_pair(
        "FREQ=YEARLY;BYMONTH=11;BYDAY=1SU", "FREQ=YEARLY;BYMONTH=3;BYDAY=2SU"
    )
    summer = parse_time_with_tzid("20260704T133045", "Test/Zone", cal)
    winter = parse_time_with_tzid("20260104T133045", "Test/Zone", cal)
    assert summer is not None and winter is not None
    assert format_time(summer) == "20260704T173045Z"
    assert format_time(winter) == "20260104T183045Z"


def test_subset_accepts_a_no_op_interval_of_one() -> None:
    """``INTERVAL=1`` is the RFC default spelled out; it changes nothing."""
    cal = _dst_pair(
        "FREQ=YEARLY;INTERVAL=1;BYMONTH=11;BYDAY=1SU",
        "FREQ=YEARLY;INTERVAL=1;BYMONTH=3;BYDAY=2SU",
    )
    assert parse_time_with_tzid("20260704T133045", "Test/Zone", cal) is not None


@pytest.mark.parametrize(
    "rrule",
    [
        "FREQ=MONTHLY;BYMONTH=3;BYDAY=2SU",  # not yearly
        "FREQ=YEARLY;BYMONTH=3;BYDAY=2SU;COUNT=10",
        "FREQ=YEARLY;BYMONTH=3;BYDAY=2SU;UNTIL=20300101T000000Z",
        "FREQ=YEARLY;BYMONTH=3;BYWEEKNO=11",
        "FREQ=YEARLY;BYMONTH=3;BYDAY=2SU;BYSETPOS=1",
        "FREQ=YEARLY;BYMONTH=3;BYDAY=SU",  # no ordinal
        "FREQ=YEARLY;BYMONTH=3;BYDAY=0SU",  # zero ordinal
        "FREQ=YEARLY;INTERVAL=2;BYMONTH=3;BYDAY=2SU",
        "FREQ=YEARLY;BYMONTH=13;BYDAY=2SU",
        "FREQ=YEARLY;BYMONTH=3;BYDAY=2SU;WKST=MO",
        "BYMONTH=3;BYDAY=2SU",  # no FREQ
        "FREQ=YEARLY;NOTAKEY=1",
        "FREQ=YEARLY;BYMONTH",  # no "="
    ],
)
def test_subset_rejects_an_rrule_outside_the_v01_shape(rrule: str) -> None:
    """Fail closed: a partial rule produces a plausible instant that is wrong."""
    cal = _dst_pair("FREQ=YEARLY;BYMONTH=11;BYDAY=1SU", rrule)
    assert parse_time_with_tzid("20260704T133045", "Test/Zone", cal) is None


def test_subset_rejects_a_pair_where_only_one_child_carries_a_rule() -> None:
    """With both children present the subset requires a yearly rule on each."""
    cal = _tz(
        _child(
            "STANDARD",
            offset_to="-0500",
            offset_from="-0400",
            dtstart="20071104T020000",
        ),
        _child(
            "DAYLIGHT",
            offset_to="-0400",
            offset_from="-0500",
            dtstart="20070311T020000",
            rrule="FREQ=YEARLY;BYMONTH=3;BYDAY=2SU",
        ),
    )
    assert parse_time_with_tzid("20260704T133045", "Test/Zone", cal) is None


def test_tzid_comparison_is_case_sensitive() -> None:
    """TZIDs are opaque identifiers per RFC 5545 §3.2.19."""
    cal = _tz(_child("STANDARD", offset_to="+0000", offset_from="+0000"))
    assert parse_time_with_tzid("20260104T133045", "test/zone", cal) is None


def test_a_negative_byday_ordinal_selects_from_the_end_of_the_month() -> None:
    """``-1SU`` is the last Sunday; the EU transition rule uses it."""
    cal = _tz(
        _child(
            "STANDARD",
            offset_to="+0100",
            offset_from="+0200",
            dtstart="20071028T030000",
            rrule="FREQ=YEARLY;BYMONTH=10;BYDAY=-1SU",
        ),
        _child(
            "DAYLIGHT",
            offset_to="+0200",
            offset_from="+0100",
            dtstart="20070325T020000",
            rrule="FREQ=YEARLY;BYMONTH=3;BYDAY=-1SU",
        ),
    )
    # 2026-03-29 is the last Sunday of March; the 30th is inside DST.
    inside = parse_time_with_tzid("20260330T120000", "Test/Zone", cal)
    outside = parse_time_with_tzid("20260320T120000", "Test/Zone", cal)
    assert inside is not None and outside is not None
    assert format_time(inside) == "20260330T100000Z"
    assert format_time(outside) == "20260320T110000Z"


# --- Component datetime accessors ------------------------------------


def _event(*props: Property) -> Component:
    """A VEVENT carrying ``props``."""
    return Component(type=CompType.EVENT, props=[Property("UID", [], "u1"), *props])


def test_dtstart_reads_a_utc_value_without_touching_the_calendar() -> None:
    """A form #2 value needs no registry."""
    c = _event(Property("DTSTART", [], "20260504T183045Z"))
    assert c.dtstart(Calendar()) == datetime(2026, 5, 4, 18, 30, 45, tzinfo=UTC)


def test_dtstart_resolves_a_tzid_value_against_the_calendar() -> None:
    """The calendar argument is not optional plumbing."""
    cal = _calendar("america_montreal")
    c = _event(
        Property("DTSTART", [Param("TZID", "America/Montreal")], "20260104T133045")
    )
    got = c.dtstart(cal)
    assert got is not None
    assert format_time(got) == "20260104T183045Z"


def test_dtstart_refuses_a_value_date_property() -> None:
    """A calendar date is not an instant; read it with ``dtstart_date``."""
    from vstar import VDate

    c = _event(Property("DTSTART", [Param("VALUE", "DATE")], "20260515"))
    assert c.dtstart(Calendar()) is None
    assert c.dtstart_date() == VDate(2026, 5, 15)


def test_dtstamp_takes_no_calendar_and_refuses_a_tzid() -> None:
    """RFC 5545 §3.8.7.2 requires DTSTAMP to be UTC; a TZID is a producer bug."""
    plain = _event(Property("DTSTAMP", [], "20260504T183045Z"))
    assert plain.dtstamp() == datetime(2026, 5, 4, 18, 30, 45, tzinfo=UTC)
    tagged = _event(
        Property("DTSTAMP", [Param("TZID", "America/Montreal")], "20260504T183045")
    )
    assert tagged.dtstamp() is None


@pytest.mark.parametrize("name", ["DTEND", "DUE", "COMPLETED"])
def test_the_other_datetime_accessors_read_their_property(name: str) -> None:
    """``dtend``, ``due`` and ``completed`` share DTSTART's semantics."""
    c = _event(Property(name, [], "20260504T183045Z"))
    got = getattr(c, name.lower())(Calendar())
    assert got == datetime(2026, 5, 4, 18, 30, 45, tzinfo=UTC)


def test_an_absent_datetime_property_reads_as_none() -> None:
    """Absence is an optional, not a failure."""
    c = _event()
    assert c.dtstart(Calendar()) is None
    assert c.dtstamp() is None


def test_set_dtstart_writes_form_two_with_no_parameters() -> None:
    """A stale TZID or VALUE=DATE would contradict the value it now carries."""
    c = _event(
        Property("DTSTART", [Param("TZID", "America/Montreal")], "20260104T133045")
    )
    c.set_dtstart(datetime(2026, 5, 4, 18, 30, 45, tzinfo=UTC))
    p = c.get("DTSTART")
    assert p is not None
    assert p.value == "20260504T183045Z"
    assert p.params == []


def test_set_dtstart_with_none_removes_the_property() -> None:
    """``None`` is how the writers spell "clear the property"."""
    c = _event(Property("DTSTART", [], "20260504T183045Z"))
    c.set_dtstart(None)
    assert c.get("DTSTART") is None


def test_set_dtstart_rejects_a_naive_datetime() -> None:
    """Naive input is refused at the boundary, not silently assumed UTC."""
    c = _event()
    with pytest.raises(ValueError, match="aware"):
        c.set_dtstart(datetime(2026, 5, 4, 18, 30, 45))


@pytest.mark.parametrize("name", ["DTEND", "DUE", "COMPLETED"])
def test_the_other_datetime_writers_write_their_property(name: str) -> None:
    """``set_dtend``, ``set_due`` and ``set_completed`` mirror ``set_dtstart``."""
    c = _event()
    getattr(c, f"set_{name.lower()}")(datetime(2026, 5, 4, 18, 30, 45, tzinfo=UTC))
    p = c.get(name)
    assert p is not None
    assert p.value == "20260504T183045Z"
