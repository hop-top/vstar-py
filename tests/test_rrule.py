# SPDX-License-Identifier: MIT

"""The layer-(c) gate: every sidecar under ``conformance/rrule/``.

Each sidecar decides exactly one call, and this file makes each of
them a test. The tree is walked rather than enumerated by name, so a
fixture added to the corpus becomes a test here without an edit.

Each ``<stem>.rrule`` input is classified by which siblings it carries:

- ``.expect.json``  -> :func:`validate_rrule` must raise the named sentinel.
- ``.formatted``    -> ``str(rule)`` must equal the file.
- ``.next.json``    -> :func:`next_occurrence` stepped ``len(expected)``
  times, then once more past the end.
- ``.expand.json``  -> :func:`occurrences`.
- ``.between.json`` -> :func:`between`.
- no sibling at all -> the fixture pins only "this parses".

``.ics`` inputs go through :func:`rule_set_from_component` and carry
either ``.expect.json`` or ``.occurrences.json``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import get_type_hints

import pytest

from _fixtures import CONFORMANCE_DIR
from vstar import Malformed, UnsupportedRrule, VstarError, format_time, parse_time
from vstar.codec import rfc5545
from vstar.rrule import (
    MAX_ITERATIONS,
    ByDay,
    Freq,
    RecurrenceRange,
    Rule,
    RuleSet,
    Weekday,
    all,  # noqa: A004 - the API-mapped name; reached as `rrule.all`
    between,
    format_date_time_list,
    next_occurrence,
    occurrences,
    parse_date_time_list,
    parse_recurrence_id,
    parse_rrule,
    rule_set_from_component,
    validate_rrule,
)
from vstar.types import Component, Param, Property

RRULE_DIR = CONFORMANCE_DIR / "rrule"


# ── Corpus loading ────────────────────────────────────────────────


def _read_json(path: Path) -> dict[str, object] | None:
    """One JSON sidecar, or ``None`` when it is absent."""
    if not path.is_file():
        return None
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict), f"{path}: sidecar is not a JSON object"
    return loaded


def _read_text(path: Path) -> str | None:
    """One text sidecar with its trailing newline trimmed, or ``None``."""
    if not path.is_file():
        return None
    return path.read_text(encoding="utf-8").rstrip("\r\n")


@dataclass(frozen=True, slots=True)
class RruleFixture:
    """One ``<stem>.rrule`` input plus whichever sidecars it carries."""

    #: Path label relative to ``rrule/``, e.g. ``evaluator/leap_day``.
    id: str
    #: Subdirectory under ``rrule/``, e.g. ``evaluator``.
    dir: str
    #: The RRULE property value, trailing newline trimmed.
    value: str
    #: ``.expect.json``'s ``sentinel``, when the fixture carries one.
    sentinel: str | None
    #: ``.formatted``'s contents, when present.
    formatted: str | None
    next: dict[str, object] | None
    expand: dict[str, object] | None
    between: dict[str, object] | None

    @property
    def has_any_sidecar(self) -> bool:
        """Whether any sidecar beyond the bare input exists."""
        return any(
            s is not None
            for s in (
                self.sentinel,
                self.formatted,
                self.next,
                self.expand,
                self.between,
            )
        )


@dataclass(frozen=True, slots=True)
class SetFixture:
    """One ``<stem>.ics`` recurrence-set input plus its sidecars."""

    id: str
    dir: str
    input: bytes
    sentinel: str | None
    occurrences: dict[str, object] | None


def _label(path: Path) -> str:
    """The fixture's path relative to ``rrule/``, extension dropped."""
    return path.relative_to(RRULE_DIR).with_suffix("").as_posix()


def load_rrule_fixtures() -> list[RruleFixture]:
    """Every ``<stem>.rrule`` fixture in the corpus, sorted by path."""
    out: list[RruleFixture] = []
    for path in sorted(RRULE_DIR.rglob("*.rrule")):
        stem = path.with_suffix("")
        expect = _read_json(path.with_suffix(".expect.json"))
        sentinel = None if expect is None else str(expect["sentinel"])
        out.append(
            RruleFixture(
                id=_label(path),
                dir=path.parent.relative_to(RRULE_DIR).as_posix(),
                value=path.read_text(encoding="utf-8").rstrip("\r\n"),
                sentinel=sentinel,
                formatted=_read_text(Path(f"{stem}.formatted")),
                next=_read_json(Path(f"{stem}.next.json")),
                expand=_read_json(Path(f"{stem}.expand.json")),
                between=_read_json(Path(f"{stem}.between.json")),
            )
        )
    return out


