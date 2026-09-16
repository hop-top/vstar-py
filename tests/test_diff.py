# SPDX-License-Identifier: MIT

"""The structural-diff gate, against ``spec/behavior/diff/``."""

from __future__ import annotations

from typing import Any

import pytest

from _fixtures import BEHAVIOR_DIR, behavior_json, behavior_stems
from vstar import (
    COMP_ALARM,
    COMP_TODO,
    Calendar,
    Card,
    Component,
    Param,
    Property,
)
from vstar.codec import rfc5545
from vstar.diff import (
    ComponentDiff,
    DiffOp,
    PropertyDiff,
    calendar_equal,
    card_equal,
    component_equal,
    of_calendar,
    of_card,
    of_component,
)

#: Every ``<name>.diff.json`` stem, walked rather than listed.
STEMS = behavior_stems("diff", ".diff.json")

#: The fixture's op tokens. Lowercase by design, so a port needs no
#: case convention of its own; the capitalized ``str()`` spelling is
#: display text and is never compared against a fixture.
_OP_TOKENS = {DiffOp.ADDED: "add", DiffOp.REMOVED: "remove", DiffOp.CHANGED: "change"}


def test_stems_are_discovered() -> None:
    """A vacuous walk would make every case below disappear silently."""
    assert len(STEMS) == 7


def _calendar(stem: str, side: str) -> Calendar:
    return rfc5545.parse((BEHAVIOR_DIR / "diff" / f"{stem}.{side}.ics").read_bytes())


def _uid_from_path(path: str) -> str:
    """The UID inside ``TYPE[uid=…]``, or empty for a positional path."""
    marker = "[uid="
    i = path.rfind(marker)
    if i < 0 or not path.endswith("]"):
        return ""
    return path[i + len(marker) : -1]


def _params_json(params: list[Param]) -> list[dict[str, str]] | None:
    """The fixture's parameter list, or ``None`` when there are none.

    ``None`` rather than ``[]``: the generator marks these fields
    omit-when-empty, so an empty list is absent from the JSON entirely
    and comes back missing on decode.
    """
    if not params:
        return None
    return [{"name": p.name, "value": p.value} for p in params]


def _op_json(pd: PropertyDiff) -> dict[str, Any]:
    """One :class:`PropertyDiff` in the fixture's shape."""
    out: dict[str, Any] = {
        "op": _OP_TOKENS[pd.op],
        "property": pd.property.name or pd.old.name,
        "before": None,
        "after": None,
    }
    if pd.op is DiffOp.ADDED:
        out["after"] = pd.property.value
        _put(out, "after_params", _params_json(pd.property.params))
    elif pd.op is DiffOp.REMOVED:
        out["before"] = pd.property.value
        _put(out, "before_params", _params_json(pd.property.params))
    else:
        out["before"] = pd.old.value
        out["after"] = pd.property.value
        _put(out, "before_params", _params_json(pd.old.params))
        _put(out, "after_params", _params_json(pd.property.params))
    return out


def _put(d: dict[str, Any], key: str, value: object) -> None:
    """Set ``key`` only when ``value`` is present, mirroring omitempty."""
    if value is not None:
        d[key] = value


def _diff_json(d: ComponentDiff) -> dict[str, Any]:
    """One :class:`ComponentDiff` in the fixture's shape.

    Nothing is sorted here. The diff's own emission order — components
    in pairing order, properties by case-insensitive name — is the
    contract, and re-sorting would hide a port that got it wrong.
    """
    out: dict[str, Any] = {
        "uid": _uid_from_path(d.path),
        "path": d.path,
        "ops": [_op_json(pd) for pd in d.properties],
    }
    subs = [s for s in d.sub_diffs if not s.is_empty()]
    if subs:
        out["subs"] = [_diff_json(s) for s in subs]
    return out


