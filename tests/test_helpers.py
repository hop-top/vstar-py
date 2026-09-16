# SPDX-License-Identifier: MIT

"""Constructors, accessors, and the emitter gate that rebuilds fixtures."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from _fixtures import CONFORMANCE_DIR, assert_bytes_equal, crlf_to_lf
from vstar import (
    CLASS_CONFIDENTIAL,
    CLASS_PRIVATE,
    CLASS_PUBLIC,
    COMP_ALARM,
    COMP_EVENT,
    COMP_JOURNAL,
    COMP_TODO,
    EVENT_CANCELLED,
    JOURNAL_FINAL,
    REL_CHILD,
    TODO_COMPLETED,
    TODO_IN_PROCESS,
    TRANSP_OPAQUE,
    TRANSP_TRANSPARENT,
    Calendar,
    Component,
    EventStatus,
    Kind,
    MissingUid,
    Param,
    Property,
    TodoStatus,
    Transp,
    VClass,
    canonical,
    hashing,
)
from vstar.duration import Related, VDuration, alarm_trigger, event_end, parse
from vstar.helpers import (
    add_category,
    add_related_to,
    alarm_fires_at,
    categories,
    class_of,
    class_or_default,
    complete,
    due,
    event_status,
    increment_sequence,
    journal_status,
    new_absolute_alarm,
    new_alarm,
    new_calendar,
    new_card,
    new_event,
    new_free_busy,
    new_journal,
    new_relative_alarm,
    new_todo,
    percent_complete,
    priority,
    related_to,
    remove_percent_complete,
    remove_priority,
    sequence,
    set_categories,
    set_class,
    set_due,
    set_event_status,
    set_journal_status,
    set_percent_complete,
    set_priority,
    set_sequence,
    set_todo_status,
    set_transp,
    todo_status,
    transp,
    transp_or_default,
)

_T = datetime(2026, 5, 4, 12, 0, tzinfo=UTC)
_HASH = "X-VSTAR-HASH"


# --------------------------------------------------------------------
# Emitter gate — rebuild committed fixtures through the helper API
# --------------------------------------------------------------------


def test_emitter_gate_one_vtodo() -> None:
    """``rfc5545/one_vtodo`` rebuilt through the helpers matches on disk.

    The bytes and the hash both, because either alone is weak: matching
    bytes with a wrong hash means the hash is never checked, and a
    matching hash over wrong bytes cannot happen but a matching hash
    over *no* bytes can, if the comparison silently comes up empty.
    """
    cal = new_calendar("-//V*//OneVTODO//EN")
    c = new_todo("abc-123", _T)
    # DUE is not in the fixture; the constructor writes it, so it goes.
    c.remove("DUE")
    c.set(Property("DTSTAMP", [], "20260504T120000Z"))
    c.set(Property("SUMMARY", [], "Buy milk"))
    set_priority(c, 3)
    cal.append(c)

    want = (CONFORMANCE_DIR / "rfc5545" / "one_vtodo.canonical").read_bytes()
    got = canonical.calendar(cal)
    assert_bytes_equal(crlf_to_lf(got), want, "one_vtodo canonical")

    want_hash = (CONFORMANCE_DIR / "rfc5545" / "one_vtodo.hash").read_text().strip()
    assert hashing.calendar(cal) == want_hash


def test_emitter_gate_rfc6350_minimal() -> None:
    """``rfc6350/minimal`` rebuilt through :func:`new_card` matches.

    ``new_card`` writes a ``KIND`` unconditionally and the fixture has
    none, so the gate clears it after construction. That is the
    documented divergence, not a defect: RFC 6350 §6.1.4 treats an
    absent ``KIND`` as ``individual``, and the constructor states what
    it built rather than relying on the reader's default.
    """
    card = new_card("urn:uuid:11111111-1111-1111-1111-111111111111", Kind.NONE)
    assert card.get("KIND") is not None, "constructor should write KIND"
    assert card.kind == Kind.INDIVIDUAL, "empty kind should default"

    card.remove("KIND")
    card.kind = Kind.NONE
    # VERSION goes too. Canonicalization prepends its own (RFC 6350 §3.3
    # puts it immediately after BEGIN:VCARD) without absorbing one the
    # card already carries, so the constructor's copy would canonicalize
    # as a second VERSION line. The reference has the same shape; see
    # the note in the port's conformance report.
    card.remove("VERSION")
    card.set(Property("FN", [], "Jad Bitar"))

    want = (CONFORMANCE_DIR / "rfc6350" / "minimal.canonical").read_bytes()
    assert_bytes_equal(crlf_to_lf(canonical.card(card)), want, "minimal canonical")

    want_hash = (CONFORMANCE_DIR / "rfc6350" / "minimal.hash").read_text().strip()
    assert hashing.card(card) == want_hash


# --------------------------------------------------------------------
# Constructors
# --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("build", "want_type", "want_props"),
    [
        (lambda: new_todo("u", _T), "VTODO", ("UID", "DTSTAMP", "DUE")),
        (lambda: new_journal("u", _T), "VJOURNAL", ("UID", "DTSTAMP", "DTSTART")),
        (
            lambda: new_event("u", _T, _T),
            "VEVENT",
            ("UID", "DTSTAMP", "DTSTART", "DTEND"),
        ),
        (
            lambda: new_free_busy("u", _T, _T),
            "VFREEBUSY",
            ("UID", "DTSTAMP", "DTSTART", "DTEND"),
        ),
        (
            lambda: new_alarm("u", "DISPLAY", "-PT15M"),
            "VALARM",
            ("UID", "DTSTAMP", "ACTION", "TRIGGER"),
        ),
    ],
)
def test_constructor_shape(
    build: object, want_type: str, want_props: tuple[str, ...]
) -> None:
    """Each constructor writes its properties, in order, then the hash."""
    c = build()  # type: ignore[operator]
    assert str(c.type) == want_type
    assert [p.name for p in c.props] == [*want_props, _HASH]


@pytest.mark.parametrize(
    "build",
    [
        lambda: new_todo("", _T),
        lambda: new_journal("", _T),
        lambda: new_event("", _T, _T),
        lambda: new_free_busy("", _T, _T),
        lambda: new_alarm("", "DISPLAY", "-PT15M"),
        lambda: new_relative_alarm("", "DISPLAY", VDuration(), Related.START),
        lambda: new_absolute_alarm("", "DISPLAY", _T),
    ],
)
def test_empty_uid_is_refused(build: object) -> None:
    """V* requires a UID on every persisted component (spec/02)."""
    with pytest.raises(MissingUid):
        build()  # type: ignore[operator]


@pytest.mark.parametrize(
    "build",
    [
        lambda: new_todo("u", _T),
        lambda: new_journal("u", _T),
        lambda: new_event("u", _T, _T),
        lambda: new_free_busy("u", _T, _T),
        lambda: new_alarm("u", "DISPLAY", "-PT15M"),
        lambda: new_relative_alarm("u", "DISPLAY", parse("-PT15M"), Related.START),
        lambda: new_absolute_alarm("u", "DISPLAY", _T),
    ],
)
def test_constructor_stamps_a_verifying_hash(build: object) -> None:
    """Every constructor leaves an ``X-VSTAR-HASH`` that verifies.

    Canonicalization strips this property (spec/03 rule 7), so no byte
    comparison against a fixture can see whether it was written. This
    assertion is the only thing standing between a dropped hash stamp
    and a green suite.
    """
    c = build()  # type: ignore[operator]
    assert hashing.get_x_vstar(c) is not None, "constructor wrote no X-VSTAR-HASH"
    ok, want, got = hashing.verify_x_vstar(c)
    assert ok, f"stored hash {got} does not match {want}"


def test_new_calendar_defaults_the_prod_id() -> None:
    """An empty PRODID takes the default, never an empty value.

    The default is version-free and language-free: PRODID is part of
    the hashed canonical form, so it must not change across releases or
    differ between ports.
    """
    assert new_calendar("").prod_id == "-//hop-top//vstar//EN"
    assert new_calendar("-//X//Y//EN").prod_id == "-//X//Y//EN"


def test_new_card_writes_version_kind_uid() -> None:
    """The card's three constructed properties, in order."""
    card = new_card("u", Kind.ORG)
    assert [p.name for p in card.props] == ["VERSION", "KIND", "UID"]
    assert card.kind == Kind.ORG
    kind = card.get("KIND")
    assert kind is not None and kind.value == "org"