def load_set_fixtures() -> list[SetFixture]:
    """Every ``<stem>.ics`` recurrence-set fixture, sorted by path."""
    out: list[SetFixture] = []
    for path in sorted(RRULE_DIR.rglob("*.ics")):
        stem = path.with_suffix("")
        expect = _read_json(path.with_suffix(".expect.json"))
        sentinel = None if expect is None else str(expect["sentinel"])
        out.append(
            SetFixture(
                id=_label(path),
                dir=path.parent.relative_to(RRULE_DIR).as_posix(),
                input=path.read_bytes(),
                sentinel=sentinel,
                occurrences=_read_json(Path(f"{stem}.occurrences.json")),
            )
        )
    return out


RRULE_FIXTURES = load_rrule_fixtures()
SET_FIXTURES = load_set_fixtures()


# ── Shared assertions ─────────────────────────────────────────────


def expect_sentinel(want: str, fn: object, label: str) -> None:
    """Assert the zero-argument ``fn`` raises the named V* sentinel."""
    assert callable(fn)
    try:
        fn()
    except VstarError as e:
        assert e.sentinel == want, f"{label}: raised {e.sentinel}, want {want} ({e})"
        return
    raise AssertionError(f"{label}: call succeeded, want {want}")


def instant(raw: object, label: str) -> datetime:
    """A sidecar timestamp as a UTC datetime, failing loudly on a bad field."""
    assert isinstance(raw, str), f"{label}: missing timestamp field"
    t = parse_time(raw)
    assert t is not None, f"{label}: {raw!r} is not RFC 5545 form #2"
    return t


def shown(times: list[datetime]) -> list[str]:
    """Render instants back to form #2 so failures read as timestamps."""
    return [format_time(t) for t in times]


def expected_of(spec: dict[str, object]) -> list[str]:
    """A sidecar's ``expected`` list, defaulting to empty."""
    raw = spec.get("expected", [])
    assert isinstance(raw, list)
    return [str(x) for x in raw]


def limit_of(spec: dict[str, object]) -> int:
    """A sidecar's ``limit``, defaulting to zero."""
    raw = spec.get("limit", 0)
    assert isinstance(raw, int)
    return raw


def error_of(spec: dict[str, object]) -> str | None:
    """A sidecar's optional ``error`` failure class."""
    raw = spec.get("error")
    return None if raw is None else str(raw)


def first_component(f: SetFixture) -> Component:
    """The first component of a ``.ics`` set fixture."""
    cal = rfc5545.parse(f.input)
    assert cal.components, f"{f.id}: calendar has no components"
    return cal.components[0]


# ── Corpus coverage ───────────────────────────────────────────────


def test_finds_the_fixture_tree() -> None:
    assert RRULE_FIXTURES
    assert SET_FIXTURES


def test_covers_every_subdirectory_the_readme_names() -> None:
    dirs = {f.dir for f in RRULE_FIXTURES} | {f.dir for f in SET_FIXTURES}
    for want in (
        "happy",
        "bounds",
        "by-clauses",
        "rejected",
        "format",
        "evaluator",
        "expansion",
        "set",
        "set/rejected",
    ):
        assert want in dirs, f"no fixtures under rrule/{want}/"


# ── rejected/ — the named sentinel ────────────────────────────────

REJECTED = [f for f in RRULE_FIXTURES if f.sentinel is not None]


def test_finds_the_rejected_fixtures() -> None:
    assert REJECTED


@pytest.mark.parametrize("f", REJECTED, ids=lambda f: f.id)
def test_rejected_fixture_names_its_sentinel(f: RruleFixture) -> None:
    want = f.sentinel
    assert want is not None
    expect_sentinel(want, lambda: validate_rrule(f.value), f.id)
    # parse_rrule and validate_rrule are the same answer by contract:
    # validate_rrule parses and discards.
    expect_sentinel(want, lambda: parse_rrule(f.value), f.id)


# ── happy/, bounds/, by-clauses/ — "this parses", and nothing more ──

BARE = [f for f in RRULE_FIXTURES if f.sentinel is None and not f.has_any_sidecar]


def test_finds_the_sidecar_less_fixtures() -> None:
    # happy/ (6) + bounds/ (3) + by-clauses/ (9).
    assert len(BARE) == 18


@pytest.mark.parametrize("f", BARE, ids=lambda f: f.id)
def test_sidecar_less_fixture_parses(f: RruleFixture) -> None:
    rule = parse_rrule(f.value)
    # The fixture pins exactly this much: the value is in scope. FREQ is
    # the one field a successful parse always sets.
    assert rule.freq is not Freq.INVALID, f.id
    validate_rrule(f.value)


# ── format/ — the fixed wire form ─────────────────────────────────

FORMATTED = [f for f in RRULE_FIXTURES if f.formatted is not None]
PARSEABLE = [f for f in RRULE_FIXTURES if f.sentinel is None]