@pytest.mark.parametrize("stem", STEMS)
def test_diff_matches_fixture(stem: str) -> None:
    """``of_calendar`` reports exactly what the fixture records."""
    want = behavior_json("diff", f"{stem}.diff.json")
    diffs = of_calendar(_calendar(stem, "a"), _calendar(stem, "b"))
    got = [_diff_json(d) for d in diffs]
    assert got == want


def test_identical_calendars_produce_no_entries() -> None:
    """Two equal documents yield ``[]``, not an entry with no ops."""
    assert behavior_json("diff", "identical.diff.json") == []
    a, b = _calendar("identical", "a"), _calendar("identical", "b")
    assert of_calendar(a, b) == []


def test_op_numbering_starts_at_one() -> None:
    """No member is a default-constructible zero."""
    assert DiffOp.ADDED.value == 1
    assert DiffOp.REMOVED.value == 2
    assert DiffOp.CHANGED.value == 3


def test_op_str_is_the_display_spelling() -> None:
    """``str()`` renders display text, not the fixture token."""
    assert str(DiffOp.ADDED) == "Added"
    assert str(DiffOp.REMOVED) == "Removed"
    assert str(DiffOp.CHANGED) == "Changed"


def test_hash_property_is_excluded_from_both_sides() -> None:
    """A restamped hash is not a content change."""
    a = _todo(Property("UID", [], "t"), Property("X-VSTAR-HASH", [], "a"))
    b = _todo(Property("UID", [], "t"), Property("x-vstar-hash", [], "b"))
    assert of_component(a, b).is_empty()


def test_properties_order_by_case_insensitive_name() -> None:
    """The emission order is by upper-cased name, not input order."""
    a = Component(type=COMP_TODO)
    b = Component(
        type=COMP_TODO,
        props=[
            Property("summary", [], "s"),
            Property("DTSTAMP", [], "d"),
            Property("uid", [], "u"),
        ],
    )
    assert [pd.property.name for pd in of_component(a, b).properties] == [
        "DTSTAMP",
        "summary",
        "uid",
    ]


def test_repeated_properties_pair_positionally() -> None:
    """The i-th on each side pairs; surplus becomes an add or remove."""
    a = _todo(Property("ATTENDEE", [], "x"), Property("ATTENDEE", [], "y"))
    b = Component(
        type=COMP_TODO,
        props=[
            Property("ATTENDEE", [], "x"),
            Property("ATTENDEE", [], "z"),
            Property("ATTENDEE", [], "w"),
        ],
    )
    ops = of_component(a, b).properties
    assert [(pd.op, pd.property.value) for pd in ops] == [
        (DiffOp.CHANGED, "z"),
        (DiffOp.ADDED, "w"),
    ]
    assert ops[0].old.value == "y"


def test_parameter_only_change_is_a_change() -> None:
    """Equal values with differing parameters still report a change."""
    a = _todo(Property("DUE", [Param("TZID", "America/Montreal")], "X"))
    b = _todo(Property("DUE", [Param("TZID", "Europe/Paris")], "X"))
    ops = of_component(a, b).properties
    assert len(ops) == 1
    assert ops[0].op is DiffOp.CHANGED
    assert ops[0].old.value == ops[0].property.value == "X"


def test_uid_less_subs_pair_positionally() -> None:
    """A VALARM with no UID pairs by index within its type bucket."""
    a = Component(type=COMP_TODO, sub=[_alarm("DISPLAY"), _alarm("AUDIO")])
    b = Component(type=COMP_TODO, sub=[_alarm("DISPLAY"), _alarm("EMAIL")])
    subs = of_component(a, b).sub_diffs
    assert [s.path for s in subs] == ["VALARM[#1]"]
    assert subs[0].properties[0].op is DiffOp.CHANGED