def test_new_card_accepts_an_empty_uid() -> None:
    """The encoder, not the constructor, is where a UID-less card fails."""
    assert new_card("", Kind.NONE).uid == ""


def test_relative_alarm_leaves_related_start_implicit() -> None:
    """``RELATED=START`` is the RFC default and stays off the wire."""
    c = new_relative_alarm("u", "DISPLAY", parse("-PT15M"), Related.START)
    trigger = c.get("TRIGGER")
    assert trigger is not None
    assert trigger.params == []
    assert trigger.value == "-PT15M"

    c_end = new_relative_alarm("u", "DISPLAY", parse("-PT15M"), Related.END)
    trigger_end = c_end.get("TRIGGER")
    assert trigger_end is not None
    assert [(p.name, p.value) for p in trigger_end.params] == [("RELATED", "END")]


def test_absolute_alarm_declares_its_value_type() -> None:
    """``VALUE=DATE-TIME`` is explicit, so no consumer has to infer it."""
    c = new_absolute_alarm("u", "DISPLAY", _T)
    trigger = c.get("TRIGGER")
    assert trigger is not None
    assert [(p.name, p.value) for p in trigger.params] == [("VALUE", "DATE-TIME")]
    assert trigger.value == "20260504T120000Z"


def test_alarm_fires_at_resolves_against_the_parent() -> None:
    """The offset is measured from the parent's anchor."""
    parent = new_event("e", _T, datetime(2026, 5, 4, 13, 0, tzinfo=UTC))
    alarm = new_relative_alarm("a", "DISPLAY", parse("-PT15M"), Related.START)
    assert alarm_fires_at(alarm, parent, Calendar()) == datetime(
        2026, 5, 4, 11, 45, tzinfo=UTC
    )
    assert alarm_trigger(alarm).relative is True