def test_finds_the_formatted_fixtures() -> None:
    assert FORMATTED


@pytest.mark.parametrize("f", FORMATTED, ids=lambda f: f.id)
def test_reemits_as_its_formatted_sibling(f: RruleFixture) -> None:
    assert str(parse_rrule(f.value)) == f.formatted, f.id


@pytest.mark.parametrize("f", PARSEABLE, ids=lambda f: f.id)
def test_round_trips_through_the_wire_form(f: RruleFixture) -> None:
    # The spec makes idempotence a property of the wire form, not of the
    # two format/ fixtures, so every parseable fixture is held to it.
    once = str(parse_rrule(f.value))
    assert str(parse_rrule(once)) == once, f.id


def test_keeps_list_values_in_authored_order() -> None:
    # Authored descending. RFC 5545 gives BY-* lists no ordering
    # semantics, so a sorting emitter would silently rewrite content —
    # and no format/ fixture carries an unsorted multi-entry BYDAY, so
    # this assertion is the only thing standing between the port and a
    # sort() slipped into the parser.
    assert str(parse_rrule("FREQ=WEEKLY;BYDAY=WE,MO")) == "FREQ=WEEKLY;BYDAY=WE,MO"
    assert (
        str(parse_rrule("FREQ=WEEKLY;BYDAY=FR,TU,MO")) == "FREQ=WEEKLY;BYDAY=FR,TU,MO"
    )
    assert (
        str(parse_rrule("FREQ=MONTHLY;BYMONTHDAY=-1,15"))
        == "FREQ=MONTHLY;BYMONTHDAY=-1,15"
    )
    assert (
        str(parse_rrule("FREQ=YEARLY;BYMONTH=12,6,1")) == "FREQ=YEARLY;BYMONTH=12,6,1"
    )
    # The parsed field itself keeps the order, not merely the rendering.
    assert [bd.weekday for bd in parse_rrule("FREQ=WEEKLY;BYDAY=WE,MO").by_day] == [
        Weekday.WE,
        Weekday.MO,
    ]


def test_elides_interval_one_and_wkst_mo() -> None:
    assert str(parse_rrule("FREQ=DAILY;INTERVAL=1;WKST=MO")) == "FREQ=DAILY"
    assert str(parse_rrule("FREQ=DAILY;INTERVAL=2")) == "FREQ=DAILY;INTERVAL=2"
    assert str(parse_rrule("FREQ=WEEKLY;WKST=SU")) == "FREQ=WEEKLY;WKST=SU"


def test_emits_rule_parts_in_the_specs_fixed_order() -> None:
    scrambled = (
        "WKST=SU;BYSETPOS=1;BYSECOND=0;BYMINUTE=0;BYHOUR=9;BYDAY=MO;"
        "BYMONTHDAY=1;BYYEARDAY=5;BYWEEKNO=2;BYMONTH=3;COUNT=4;INTERVAL=2;FREQ=YEARLY"
    )
    assert str(parse_rrule(scrambled)) == (
        "FREQ=YEARLY;INTERVAL=2;COUNT=4;BYMONTH=3;BYWEEKNO=2;BYYEARDAY=5;"
        "BYMONTHDAY=1;BYDAY=MO;BYHOUR=9;BYMINUTE=0;BYSECOND=0;BYSETPOS=1;WKST=SU"
    )


def test_renders_a_property_carrying_the_wire_form() -> None:
    p = parse_rrule("FREQ=DAILY;INTERVAL=1").to_property()
    assert p.name == "RRULE"
    assert p.value == "FREQ=DAILY"
    assert p.params == []


def test_emits_until_and_count_in_their_fixed_slots() -> None:
    assert (
        str(parse_rrule("FREQ=DAILY;UNTIL=20261231T235959Z"))
        == "FREQ=DAILY;UNTIL=20261231T235959Z"
    )
    assert str(parse_rrule("FREQ=WEEKLY;COUNT=10")) == "FREQ=WEEKLY;COUNT=10"


# ── evaluator/ — .next.json ───────────────────────────────────────

STEPPED = [f for f in RRULE_FIXTURES if f.next is not None]


def test_finds_the_next_fixtures() -> None:
    assert STEPPED


