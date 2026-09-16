# SPDX-License-Identifier: MIT

"""RFC 5545 §3.3.6 DURATION and the §3.8.6.3 TRIGGER property.

``spec/behavior/duration/parse.json`` and the ``*.trigger.json`` sidecars
are the gates. Two columns in ``parse.json`` are easy to misread:

- ``negative`` is ``is_negative()`` — the *normalized* predicate — not
  the struct's sign flag. ``-PT0S`` is ``negative: false``, because a
  zero-length duration is never subtractive however it was authored.
- ``seconds`` is the nominal signed second count, which is what
  ``signed()`` reports. It cannot express the sign of a zero-length
  value, which is why ``negative`` is carried separately.

``day_form`` is the third thing a port drops: ``P0D`` and ``PT0S`` are
numerically identical and every unit field is zero in both, so without
the flag ``str()`` cannot reproduce the authored spelling — and rule 12
preserves DURATION values verbatim.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TypedDict

import pytest

from _fixtures import CONFORMANCE_DIR
from vstar import (
    Calendar,
    Component,
    CompType,
    Malformed,
    NoAnchor,
    NoTrigger,
    Param,
    Property,
    VstarError,
    format_time,
)
from vstar.codec import rfc5545
from vstar.duration import (
    Related,
    Trigger,
    VDuration,
    alarm_repeat_cycle,
    alarm_trigger,
    event_end,
    from_signed,
    parse,
    parse_trigger,
    valid,
)

BEHAVIOR_DIR = Path(__file__).resolve().parents[2] / "spec" / "behavior" / "duration"


class ParseCase(TypedDict, total=False):
    """One row of ``behavior/duration/parse.json``.

    ``error`` replaces both result columns on a malformed value, per the
    behavior-fixture convention, so every field but ``value`` is
    optional.
    """

    #: The DURATION wire value under test. Always present.
    value: str
    #: The whole duration as a signed second count — what ``signed()``
    #: reports. Absent when ``error`` is present.
    seconds: int
    #: ``is_negative()`` — the NORMALIZED predicate, not the raw sign
    #: flag. ``-PT0S`` is ``False`` here.
    negative: bool
    #: The failure class, when parsing must fail.
    error: str


with (BEHAVIOR_DIR / "parse.json").open(encoding="utf-8") as fh:
    PARSE_CASES: list[ParseCase] = json.load(fh)

PARSE_IDS = [c["value"] or "<empty>" for c in PARSE_CASES]

TRIGGER_FILES = sorted(BEHAVIOR_DIR.glob("*.trigger.json"))


def test_the_parse_table_has_cases_to_walk() -> None:
    """An empty table would make every parametrized test below vacuous."""
    assert len(PARSE_CASES) >= 20
    assert any("error" in c for c in PARSE_CASES)
    assert any("seconds" in c for c in PARSE_CASES)


@pytest.mark.parametrize("case", PARSE_CASES, ids=PARSE_IDS)
def test_parse_matches_the_behavior_table(case: ParseCase) -> None:
    """Each row of ``behavior/duration/parse.json``, parsed and compared."""
    if "error" in case:
        assert case["error"] == "ErrMalformed"
        with pytest.raises(Malformed) as excinfo:
            parse(case["value"])
        assert excinfo.value.sentinel == "ErrMalformed"
        return
    d = parse(case["value"])
    assert d.signed() == timedelta(seconds=case["seconds"])
    assert d.is_negative() is case["negative"]


@pytest.mark.parametrize("case", PARSE_CASES, ids=PARSE_IDS)
def test_valid_agrees_with_parse(case: ParseCase) -> None:
    """``valid`` is ``parse`` with the result discarded, and nothing else."""
    assert valid(case["value"]) is ("error" not in case)


def test_the_negative_column_is_the_normalized_predicate() -> None:
    """``-PT0S`` carries the sign flag but is not negative.

    Reading the column as the struct's flag rather than the predicate
    inverts this one row and nothing else — which is exactly the kind of
    near-miss the table exists to catch.
    """
    d = parse("-PT0S")
    assert d.negative is True
    assert d.is_negative() is False
    assert d.signed() == timedelta(0)


@pytest.mark.parametrize(
    "value",
    [
        "P1W",
        "P26W",
        "P7D",
        "PT1H",
        "PT15M",
        "PT30S",
        "P1DT2H30M45S",
        "PT1H30M",
        "-PT15M",
        "P0D",
        "PT0S",
    ],
)
def test_parse_and_str_round_trip_byte_for_byte(value: str) -> None:
    """The authored units survive; nothing is collapsed to a second count."""
    assert str(parse(value)) == value


def test_an_explicit_plus_sign_is_the_one_normalization() -> None:
    """A positive duration is the default, so ``+`` is dropped on emit."""
    assert str(parse("+PT15M")) == "PT15M"


def test_day_form_distinguishes_p0d_from_pt0s() -> None:
    """Both are numerically zero; the flag is what reproduces the spelling."""
    p0d = parse("P0D")
    pt0s = parse("PT0S")
    assert p0d.day_form is True
    assert pt0s.day_form is False
    assert str(p0d) == "P0D"
    assert str(pt0s) == "PT0S"
    assert p0d.signed() == pt0s.signed() == timedelta(0)


def test_day_form_affects_formatting_only() -> None:
    """``signed``, ``is_negative`` and ``add_to`` ignore the flag."""
    anchor = datetime(2026, 5, 4, tzinfo=UTC)
    p0d = parse("P0D")
    pt0s = parse("PT0S")
    assert p0d.signed() == pt0s.signed()
    assert p0d.is_negative() == pt0s.is_negative()
    assert p0d.add_to(anchor) == pt0s.add_to(anchor)


def test_the_zero_duration_formats_as_pt0s_not_a_bare_p() -> None:
    """``P`` alone is rejected by ``parse``, so it cannot be an output."""
    assert str(VDuration()) == "PT0S"
    assert valid(str(VDuration()))


def test_signed_treats_days_as_24_hours_and_weeks_as_7_days() -> None:
    """The nominal view: exact for time-only values and in a fixed-offset zone."""
    assert parse("P1D").signed() == timedelta(hours=24)
    assert parse("P1W").signed() == timedelta(days=7)


def test_add_to_advances_calendar_days_rather_than_elapsed_hours() -> None:
    """The distinction the authored-unit design exists to preserve.

    In UTC the two agree; the API contract is that ``add_to`` moves the
    calendar and ``signed`` reports nominal length, so a caller doing
    wall-clock arithmetic in a DST zone reaches for the former.
    """
    anchor = datetime(2026, 3, 7, 12, 0, 0, tzinfo=UTC)
    assert parse("P1D").add_to(anchor) == datetime(2026, 3, 8, 12, 0, 0, tzinfo=UTC)
    assert parse("PT24H").add_to(anchor) == datetime(2026, 3, 8, 12, 0, 0, tzinfo=UTC)


def test_add_to_subtracts_for_a_negative_duration() -> None:
    """The sign applies to the whole value, calendar and clock parts alike."""
    anchor = datetime(2026, 5, 4, 12, 0, 0, tzinfo=UTC)
    assert parse("-P1DT2H").add_to(anchor) == datetime(2026, 5, 3, 10, 0, 0, tzinfo=UTC)


def test_add_to_rejects_a_naive_anchor() -> None:
    """Aware datetimes only, at every boundary."""
    with pytest.raises(ValueError, match="aware"):
        parse("PT1H").add_to(datetime(2026, 5, 4, 12, 0, 0))


def test_from_signed_never_uses_the_week_or_day_units() -> None:
    """A timedelta carries no calendar information to justify ``P1D``."""
    assert str(from_signed(timedelta(hours=24))) == "PT24H"
    assert str(from_signed(timedelta(days=7))) == "PT168H"


def test_from_signed_truncates_sub_second_precision() -> None:
    """RFC 5545 durations have second resolution."""
    assert str(from_signed(timedelta(seconds=1, microseconds=999999))) == "PT1S"


def test_from_signed_carries_the_sign() -> None:
    """A negative timedelta produces a negative duration."""
    d = from_signed(timedelta(minutes=-15))
    assert d.is_negative() is True
    assert str(d) == "-PT15M"


def test_from_signed_of_zero_is_pt0s() -> None:
    """Zero has one spelling here; ``day_form`` is a parse-time record."""
    assert str(from_signed(timedelta(0))) == "PT0S"


@pytest.mark.parametrize(
    "value",
    [
        "P1Y",  # ISO 8601 years: not RFC 5545
        "P1M",  # months either
        "PT1.5H",  # fractional
        "P-1D",  # per-component sign
        " PT15M",
        "PT15M ",
        "PT 15M",
        "PT",  # empty time part
        "P1D2H",  # time unit outside the T part
        "PT1S1M",  # out of order
        "PT1H1H",  # repeated
    ],
)
def test_parse_rejects_shapes_the_table_does_not_cover(value: str) -> None:
    """The table is thin by construction; these pin the rest of the grammar."""
    with pytest.raises(Malformed):
        parse(value)


# --- Trigger ---------------------------------------------------------


class TriggerCase(TypedDict, total=False):
    """One row of a ``behavior/duration/<name>.trigger.json`` sidecar."""

    #: The VALARM's UID, keying the row to its ``.ics``. Always present.
    alarm_uid: str
    #: The resolved firing instant, in form #2. Absent on a failure row.
    fires_at: str
    #: The failure class, when resolution must fail.
    error: str


def _trigger_cases() -> list[tuple[str, str, TriggerCase]]:
    """Every ``(stem, alarm_uid, expectation)`` from the trigger sidecars.

    The tree is walked rather than named, so a sidecar added upstream
    becomes a test with no edit here.
    """
    out: list[tuple[str, str, TriggerCase]] = []
    for path in TRIGGER_FILES:
        stem = path.name.removesuffix(".trigger.json")
        with path.open(encoding="utf-8") as fh:
            entries: list[TriggerCase] = json.load(fh)
        out.extend((stem, entry["alarm_uid"], entry) for entry in entries)
    return out


TRIGGER_CASES = _trigger_cases()
TRIGGER_IDS = [f"{stem}/{uid}" for stem, uid, _ in TRIGGER_CASES]

_PARSED: dict[str, Calendar] = {}


def _behavior_calendar(stem: str) -> Calendar:
    """The named ``behavior/duration/<stem>.ics`` document, parsed once."""
    if stem not in _PARSED:
        _PARSED[stem] = rfc5545.parse((BEHAVIOR_DIR / f"{stem}.ics").read_bytes())
    return _PARSED[stem]


def _find_alarm(cal: Calendar, uid: str) -> tuple[Component, Component]:
    """The ``(parent, alarm)`` pair whose VALARM carries ``uid``."""
    for parent in cal.components:
        for alarm in parent.sub:
            if alarm.uid() == uid:
                return parent, alarm
    raise AssertionError(f"no VALARM with UID {uid!r}")


def test_the_trigger_sidecars_have_cases_to_walk() -> None:
    """A loader finding nothing would pass every trigger test below."""
    assert len(TRIGGER_CASES) >= 8
    assert any("error" in e for _, _, e in TRIGGER_CASES)
    assert any("fires_at" in e for _, _, e in TRIGGER_CASES)


@pytest.mark.parametrize(("stem", "uid", "expect"), TRIGGER_CASES, ids=TRIGGER_IDS)
def test_trigger_resolution_matches_the_behavior_sidecars(
    stem: str, uid: str, expect: TriggerCase
) -> None:
    """Each sidecar row: when the alarm fires, or which class it fails in.

    The failure rows span three sentinels — ``ErrNoTrigger``,
    ``ErrNoAnchor`` and ``ErrMalformed`` — so this catches the common
    base and asserts the identifier. Catching a bare ``Exception`` would
    let a ``KeyError`` from the loader pass for a conformant failure.
    """
    cal = _behavior_calendar(stem)
    parent, alarm = _find_alarm(cal, uid)
    if "error" in expect:
        with pytest.raises(VstarError) as excinfo:
            alarm_trigger(alarm).resolve(parent, cal)
        assert excinfo.value.sentinel == expect["error"]
        return
    fires = alarm_trigger(alarm).resolve(parent, cal)
    assert format_time(fires) == expect["fires_at"]


def _prop(value: str, *params: Param) -> Property:
    """A TRIGGER property carrying ``value`` and ``params``."""
    return Property("TRIGGER", list(params), value)


def test_an_explicit_value_duration_is_authoritative() -> None:
    """The parameter decides; the value is read as what it claims to be."""
    t = parse_trigger(_prop("-PT15M", Param("VALUE", "DURATION")))
    assert t.relative is True
    assert str(t.duration) == "-PT15M"


def test_an_explicit_value_date_time_is_authoritative() -> None:
    """Same in the other direction."""
    t = parse_trigger(_prop("20260531T220000Z", Param("VALUE", "DATE-TIME")))
    assert t.relative is False
    assert format_time(t.absolute) == "20260531T220000Z"


def test_a_value_parameter_contradicting_its_value_is_malformed() -> None:
    """Never silently re-read as the other form — that is the whole rule."""
    with pytest.raises(Malformed):
        parse_trigger(_prop("20260531T220000Z", Param("VALUE", "DURATION")))
    with pytest.raises(Malformed):
        parse_trigger(_prop("-PT15M", Param("VALUE", "DATE-TIME")))


def test_an_unsupported_value_parameter_is_malformed() -> None:
    """DURATION and DATE-TIME are the only two forms TRIGGER has."""
    with pytest.raises(Malformed):
        parse_trigger(_prop("-PT15M", Param("VALUE", "TEXT")))


def test_without_a_value_parameter_the_value_shape_decides() -> None:
    """Producers in the wild routinely omit it, and the shapes are unambiguous."""
    assert parse_trigger(_prop("-PT15M")).relative is True
    assert parse_trigger(_prop("20260531T220000Z")).relative is False


def test_a_value_that_is_neither_form_is_malformed() -> None:
    """Nothing to infer from."""
    with pytest.raises(Malformed):
        parse_trigger(_prop("tomorrow-ish"))


def test_related_defaults_to_start() -> None:
    """RFC 5545 §3.2.14: an absent RELATED means START."""
    assert parse_trigger(_prop("-PT15M")).related is Related.START


def test_related_end_is_honored_on_a_relative_trigger() -> None:
    """The other anchor."""
    t = parse_trigger(_prop("-PT10M", Param("RELATED", "END")))
    assert t.related is Related.END


def test_related_is_matched_case_insensitively() -> None:
    """Parameter values are case-insensitive per RFC 5545 §3.2."""
    assert (
        parse_trigger(_prop("-PT10M", Param("related", "end"))).related is Related.END
    )


def test_related_on_an_absolute_trigger_is_malformed() -> None:
    """RFC 5545 §3.2.14 scopes the parameter to DURATION-valued triggers."""
    with pytest.raises(Malformed):
        parse_trigger(_prop("20260531T220000Z", Param("RELATED", "END")))


def test_an_unknown_related_value_is_malformed() -> None:
    """START and END are the whole vocabulary."""
    with pytest.raises(Malformed):
        parse_trigger(_prop("-PT15M", Param("RELATED", "MIDDLE")))


def test_related_renders_its_rfc_wire_spelling() -> None:
    """``str(Related.START)`` is what goes on the wire."""
    assert str(Related.START) == "START"
    assert str(Related.END) == "END"


def test_to_property_omits_related_start() -> None:
    """START is the RFC default and emitters leave it implicit."""
    p = parse_trigger(_prop("-PT15M")).to_property()
    assert p.name == "TRIGGER"
    assert p.value == "-PT15M"
    assert p.params == []


def test_to_property_writes_related_end_explicitly() -> None:
    """The non-default anchor has to be stated."""
    p = parse_trigger(_prop("-PT10M", Param("RELATED", "END"))).to_property()
    assert [(x.name, x.value) for x in p.params] == [("RELATED", "END")]


def test_to_property_writes_an_absolute_trigger_as_value_date_time() -> None:
    """So a consumer never has to infer the form."""
    p = parse_trigger(_prop("20260531T220000Z")).to_property()
    assert [(x.name, x.value) for x in p.params] == [("VALUE", "DATE-TIME")]
    assert p.value == "20260531T220000Z"


def test_to_property_round_trips_through_parse_trigger() -> None:
    """Re-parsing an emitted property recovers the same trigger."""
    for value, params in (
        ("-PT15M", ()),
        ("-PT10M", (Param("RELATED", "END"),)),
        ("20260531T220000Z", ()),
    ):
        first = parse_trigger(_prop(value, *params))
        again = parse_trigger(first.to_property())
        assert again.relative == first.relative
        assert again.related == first.related
        assert str(again.duration) == str(first.duration)
        assert again.absolute == first.absolute


def test_resolve_of_an_absolute_trigger_ignores_the_parent() -> None:
    """There is nothing to anchor against."""
    t = parse_trigger(_prop("20260531T220000Z"))
    empty = Component(type=CompType.EVENT)
    assert format_time(t.resolve(empty, Calendar())) == "20260531T220000Z"


def test_resolve_of_a_relative_start_trigger_offsets_dtstart() -> None:
    """The common case: fire N minutes before the parent begins."""
    parent = Component(
        type=CompType.EVENT,
        props=[Property("DTSTART", [], "20260601T090000Z")],
    )
    t = parse_trigger(_prop("-PT15M"))
    assert format_time(t.resolve(parent, Calendar())) == "20260601T084500Z"


def test_resolve_of_a_relative_end_trigger_offsets_dtend() -> None:
    """DTEND wins when present — it is the explicit statement."""
    parent = Component(
        type=CompType.EVENT,
        props=[
            Property("DTSTART", [], "20260601T090000Z"),
            Property("DTEND", [], "20260601T170000Z"),
        ],
    )
    t = parse_trigger(_prop("-PT10M", Param("RELATED", "END")))
    assert format_time(t.resolve(parent, Calendar())) == "20260601T165000Z"


def test_resolve_of_a_relative_end_trigger_falls_back_to_dtstart_plus_duration() -> (
    None
):
    """RFC 5545 §3.6.1 permits exactly one of DTEND and DURATION."""
    parent = Component(
        type=CompType.EVENT,
        props=[
            Property("DTSTART", [], "20260601T090000Z"),
            Property("DURATION", [], "PT2H"),
        ],
    )
    t = parse_trigger(_prop("PT0S", Param("RELATED", "END")))
    assert format_time(t.resolve(parent, Calendar())) == "20260601T110000Z"


def test_resolve_of_a_vtodo_end_trigger_anchors_to_due() -> None:
    """A VTODO ends at DUE, not at a DTEND it does not have."""
    parent = Component(
        type=CompType.TODO,
        props=[Property("DUE", [], "20260601T170000Z")],
    )
    t = parse_trigger(_prop("-PT1H", Param("RELATED", "END")))
    assert format_time(t.resolve(parent, Calendar())) == "20260601T160000Z"


def test_resolve_raises_no_anchor_when_the_anchor_is_missing() -> None:
    """Reported, never silently resolved against a zero time in year 1."""
    parent = Component(type=CompType.EVENT, props=[Property("UID", [], "u1")])
    with pytest.raises(NoAnchor) as excinfo:
        parse_trigger(_prop("-PT15M")).resolve(parent, Calendar())
    assert excinfo.value.sentinel == "ErrNoAnchor"


def test_resolve_uses_the_calendar_to_resolve_a_tzid_anchor() -> None:
    """The calendar supplies the VTIMEZONE registry the anchor needs."""
    cal = rfc5545.parse(
        (CONFORMANCE_DIR / "time" / "america_montreal.ics").read_bytes()
    )
    parent = Component(
        type=CompType.EVENT,
        props=[
            Property("DTSTART", [Param("TZID", "America/Montreal")], "20260104T133045")
        ],
    )
    t = parse_trigger(_prop("-PT15M"))
    assert format_time(t.resolve(parent, cal)) == "20260104T181545Z"


def test_alarm_trigger_raises_no_trigger_when_the_property_is_absent() -> None:
    """RFC 5545 §3.6.6 makes TRIGGER mandatory; absence is a producer bug."""
    alarm = Component(type=CompType.ALARM, props=[Property("ACTION", [], "DISPLAY")])
    with pytest.raises(NoTrigger) as excinfo:
        alarm_trigger(alarm)
    assert excinfo.value.sentinel == "ErrNoTrigger"


def test_event_end_prefers_dtend_over_duration() -> None:
    """DTEND is the explicit statement and wins when both are present."""
    c = Component(
        type=CompType.EVENT,
        props=[
            Property("DTSTART", [], "20260601T090000Z"),
            Property("DTEND", [], "20260601T170000Z"),
            Property("DURATION", [], "PT1H"),
        ],
    )
    end = event_end(c, Calendar())
    assert end is not None
    assert format_time(end) == "20260601T170000Z"


def test_event_end_is_none_when_neither_form_is_available() -> None:
    """Absence, not a failure."""
    c = Component(
        type=CompType.EVENT, props=[Property("DTSTART", [], "20260601T090000Z")]
    )
    assert event_end(c, Calendar()) is None


def test_event_end_is_none_when_the_duration_is_malformed() -> None:
    """Torn data does not become a plausible end instant."""
    c = Component(
        type=CompType.EVENT,
        props=[
            Property("DTSTART", [], "20260601T090000Z"),
            Property("DURATION", [], "nonsense"),
        ],
    )
    assert event_end(c, Calendar()) is None


def test_alarm_repeat_cycle_reads_the_duration_repeat_pair() -> None:
    """RFC 5545 §3.8.6.2: the two properties travel together."""
    alarm = Component(
        type=CompType.ALARM,
        props=[Property("DURATION", [], "PT5M"), Property("REPEAT", [], "3")],
    )
    d, repeat = alarm_repeat_cycle(alarm)
    assert str(d) == "PT5M"
    assert repeat == 3


def test_alarm_repeat_cycle_is_zero_when_neither_property_is_present() -> None:
    """Neither present is a legal alarm, not an error."""
    alarm = Component(type=CompType.ALARM, props=[Property("ACTION", [], "DISPLAY")])
    d, repeat = alarm_repeat_cycle(alarm)
    assert str(d) == "PT0S"
    assert repeat == 0


@pytest.mark.parametrize(
    "props",
    [
        [Property("DURATION", [], "PT5M")],
        [Property("REPEAT", [], "3")],
        [Property("DURATION", [], "bad"), Property("REPEAT", [], "3")],
        [Property("DURATION", [], "PT5M"), Property("REPEAT", [], "many")],
        [Property("DURATION", [], "PT5M"), Property("REPEAT", [], "-1")],
    ],
)
def test_alarm_repeat_cycle_rejects_a_half_or_invalid_pair(
    props: list[Property],
) -> None:
    """One without the other, or a value outside its domain, is malformed."""
    with pytest.raises(Malformed):
        alarm_repeat_cycle(Component(type=CompType.ALARM, props=props))


def test_trigger_is_constructible_directly() -> None:
    """The type is data, not a parse-only artifact."""
    t = Trigger(relative=True, duration=parse("-PT15M"), related=Related.END)
    assert t.to_property().value == "-PT15M"