# --------------------------------------------------------------------
# event_end does NOT fall back to a VTODO's DUE
# --------------------------------------------------------------------


def test_event_end_does_not_fall_back_to_due() -> None:
    """``event_end`` knows ``DTEND`` and ``DTSTART``+``DURATION`` only.

    The VTODO ``DUE`` fallback lives in the trigger's anchor resolution,
    not here. Folding it in would make ``event_end`` answer a question
    about a VTODO that a caller asking for an *event's* end never asked.
    """
    todo = Component(type=COMP_TODO)
    todo.set_due(_T)
    assert event_end(todo, Calendar()) is None

    ev = Component(type=COMP_EVENT)
    ev.set_dtstart(_T)
    ev.set_dtend(datetime(2026, 5, 4, 13, 0, tzinfo=UTC))
    assert event_end(ev, Calendar()) == datetime(2026, 5, 4, 13, 0, tzinfo=UTC)


def test_trigger_anchor_is_where_due_is_honoured() -> None:
    """A ``RELATED=END`` trigger on a VTODO anchors to ``DUE``."""
    todo = new_todo("t", datetime(2026, 5, 4, 17, 0, tzinfo=UTC))
    alarm = new_relative_alarm("a", "DISPLAY", parse("-PT30M"), Related.END)
    assert alarm_fires_at(alarm, todo, Calendar()) == datetime(
        2026, 5, 4, 16, 30, tzinfo=UTC
    )


# --------------------------------------------------------------------
# Categories
# --------------------------------------------------------------------


def test_categories_splits_trims_and_drops_empties() -> None:
    """A comma-delimited value, per RFC 5545 §3.8.1.2."""
    c = Component(type=COMP_TODO, props=[Property("CATEGORIES", [], " a , ,b,, c ")])
    assert categories(c) == ["a", "b", "c"]
    assert categories(Component(type=COMP_TODO)) == []


def test_set_categories_dedupes_and_joins_without_spaces() -> None:
    """First-seen order survives; the join is the canonical form."""
    c = Component(type=COMP_TODO)
    set_categories(c, [" x ", "y", "x", "  ", "z"])
    p = c.get("CATEGORIES")
    assert p is not None and p.value == "x,y,z"


def test_set_categories_with_nothing_removes_the_property() -> None:
    """An empty list is "no categories", not a property holding nothing."""
    c = Component(type=COMP_TODO, props=[Property("CATEGORIES", [], "a")])
    set_categories(c, [])
    assert c.get("CATEGORIES") is None


