# SPDX-License-Identifier: MIT

"""The in-memory data model: accessors, wire-string enums, VDate."""

from __future__ import annotations

import vstar
from vstar import (
    DEFAULT_REL_TYPE,
    VALUE_DATE,
    VALUE_PARAM,
    Calendar,
    Card,
    Component,
    CompType,
    EventStatus,
    JournalStatus,
    Kind,
    Param,
    Property,
    TodoStatus,
    Transp,
    VClass,
    VDate,
    date_of,
    format_date,
    parse_date,
    parse_rel_type,
    property_equal,
)


def prop(name: str, value: str, *params: Param) -> Property:
    return Property(name=name, params=list(params), value=value)


class TestProperty:
    def test_property_equal_folds_names_and_sorts_params(self) -> None:
        a = prop("summary", "x", Param("CN", "Jad"), Param("ROLE", "CHAIR"))
        b = prop("SUMMARY", "x", Param("role", "CHAIR"), Param("cn", "Jad"))
        assert property_equal(a, b)

    def test_property_equal_is_case_sensitive_on_value(self) -> None:
        assert not property_equal(prop("SUMMARY", "x"), prop("SUMMARY", "X"))

    def test_property_equal_rejects_differing_param_counts(self) -> None:
        assert not property_equal(prop("X", "v", Param("A", "1")), prop("X", "v"))

    def test_property_equal_does_not_mutate_inputs(self) -> None:
        a = prop("X", "v", Param("B", "1"), Param("A", "2"))
        property_equal(a, a)
        assert [p.name for p in a.params] == ["B", "A"]


class TestComponent:
    def test_get_is_case_insensitive(self) -> None:
        c = Component(type=CompType.TODO, props=[prop("UID", "x")], sub=[])
        found = c.get("uid")
        assert found is not None
        assert found.value == "x"

    def test_get_returns_none_when_absent(self) -> None:
        assert Component(type=CompType.TODO, props=[], sub=[]).get("UID") is None

    def test_get_all_returns_every_match_in_order(self) -> None:
        c = Component(
            type=CompType.EVENT,
            props=[prop("CATEGORIES", "a"), prop("UID", "u"), prop("categories", "b")],
            sub=[],
        )
        assert [p.value for p in c.get_all("CATEGORIES")] == ["a", "b"]

    def test_set_replaces_in_place_and_drops_duplicates(self) -> None:
        c = Component(
            type=CompType.EVENT,
            props=[
                prop("A", "1"),
                prop("UID", "old"),
                prop("uid", "dup"),
                prop("B", "2"),
            ],
            sub=[],
        )
        c.set(prop("UID", "new"))
        assert [(p.name, p.value) for p in c.props] == [
            ("A", "1"),
            ("UID", "new"),
            ("B", "2"),
        ]

    def test_set_appends_when_absent(self) -> None:
        c = Component(type=CompType.EVENT, props=[prop("A", "1")], sub=[])
        c.set(prop("UID", "x"))
        assert [p.name for p in c.props] == ["A", "UID"]

    def test_add_keeps_same_named_properties(self) -> None:
        c = Component(type=CompType.EVENT, props=[prop("CATEGORIES", "a")], sub=[])
        c.add(prop("CATEGORIES", "b"))
        assert len(c.props) == 2

    def test_remove_deletes_every_match(self) -> None:
        c = Component(
            type=CompType.EVENT,
            props=[prop("X", "1"), prop("x", "2"), prop("Y", "3")],
            sub=[],
        )
        c.remove("X")
        assert [p.name for p in c.props] == ["Y"]

    def test_uid_and_dtstamp_raw_default_to_empty(self) -> None:
        c = Component(type=CompType.EVENT, props=[], sub=[])
        assert c.uid() == ""
        assert c.dtstamp_raw() == ""

    def test_uid_and_dtstamp_raw_read_the_property(self) -> None:
        c = Component(
            type=CompType.EVENT,
            props=[prop("UID", "u"), prop("DTSTAMP", "20260515T120000Z")],
            sub=[],
        )
        assert c.uid() == "u"
        assert c.dtstamp_raw() == "20260515T120000Z"


