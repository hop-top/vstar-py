# SPDX-License-Identifier: MIT

"""The supersession projection gate, against ``spec/behavior/supersession/``."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from _fixtures import CONFORMANCE_DIR, behavior_json, behavior_stems
from vstar import (
    COMP_JOURNAL,
    COMP_TODO,
    Calendar,
    Component,
    Property,
    TargetCorrupted,
    hashing,
)
from vstar.codec import rfc5545
from vstar.supersession import (
    CATEGORY_STATUS_SUPERSESSION,
    PROP_EFFECTIVE_STATUS,
    superseded,
    supersedes,
)

#: Every ``<name>.effective.json`` stem, walked rather than listed.
STEMS = behavior_stems("supersession", ".effective.json")

_AT = datetime(2026, 5, 4, 14, 30, tzinfo=UTC)


def _calendar(stem: str) -> Calendar:
    """The conformance fixture the projection table is keyed to.

    No new ``.ics`` files are minted for this family — the inputs are
    the existing corpus, keyed by the same name.
    """
    path = CONFORMANCE_DIR / "supersession" / f"{stem}.ics"
    return rfc5545.parse(path.read_bytes())


def test_stems_are_discovered() -> None:
    """A vacuous walk would make every case below disappear silently."""
    assert len(STEMS) == 5


@pytest.mark.parametrize("stem", STEMS)
def test_effective_status_matches_fixture(stem: str) -> None:
    """The ledger projects exactly the statuses the fixture records.

    Built the same way the reference builds it: ask every top-level
    component what the whole component list says about it, and keep only
    the ones with an answer. A UID absent from the map is not
    superseded — which is why ``corrupt_mutated`` is ``{}`` even though
    its hash is broken. Supersession is a projection query, not a
    validator.
    """
    want = behavior_json("supersession", f"{stem}.effective.json")
    cal = _calendar(stem)

    got: dict[str, str] = {}
    for c in cal.components:
        status = superseded(c, cal.components)
        if status is None:
            continue
        assert c.uid() != "", f"{stem}: superseded component has no UID"
        got[c.uid()] = status

    assert got == want


def test_corrupt_target_is_refused() -> None:
    """A target whose stored hash no longer verifies cannot be superseded.

    This is the case the whole integrity check exists for: writing a
    supersession against content that changed after it was hashed would
    attach the new status to bytes nobody agreed to.
    """
    cal = _calendar("corrupt_mutated")
    target = cal.find("todo-corrupt")
    assert target is not None

    ok, _want, _got = hashing.verify_x_vstar(target)
    assert ok is False, "fixture should carry a stale hash"

    with pytest.raises(TargetCorrupted):
        supersedes(target, "COMPLETED", _AT)


def test_supersedes_builds_the_journal() -> None:
    """The constructed entry carries every property, hash last."""
    target = Component(type=COMP_TODO, props=[Property("UID", [], "todo-1")])
    hashing.set_x_vstar(target)

    j = supersedes(target, "COMPLETED", _AT)

    assert str(j.type) == "VJOURNAL"
    assert j.uid() == "journal:status:todo-1:20260504T143000Z"
    assert j.dtstamp_raw() == "20260504T143000Z"
    related = j.get("RELATED-TO")
    assert related is not None and related.value == "todo-1"
    cats = j.get("CATEGORIES")
    assert cats is not None and cats.value == CATEGORY_STATUS_SUPERSESSION
    status = j.get(PROP_EFFECTIVE_STATUS)
    assert status is not None and status.value == "COMPLETED"

    ok, want, got = hashing.verify_x_vstar(j)
    assert ok, f"stored hash {got} does not match {want}"


def test_supersedes_does_not_mutate_the_target() -> None:
    """The append-only contract: the target is read, never written."""
    target = Component(type=COMP_TODO, props=[Property("UID", [], "todo-1")])
    hashing.set_x_vstar(target)
    before = [(p.name, p.value) for p in target.props]

    supersedes(target, "CANCELLED", _AT)

    assert [(p.name, p.value) for p in target.props] == before


def test_unhashed_target_is_accepted() -> None:
    """No stored hash means no integrity claim, so nothing to refuse."""
    target = Component(type=COMP_TODO, props=[Property("UID", [], "todo-bare")])
    assert hashing.get_x_vstar(target) is None
    j = supersedes(target, "COMPLETED", _AT)
    assert j.get(PROP_EFFECTIVE_STATUS) is not None


def test_superseded_without_uid_is_none() -> None:
    """A component with no UID has nothing for a ledger to name."""
    assert superseded(Component(type=COMP_TODO), []) is None


def test_superseded_on_empty_ledger_is_none() -> None:
    """ "Nothing supersedes this" is an answer, not a failure."""
    c = Component(type=COMP_TODO, props=[Property("UID", [], "todo-1")])
    assert superseded(c, []) is None


def test_later_dtstamp_wins() -> None:
    """The latest entry by ``DTSTAMP`` projects, whatever the order."""
    target = Component(type=COMP_TODO, props=[Property("UID", [], "t")])
    early = _entry("t", "IN-PROCESS", "20260101T000000Z")
    late = _entry("t", "COMPLETED", "20260601T000000Z")

    assert superseded(target, [late, early]) == "COMPLETED"
    assert superseded(target, [early, late]) == "COMPLETED"


def test_dtstamp_tie_goes_to_the_later_entry() -> None:
    """A tie resolves by ledger position, since the scan is stable."""
    target = Component(type=COMP_TODO, props=[Property("UID", [], "t")])
    first = _entry("t", "IN-PROCESS", "20260101T000000Z")
    second = _entry("t", "COMPLETED", "20260101T000000Z")
    assert superseded(target, [first, second]) == "COMPLETED"


def test_unparseable_dtstamp_loses_but_does_not_raise() -> None:
    """Ledger noise is demoted, never fatal — this is a query."""
    target = Component(type=COMP_TODO, props=[Property("UID", [], "t")])
    broken = _entry("t", "CANCELLED", "not-a-timestamp")
    good = _entry("t", "COMPLETED", "20260101T000000Z")
    assert superseded(target, [broken, good]) == "COMPLETED"
    assert superseded(target, [broken]) == "CANCELLED"


def test_category_must_be_a_whole_token() -> None:
    """A longer category containing the token does not match.

    ``CATEGORIES`` is comma-delimited, so the comparison is per token —
    substring matching would let ``status-supersession-deferred``
    silently project a status.
    """
    target = Component(type=COMP_TODO, props=[Property("UID", [], "t")])
    entry = _entry("t", "COMPLETED", "20260101T000000Z")
    entry.set(Property("CATEGORIES", [], "status-supersession-deferred"))
    assert superseded(target, [entry]) is None


def test_category_match_is_case_insensitive_and_trimmed() -> None:
    """A token survives surrounding space and any casing."""
    target = Component(type=COMP_TODO, props=[Property("UID", [], "t")])
    entry = _entry("t", "COMPLETED", "20260101T000000Z")
    entry.set(Property("CATEGORIES", [], "other, STATUS-Supersession ,more"))
    assert superseded(target, [entry]) == "COMPLETED"


def test_non_journal_entries_are_ignored() -> None:
    """Only a VJOURNAL supersedes; a VTODO carrying the marks does not."""
    target = Component(type=COMP_TODO, props=[Property("UID", [], "t")])
    entry = _entry("t", "COMPLETED", "20260101T000000Z")
    entry.type = COMP_TODO
    assert superseded(target, [entry]) is None


def test_entry_without_status_is_skipped() -> None:
    """A supersession naming a target but stating nothing says nothing."""
    target = Component(type=COMP_TODO, props=[Property("UID", [], "t")])
    entry = _entry("t", "COMPLETED", "20260101T000000Z")
    entry.remove(PROP_EFFECTIVE_STATUS)
    assert superseded(target, [entry]) is None


def _entry(target_uid: str, status: str, stamp: str) -> Component:
    """A supersession VJOURNAL built by hand, for the unit cases."""
    c = Component(type=COMP_JOURNAL)
    c.set(Property("UID", [], f"journal:status:{target_uid}:{stamp}"))
    c.set(Property("DTSTAMP", [], stamp))
    c.set(Property("RELATED-TO", [], target_uid))
    c.set(Property("CATEGORIES", [], CATEGORY_STATUS_SUPERSESSION))
    c.set(Property(PROP_EFFECTIVE_STATUS, [], status))
    return c