@pytest.mark.parametrize("f", STEPPED, ids=lambda f: f.id)
def test_steps_through_its_expected_occurrences(f: RruleFixture) -> None:
    spec = f.next
    assert spec is not None
    rule = parse_rrule(f.value)
    dtstart = instant(spec.get("dtstart"), f"{f.id}.dtstart")
    after = instant(spec.get("after"), f"{f.id}.after")

    for i, want in enumerate(expected_of(spec)):
        got = next_occurrence(rule, dtstart, after)
        assert got is not None, f"{f.id}: step {i} returned None, want {want}"
        assert format_time(got) == want, f"{f.id}: step {i}"
        after = got

    # The step past the end is what tells termination apart from the
    # iteration cap, and the sidecar says which answer is right.
    #
    # With an `error`, that step MUST fail with it — neither yield
    # another occurrence nor report ordinary termination. Without one,
    # the step is decidable only for a rule that bounds itself: an
    # unbounded FREQ=DAILY genuinely has a next occurrence forever, so
    # asserting None there would assert a falsehood rather than catch a
    # port that stops early.
    want_err = error_of(spec)
    label = f"{f.id}: step past the end"
    if want_err is not None:
        expect_sentinel(want_err, lambda: next_occurrence(rule, dtstart, after), label)
    elif rule.count > 0 or rule.until is not None:
        assert next_occurrence(rule, dtstart, after) is None, label
    else:
        assert next_occurrence(rule, dtstart, after) is not None, label


def test_distinguishes_the_iteration_cap_from_termination() -> None:
    # Unsatisfiable by construction — February never has a 30th — so the
    # evaluator must give up loudly rather than report completion.
    rule = parse_rrule("FREQ=YEARLY;BYMONTH=2;BYMONTHDAY=30")
    dtstart = instant("20260101T090000Z", "cap.dtstart")
    expect_sentinel(
        "ErrIterationCap", lambda: next_occurrence(rule, dtstart, dtstart), "cap"
    )
    expect_sentinel(
        "ErrIterationCap", lambda: occurrences(rule, dtstart, 5), "cap occurrences"
    )

    # A terminating rule is the contrasting case: None, no raise.
    bounded = parse_rrule("FREQ=DAILY;COUNT=1")
    assert next_occurrence(bounded, dtstart, dtstart) is None


def test_publishes_a_finite_iteration_bound() -> None:
    assert MAX_ITERATIONS == 100000


def test_skips_bymonthday_29_in_a_non_leap_february_and_honours_minus_one() -> None:
    skip = parse_rrule("FREQ=MONTHLY;BYMONTHDAY=29")
    dtstart = instant("20260129T120000Z", "skip.dtstart")
    # 2026 is not a leap year: February is skipped entirely.
    times, _ = occurrences(skip, dtstart, 3)
    assert shown(times) == ["20260129T120000Z", "20260329T120000Z", "20260429T120000Z"]

    last = parse_rrule("FREQ=MONTHLY;BYMONTHDAY=-1")
    jan = instant("20260131T120000Z", "last.dtstart")
    times, _ = occurrences(last, jan, 3)
    assert shown(times) == ["20260131T120000Z", "20260228T120000Z", "20260331T120000Z"]


def test_anchors_week_boundaries_on_wkst() -> None:
    # The same BYDAY set under two week starts: with WKST=SU the Sunday
    # opens its own week, with WKST=MO it closes the previous one, so
    # INTERVAL=2 selects different days.
    dtstart = instant("20260105T090000Z", "wkst.dtstart")  # a Monday
    su = parse_rrule("FREQ=WEEKLY;INTERVAL=2;BYDAY=SU,MO;WKST=SU")
    mo = parse_rrule("FREQ=WEEKLY;INTERVAL=2;BYDAY=SU,MO;WKST=MO")
    su_times, _ = occurrences(su, dtstart, 4)
    mo_times, _ = occurrences(mo, dtstart, 4)
    assert shown(su_times) != shown(mo_times)


def test_rejects_a_rule_the_evaluator_cannot_walk() -> None:
    dtstart = instant("20260101T000000Z", "unsupported.dtstart")
    broken = Rule(freq=Freq.DAILY, interval=0)
    expect_sentinel(
        "ErrUnsupportedRRule",
        lambda: next_occurrence(broken, dtstart, dtstart),
        "interval 0",
    )
    expect_sentinel(
        "ErrUnsupportedRRule",
        lambda: occurrences(broken, dtstart, 5),
        "interval 0 occurrences",
    )
    invalid = Rule()
    expect_sentinel(
        "ErrUnsupportedRRule",
        lambda: next_occurrence(invalid, dtstart, dtstart),
        "freq invalid",
    )


def test_dtstart_is_the_first_occurrence_when_it_satisfies_the_filters() -> None:
    rule = parse_rrule("FREQ=DAILY")
    dtstart = instant("20260401T120000Z", "first.dtstart")
    times, _ = occurrences(rule, dtstart, 1)
    assert shown(times) == ["20260401T120000Z"]


# ── expansion/ — .expand.json and .between.json ───────────────────

