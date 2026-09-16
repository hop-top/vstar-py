# SPDX-License-Identifier: MIT

"""The ``ext`` classification gate, against ``spec/behavior/ext/``."""

from __future__ import annotations

import pytest

from _fixtures import behavior_json
from vstar import COMP_TODO, Component, Property
from vstar.ext import Scope, extensions_by_scope, is_extension, scope_of, system_name


def _scope_rows() -> list[dict[str, str | None]]:
    """The ``scopes.json`` table, in file order.

    Order is part of the contract — the fixture is a flat table, not a
    set — so the rows are used as read rather than sorted.
    """
    rows = behavior_json("ext", "scopes.json")
    assert isinstance(rows, list)
    return rows


SCOPE_ROWS = _scope_rows()


def test_scope_table_is_not_empty() -> None:
    """The gate would pass vacuously on an empty table."""
    assert len(SCOPE_ROWS) == 17


@pytest.mark.parametrize("row", SCOPE_ROWS, ids=lambda r: repr(r["name"]))
def test_scope_of_matches_fixture(row: dict[str, str | None]) -> None:
    """Each name classifies into the scope the fixture records.

    The fixture's token is lowercase, which is the member *value* — the
    capitalized display spelling is what ``str()`` renders, and
    comparing against that would be comparing against debug text.
    """
    name = row["name"]
    assert isinstance(name, str)
    assert scope_of(name).value == row["scope"]


@pytest.mark.parametrize("row", SCOPE_ROWS, ids=lambda r: repr(r["name"]))
def test_system_name_matches_fixture(row: dict[str, str | None]) -> None:
    """The owning system is extracted for system-scoped names only."""
    name = row["name"]
    assert isinstance(name, str)
    assert system_name(name) == row["system"]


def test_every_scope_is_covered() -> None:
    """The table exercises all five scopes, so none passes untested."""
    seen = {row["scope"] for row in SCOPE_ROWS}
    assert seen == {s.value for s in Scope}


@pytest.mark.parametrize(
    ("name", "want"),
    [
        ("X-FOO", True),
        ("x-foo", True),
        ("X-", True),
        ("X", False),
        ("", False),
        ("DTSTART", False),
        ("XFOO", False),
    ],
)
def test_is_extension(name: str, want: bool) -> None:
    """The ``X-`` prefix test, hyphen required and case-insensitive."""
    assert is_extension(name) is want


def test_scope_str_is_the_display_spelling() -> None:
    """``str()`` renders the reference's capitalized spelling.

    Held apart from the wire token so neither can be derived from the
    other by a case transform — ``VStar`` is not the title case of
    ``vstar``.
    """
    assert str(Scope.VSTAR) == "VStar"
    assert str(Scope.NONE) == "None"
    assert str(Scope.EXPERIMENTAL) == "Experimental"
    assert Scope.VSTAR.value == "vstar"


def test_scope_none_is_the_first_member() -> None:
    """ "Not an extension" leads the enum, as the reference's zero value."""
    assert next(iter(Scope)) is Scope.NONE


def test_extensions_by_scope_filters_and_keeps_order() -> None:
    """Matching properties come back in ``props`` order, unsorted."""
    c = Component(
        type=COMP_TODO,
        props=[
            Property("X-AGR-INTENT", [], "b"),
            Property("SUMMARY", [], "s"),
            Property("X-ACME-TICKET-ID", [], "a"),
            Property("X-VSTAR-HASH", [], "h"),
            Property("X-EXP-DRAFT", [], "e"),
        ],
    )
    assert [p.name for p in extensions_by_scope(c, Scope.SYSTEM)] == [
        "X-AGR-INTENT",
        "X-ACME-TICKET-ID",
    ]
    assert [p.name for p in extensions_by_scope(c, Scope.VSTAR)] == ["X-VSTAR-HASH"]
    assert [p.name for p in extensions_by_scope(c, Scope.EXPERIMENTAL)] == [
        "X-EXP-DRAFT"
    ]
    assert [p.name for p in extensions_by_scope(c, Scope.NONE)] == ["SUMMARY"]


def test_extensions_by_scope_does_not_recurse() -> None:
    """Sub-components are the caller's to walk."""
    child = Component(type=COMP_TODO, props=[Property("X-EXP-A", [], "x")])
    parent = Component(type=COMP_TODO, props=[], sub=[child])
    assert extensions_by_scope(parent, Scope.EXPERIMENTAL) == []