def test_add_category_is_idempotent_and_leaves_the_hash_alone() -> None:
    """A no-op change does not restamp an unaltered component."""
    c = Component(type=COMP_TODO)
    add_category(c, "a")
    before = hashing.get_x_vstar(c)
    add_category(c, "a")
    add_category(c, "")
    assert hashing.get_x_vstar(c) == before
    assert categories(c) == ["a"]


# --------------------------------------------------------------------
# Classification and transparency
# --------------------------------------------------------------------


def test_class_reports_absence_and_defaults_separately() -> None:
    """Only the ``_or_default`` form applies the RFC default."""
    c = Component(type=COMP_EVENT)
    assert class_of(c) is None
    assert class_or_default(c) is VClass.PUBLIC
    set_class(c, CLASS_PRIVATE)
    assert class_of(c) is VClass.PRIVATE
    assert class_or_default(c) is VClass.PRIVATE


def test_class_rejects_an_unrecognized_wire_value() -> None:
    """A value outside the vocabulary reads as absence."""
    c = Component(type=COMP_EVENT, props=[Property("CLASS", [], "SECRET")])
    assert class_of(c) is None
    assert class_or_default(c) is CLASS_PUBLIC


def test_set_class_is_a_no_op_off_its_types() -> None:
    """``CLASS`` applies to VEVENT, VTODO and VJOURNAL alone."""
    c = Component(type=COMP_ALARM)
    set_class(c, CLASS_CONFIDENTIAL)
    assert c.get("CLASS") is None
    assert hashing.get_x_vstar(c) is None


def test_transp_defaults_to_opaque_and_applies_to_events_only() -> None:
    """Only an event blocks time, so only an event carries ``TRANSP``."""
    ev = Component(type=COMP_EVENT)
    assert transp(ev) is None
    assert transp_or_default(ev) is TRANSP_OPAQUE
    set_transp(ev, TRANSP_TRANSPARENT)
    assert transp(ev) is Transp.TRANSPARENT

    todo = Component(type=COMP_TODO)
    set_transp(todo, TRANSP_TRANSPARENT)
    assert todo.get("TRANSP") is None


# --------------------------------------------------------------------
# Relations
# --------------------------------------------------------------------


def test_related_to_defaults_the_reltype() -> None:
    """An absent ``RELTYPE`` is ``PARENT`` per RFC 5545 §3.2.15."""
    c = Component(type=COMP_TODO)
    add_related_to(c, "parent-uid", "")
    refs = related_to(c)
    assert len(refs) == 1
    assert refs[0].uid == "parent-uid"
    assert refs[0].rel_type == "PARENT"
    assert c.get_all("RELATED-TO")[0].params == []


def test_add_related_to_appends_rather_than_replaces() -> None:
    """A component may relate to many others, each its own property."""
    c = Component(type=COMP_TODO)
    add_related_to(c, "a", REL_CHILD)
    add_related_to(c, "b", REL_CHILD)
    assert [r.uid for r in related_to(c)] == ["a", "b"]
    assert [r.rel_type for r in related_to(c)] == ["CHILD", "CHILD"]


def test_add_related_to_ignores_an_empty_uid() -> None:
    """A reference to nothing is not a relationship."""
    c = Component(type=COMP_TODO)
    add_related_to(c, "", REL_CHILD)
    assert related_to(c) == []


def test_reltype_param_matches_case_insensitively() -> None:
    """The parameter name is matched without regard to wire casing."""
    prop = Property("RELATED-TO", [Param("reltype", "CHILD")], "x")
    c = Component(type=COMP_TODO, props=[prop])
    assert related_to(c)[0].rel_type == "CHILD"


# --------------------------------------------------------------------
# Integer-valued properties
# --------------------------------------------------------------------


def test_sequence_reports_absence_rather_than_zero() -> None:
    """``None`` and ``0`` are different facts about a component."""
    c = Component(type=COMP_TODO)
    assert sequence(c) is None
    set_sequence(c, 0)
    assert sequence(c) == 0