EXPANDED = [f for f in RRULE_FIXTURES if f.expand is not None]
WINDOWED = [f for f in RRULE_FIXTURES if f.between is not None]


def test_finds_the_expansion_fixtures() -> None:
    assert EXPANDED
    assert WINDOWED


@pytest.mark.parametrize("f", EXPANDED, ids=lambda f: f.id)
def test_expands_to_its_expand_sidecar(f: RruleFixture) -> None:
    spec = f.expand
    assert spec is not None
    rule = parse_rrule(f.value)
    dtstart = instant(spec.get("dtstart"), f"{f.id}.dtstart")
    limit = limit_of(spec)
    want_err = error_of(spec)
    if want_err is not None:
        expect_sentinel(want_err, lambda: occurrences(rule, dtstart, limit), f.id)
        return
    times, complete = occurrences(rule, dtstart, limit)
    assert shown(times) == expected_of(spec), f.id
    assert complete is bool(spec.get("complete", False)), f"{f.id}: complete flag"


@pytest.mark.parametrize("f", WINDOWED, ids=lambda f: f.id)
def test_windows_to_its_between_sidecar(f: RruleFixture) -> None:
    spec = f.between
    assert spec is not None
    rule = parse_rrule(f.value)
    dtstart = instant(spec.get("dtstart"), f"{f.id}.dtstart")
    start = instant(spec.get("start"), f"{f.id}.start")
    end = instant(spec.get("end"), f"{f.id}.end")
    want_err = error_of(spec)
    if want_err is not None:
        expect_sentinel(want_err, lambda: between(rule, dtstart, start, end), f.id)
        return
    assert shown(between(rule, dtstart, start, end)) == expected_of(spec), f.id


def test_treats_the_window_as_half_open() -> None:
    rule = parse_rrule("FREQ=DAILY")
    dtstart = instant("20260401T120000Z", "half-open.dtstart")
    got = between(rule, dtstart, dtstart, instant("20260403T120000Z", "half-open.end"))
    # start is included, end is not.
    assert shown(got) == ["20260401T120000Z", "20260402T120000Z"]


def test_refuses_an_unbounded_window() -> None:
    rule = parse_rrule("FREQ=DAILY")
    dtstart = instant("20260401T120000Z", "unbounded.dtstart")
    expect_sentinel(
        "ErrUnboundedExpansion",
        lambda: between(rule, dtstart, dtstart, None),
        "missing end",
    )
    expect_sentinel(
        "ErrUnboundedExpansion",
        lambda: between(rule, dtstart, dtstart, dtstart),
        "zero window",
    )
    expect_sentinel(
        "ErrUnboundedExpansion",
        lambda: between(
            rule, dtstart, dtstart, instant("20260331T120000Z", "inverted")
        ),
        "inverted window",
    )


def test_refuses_a_negative_limit() -> None:
    rule = parse_rrule("FREQ=DAILY")
    dtstart = instant("20260401T120000Z", "negative.dtstart")
    expect_sentinel(
        "ErrUnboundedExpansion",
        lambda: occurrences(rule, dtstart, -1),
        "negative limit",
    )


def test_reports_a_zero_limit_as_neither_complete_nor_truncated() -> None:
    rule = parse_rrule("FREQ=DAILY;COUNT=2")
    dtstart = instant("20260401T120000Z", "zero.dtstart")
    times, complete = occurrences(rule, dtstart, 0)
    assert times == []
    assert complete is False


def test_yields_lazily_from_all() -> None:
    # An unbounded rule: a materializing implementation never returns.
    rule = parse_rrule("FREQ=DAILY")
    dtstart = instant("20260401T120000Z", "all.dtstart")
    seen: list[datetime] = []
    for t in all(rule, dtstart):
        seen.append(t)
        if len(seen) == 3:
            break
    assert shown(seen) == ["20260401T120000Z", "20260402T120000Z", "20260403T120000Z"]


def test_ends_all_when_the_rule_terminates() -> None:
    rule = parse_rrule("FREQ=DAILY;COUNT=2")
    dtstart = instant("20260401T120000Z", "all-count.dtstart")
    assert shown(list(all(rule, dtstart))) == ["20260401T120000Z", "20260402T120000Z"]


def test_until_is_inclusive() -> None:
    rule = parse_rrule("FREQ=DAILY;UNTIL=20260403T120000Z")
    dtstart = instant("20260401T120000Z", "until.dtstart")
    times, complete = occurrences(rule, dtstart, 10)
    assert shown(times) == ["20260401T120000Z", "20260402T120000Z", "20260403T120000Z"]
    assert complete is True


# ── set/ — .ics recurrence sets ───────────────────────────────────

SET_REJECTED = [f for f in SET_FIXTURES if f.sentinel is not None]
SET_EXPANDED = [f for f in SET_FIXTURES if f.occurrences is not None]