def test_is_empty_is_recursive() -> None:
    """A diff whose only change is nested is not empty."""
    nested = ComponentDiff(
        path="VALARM[#0]",
        properties=[
            PropertyDiff(op=DiffOp.ADDED, property=Property("ACTION", [], "D"))
        ],
    )
    assert not ComponentDiff(path="p", sub_diffs=[nested]).is_empty()
    assert ComponentDiff(path="p", sub_diffs=[ComponentDiff(path="q")]).is_empty()


def test_str_renders_the_block() -> None:
    """The unified-diff-ish rendering, two spaces per nesting level."""
    d = ComponentDiff(
        path="VCALENDAR.VTODO[uid=t]",
        properties=[
            PropertyDiff(
                op=DiffOp.ADDED,
                property=Property("DUE", [], "20260101T000000Z"),
            ),
            PropertyDiff(
                op=DiffOp.CHANGED,
                property=Property("SUMMARY", [], "new"),
                old=Property("SUMMARY", [], "old"),
            ),
            PropertyDiff(op=DiffOp.REMOVED, property=Property("PRIORITY", [], "3")),
        ],
        sub_diffs=[
            ComponentDiff(
                path="VCALENDAR.VTODO[uid=t].VALARM[#0]",
                properties=[
                    PropertyDiff(
                        op=DiffOp.ADDED, property=Property("ACTION", [], "DISPLAY")
                    )
                ],
            )
        ],
    )
    assert str(d) == (
        "--- VCALENDAR.VTODO[uid=t]\n"
        "+ DUE:20260101T000000Z\n"
        "~ SUMMARY: old -> new\n"
        "- PRIORITY:3\n"
        "  --- VCALENDAR.VTODO[uid=t].VALARM[#0]\n"
        "  + ACTION:DISPLAY\n"
    )


def test_str_sorts_rendered_parameters() -> None:
    """Parameters render in a deterministic order, whatever the input."""
    d = ComponentDiff(
        path="p",
        properties=[
            PropertyDiff(
                op=DiffOp.ADDED,
                property=Property(
                    "DUE", [Param("VALUE", "DATE"), Param("TZID", "UTC")], "X"
                ),
            )
        ],
    )
    assert str(d) == "--- p\n+ DUE;TZID=UTC;VALUE=DATE:X\n"


def test_str_of_empty_diff_is_blank() -> None:
    """Nothing changed renders as nothing, not a bare header."""
    assert str(ComponentDiff(path="VCALENDAR.VTODO[uid=t]")) == ""


def test_equality_ignores_property_order() -> None:
    """Semantic equality routes through canonical bytes."""
    a = _todo(Property("UID", [], "t"), Property("SUMMARY", [], "s"))
    b = _todo(Property("SUMMARY", [], "s"), Property("UID", [], "t"))
    assert component_equal(a, b)


def test_calendar_equality_ignores_component_order() -> None:
    """Canonicalization sorts top-level components, so order is moot."""
    x = Component(type=COMP_TODO, props=[Property("UID", [], "a")])
    y = Component(type=COMP_TODO, props=[Property("UID", [], "b")])
    assert calendar_equal(
        Calendar(prod_id="p", components=[x, y]),
        Calendar(prod_id="p", components=[y, x]),
    )


def test_card_equality_and_diff() -> None:
    """Cards diff on properties alone and never carry sub-diffs."""
    a = Card(uid="u", props=[Property("FN", [], "A")])
    b = Card(uid="u", props=[Property("FN", [], "B")])
    assert not card_equal(a, b)
    d = of_card(a, b)
    assert d.path == ""
    assert d.sub_diffs == []
    assert [pd.op for pd in d.properties] == [DiffOp.CHANGED]


def _todo(*props: Property) -> Component:
    """A VTODO carrying ``props`` — the common shape in these cases."""
    return Component(type=COMP_TODO, props=list(props))


def _alarm(action: str) -> Component:
    """A UID-less VALARM, the positional-pairing case."""
    return Component(type=COMP_ALARM, props=[Property("ACTION", [], action)])