def test_increment_sequence_treats_absent_as_zero() -> None:
    """The first increment of a never-revised component yields 1."""
    c = Component(type=COMP_TODO)
    increment_sequence(c)
    assert sequence(c) == 1
    increment_sequence(c)
    assert sequence(c) == 2


@pytest.mark.parametrize("raw", ["03", "+3", " 3", "-1", "three", ""])
def test_integer_parse_must_round_trip(raw: str) -> None:
    """A value that does not render back to itself is not that integer."""
    c = Component(type=COMP_TODO, props=[Property("SEQUENCE", [], raw)])
    assert sequence(c) is None


def test_priority_range_is_enforced_without_clamping() -> None:
    """Out of range is a no-op; clamping would record an unasked value."""
    c = Component(type=COMP_TODO)
    set_priority(c, 12)
    assert c.get("PRIORITY") is None
    set_priority(c, 3)
    set_priority(c, -1)
    assert priority(c) == 3
    remove_priority(c)
    assert priority(c) is None


def test_priority_zero_is_a_real_value() -> None:
    """RFC 5545 §3.8.1.9 makes 0 "undefined", not "unset"."""
    c = Component(type=COMP_TODO)
    set_priority(c, 0)
    assert priority(c) == 0
    assert c.get("PRIORITY") is not None


def test_priority_does_not_apply_to_journals() -> None:
    """``PRIORITY`` is scheduling-only."""
    c = Component(type=COMP_JOURNAL)
    set_priority(c, 5)
    assert c.get("PRIORITY") is None


def test_percent_complete_is_vtodo_only_and_bounded() -> None:
    """0-100 on a VTODO; anything else is a no-op."""
    c = Component(type=COMP_TODO)
    set_percent_complete(c, 101)
    assert percent_complete(c) is None
    set_percent_complete(c, 50)
    assert percent_complete(c) == 50
    remove_percent_complete(c)
    assert percent_complete(c) is None

    ev = Component(type=COMP_EVENT)
    set_percent_complete(ev, 50)
    assert ev.get("PERCENT-COMPLETE") is None


def test_set_percent_complete_does_not_complete_the_task() -> None:
    """100 percent is progress; ``complete`` is the state change."""
    c = Component(type=COMP_TODO)
    set_percent_complete(c, 100)
    assert c.get("STATUS") is None
    assert c.get("COMPLETED") is None


# --------------------------------------------------------------------
# Status
# --------------------------------------------------------------------


def test_the_three_status_pairs_are_type_scoped() -> None:
    """Each setter writes only on its own component type."""
    todo = Component(type=COMP_TODO)
    set_todo_status(todo, TODO_IN_PROCESS)
    assert todo_status(todo) is TodoStatus.IN_PROCESS

    ev = Component(type=COMP_EVENT)
    set_event_status(ev, EVENT_CANCELLED)
    assert event_status(ev) is EventStatus.CANCELLED
    set_todo_status(ev, TODO_COMPLETED)
    assert event_status(ev) is EventStatus.CANCELLED

    jr = Component(type=COMP_JOURNAL)
    set_journal_status(jr, JOURNAL_FINAL)
    assert journal_status(jr) == "FINAL"


def test_complete_writes_all_three_properties_and_one_hash() -> None:
    """ "Done" is status, timestamp and progress together, hashed once."""
    c = new_todo("t", _T)
    complete(c, _T)

    status = c.get("STATUS")
    assert status is not None and status.value == "COMPLETED"
    assert c.get("COMPLETED") is not None
    pct = c.get("PERCENT-COMPLETE")
    assert pct is not None and pct.value == "100"

    ok, want, got = hashing.verify_x_vstar(c)
    assert ok, f"stored hash {got} does not match {want}"


def test_complete_is_a_no_op_off_vtodo() -> None:
    """Only a task can be completed."""
    ev = Component(type=COMP_EVENT)
    complete(ev, _T)
    assert ev.get("STATUS") is None


# --------------------------------------------------------------------
# Due
# --------------------------------------------------------------------


def test_due_round_trips_and_refreshes_the_hash() -> None:
    """The reader and writer pair, with the hash restamped after."""
    c = Component(type=COMP_TODO)
    set_due(c, _T)
    assert due(c, Calendar()) == _T
    ok, _want, _got = hashing.verify_x_vstar(c)
    assert ok