def test_finds_the_set_fixtures() -> None:
    assert SET_REJECTED
    assert SET_EXPANDED


@pytest.mark.parametrize("f", SET_REJECTED, ids=lambda f: f.id)
def test_set_fixture_names_its_sentinel(f: SetFixture) -> None:
    want = f.sentinel
    assert want is not None
    comp = first_component(f)
    expect_sentinel(want, lambda: rule_set_from_component(comp), f.id)


@pytest.mark.parametrize("f", SET_EXPANDED, ids=lambda f: f.id)
def test_set_expands_to_its_occurrences_sidecar(f: SetFixture) -> None:
    spec = f.occurrences
    assert spec is not None
    rule_set = rule_set_from_component(first_component(f))
    limit = limit_of(spec)
    want_err = error_of(spec)
    if want_err is not None:
        expect_sentinel(want_err, lambda: rule_set.occurrences(limit), f.id)
        return
    times, complete = rule_set.occurrences(limit)
    assert shown(times) == expected_of(spec), f.id
    assert complete is bool(spec.get("complete", False)), f"{f.id}: complete flag"


def _component(*lines: str) -> Component:
    """Parse a small VEVENT-bearing calendar and return its component."""
    ics = "\r\n".join(
        [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "PRODID:-//V*//test//EN",
            "BEGIN:VEVENT",
            "UID:set-test",
            "DTSTAMP:20260101T000000Z",
            *lines,
            "END:VEVENT",
            "END:VCALENDAR",
            "",
        ]
    )
    cal = rfc5545.parse(ics.encode("utf-8"))
    return cal.components[0]


def test_removes_exdate_after_merging_rdate() -> None:
    # The ordering is load-bearing: an instant named by BOTH an RDATE
    # and an EXDATE stays excluded, because EXDATE is applied last.
    comp = _component(
        "DTSTART:20260401T120000Z",
        "RDATE:20260410T120000Z",
        "EXDATE:20260410T120000Z",
    )
    times, _ = rule_set_from_component(comp).occurrences(10)
    assert shown(times) == ["20260401T120000Z"]


def test_sorts_and_de_duplicates_the_merged_result() -> None:
    comp = _component(
        "DTSTART:20260401T120000Z",
        "RRULE:FREQ=DAILY;COUNT=2",
        "RDATE:20260402T120000Z,20260401T120000Z,20260403T120000Z",
    )
    times, _ = rule_set_from_component(comp).occurrences(10)
    assert shown(times) == ["20260401T120000Z", "20260402T120000Z", "20260403T120000Z"]


def test_windows_a_set() -> None:
    comp = _component(
        "DTSTART:20260401T120000Z",
        "RRULE:FREQ=DAILY",
        "EXDATE:20260403T120000Z",
    )
    rule_set = rule_set_from_component(comp)
    got = rule_set.between(
        instant("20260402T120000Z", "set-window.start"),
        instant("20260405T120000Z", "set-window.end"),
    )
    assert shown(got) == ["20260402T120000Z", "20260404T120000Z"]


def test_set_refuses_an_unbounded_window() -> None:
    rule_set = rule_set_from_component(
        _component("DTSTART:20260401T120000Z", "RRULE:FREQ=DAILY")
    )
    start = instant("20260401T120000Z", "set-unbounded.start")
    expect_sentinel(
        "ErrUnboundedExpansion",
        lambda: rule_set.between(start, None),
        "set missing end",
    )
    expect_sentinel(
        "ErrUnboundedExpansion",
        lambda: rule_set.between(start, start),
        "set zero window",
    )
    expect_sentinel(
        "ErrUnboundedExpansion", lambda: rule_set.occurrences(-1), "set negative limit"
    )


@pytest.mark.parametrize(
    "line",
    [
        "EXDATE;VALUE=DATE:20260402",
        "RDATE;VALUE=DATE:20260402",
        "EXDATE;TZID=America/New_York:20260402T080000",
        "RDATE;TZID=America/New_York:20260402T080000",
    ],
)
def test_refuses_value_date_and_tzid_on_exdate_and_rdate(line: str) -> None:
    comp = _component("DTSTART:20260401T120000Z", line)
    expect_sentinel("ErrUnsupportedRRule", lambda: rule_set_from_component(comp), line)


def test_an_rdate_only_set_is_legal_and_finite() -> None:
    comp = _component("DTSTART:20260401T120000Z", "RDATE:20260405T120000Z")
    rule_set = rule_set_from_component(comp)
    assert rule_set.rrule is None
    times, complete = rule_set.occurrences(10)
    assert shown(times) == ["20260401T120000Z", "20260405T120000Z"]
    assert complete is True