class TestCalendar:
    def test_find_matches_uid_case_sensitively(self) -> None:
        cal = Calendar(
            prod_id="-//t//EN",
            components=[
                Component(type=CompType.TODO, props=[prop("UID", "A")], sub=[])
            ],
        )
        assert cal.find("A") is not None
        assert cal.find("a") is None

    def test_append_and_filter(self) -> None:
        cal = Calendar(prod_id="-//t//EN", components=[])
        cal.append(Component(type=CompType.TODO, props=[], sub=[]))
        cal.append(Component(type=CompType.EVENT, props=[], sub=[]))
        assert len(cal.filter(CompType.TODO)) == 1
        assert cal.filter(CompType.JOURNAL) == []


class TestCard:
    def test_accessors_mirror_component(self) -> None:
        card = Card(uid="u", kind=Kind.INDIVIDUAL, props=[prop("FN", "Jad")])
        found = card.get("fn")
        assert found is not None and found.value == "Jad"
        card.add(prop("FN", "J"))
        assert len(card.get_all("FN")) == 2
        card.set(prop("FN", "Only"))
        assert [p.value for p in card.get_all("FN")] == ["Only"]
        card.remove("FN")
        assert card.props == []


class TestEnums:
    def test_wire_values_are_normative(self) -> None:
        # ``.value`` rather than a bare ``==``: the assertion is about
        # the wire string, and mypy rejects a StrEnum-vs-str-literal
        # comparison as non-overlapping even though it is true at run
        # time.
        assert CompType.CALENDAR.value == "VCALENDAR"
        assert CompType.ALARM.value == "VALARM"
        assert Kind.ORG.value == "org"
        assert Kind.NONE.value == ""
        assert TodoStatus.NEEDS_ACTION.value == "NEEDS-ACTION"
        assert TodoStatus.IN_PROCESS.value == "IN-PROCESS"
        assert EventStatus.TENTATIVE.value == "TENTATIVE"
        assert JournalStatus.DRAFT.value == "DRAFT"
        assert VClass.CONFIDENTIAL.value == "CONFIDENTIAL"
        assert Transp.TRANSPARENT.value == "TRANSPARENT"

    def test_every_cancelled_spelling_is_the_rfc_double_l(self) -> None:
        for member in (
            TodoStatus.CANCELLED,
            EventStatus.CANCELLED,
            JournalStatus.CANCELLED,
        ):
            assert member.value == "CANCELLED"

    def test_status_types_are_distinct(self) -> None:
        # Three vocabularies, three types. The RFC scopes each to one
        # component type, so a cross-type assignment must not typecheck
        # and the members must not be the same object.
        assert TodoStatus.CANCELLED is not EventStatus.CANCELLED  # type: ignore[comparison-overlap]
        assert JournalStatus.CANCELLED is not EventStatus.CANCELLED  # type: ignore[comparison-overlap]
        assert not hasattr(vstar, "Status")

    def test_the_open_enums_admit_an_unregistered_wire_string(self) -> None:
        # STANDARD and DAYLIGHT are real RFC 5545 components outside the
        # modelled vocabulary; a closed enum would make them unreadable.
        assert CompType("STANDARD").value == "STANDARD"
        assert CompType("DAYLIGHT").value == "DAYLIGHT"
        assert CompType("X-CUSTOM").value == "X-CUSTOM"
        assert Kind("location").value == "location"

    def test_value_constants(self) -> None:
        assert VALUE_PARAM == "VALUE"
        assert VALUE_DATE == "DATE"


class TestRelType:
    def test_empty_yields_parent_and_true(self) -> None:
        assert parse_rel_type("") == (DEFAULT_REL_TYPE, True)
        assert DEFAULT_REL_TYPE == "PARENT"

    def test_registered_value_folds_case(self) -> None:
        assert parse_rel_type("depends-on") == ("DEPENDS-ON", True)

    def test_unregistered_value_returns_verbatim_with_false(self) -> None:
        assert parse_rel_type("X-CUSTOM") == ("X-CUSTOM", False)

    def test_registry_is_the_rfc_9253_vocabulary(self) -> None:
        for value in (
            "PARENT",
            "CHILD",
            "SIBLING",
            "FINISHTOSTART",
            "FINISHTOFINISH",
            "STARTTOFINISH",
            "STARTTOSTART",
            "DEPENDS-ON",
            "FIRST",
            "NEXT",
            "CONCEPT",
            "REFID",
        ):
            assert parse_rel_type(value) == (value, True)

    def test_equal_fold(self) -> None:
        from vstar import equal_fold

        assert equal_fold("PARENT", "parent")
        assert not equal_fold("PARENT", "CHILD")