def test_a_rule_set_can_be_built_directly() -> None:
    dtstart = instant("20260401T120000Z", "direct.dtstart")
    rule_set = RuleSet(dtstart=dtstart, rrule=parse_rrule("FREQ=DAILY;COUNT=2"))
    times, complete = rule_set.occurrences(10)
    assert shown(times) == ["20260401T120000Z", "20260402T120000Z"]
    assert complete is True


def test_set_exdate_removals_do_not_consume_limit_slots() -> None:
    comp = _component(
        "DTSTART:20260401T120000Z",
        "RRULE:FREQ=DAILY",
        "EXDATE:20260402T120000Z,20260403T120000Z",
    )
    times, complete = rule_set_from_component(comp).occurrences(2)
    assert shown(times) == ["20260401T120000Z", "20260404T120000Z"]
    assert complete is False


# ── Date-time lists and RECURRENCE-ID ─────────────────────────────


def test_parses_a_date_time_list_sorted_and_de_duplicated() -> None:
    got = parse_date_time_list("20260403T120000Z,20260401T120000Z,20260403T120000Z")
    assert shown(got) == ["20260401T120000Z", "20260403T120000Z"]


def test_refuses_a_malformed_date_time_list() -> None:
    expect_sentinel("ErrMalformed", lambda: parse_date_time_list(""), "empty list")
    expect_sentinel(
        "ErrMalformed", lambda: parse_date_time_list("20260403T120000"), "form #1"
    )
    expect_sentinel(
        "ErrMalformed", lambda: parse_date_time_list("20260403"), "date only"
    )


def test_formats_a_date_time_list_sorted_and_de_duplicated() -> None:
    a = instant("20260403T120000Z", "fmt.a")
    b = instant("20260401T120000Z", "fmt.b")
    assert format_date_time_list([a, b, a]) == "20260401T120000Z,20260403T120000Z"
    assert format_date_time_list([]) == ""


def test_parses_a_recurrence_id_without_a_range() -> None:
    rid = parse_recurrence_id(Property(name="RECURRENCE-ID", value="20260403T120000Z"))
    assert format_time(rid.time) == "20260403T120000Z"
    assert rid.range is RecurrenceRange.THIS_INSTANCE
    p = rid.to_property()
    assert p.name == "RECURRENCE-ID"
    assert p.value == "20260403T120000Z"
    # The default is expressed by omitting the parameter, so emitting a
    # token for it would change the bytes.
    assert p.params == []


def test_parses_a_recurrence_id_with_this_and_future() -> None:
    rid = parse_recurrence_id(
        Property(
            name="RECURRENCE-ID",
            params=[Param("RANGE", "THISANDFUTURE")],
            value="20260403T120000Z",
        )
    )
    assert rid.range is RecurrenceRange.THIS_AND_FUTURE
    p = rid.to_property()
    assert [(x.name, x.value) for x in p.params] == [("RANGE", "THISANDFUTURE")]


def test_refuses_a_bad_recurrence_id() -> None:
    expect_sentinel(
        "ErrMalformed",
        lambda: parse_recurrence_id(Property(name="DTSTART", value="20260403T120000Z")),
        "wrong property",
    )
    expect_sentinel(
        "ErrMalformed",
        lambda: parse_recurrence_id(Property(name="RECURRENCE-ID", value="20260403")),
        "not form #2",
    )
    expect_sentinel(
        "ErrMalformed",
        lambda: parse_recurrence_id(
            Property(
                name="RECURRENCE-ID",
                params=[Param("RANGE", "THISANDPRIOR")],
                value="20260403T120000Z",
            )
        ),
        "unknown RANGE",
    )
    expect_sentinel(
        "ErrUnsupportedRRule",
        lambda: parse_recurrence_id(
            Property(
                name="RECURRENCE-ID",
                params=[Param("TZID", "America/New_York")],
                value="20260403T080000",
            )
        ),
        "TZID",
    )


# ── Parse-scope details the corpus does not spell out ─────────────


@pytest.mark.parametrize(
    ("value", "label"),
    [
        ("", "empty"),
        ("FREQ", "no separator"),
        ("=DAILY", "empty key"),
        ("FREQ=DAILY;FREQ=WEEKLY", "duplicate rule-part"),
        ("FREQ=daily", "lowercase FREQ"),
        ("FREQ=DAILY;INTERVAL=1e3", "non-integer INTERVAL"),
        ("FREQ=DAILY;INTERVAL=-2", "negative INTERVAL"),
        ("FREQ=DAILY;COUNT=0", "zero COUNT"),
        ("FREQ=WEEKLY;BYDAY=", "empty BYDAY"),
        ("FREQ=WEEKLY;BYDAY=XX", "bad weekday"),
        ("FREQ=WEEKLY;BYDAY=54MO", "BYDAY ordinal out of range"),
        ("FREQ=YEARLY;BYMONTH=13", "BYMONTH out of range"),
        ("FREQ=DAILY;BYHOUR=24", "BYHOUR out of range"),
        ("FREQ=DAILY;BYMINUTE=60", "BYMINUTE out of range"),
        ("FREQ=DAILY;BYSECOND=61", "BYSECOND out of range"),
        ("FREQ=YEARLY;BYYEARDAY=0", "BYYEARDAY zero"),
        ("FREQ=YEARLY;BYYEARDAY=367", "BYYEARDAY out of range"),
        ("FREQ=DAILY;WKST=XX", "bad WKST"),
    ],
)
def test_rejects_structurally_broken_rule_parts(value: str, label: str) -> None:
    expect_sentinel("ErrMalformed", lambda: parse_rrule(value), label)


def test_accepts_the_rfc_edges_the_scope_keeps() -> None:
    # BYSECOND=60 is retained for leap seconds per RFC 5545 §3.3.10.
    assert parse_rrule("FREQ=DAILY;BYSECOND=60").by_second == [60]
    # A BYDAY ordinal at either extreme of -53..53.
    assert parse_rrule("FREQ=YEARLY;BYDAY=53MO").by_day == [ByDay(53, Weekday.MO)]
    assert parse_rrule("FREQ=YEARLY;BYDAY=-53MO").by_day == [ByDay(-53, Weekday.MO)]
    # An ordinal-less BYDAY carries ordinal 0 — "every weekday of this
    # kind", spelled by omission because the explicit 0 prefix is invalid.
    assert parse_rrule("FREQ=WEEKLY;BYDAY=MO").by_day == [ByDay(0, Weekday.MO)]


def test_accepts_freq_minutely() -> None:
    # MINUTELY is in scope; only SECONDLY and RSCALE stay deferred. The
    # corpus pins the same through happy/freq_minutely, but a fixture
    # cannot name the enum member the parse must produce.
    assert parse_rrule("FREQ=MINUTELY").freq is Freq.MINUTELY
    validate_rrule("FREQ=MINUTELY")


def test_applies_the_rfc_defaults_at_parse() -> None:
    rule = parse_rrule("FREQ=DAILY")
    assert rule.interval == 1
    assert rule.week_start is Weekday.MO
    assert rule.count == 0
    assert rule.until is None
    assert rule.by_day == []


def test_weekday_numbering_is_su_zero() -> None:
    # RFC 5545 §3.3.10, which is neither ISO-8601's MO=1 nor Python's
    # date.weekday() MO=0. The conversion lives at one boundary.
    assert [int(w) for w in Weekday] == [0, 1, 2, 3, 4, 5, 6]
    assert Weekday.SU.to_weekday() == 6
    assert Weekday.MO.to_weekday() == 0
    assert str(Weekday.SU) == "SU"
    assert str(Freq.DAILY) == "DAILY"
    assert str(RecurrenceRange.THIS_AND_FUTURE) == "THISANDFUTURE"


def test_validate_rrule_raises_and_is_not_a_boolean() -> None:
    # The identity of the failure is the payload; a boolean would throw
    # it away and the rejected/ fixtures assert it. The annotation is
    # part of that contract, so it is asserted rather than assumed.
    assert get_type_hints(validate_rrule)["return"] is type(None)
    # An accepted value returns without raising, and returns nothing.
    validate_rrule("FREQ=DAILY")
    with pytest.raises(Malformed):
        validate_rrule("FOO=BAR")
    with pytest.raises(UnsupportedRrule):
        validate_rrule("FREQ=SECONDLY")


@pytest.mark.parametrize(
    ("value", "detail"),
    [
        ("FREQ=SECONDLY", "FREQ=SECONDLY"),
        ("FREQ=DAILY;RSCALE=GREGORIAN", "rule-part RSCALE"),
    ],
    ids=["freq", "rule-part"],
)
def test_unsupported_messages_name_the_parsing_scope(value: str, detail: str) -> None:
    # The wording is shared by every port and names the scope, never a
    # spec version, so it cannot go stale when the spec is re-cut.
    with pytest.raises(UnsupportedRrule) as info:
        parse_rrule(value)
    assert str(info.value) == (
        f"ErrUnsupportedRRule: rrule: {detail}: outside the RRULE parsing scope"
    )


def test_an_invalid_rule_renders_as_the_empty_string() -> None:
    # A rule with no FREQ renders empty rather than as a partial value
    # that would fail to re-parse.
    assert str(Rule()) == ""
    assert Rule().to_property().name == ""