class TestVDate:
    def test_is_zero(self) -> None:
        assert VDate(0, 0, 0).is_zero()
        assert not VDate(2026, 5, 15).is_zero()

    def test_format_date_pads_to_eight_octets(self) -> None:
        assert format_date(VDate(2026, 5, 15)) == "20260515"
        assert format_date(VDate(7, 1, 2)) == "00070102"

    def test_format_date_of_zero_is_empty(self) -> None:
        assert format_date(VDate(0, 0, 0)) == ""

    def test_format_date_rejects_out_of_range_fields(self) -> None:
        assert format_date(VDate(2026, 13, 1)) == ""
        assert format_date(VDate(2026, 1, 32)) == ""
        assert format_date(VDate(10000, 1, 1)) == ""

    def test_str_is_the_wire_form(self) -> None:
        assert str(VDate(2026, 5, 15)) == "20260515"

    def test_parse_date_round_trips(self) -> None:
        assert parse_date("20260515") == VDate(2026, 5, 15)

    def test_parse_date_rejects_non_date_shapes(self) -> None:
        for bad in (
            "",
            "2026-05-15",
            "20260515T120000Z",
            "2026051",
            "202605155",
            " 20260515",
            "2026051a",
            "20260230",
            "20260229",
            "20261301",
            "20260500",
        ):
            assert parse_date(bad) is None, bad

    def test_parse_date_accepts_a_leap_day(self) -> None:
        assert parse_date("20240229") == VDate(2024, 2, 29)

    def test_date_of_uses_the_datetime_fields(self) -> None:
        from datetime import UTC, datetime

        assert date_of(datetime(2026, 5, 15, 20, 0, tzinfo=UTC)) == VDate(2026, 5, 15)

    def test_to_datetime_is_midnight_utc(self) -> None:
        from datetime import UTC, datetime

        assert VDate(2026, 5, 15).to_datetime() == datetime(2026, 5, 15, tzinfo=UTC)


class TestComponentDateAccessors:
    def _all_day(self, name: str, value: str = "20260515") -> Component:
        return Component(
            type=CompType.TODO,
            props=[prop(name, value, Param(VALUE_PARAM, VALUE_DATE))],
            sub=[],
        )

    def test_is_date_only_requires_the_value_param(self) -> None:
        assert self._all_day("DUE").is_date_only("DUE")
        untagged = Component(
            type=CompType.TODO, props=[prop("DUE", "20260515")], sub=[]
        )
        assert not untagged.is_date_only("DUE")
        assert not untagged.is_date_only("DTSTART")

    def test_date_accessors_require_value_date(self) -> None:
        assert self._all_day("DTSTART").dtstart_date() == VDate(2026, 5, 15)
        assert self._all_day("DTEND").dtend_date() == VDate(2026, 5, 15)
        assert self._all_day("DUE").due_date() == VDate(2026, 5, 15)
        assert self._all_day("COMPLETED").completed_date() == VDate(2026, 5, 15)

    def test_untagged_value_does_not_surface_as_a_date(self) -> None:
        c = Component(type=CompType.TODO, props=[prop("DUE", "20260515")], sub=[])
        assert c.due_date() is None

    def test_malformed_date_value_does_not_surface(self) -> None:
        assert self._all_day("DUE", "20260230").due_date() is None

    def test_setters_write_the_value_param_and_drop_stale_ones(self) -> None:
        c = Component(
            type=CompType.TODO,
            props=[prop("DTSTART", "20260515T120000", Param("TZID", "X"))],
            sub=[],
        )
        c.set_dtstart_date(VDate(2026, 5, 16))
        written = c.get("DTSTART")
        assert written is not None
        assert written.value == "20260516"
        assert [(p.name, p.value) for p in written.params] == [
            (VALUE_PARAM, VALUE_DATE)
        ]

    def test_setting_the_zero_date_removes_the_property(self) -> None:
        c = self._all_day("DUE")
        c.set_due_date(VDate(0, 0, 0))
        assert c.get("DUE") is None

    def test_every_date_setter_exists(self) -> None:
        c = Component(type=CompType.TODO, props=[], sub=[])
        d = VDate(2026, 5, 15)
        c.set_dtstart_date(d)
        c.set_dtend_date(d)
        c.set_due_date(d)
        c.set_completed_date(d)
        assert [p.name for p in c.props] == ["DTSTART", "DTEND", "DUE", "COMPLETED"]
